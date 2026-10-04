"""Command entry point and native hook signal handling."""

from __future__ import annotations

import argparse
import asyncio
import json
import signal
import sys

from . import review


async def hook(event: object) -> dict:
    """Translate SIGINT/SIGTERM into owned asynchronous reviewer cancellation."""
    loop = asyncio.get_running_loop()
    task = asyncio.current_task()
    installed = []
    try:
        for signum in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(signum, task.cancel)
            installed.append(signum)
        return await review.check(event)
    finally:
        for signum in installed:
            loop.remove_signal_handler(signum)


def main(argv: list[str] | None = None) -> int:
    """Print only native JSON on hook stdout; never start or resume Main."""
    parser = argparse.ArgumentParser(description="Codex native Stop completion review")
    parser.add_argument("command", choices=["bind", "hook"])
    args = parser.parse_args(argv)
    event = None
    try:
        if args.command == "bind":
            result = asyncio.run(review.bind())
        else:
            event = json.load(sys.stdin)
            result = asyncio.run(hook(event))
    except (KeyboardInterrupt, asyncio.CancelledError):
        return 130
    except Exception as error:
        if args.command == "bind":
            print(f"stop-review: {error}", file=sys.stderr)
            return 1
        reason = f"Completion hook failed: {error}"
        if isinstance(event, dict) and event.get("hook_event_name") == "Interrupt":
            result = {"systemMessage": reason}
        else:
            result = {"continue": False, "stopReason": reason, "systemMessage": reason}
    print(json.dumps(result, ensure_ascii=False))
    return 0
