"""Public CLI checks through a controlled WebSocket peer, using only unittest."""

import asyncio
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'plugins/stop-review'))
from stop_review import review
from stop_review import client

SCRIPT = ROOT / 'plugins/stop-review/scripts/stop_review.py'
EVENT = {'hook_event_name': 'Stop', 'session_id': 'shared-session', 'turn_id': 'main-turn',
         'stop_hook_active': False, 'model': 'actual-model'}


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.host = Path(self.temporary.name)
        shim = self.host / 'codex'
        shim.write_text(f'#!{sys.executable}\nimport runpy\nrunpy.run_path({str(ROOT / "tests/peer.py")!r})\n')
        shim.chmod(0o700)
        self.environment = patch.dict(os.environ, {
            'PATH': str(self.host) + os.pathsep + os.environ['PATH'],
            'CODEX_HOME': str(self.host), 'CODEX_THREAD_ID': 'main',
            'STOP_REVIEW_TEST_ROOT': str(self.host),
        })
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.options()
        bound = self.invoke('bind')
        self.assertEqual(bound.returncode, 0, bound.stderr)

    def options(self, **values):
        (self.host / 'options.json').write_text(json.dumps(values))

    def invoke(self, command='hook', event=None):
        return subprocess.run([sys.executable, str(SCRIPT), command], text=True,
                              input=json.dumps(EVENT if event is None else event),
                              capture_output=True, timeout=15)

    def wire(self):
        return [json.loads(line) for line in (self.host / 'wire.jsonl').read_text().splitlines()]

    def stop(self, event=None):
        result = self.invoke(event=event)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_native_fork_and_schema(self):
        self.assertEqual(self.stop(), {})
        calls = self.wire()
        fork = next(m['params'] for m in calls if m.get('method') == 'thread/fork')
        self.assertEqual(fork, {
            'threadId': 'main', 'model': 'actual-model', 'modelProvider': 'provider',
            'excludeTurns': True, 'sandbox': 'read-only', 'approvalPolicy': 'never',
            'deferGoalContinuation': True,
        })
        starts = [m['params'] for m in calls if m.get('method') == 'turn/start']
        self.assertEqual([m['threadId'] for m in starts], ['reviewer'])
        self.assertEqual(starts[0]['outputSchema'], review.SCHEMA)
        self.assertEqual(starts[0]['input'][0]['text'],
                         (ROOT / 'plugins/stop-review/stop_review/prompt.md').read_text())
        methods = [m.get('method') for m in calls]
        self.assertLess(methods.index('thread/goal/clear'), methods.index('thread/goal/get'))
        self.assertLess(methods.index('thread/goal/get'), methods.index('turn/start'))
        self.assertTrue(all(m['params']['threadId'] == 'reviewer' for m in calls
                            if m.get('method', '').startswith('thread/goal/')))

    def test_decisions(self):
        for status, steps in [('completed', []), ('waiting', []), ('actionable', ['Run the requested check'])]:
            with self.subTest(status=status):
                self.options(child=status, output=json.dumps({
                    'status': status, 'reason': 'Evidence-based reason', 'next_steps': steps,
                }))
                expected = {'decision': 'block', 'reason': 'Evidence-based reason\n' + steps[0]} if steps else {}
                self.assertEqual(self.stop(), expected)

    def test_foreign_events_and_shared_session_forks_do_not_recurse(self):
        for change in [{'session_id': 'unbound'}, {'hook_event_name': 'Interrupt'},
                       {'hook_event_name': 'SubagentStop'}, {'turn_id': 'review-turn'}]:
            with self.subTest(change=change):
                self.assertEqual(self.stop({**EVENT, **change}), {})
        self.assertFalse(any(m.get('method') == 'thread/fork' for m in self.wire()))

    def test_stopped_or_changed_main_is_never_revived(self):
        for values in [{'stopped': True}, {'current_turn': 'new-turn'}, {'stop_during_review': True}]:
            with self.subTest(values=values):
                self.options(**values, output=json.dumps({
                    'status': 'actionable', 'reason': 'Work remains', 'next_steps': ['Continue'],
                }))
                self.assertEqual(self.stop(), {})
        self.assertTrue(all(m['params']['threadId'] != 'main' for m in self.wire()
                            if m.get('method') in ('turn/start', 'turn/interrupt')))

    def test_errors_are_visible_and_bounded(self):
        cases = [
            {'rpc_error': 'thread/fork'}, {'fork_model': 'wrong'}, {'fork_provider': 'wrong'},
            {'fork_parent': 'other'}, {'child': 'main'}, {'output': 'not JSON'},
            {'goal': {'objective': 'continue work'}}, {'outcome': 'interrupted'},
            {'output': '{"status":"actionable","reason":"gap","next_steps":[]}'},
            {'output': '{"status":"error","reason":"evidence unavailable","next_steps":[]}'},
        ]
        for number, values in enumerate(cases):
            with self.subTest(values=values):
                values = {'child': f'reviewer-{number}', **values}
                self.options(**values)
                self.assertEqual(self.stop()['decision'], 'block')
                if values.get('child') != 'main':
                    values['child'] += '-two'
                self.options(**values)
                result = self.stop({**EVENT, 'stop_hook_active': True})
                self.assertIs(result['continue'], False)
                self.assertTrue(result['systemMessage'])

    def test_schema_rejects_ambiguous_output(self):
        cases = ['[]', 'null', '{}', '{"status":"unknown","reason":"x","next_steps":[]}',
                 '{"status":"completed","reason":" ","next_steps":[]}',
                 '{"status":"completed","reason":"x","next_steps":["do more"]}',
                 '{"status":"actionable","reason":"x","next_steps":[1]}',
                 '{"status":"completed","reason":"x","reason":"y","next_steps":[]}',
                 '{"status":"completed","reason":"x","next_steps":[],"extra":true}',
                 '```json\n{"status":"completed","reason":"x","next_steps":[]}\n```']
        for text in cases:
            with self.subTest(text=text), self.assertRaises((ValueError, TypeError)):
                review.parse_result(text)

    def test_malformed_hook_fails_closed(self):
        self.assertIs(self.stop({**EVENT, 'stop_hook_active': 'false'})['continue'], False)
        self.assertFalse(any(m.get('method') == 'thread/fork' for m in self.wire()))

    def test_root_identity_and_reviewer_rebinding(self):
        self.assertEqual(self.stop(), {})
        with patch.dict(os.environ, {'CODEX_THREAD_ID': 'reviewer'}):
            result = self.invoke('bind')
            self.assertEqual(result.returncode, 1)
            self.assertIn('reviewer cannot bind', result.stderr)
        with patch.dict(os.environ, {'CODEX_THREAD_ID': 'child'}):
            self.options(parent='main')
            self.assertEqual(self.invoke('bind').returncode, 1)

    def test_binding_idempotent_and_foreign_binding_rejected(self):
        self.assertEqual(self.invoke('bind').returncode, 0)
        with patch.dict(os.environ, {'CODEX_THREAD_ID': 'different-root'}):
            self.assertEqual(self.invoke('bind').returncode, 1)

    def test_foreign_output_and_observed_usage(self):
        usage = {'last': {'inputTokens': 120, 'cachedInputTokens': 0, 'outputTokens': 21}}
        self.options(foreign_output=True, usage=usage, request_tool=True)
        self.assertEqual(self.stop(), {})
        record = json.loads(next((self.host / 'stop-review/reviews').glob('*.json')).read_text())
        self.assertEqual(record['usage'], usage)
        reply = next(m for m in self.wire() if m.get('id') == 'tool-call')
        self.assertIn('error', reply)

    def test_timeout_cancels_owned_reviewer(self):
        self.options(hold=True)
        with patch.object(review, 'REVIEW_TIMEOUT', 0.1):
            result = asyncio.run(review.check(EVENT))
        self.assertEqual(result['decision'], 'block')
        interrupts = [m['params'] for m in self.wire() if m.get('method') == 'turn/interrupt']
        self.assertEqual(interrupts, [{'threadId': 'reviewer', 'turnId': 'review-turn'}])

    def test_uncertain_start_is_reconciled_and_cancelled(self):
        self.options(hold=True, malformed_start=True)
        result = self.stop()
        self.assertEqual(result['decision'], 'block')
        interrupts = [m['params'] for m in self.wire() if m.get('method') == 'turn/interrupt']
        self.assertEqual(interrupts, [{'threadId': 'reviewer', 'turnId': 'review-turn'}])

    def test_lost_start_reply_is_reconciled_and_cancelled(self):
        self.options(hold=True, drop_start_reply=True)
        with patch.object(client, 'RPC_TIMEOUT', 0.3):
            result = asyncio.run(review.check(EVENT))
        self.assertEqual(result['decision'], 'block')
        interrupts = [m['params'] for m in self.wire() if m.get('method') == 'turn/interrupt']
        self.assertEqual(interrupts, [{'threadId': 'reviewer', 'turnId': 'review-turn'}])

    def test_lost_start_reply_with_only_inherited_turn_is_unconfirmed(self):
        (self.host / 'child-turn.json').write_text(json.dumps({
            'id': 'old-completed', 'status': 'completed', 'items': [],
        }))
        self.options(hold=True, drop_start_reply=True, hide_started_turn=True)
        with patch.object(client, 'RPC_TIMEOUT', 0.3):
            result = asyncio.run(review.check(EVENT))
        self.assertEqual(result['decision'], 'block')
        self.assertIn('cancellation unconfirmed', result['reason'])
        self.assertFalse(any(m.get('method') == 'turn/interrupt' for m in self.wire()))

    def test_start_cannot_claim_inherited_turn_identity(self):
        (self.host / 'child-turn.json').write_text(json.dumps({
            'id': 'old-completed', 'status': 'completed', 'items': [],
        }))
        self.options(hold=True, review_turn='old-completed')
        result = self.stop()
        self.assertEqual(result['decision'], 'block')
        self.assertIn('cancellation unconfirmed', result['reason'])
        self.assertFalse(any(m.get('method') == 'turn/interrupt' for m in self.wire()))

    def test_invalid_start_status_cancels_exact_reviewer(self):
        self.options(hold=True, invalid_start_status=True)
        result = self.stop()
        self.assertEqual(result['decision'], 'block')
        interrupts = [m['params'] for m in self.wire() if m.get('method') == 'turn/interrupt']
        self.assertEqual(interrupts, [{'threadId': 'reviewer', 'turnId': 'review-turn'}])

    def test_goals_disabled_host_still_reviews(self):
        self.options(goals_disabled=True)
        self.assertEqual(self.stop(), {})
        self.assertTrue(any(m.get('method') == 'turn/start' for m in self.wire()))

    def test_deadline_includes_initial_connection(self):
        class SlowConnection:
            async def __aenter__(self):
                await asyncio.sleep(5)
            async def __aexit__(self, *args):
                pass
        before = time.monotonic()
        with patch.object(review, 'Client', return_value=SlowConnection()), patch.object(review, 'WORK_TIMEOUT', 0.05):
            with self.assertRaises(TimeoutError):
                asyncio.run(review.check(EVENT))
        self.assertLess(time.monotonic() - before, 1)

    def test_interrupt_hook_cleans_up_after_stop_process_killed(self):
        self.options(hold=True)
        process = subprocess.Popen([sys.executable, str(SCRIPT), 'hook'], stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            process.stdin.write(json.dumps(EVENT))
            process.stdin.close()
            deadline = time.monotonic() + 5
            while not (self.host / 'review-started').exists() and time.monotonic() < deadline:
                time.sleep(0.02)
            self.assertTrue((self.host / 'review-started').exists())
            process.kill()
            process.wait(timeout=5)
            self.assertEqual(self.stop({**EVENT, 'hook_event_name': 'Interrupt', 'turn_id': 'foreign'}), {})
            self.assertFalse(any(m.get('method') == 'turn/interrupt' for m in self.wire()))
            result = self.stop({**EVENT, 'hook_event_name': 'Interrupt'})
            self.assertEqual(result, {})
            interrupts = [m['params'] for m in self.wire() if m.get('method') == 'turn/interrupt']
            self.assertEqual(interrupts, [{'threadId': 'reviewer', 'turnId': 'review-turn'}])
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
            process.stdout.close()
            process.stderr.close()

    def test_interrupt_unconfirmed_cleanup_is_visible(self):
        record = self.host / 'stop-review/reviewers' / (review.key('reviewer') + '.json')
        review.write_json(record, {'thread_id': 'reviewer', 'turn_id': 'review-turn',
                                  'parent': 'main', 'parent_turn': 'main-turn', 'previous_turn': None})
        self.options()
        result = self.stop({**EVENT, 'hook_event_name': 'Interrupt'})
        self.assertIn('cancellation unconfirmed', result['systemMessage'])
        self.assertNotIn('decision', result)

    def test_interrupt_does_not_mistake_inherited_turn_for_cancelled_review(self):
        record = self.host / 'stop-review/reviewers' / (review.key('reviewer') + '.json')
        review.write_json(record, {'thread_id': 'reviewer', 'parent': 'main',
                                  'parent_turn': 'main-turn', 'previous_turn': 'inherited-turn'})
        (self.host / 'child-turn.json').write_text(json.dumps({
            'id': 'inherited-turn', 'status': 'completed', 'items': [],
        }))
        result = self.stop({**EVENT, 'hook_event_name': 'Interrupt'})
        self.assertIn('cancellation unconfirmed', result['systemMessage'])
        self.assertFalse(any(m.get('method') == 'turn/interrupt' for m in self.wire()))

    def test_interrupt_legacy_record_requires_known_turn(self):
        record = self.host / 'stop-review/reviewers' / (review.key('reviewer') + '.json')
        identity = {'thread_id': 'reviewer', 'parent': 'main', 'parent_turn': 'main-turn'}
        review.write_json(record, identity)
        result = self.stop({**EVENT, 'hook_event_name': 'Interrupt'})
        self.assertIn('cancellation unconfirmed', result['systemMessage'])
        review.write_json(record, {**identity, 'turn_id': 'review-turn'})
        (self.host / 'child-turn.json').write_text(json.dumps({
            'id': 'review-turn', 'status': 'inProgress', 'items': [],
        }))
        self.assertEqual(self.stop({**EVENT, 'hook_event_name': 'Interrupt'}), {})

    def test_interrupt_binding_failure_uses_interrupt_contract(self):
        binding = next((self.host / 'stop-review/bindings').glob('*.json'))
        binding.write_text('invalid JSON')
        result = self.stop({**EVENT, 'hook_event_name': 'Interrupt'})
        self.assertEqual(set(result), {'systemMessage'})
        self.assertIn('Completion hook failed', result['systemMessage'])

    def test_sigterm_cancels_without_continuation(self):
        self.options(hold=True)
        process = subprocess.Popen([sys.executable, str(SCRIPT), 'hook'], stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            process.stdin.write(json.dumps(EVENT))
            process.stdin.close()
            deadline = time.monotonic() + 5
            while not (self.host / 'review-started').exists() and time.monotonic() < deadline:
                time.sleep(0.02)
            self.assertTrue((self.host / 'review-started').exists())
            process.send_signal(signal.SIGTERM)
            process.wait(timeout=10)
            self.assertEqual(process.returncode, 130, process.stderr.read())
            self.assertEqual(process.stdout.read(), '')
            self.assertTrue(any(m.get('method') == 'turn/interrupt' for m in self.wire()))
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
            process.stdout.close()
            process.stderr.close()

    def test_package_paths(self):
        plugin = ROOT / 'plugins/stop-review'
        manifest = json.loads((plugin / '.codex-plugin/plugin.json').read_text())
        hooks = json.loads((plugin / manifest['hooks']).read_text())
        self.assertEqual(hooks['hooks']['Stop'][0]['hooks'][0]['command'],
                         'python3 "${PLUGIN_ROOT}/scripts/stop_review.py" hook')
        catalog = json.loads((ROOT / '.agents/plugins/marketplace.json').read_text())
        self.assertEqual((ROOT / catalog['plugins'][0]['source']['path']).resolve(), plugin)

    def test_state_is_private_atomic_and_no_clobber(self):
        root = self.host / 'stop-review'
        binding = next((root / 'bindings').glob('*.json'))
        self.assertEqual(root.stat().st_mode & 0o777, 0o700)
        self.assertEqual(binding.parent.stat().st_mode & 0o777, 0o700)
        self.assertEqual(binding.stat().st_mode & 0o777, 0o600)
        original = binding.read_bytes()
        with self.assertRaises(FileExistsError):
            review.write_json(binding, {'unexpected': True}, exclusive=True)
        self.assertEqual(binding.read_bytes(), original)
        self.assertEqual(list(binding.parent.iterdir()), [binding])
        self.assertEqual(self.stop(), {})
        for path in (root / 'reviewers').glob('*.json'):
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(path.parent.stat().st_mode & 0o777, 0o700)


if __name__ == '__main__':
    unittest.main()
