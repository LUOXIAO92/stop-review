"""Adapt a native Codex fork's final JSON to the native Stop hook response."""

import json
import os
from pathlib import Path
import subprocess
import sys
from uuid import UUID


def parse_result(text):
    def unique(pairs):
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
    if not isinstance(steps, list) or any(not isinstance(s, str) or not s.strip() for s in steps):
        raise ValueError("Reviewer next_steps must contain nonempty descriptions")
    if (result["status"] == "actionable") != bool(steps):
        raise ValueError("Only actionable review must contain next_steps")
    return result


def stopped(reason):
    return {"continue": False, "stopReason": reason, "systemMessage": reason}


def review(event):
    if os.environ.get("STOP_REVIEW_CHILD") == "1":
        return {}
    if not isinstance(event, dict):
        raise ValueError("Expected a native hook event object")
    if event.get("hook_event_name") != "Stop":
        return {}
    # In 0.159.2 root Stop events identify the root thread. SubagentStop is ignored.
    # CODEX_THREAD_ID in a hook may instead be the daemon's stale environment.
    session = event.get("session_id")
    if not isinstance(session, str) or str(UUID(session)) != session:
        raise ValueError("Stop must identify its native root session UUID")
    model = event.get("model")
    if not isinstance(model, str) or not model.strip():
        raise ValueError("Stop must provide its current native model")
    prompt = Path(__file__).resolve().parents[1].joinpath("prompt.md").read_text(encoding="utf-8")
    completed = subprocess.run(
        ["codex", "exec", "fork", "--ephemeral", "--model=" + model,
         "--skip-git-repo-check", session, "-"],
        input=prompt, text=True, encoding="utf-8", capture_output=True,
        env={**os.environ, "STOP_REVIEW_CHILD": "1"},
        # Stay in the host hook's process group: its timeout/interruption owns cleanup.
        check=False,
    )
    if completed.returncode:
        detail = completed.stderr.strip()[-2000:]
        raise RuntimeError(f"Native codex exec fork exited {completed.returncode}: {detail}")
    result = parse_result(completed.stdout)
    if result["status"] in ("completed", "waiting"):
        return {}
    if result["status"] == "error":
        return stopped("Completion review failed: " + result["reason"])
    return {"decision": "block", "reason": "\n".join([result["reason"], *result["next_steps"]])}


def main():
    try:
        result = review(json.load(sys.stdin))
    except Exception as error:
        result = stopped(f"Completion review failed ({type(error).__name__}): {error}")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
