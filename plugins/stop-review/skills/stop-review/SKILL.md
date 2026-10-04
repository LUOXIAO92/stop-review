---
name: stop-review
description: Enable completion review for the current Codex Main when the user asks for a check before it stops.
---

Run the bundled `../../scripts/stop_review.py bind` using Python 3 from this
skill's directory. This captures the current native thread from its execution
environment and verifies it with the existing Codex daemon. Never supply or
override a thread identity. If binding fails, report the error.

Binding alone does not install or trust the Stop hook. The plugin must be enabled
and its current hook trusted through Codex's `/hooks` screen. Do not bypass trust.

The hook compares the current user requirements with inherited results and
evidence. It permits completion or genuine waiting and returns concrete,
authorized unfinished work to the same Main through the native Stop response.
Do not run a substitute review or manually restart a stopped Main.
