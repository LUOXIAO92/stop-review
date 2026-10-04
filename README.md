# Stop Review

[English](README.md) | [简体中文](README.zh-CN.md)

When Codex Main is about to finish, Stop Review uses the native `codex exec fork --ephemeral` command to check whether the actual execution results and evidence satisfy the user's requirements. The review prompt is appended after the conversation inherited by the native fork.

The plugin consists of a Stop hook, a Python standard-library script, and a review prompt.

## Installation

Requires Linux/macOS, Python 3.11+, Codex 0.159.2, and a local Main session whose native history is accessible through the same `CODEX_HOME`. Both `python3` and `codex` must be available on the hook's `PATH`.

```sh
git clone https://github.com/LUOXIAO92/stop-review.git
cd stop-review
codex plugin marketplace add "$PWD"
codex plugin add stop-review@stop-review-local
```

Restart Codex, then inspect and trust Stop Review's Stop definition in `/hooks`. The hook takes effect within the plugin's installation scope.

## Uninstall

```sh
codex plugin remove stop-review@stop-review-local
```

## How it works

The hook calls the installed native executable directly:

```sh
codex exec fork --ephemeral --model="$MODEL" --skip-git-repo-check "$SESSION_ID" -
```

`MODEL` and `SESSION_ID` come from the current native Stop event, and the review prompt is passed through stdin. Native Codex handles forking, execution, and exit. The script validates the final JSON and returns a native Stop response.

- `completed` / `waiting`: allow the turn to end
- `actionable`: return specific unfinished tasks to the same Main; subsequent Stop events trigger another review
- `error` / invalid output / native process failure: show an error and stop the turn

Each review adds one model execution and the time spent waiting for it. See [Implementation](docs/implementation.md) for details.

## Tests

```sh
python3 -m unittest discover -s tests -v
python3 -m compileall -q plugins/stop-review/scripts tests
```

Local unit tests use a temporary `codex` test double to check process invocation and hook responses.

## License

[Apache-2.0](LICENSE). The plugin directory includes the same full license. See [Source provenance](PROVENANCE.md).
