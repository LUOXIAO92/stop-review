"""Test the thin hook against a fake native executable, without sessions or models."""

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins/stop-review"
SCRIPT = PLUGIN / "scripts/stop_review.py"
SPEC = importlib.util.spec_from_file_location("stop_review_hook", SCRIPT)
HOOK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(HOOK)
EVENT = {
    "hook_event_name": "Stop",
    "session_id": "a8347392-ce85-4a83-8d9e-284599cd97d1",
    "turn_id": "current-turn",
    "model": "current-model",
    "stop_hook_active": False,
}
RESULT = {"status": "completed", "reason": "Required checks passed", "next_steps": []}


class HookTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.folder = Path(temporary.name)
        self.log = self.folder / "invocation.json"
        executable = self.folder / "codex"
        executable.write_text(
            f"#!{sys.executable}\n"
            "import json, os, sys\n"
            "from pathlib import Path\n"
            "Path(os.environ['FAKE_LOG']).write_text(json.dumps({\n"
            " 'args': sys.argv[1:], 'stdin': sys.stdin.read(),\n"
            " 'marker': os.environ.get('STOP_REVIEW_CHILD'),\n"
            " 'home': os.environ.get('CODEX_HOME'), 'cwd': os.getcwd(),\n"
            " 'pgid': os.getpgrp(),\n"
            "}))\n"
            "print(os.environ['FAKE_RESULT'])\n"
            "print(os.environ.get('FAKE_ERROR', ''), file=sys.stderr)\n"
            "raise SystemExit(int(os.environ.get('FAKE_EXIT', '0')))\n"
        )
        executable.chmod(0o700)
        self.env = {
            **os.environ,
            "PATH": str(self.folder) + os.pathsep + os.environ["PATH"],
            "FAKE_LOG": str(self.log),
            "FAKE_RESULT": json.dumps(RESULT),
            "CODEX_HOME": str(self.folder / "same-native-home"),
            "CODEX_THREAD_ID": "stale-daemon-value-must-not-be-used",
        }
        self.env.pop("STOP_REVIEW_CHILD", None)

    def invoke(self, event=EVENT, raw=None):
        process = subprocess.run(
            [sys.executable, str(SCRIPT)],
            input=json.dumps(event) if raw is None else raw,
            text=True, capture_output=True, env=self.env,
            cwd=self.folder, timeout=5,
        )
        self.assertEqual(process.returncode, 0, process.stderr)
        return json.loads(process.stdout)

    def test_only_native_fork_receives_prompt_and_parent_model(self):
        self.assertEqual(self.invoke(), {})
        call = json.loads(self.log.read_text())
        self.assertEqual(call["args"], [
            "exec", "fork", "--ephemeral", "--model=current-model",
            "--skip-git-repo-check", EVENT["session_id"], "-",
        ])
        self.assertEqual(call["stdin"], (PLUGIN / "prompt.md").read_text())
        self.assertEqual(call["marker"], "1")
        self.assertEqual(call["home"], self.env["CODEX_HOME"])
        self.assertEqual(call["cwd"], str(self.folder))
        self.assertEqual(call["pgid"], os.getpgrp())
        self.assertFalse(Path(self.env["CODEX_HOME"]).exists())

    def test_decisions(self):
        for status, steps in [
            ("completed", []), ("waiting", []),
            ("actionable", ["Run the remaining authorized check"]),
        ]:
            with self.subTest(status=status):
                self.env["FAKE_RESULT"] = json.dumps({**RESULT, "status": status, "next_steps": steps})
                expected = {"decision": "block", "reason": RESULT["reason"] + "\n" + steps[0]} if steps else {}
                self.assertEqual(self.invoke(), expected)

    def test_continued_main_is_reviewed_again(self):
        self.assertEqual(self.invoke({**EVENT, "stop_hook_active": True}), {})
        self.assertTrue(self.log.exists())

    def test_child_guard_prevents_recursive_native_call(self):
        self.env["STOP_REVIEW_CHILD"] = "1"
        self.assertEqual(self.invoke(), {})
        self.assertFalse(self.log.exists())

    def test_other_events_do_not_fork(self):
        for event_name in ("SubagentStop", "Interrupt", "SessionEnd"):
            with self.subTest(event_name=event_name):
                self.assertEqual(self.invoke({**EVENT, "hook_event_name": event_name}), {})
        self.assertFalse(self.log.exists())

    def test_missing_or_invalid_identity_is_visible_and_never_guessed(self):
        for field, value in [("session_id", None), ("session_id", "--last"), ("model", " ")]:
            with self.subTest(field=field, value=value):
                reply = self.invoke({**EVENT, field: value})
                self.assertFalse(reply["continue"])
                self.assertIn("Completion review failed", reply["systemMessage"])
        self.assertFalse(self.log.exists())

    def test_model_is_a_single_option_value(self):
        self.invoke({**EVENT, "model": "--something with spaces"})
        self.assertEqual(json.loads(self.log.read_text())["args"][3], "--model=--something with spaces")

    def test_native_failure_stops_visibly_without_retry(self):
        self.env.update(FAKE_EXIT="1", FAKE_ERROR="Session not found")
        reply = self.invoke()
        self.assertFalse(reply["continue"])
        self.assertIn("Native codex exec fork exited 1: Session not found", reply["systemMessage"])
        self.assertNotIn("decision", reply)

    def test_explicit_review_error_is_not_completion(self):
        self.env["FAKE_RESULT"] = json.dumps({**RESULT, "status": "error", "reason": "Required context unavailable"})
        reply = self.invoke()
        self.assertFalse(reply["continue"])
        self.assertIn("Required context unavailable", reply["systemMessage"])

    def test_invalid_json_is_not_completion(self):
        for output in ["", "{}", "[]", "```json\n{}\n```", '{"status":"completed","status":"waiting"}',
                       json.dumps({**RESULT, "extra": True}), json.dumps({**RESULT, "reason": " "}),
                       json.dumps({**RESULT, "status": "actionable"}),
                       json.dumps({**RESULT, "next_steps": ["Unexpected work"]}),
                       json.dumps({**RESULT, "status": "actionable", "next_steps": [2]})]:
            with self.subTest(output=output):
                self.env["FAKE_RESULT"] = output
                self.assertFalse(self.invoke()["continue"])

    def test_bad_hook_input_is_visible(self):
        for raw in ("", "not JSON", "null", "[]"):
            with self.subTest(raw=raw):
                self.assertFalse(self.invoke(raw=raw)["continue"])
        self.assertFalse(self.log.exists())

    def test_missing_native_program_is_visible(self):
        self.env["PATH"] = str(self.folder / "missing")
        reply = self.invoke()
        self.assertFalse(reply["continue"])
        self.assertIn("FileNotFoundError", reply["systemMessage"])

    def test_no_added_process_or_session_lifecycle(self):
        native_result = subprocess.CompletedProcess([], 0, json.dumps(RESULT), "")
        with patch.dict(os.environ, {"STOP_REVIEW_CHILD": "0"}), patch.object(HOOK.subprocess, "run", return_value=native_result) as run:
            self.assertEqual(HOOK.review(EVENT), {})
        args, kwargs = run.call_args
        self.assertEqual(len(args), 1)
        self.assertFalse(kwargs.get("shell", False))
        self.assertFalse(kwargs.get("start_new_session", False))
        self.assertNotIn("preexec_fn", kwargs)
        self.assertNotIn("timeout", kwargs)
        self.assertNotIn("cwd", kwargs)

    def test_plugin_is_only_native_hook_script_and_prompt(self):
        manifest = json.loads((PLUGIN / ".codex-plugin/plugin.json").read_text())
        hooks = json.loads((PLUGIN / "hooks/hooks.json").read_text())
        self.assertNotIn("skills", manifest)
        self.assertEqual(set(hooks["hooks"]), {"Stop"})
        self.assertEqual(hooks["hooks"]["Stop"][0]["hooks"][0], {
            "type": "command", "command": 'python3 "${PLUGIN_ROOT}/scripts/stop_review.py"', "timeout": 600,
        })
        for old in ("pyproject.toml", "MANIFEST.in", "plugins/stop-review/stop_review", "plugins/stop-review/skills"):
            self.assertFalse((ROOT / old).exists())


if __name__ == "__main__":
    unittest.main()
