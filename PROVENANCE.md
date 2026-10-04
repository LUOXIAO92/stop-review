# Source provenance

This standalone package was extracted and adapted from the
[LUOXIAO92/graphtraj dev revision](https://github.com/LUOXIAO92/graphtraj/tree/32d5f701d95d0426d825cd62ee3f7db6ad8985e4),
commit `32d5f701d95d0426d825cd62ee3f7db6ad8985e4`.

The native Stop, fork, identity, cancellation, and transport approach was adapted
from these files:

- `src/graphtraj/runtimes/codex/stop_hook.py`
- `src/graphtraj/runtimes/codex/finalize.py`
- `src/graphtraj/runtimes/codex/app_server.py`
- `src/graphtraj/runtimes/codex/websocket.py`
- `src/graphtraj/runtimes/codex/host_events.py`
- `src/graphtraj/execution/main_finalize.py`
- `tests/test_main_finalize.py`

The owner of the original source, LUOXIAO92, selected Apache-2.0 for this
standalone package. Its license is provided in the root [LICENSE](LICENSE).
An identical copy is included at `plugins/stop-review/LICENSE` so that the native
plugin carries the license when distributed separately from the repository.

The source revision did not include a repository-wide LICENSE/COPYING/NOTICE.
Its nested `runtimes/codex/policy/LICENSE` and `NOTICE` concern separate policy
assets; none of those assets are included here. This package's license does not
relicense those excluded assets or the graphtraj repository as a whole.

This is an independent extraction, not a release of graphtraj. The adapted
implementation, plugin packaging, and tests are maintained in this project.

Hook compatibility and cancellation notes were checked against the installed
Codex 0.159.2 help and generated experimental schemas, and current official docs.
The native Interrupt cleanup behavior is also documented in the official
[hook command runner](https://github.com/openai/codex/blob/main/codex-rs/hooks/src/engine/command_runner.rs),
[task interruption](https://github.com/openai/codex/blob/main/codex-rs/core/src/tasks/mod.rs),
and [goal request processor](https://github.com/openai/codex/blob/main/codex-rs/app-server/src/request_processors/thread_goal_processor.rs).
