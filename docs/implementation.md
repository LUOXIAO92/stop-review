# Implementation

[English](implementation.md) | [简体中文](implementation.zh-CN.md)

## Review flow

1. Read the current `session_id` and `model` from Codex's root `Stop` event.
2. Run `codex exec fork --ephemeral` in the same working directory, environment, and `CODEX_HOME`, using the model from the event. `--skip-git-repo-check` allows Main to run outside a Git directory.
3. Append the review prompt through stdin. The native fork reads the session history.
4. Read the native exec process's final output, validate the JSON fields, status, and `next_steps`, and convert the result to a native Stop response.

## Runtime environment

The plugin works with a local Main whose native history is readable on the same machine under the same `CODEX_HOME`. Native exec loads the current local configuration. If the session history cannot be read, the review returns an error.

The review prompt asks the reviewer to assess the user's requirements against the available execution results and evidence, and to output only the review JSON.

## Exit and repeated reviews

The reviewer process is marked with `STOP_REVIEW_CHILD=1`, which the hook uses to skip nested reviews. The plugin handles Main's `Stop` events; subsequent Stop events trigger another review.

The script waits synchronously for the native process. The hook timeout is 600 seconds. The native hook runner handles user interruption, timeouts, and process-tree cleanup.

## Results

- `completed` / `waiting`: allow Main to end the current turn.
- `actionable`: return unfinished tasks to Main so it can continue.
- `error`, invalid JSON, or native process failure: show an error and stop the turn.
