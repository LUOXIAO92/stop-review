"""Bind one Main and return native Stop decisions from a fresh context fork."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path

from .client import Client, RPCError


REVIEW_TIMEOUT = 420
CANCEL_TIMEOUT = 10
WORK_TIMEOUT = 480
SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["status", "reason", "next_steps"],
    "properties": {
        "status": {"type": "string", "enum": ["completed", "waiting", "actionable", "error"]},
        "reason": {"type": "string", "minLength": 1},
        "next_steps": {"type": "array", "items": {"type": "string", "minLength": 1}},
    },
}


def home() -> Path:
    """Select the same public daemon namespace as the native Codex proxy."""
    return Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")).resolve()


def key(value: str) -> str:
    """Convert a native identifier into a filesystem-safe local record key."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def write_json(path: Path, value: dict, *, exclusive: bool = False) -> None:
    """Write private local state without exposing partial JSON to concurrent hooks."""
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        if exclusive:
            os.link(temporary, path)
        else:
            os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


async def bind() -> dict:
    """Bind the native root captured from this Main's execution environment."""
    thread_id = os.environ.get("CODEX_THREAD_ID")
    if not thread_id:
        raise ValueError("Run bind inside the owning Codex Main; CODEX_THREAD_ID is missing")
    root = home() / "stop-review"
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    if (root / "reviewers" / (key(thread_id) + ".json")).exists():
        raise ValueError("A completion reviewer cannot bind itself as Main")
    async with Client(home(), Path.cwd()) as client:
        thread = await client.read_thread(thread_id)
    source = thread.get("source")
    if thread.get("parentThreadId") is not None or isinstance(source, dict) and "subAgent" in source:
        raise ValueError("Only the owning root Main can bind completion review")
    session_id = thread.get("sessionId")
    if not isinstance(session_id, str) or not session_id:
        raise ValueError("The host did not provide its native hook session identity")
    binding = {"thread_id": thread_id, "session_id": session_id,
               "codex_home": str(home()), "cwd": str(Path.cwd().resolve())}
    path = root / "bindings" / (key(session_id) + ".json")
    if path.exists() and json.loads(path.read_text(encoding="utf-8")) != binding:
        raise ValueError("This native session already belongs to another Main binding")
    if not path.exists():
        write_json(path, binding, exclusive=True)
    return {"binding": str(path), "thread_id": thread_id, "session_id": session_id}


def parse_result(text: str) -> dict:
    """Validate the entire reviewer response without guessing task completion."""
    def unique(pairs: list) -> dict:
        result = {}
        for name, value in pairs:
            if name in result:
                raise ValueError("Duplicate reviewer JSON field")
            result[name] = value
        return result

    result = json.loads(text, object_pairs_hook=unique)
    if not isinstance(result, dict) or set(result) != {"status", "reason", "next_steps"}:
        raise ValueError("Reviewer must return exactly status, reason, and next_steps")
    if result["status"] not in ("completed", "waiting", "actionable", "error"):
        raise ValueError("Unknown reviewer status")
    if not isinstance(result["reason"], str) or not result["reason"].strip():
        raise ValueError("Reviewer reason must be nonempty")
    steps = result["next_steps"]
    if not isinstance(steps, list) or any(not isinstance(step, str) or not step.strip() for step in steps):
        raise ValueError("Reviewer next_steps must contain nonempty descriptions")
    if (result["status"] == "actionable") != bool(steps):
        raise ValueError("Only actionable review must contain next_steps")
    return result


def response(result: dict, continued: bool) -> dict:
    """Only authorized unfinished work blocks Stop; repeated errors end visibly."""
    if result["status"] in ("completed", "waiting"):
        return {}
    reason = "\n".join([result["reason"], *result["next_steps"]])
    if result["status"] == "error" and continued:
        return {"continue": False, "stopReason": reason, "systemMessage": reason}
    return {"decision": "block", "reason": reason}


async def cancel_review(
    binding: dict, child: str, turn_id: str | None, previous_turn: str | None,
) -> None:
    """Reconcile an uncertain start and confirm only this child's turn is terminal.

    Use a fresh proxy because the start connection may have failed. A successful
    interrupt RPC alone is not proof of cancellation.
    """
    async with asyncio.timeout(CANCEL_TIMEOUT):
        async with Client(Path(binding["codex_home"]), Path(binding["cwd"]), close_timeout=0.1) as client:
            interrupted = False
            while True:
                result = await client.call("thread/turns/list", {
                    "threadId": child, "limit": 1, "itemsView": "notLoaded", "sortDirection": "desc",
                })
                turns = result.get("data")
                if not isinstance(turns, list) or not turns or not isinstance(turns[0], dict):
                    raise RuntimeError("The reviewer's turn could not be reconciled")
                latest = turns[0]
                if turn_id is None and latest.get("id") == previous_turn:
                    raise RuntimeError("No distinct reviewer turn could be confirmed")
                if turn_id is None:
                    turn_id = latest.get("id")
                if not isinstance(turn_id, str) or not turn_id or latest.get("id") != turn_id:
                    raise RuntimeError("The reviewer turn identity changed during cancellation")
                if latest.get("status") in ("completed", "interrupted", "failed"):
                    return
                if latest.get("status") != "inProgress":
                    raise RuntimeError("Reviewer cancellation was not confirmed")
                if not interrupted:
                    await client.call("turn/interrupt", {"threadId": child, "turnId": turn_id})
                    interrupted = True
                await asyncio.sleep(0.05)


async def run_review(client: Client, binding: dict, event: dict, root: Path) -> dict:
    """Fork current native context and append only the completion-review task."""
    parent = await client.read_thread(binding["thread_id"])
    provider = parent.get("modelProvider")
    if not isinstance(provider, str) or not provider:
        raise ValueError("The current Main provider is unavailable")
    fork = await client.call("thread/fork", {
        "threadId": binding["thread_id"], "model": event["model"],
        "modelProvider": provider, "excludeTurns": True,
        "sandbox": "read-only", "approvalPolicy": "never",
        "deferGoalContinuation": True,
    })
    child = fork.get("thread", {}).get("id")
    if (not isinstance(child, str) or not child or child == binding["thread_id"]
            or fork["thread"].get("forkedFromId") != binding["thread_id"]
            or fork.get("model") != event["model"] or fork.get("modelProvider") != provider):
        raise ValueError("The reviewer fork did not preserve Main identity, model, and provider")
    record = root / "reviewers" / (key(child) + ".json")
    write_json(record, {"thread_id": child, "parent": binding["thread_id"],
                       "parent_turn": event["turn_id"]}, exclusive=True)

    # A one-shot reviewer must never inherit Main's automatic goal execution.
    try:
        await client.call("thread/goal/clear", {"threadId": child})
        goal = await client.call("thread/goal/get", {"threadId": child})
        if "goal" not in goal or goal["goal"] is not None:
            raise ValueError("The reviewer still has an automatic goal")
    except RPCError as error:
        if error.code != -32600 or error.message != "goals feature is disabled":
            raise
    if not await client.current_turn(binding, event["turn_id"]):
        return {"status": "waiting", "reason": "Main stopped or changed turns", "next_steps": []}
    inherited = await client.call("thread/turns/list", {
        "threadId": child, "limit": 1, "itemsView": "notLoaded", "sortDirection": "desc",
    })
    prior = inherited.get("data")
    if not isinstance(prior, list) or prior and (
        not isinstance(prior[0], dict) or not isinstance(prior[0].get("id"), str) or not prior[0]["id"]
    ):
        raise ValueError("The reviewer's inherited turn boundary is unavailable")
    previous_turn = prior[0]["id"] if prior else None
    identity = {"thread_id": child, "parent": binding["thread_id"],
                "parent_turn": event["turn_id"], "previous_turn": previous_turn}
    write_json(record, identity)
    prompt = Path(__file__).with_name("prompt.md").read_text(encoding="utf-8")
    # Shield the start reply so cancellation still obtains the exact owned turn.
    starting = asyncio.create_task(client.call("turn/start", {
        "threadId": child, "input": [{"type": "text", "text": prompt}],
        "outputSchema": SCHEMA,
    }))
    turn = None
    try:
        try:
            started = await asyncio.shield(starting)
        except asyncio.CancelledError as interrupted:
            # Await the in-flight reply when possible, without abandoning ownership.
            try:
                started = await starting
                turn = started.get("turn")
            except Exception:
                pass
            raise interrupted
        turn = started.get("turn")
        if not isinstance(turn, dict) or not isinstance(turn.get("id"), str) or not turn["id"]:
            raise ValueError("The host did not identify the reviewer turn")
        if turn["id"] == previous_turn:
            raise ValueError("The host reused an inherited turn instead of creating a reviewer turn")
        if turn.get("status") not in ("inProgress", "completed", "interrupted", "failed"):
            raise ValueError("The host did not identify the reviewer turn status")
        write_json(record, {**identity, "turn_id": turn["id"]})
        result = await asyncio.wait_for(client.wait(child, turn), REVIEW_TIMEOUT)
    except BaseException as error:
        try:
            known_turn = turn.get("id") if isinstance(turn, dict) else None
            await cancel_review(binding, child, known_turn if known_turn != previous_turn else None,
                                previous_turn)
        except Exception as cleanup:
            if isinstance(error, asyncio.CancelledError):
                print(f"Reviewer cancellation unconfirmed: {cleanup}", file=sys.stderr)
                raise error
            raise RuntimeError(f"Reviewer failed; cancellation unconfirmed: {cleanup}") from error
        raise
    write_json(root / "reviews" / (key(child) + ".json"), {
        "thread_id": child, "turn_id": turn["id"], "parent": binding["thread_id"],
        "parent_turn": event["turn_id"], "model": event["model"],
        "provider": provider, **result,
    })
    if result["status"] != "completed":
        raise RuntimeError("The reviewer did not complete successfully")
    return parse_result(result["output"])


async def check(event: object) -> dict:
    """Ignore unbound/foreign Stops, check ownership, and return one native decision."""
    if not isinstance(event, dict) or event.get("hook_event_name") not in ("Stop", "Interrupt"):
        return {}
    session = event.get("session_id")
    if not isinstance(session, str) or not session:
        return {}
    root = home() / "stop-review"
    path = root / "bindings" / (key(session) + ".json")
    if not path.exists():
        return {}
    binding = json.loads(path.read_text(encoding="utf-8"))
    if binding.get("session_id") != session or binding.get("codex_home") != str(home()):
        raise ValueError("Stop does not match its stored Main binding")
    if event["hook_event_name"] == "Interrupt":
        return await interrupted_main(binding, event, root)
    if (not isinstance(event.get("turn_id"), str) or not event["turn_id"]
            or not isinstance(event.get("model"), str) or not event["model"]
            or type(event.get("stop_hook_active")) is not bool):
        raise ValueError("Stop must provide its native turn, model, and continuation state")
    # Budget begins before connection/identity RPCs, reserving over a minute for
    # an in-flight start reply, owned cancellation, proxy close, and host output.
    async with asyncio.timeout(WORK_TIMEOUT):
        async with Client(home(), Path(binding["cwd"])) as client:
            if not await client.current_turn(binding, event["turn_id"]):
                return {}
            try:
                result = await run_review(client, binding, event, root)
            except asyncio.CancelledError:
                raise
            except Exception as error:
                result = {"status": "error", "reason": f"Completion review failed ({type(error).__name__}): {error}",
                          "next_steps": []}
            # Even a failed review cannot continue an interrupted or replaced turn.
            if not await client.current_turn(binding, event["turn_id"]):
                return {}
            return response(result, event["stop_hook_active"])


async def interrupted_main(binding: dict, event: dict, root: Path) -> dict:
    """Use the separate native Interrupt hook after a Stop process was killed.

    Native Interrupt hooks allow at most three seconds. Cleanup is best-effort
    within two seconds, and an unconfirmed outcome is returned to the host UI.
    """
    turn = event.get("turn_id")
    if not isinstance(turn, str) or not turn:
        return {}
    warnings = []
    try:
        async with asyncio.timeout(2):
            for path in (root / "reviewers").glob("*.json"):
                try:
                    record = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, ValueError) as error:
                    warnings.append(f"Unreadable reviewer record: {path.name}: {error}")
                    continue
                if record.get("parent") == binding["thread_id"] and record.get("parent_turn") == turn:
                    if "previous_turn" in record or record.get("turn_id"):
                        await cancel_review(binding, record["thread_id"], record.get("turn_id"),
                                            record.get("previous_turn"))
                    else:
                        warnings.append("Interrupted Main: reviewer cancellation unconfirmed (no saved turn boundary)")
    except Exception as error:
        warnings.append(f"Interrupted Main: reviewer cancellation unconfirmed ({type(error).__name__}: {error})")
    return {"systemMessage": "\n".join(warnings)} if warnings else {}
