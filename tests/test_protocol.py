import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from protocol import Completion, trace_state
from report import validate


class ProtocolTest(unittest.TestCase):
    def observe(self, completion, now, **kwargs):
        values = dict(alive=True, ready=True, active=set(), statuses=2, errors=[], count=10, cpu_percent=0.5)
        values.update(kwargs)
        return completion.observe(now, **values)

    def test_empty_ui_without_refresh_times_out(self):
        c = Completion(2, 0)
        self.assertFalse(self.observe(c, 1))
        self.assertFalse(self.observe(c, 5))
        with self.assertRaises(TimeoutError):
            self.observe(c, 120)

    def test_requires_quiet_window_after_completed_refresh(self):
        c = Completion(1, 0)
        self.assertFalse(self.observe(c, 1, active={'git'}))
        self.assertFalse(self.observe(c, 2))
        self.assertFalse(self.observe(c, 4))
        self.assertTrue(self.observe(c, 5))

    def test_new_activity_and_busy_ui_reset_window(self):
        c = Completion(1, 0)
        self.assertFalse(self.observe(c, 1))
        self.assertFalse(self.observe(c, 3, count=11))
        self.assertFalse(self.observe(c, 5, ready=False))
        self.assertFalse(self.observe(c, 6))
        self.assertTrue(self.observe(c, 9))

    def test_ignored_deletion_needs_cpu_evidence_even_with_empty_ui(self):
        c = Completion(0, 0, require_status=False)
        self.assertFalse(self.observe(c, 1, statuses=0, cpu_percent=None))
        self.assertFalse(self.observe(c, 5, statuses=0, cpu_percent=20))
        self.assertFalse(self.observe(c, 6, statuses=0))
        self.assertTrue(self.observe(c, 9, statuses=0))

    def test_crash_and_failed_status_are_errors(self):
        for kwargs in [{'alive': False}, {'errors': ['failure']}]:
            with self.subTest(kwargs=kwargs), self.assertRaises(RuntimeError):
                self.observe(Completion(1, 0), 1, **kwargs)

    def test_old_status_exit_cannot_prove_new_refresh(self):
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory) / 'trace'
            p.write_text('\n'.join(json.dumps(e) for e in [
                {'event': 'start', 'sid': '1', 'argv': ['git', 'status'], 'time': '2026-01-01T00:00:00Z'},
                {'event': 'exit', 'sid': '1', 'code': 0, 'time': '2026-01-01T00:00:10Z'},
            ]))
            self.assertEqual(trace_state(p, since=1767225605)[1], 0)

    def test_trace_counts_only_successful_status_and_tracks_active_commands(self):
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory) / 'trace'
            events = [
                {'event': 'start', 'sid': '1', 'argv': ['git', 'status']},
                {'event': 'exit', 'sid': '1', 'code': 0},
                {'event': 'start', 'sid': '2', 'argv': ['git', 'diff']},
                {'event': 'exit', 'sid': '2', 'code': 0},
                {'event': 'start', 'sid': '3', 'argv': ['git', 'status']},
                {'event': 'exit', 'sid': '3', 'code': 1},
                {'event': 'start', 'sid': '4', 'argv': ['git', 'status']},
            ]
            p.write_text('\n'.join(json.dumps(e) for e in events) + '\n{"partial":')
            active, statuses, errors, _ = trace_state(p)
            self.assertEqual(active, {'4'})
            self.assertEqual(statuses, 1)
            self.assertEqual(len(errors), 1)


class ReportTest(unittest.TestCase):
    def setUp(self):
        self.editors = [{'id': editor} for editor in ['vscode', 'lvce', 'atom']]
        self.fixture = {'commit': 'pinned'}
        self.results = [dict(editor=editor, trial=1, status='ok', deleted=True,
                             fixture=self.fixture, baselineStatuses=1, finalStatuses=2,
                             totalSeconds=5, deletionSeconds=1, afterDeletionSeconds=4, refreshObserved=True,
                             cpuEvidence=[dict(seconds=i*.25, cpuPercent=.5, ready=True, activeGit=0, traceLines=20) for i in range(13)])
                        for editor in self.editors]

    def test_complete_inventory(self):
        validate(self.results, 1, self.editors, self.fixture)

    def test_no_refresh_requires_valid_cpu_and_ui_evidence(self):
        self.results[0].update(finalStatuses=1, refreshObserved=False)
        validate(self.results, 1, self.editors, self.fixture)
        self.results[0]['cpuEvidence'][4]['cpuPercent'] = 80
        with self.assertRaises(ValueError):
            validate(self.results, 1, self.editors, self.fixture)

    def test_rejects_missing_duplicate_and_failed_trials(self):
        for results in [self.results[:-1], self.results + [self.results[0]]]:
            with self.assertRaises(ValueError):
                validate(results, 1, self.editors, self.fixture)
        for key, value in [('status', 'failed'), ('totalSeconds', float('nan')),
                           ('totalSeconds', 0), ('finalStatuses', 1), ('cpuEvidence', []), ('deleted', False),
                           ('afterDeletionSeconds', 100)]:
            results = copy.deepcopy(self.results)
            results[0][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate(results, 1, self.editors, self.fixture)


if __name__ == '__main__':
    unittest.main()
