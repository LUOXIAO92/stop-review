# Source provenance

The completion-review prompt and verdict semantics originated in the
[LUOXIAO92/graphtraj dev revision](https://github.com/LUOXIAO92/graphtraj/tree/32d5f701d95d0426d825cd62ee3f7db6ad8985e4),
commit `32d5f701d95d0426d825cd62ee3f7db6ad8985e4`, especially
`src/graphtraj/runtimes/codex/finalize.py` and `src/graphtraj/execution/main_finalize.py`.
Version 0.2 replaces the prior extracted transport and lifecycle implementation
with a thin invocation of the installed native Codex program. No former RPC,
WebSocket, binding, public CLI, skill, or Python package is included.

The original source owner, LUOXIAO92, selected Apache-2.0 for this standalone
project. Full identical licenses are included at [LICENSE](LICENSE) and
[plugins/stop-review/LICENSE](plugins/stop-review/LICENSE).
The source revision had no repository-wide LICENSE/COPYING/NOTICE. Its nested
`runtimes/codex/policy/LICENSE` and `NOTICE` concern policy assets not included
here. This project's license does not relicense those assets or graphtraj as a whole.

## Native interface verification

Verified against the installed `codex-cli 0.159.2`, corresponding to official
commit `ff6aec96948b70d94983af2641a6b67c94faeff5`:

- [Native exec fork and its config parameters](https://github.com/openai/codex/blob/ff6aec96948b70d94983af2641a6b67c94faeff5/codex-rs/exec/src/lib.rs#L1024-L1087)
- [Headless configuration defaults](https://github.com/openai/codex/blob/ff6aec96948b70d94983af2641a6b67c94faeff5/codex-rs/exec/src/lib.rs#L540-L600)
- [Ephemeral root cache routing and root identity](https://github.com/openai/codex/blob/ff6aec96948b70d94983af2641a6b67c94faeff5/codex-rs/core/src/session/session.rs#L878-L916)
- [Base instructions and dynamic tool inheritance](https://github.com/openai/codex/blob/ff6aec96948b70d94983af2641a6b67c94faeff5/codex-rs/core/src/session/mod.rs#L739-L835)
- [Goal inheritance conditions](https://github.com/openai/codex/blob/ff6aec96948b70d94983af2641a6b67c94faeff5/codex-rs/app-server/src/request_processors/thread_processor.rs#L5242-L5267)
- [Native Stop payload and response](https://github.com/openai/codex/blob/ff6aec96948b70d94983af2641a6b67c94faeff5/codex-rs/hooks/src/events/stop.rs)
- [Native hook environment and process-tree cleanup](https://github.com/openai/codex/blob/ff6aec96948b70d94983af2641a6b67c94faeff5/codex-rs/hooks/src/engine/command_runner.rs#L252-L455)

The native CLI does not expose a `swarm` command, and this version's hooks do not
provide a native agent/prompt handler. The plugin calls the supported native fork
entry point; it does not invent either interface. Source inspection and mocked
process tests are not real-host integration or cache-performance measurements.
