"""Synthetic regressions for false-green CI and replay boundary failures."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from scripts.verify_project import compare_demo_outputs, require_success, select_tests


def write_pair(root, changes=None):
    registration = dict(data_kind='synthetic', market_data_approved=False,
                        strategy_evaluation_approved=False)
    report = dict(data_kind='synthetic', market_performance_evaluated=False,
                  profitability_evaluated=False, strategy_evaluation_approved=False)
    for folder in (root / 'first', root / 'second'):
        folder.mkdir()
        (folder / 'registration.json').write_text(json.dumps(registration))
        (folder / 'result.json').write_text(json.dumps(report))
        (folder / 'predictions.csv').write_text('data_kind,actual_return\nsynthetic,0.001\n')
    if changes:
        for folder in (root / 'first', root / 'second'):
            changed = copy.deepcopy(report)
            changed.update(changes)
            (folder / 'result.json').write_text(json.dumps(changed))


class ProjectVerificationTests(unittest.TestCase):
    def test_empty_result_is_not_success(self):
        with self.assertRaisesRegex(RuntimeError, 'No tests'):
            require_success(unittest.TestResult())

    def test_successful_result_accepted(self):
        result = unittest.TestResult()
        unittest.FunctionTestCase(lambda: None).run(result)
        require_success(result)

    def test_failures_and_errors_rejected(self):
        for error in (AssertionError('failure'), ValueError('error')):
            def fail():
                raise error
            result = unittest.TestResult()
            unittest.FunctionTestCase(fail).run(result)
            with self.assertRaisesRegex(RuntimeError, 'failed'):
                require_success(result)

    def test_skipped_test_cannot_pass_full_check(self):
        def skip():
            raise unittest.SkipTest('missing optional dependency')
        result = unittest.TestResult()
        unittest.FunctionTestCase(skip).run(result)
        self.assertTrue(result.wasSuccessful())
        with self.assertRaisesRegex(RuntimeError, 'Unexpected skipped'):
            require_success(result)

    def test_core_excludes_only_the_named_optional_module(self):
        core = unittest.FunctionTestCase(lambda: None)
        forecast = unittest.FunctionTestCase(lambda: None)
        core.id = lambda: 'daily_data.test_ingest.Example.test_core'
        forecast.id = lambda: 'daily_data.test_forecast_evaluation.Example.test_forecast'
        suite = unittest.TestSuite([unittest.TestSuite([core, forecast])])
        selected, excluded = select_tests(suite, 'core')
        self.assertEqual(selected.countTestCases(), 1)
        self.assertEqual(excluded, 1)
        selected, excluded = select_tests(suite, 'full')
        self.assertEqual(selected.countTestCases(), 2)
        self.assertEqual(excluded, 0)
        with self.assertRaises(ValueError):
            select_tests(suite, 'unknown')

    def test_matching_synthetic_artifacts_accepted(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_pair(root)
            compare_demo_outputs(root / 'first', root / 'second')

    def test_changed_artifact_fails_replay(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_pair(root)
            (root / 'second' / 'predictions.csv').write_text('data_kind,actual_return\nsynthetic,0.002\n')
            with self.assertRaisesRegex(ValueError, 'differs'):
                compare_demo_outputs(root / 'first', root / 'second')

    def test_equal_files_do_not_hide_market_or_strategy_flags(self):
        for changes in ({'data_kind': 'market'}, {'profitability_evaluated': True},
                        {'market_performance_evaluated': True},
                        {'strategy_evaluation_approved': True}):
            with self.subTest(changes=changes), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                write_pair(root, changes)
                with self.assertRaises(ValueError):
                    compare_demo_outputs(root / 'first', root / 'second')

    def test_empty_or_nonsynthetic_predictions_rejected(self):
        for payload in ('data_kind,actual_return\n', 'data_kind,actual_return\nmarket,0.001\n'):
            with tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                write_pair(root)
                for folder in ('first', 'second'):
                    (root / folder / 'predictions.csv').write_text(payload)
                with self.assertRaises(ValueError):
                    compare_demo_outputs(root / 'first', root / 'second')

    def test_missing_artifact_is_an_error(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_pair(root)
            (root / 'second' / 'registration.json').unlink()
            with self.assertRaises(FileNotFoundError):
                compare_demo_outputs(root / 'first', root / 'second')


if __name__ == '__main__':
    unittest.main()
