"""Synthetic tests; no captured market prices or private release evidence."""
import copy
import csv
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

try:
    import numpy as np
except ModuleNotFoundError:
    np = None

if np is not None:
    from daily_data import forecast_evaluation as evaluation


@unittest.skipIf(np is None, 'Install requirements-forecast.txt for forecasting tests')
class ForecastEvaluationTests(unittest.TestCase):
    def test_future_bar_changes_do_not_change_earlier_features(self):
        rows = evaluation.synthetic_rows(90)
        before = evaluation.build_samples(rows)
        altered = copy.deepcopy(rows)
        altered[50].update(open=400, close=410, high=420, low=390, volume=99999)
        after = evaluation.build_samples(altered)
        for first, second in zip(before, after):
            if first['origin'] < rows[50]['day']:
                self.assertEqual(first['x'], second['x'])
        # An earlier forecast's outcome can change without changing its features.
        self.assertNotEqual(before[29]['y'], after[29]['y'])

    def test_labels_use_next_observation_and_features_have_expected_width(self):
        rows = evaluation.synthetic_rows(60)
        samples = evaluation.build_samples(rows)
        self.assertEqual(len(samples), 39)
        self.assertEqual(samples[0]['origin'], rows[20]['day'])
        self.assertEqual(samples[0]['target_day'], rows[21]['day'])
        self.assertEqual(len(samples[0]['x']), len(evaluation.FEATURES))
        self.assertAlmostEqual(samples[0]['y'], rows[21]['close']/rows[20]['close'] - 1)

    def test_duplicate_unordered_and_noniso_dates_are_rejected(self):
        rows = evaluation.synthetic_rows(60)
        cases = [rows[::-1], rows + [rows[-1]]]
        malformed = copy.deepcopy(rows)
        malformed[5]['day'] = 'not-a-date'
        cases.append(malformed)
        for bars in cases:
            with self.assertRaises(ValueError):
                evaluation.build_samples(bars)

    def test_invalid_ohlcv_and_empty_trailing_volume_are_rejected(self):
        for key, value in [('close', float('nan')), ('high', -1), ('low', 999),
                           ('volume', -1), ('volume', .5)]:
            bars = evaluation.synthetic_rows(60)
            bars[30][key] = value
            with self.subTest(key=key, value=value):
                with self.assertRaises(ValueError):evaluation.build_samples(bars)
        bars = evaluation.synthetic_rows(60)
        for bar in bars:bar['volume'] = 0
        with self.assertRaises(ValueError):evaluation.build_samples(bars)

    def test_partition_purges_boundary_spanning_labels(self):
        rows = evaluation.synthetic_rows()
        groups = evaluation.partition(evaluation.build_samples(rows), evaluation.demo_protocol(rows))
        self.assertEqual({k: len(v) for k, v in groups.items()},
                         {'train': 199, 'validation': 69, 'test': 69, 'excluded_boundary': 2})
        for name, first, last in [('validation', rows[220]['day'], rows[289]['day']),
                                  ('test', rows[290]['day'], rows[-1]['day'])]:
            self.assertTrue(all(r['origin'] >= first and r['target_day'] <= last for r in groups[name]))

    def test_overlapping_partition_bounds_and_reversed_targets_are_rejected(self):
        rows = evaluation.synthetic_rows()
        protocol = evaluation.demo_protocol(rows)
        samples = evaluation.build_samples(rows)
        for changes in ({'validation_start': protocol['training_end']},
                        {'test_start': protocol['validation_end']},
                        {'validation_end': protocol['validation_start'][:-2] + '01'}):
            with self.assertRaises(ValueError):evaluation.partition(samples, dict(protocol, **changes))
        sample = dict(samples[0], target_day=samples[0]['origin'])
        with self.assertRaises(ValueError):evaluation.partition([sample], protocol)

    def test_scaling_and_parameters_do_not_use_future_partitions(self):
        rows = evaluation.synthetic_rows()
        protocol = evaluation.demo_protocol(rows)
        groups = evaluation.partition(evaluation.build_samples(rows), protocol)
        train = groups['train']
        model = evaluation.fit([r['x'] for r in train], [r['y'] for r in train])
        np.testing.assert_allclose(model['center'], np.mean([r['x'] for r in train], axis=0))
        altered = copy.deepcopy(rows)
        for row in altered[220:]:
            for field in ('open', 'high', 'low', 'close'):row[field] *= 3
        altered_train = evaluation.partition(evaluation.build_samples(altered), protocol)['train']
        changed_model = evaluation.fit([r['x'] for r in altered_train], [r['y'] for r in altered_train])
        self.assertEqual(model, changed_model)

    def test_constant_feature_scaling_and_prediction_do_not_mutate_model(self):
        x = np.column_stack((np.arange(40), np.ones(40)))
        model = evaluation.fit(x, np.linspace(-.01, .02, 40))
        before = copy.deepcopy(model)
        predictions = evaluation.predict(model, x)
        self.assertTrue(np.isfinite(predictions).all())
        self.assertEqual(model['scale'][1], 1)
        self.assertEqual(model, before)

    def test_invalid_fit_and_prediction_shapes_or_regularization_are_rejected(self):
        x, y = np.ones((40, 2)), np.ones(40)
        for xx, yy in [(x, y[:-1]), (x[:, 0], y), (x, y[:, None]), (x[:20], y[:20])]:
            with self.assertRaises(ValueError):evaluation.fit(xx, yy)
        for alpha in (0, -1, float('nan'), float('inf')):
            with self.assertRaises(ValueError):evaluation.fit(x, y, alpha)
        model = evaluation.fit(x, y)
        with self.assertRaises(ValueError):evaluation.predict(model, np.ones((3, 4)))

    def test_zero_baseline_abstains_from_direction_and_metric_inputs_are_checked(self):
        result = evaluation.metrics([.1, -.1], [0, 0])
        self.assertIsNone(result['directional_accuracy'])
        self.assertEqual(result['directional_predictions'], 0)
        self.assertAlmostEqual(result['mae'], .1)
        for y, pred in [([], []), ([1, 2], [1]), ([float('nan')], [1])]:
            with self.assertRaises(ValueError):evaluation.metrics(y, pred)

    def test_demo_registers_before_fit_and_reproduces_outputs(self):
        with tempfile.TemporaryDirectory() as folder:
            first, second = Path(folder)/'first', Path(folder)/'second'
            original_fit = evaluation.fit
            def check_registration(*args, **kwargs):
                registration = json.loads((first/'registration.json').read_text())
                self.assertEqual(registration['data_kind'], 'synthetic')
                self.assertFalse((first/'result.json').exists())
                return original_fit(*args, **kwargs)
            with patch.object(evaluation, 'fit', side_effect=check_registration):
                report = evaluation.run_demo(first)
            self.assertEqual(report, evaluation.run_demo(second))
            for name in ('registration.json', 'predictions.csv', 'result.json'):
                self.assertEqual((first/name).read_bytes(), (second/name).read_bytes())
            expected = hashlib.sha256(json.dumps(evaluation.synthetic_rows(), sort_keys=True,
                                                separators=(',', ':')).encode()).hexdigest()
            self.assertEqual(report['input_sha256'], expected)
            with (first/'predictions.csv').open() as handle:predictions = list(csv.DictReader(handle))
            self.assertEqual(len(predictions), 138)
            self.assertTrue(all(row['data_kind'] == 'synthetic' for row in predictions))
            self.assertFalse(report['market_performance_evaluated'])
            self.assertFalse(report['profitability_evaluated'])

    def test_cli_requires_synthetic_mode_and_refuses_existing_outputs(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder)/'demo'
            command = [sys.executable, '-m', 'daily_data.forecast_evaluation', '--output', str(output)]
            cwd = Path(__file__).resolve().parents[1]
            rejected = subprocess.run(command, cwd=cwd, capture_output=True, text=True)
            self.assertNotEqual(rejected.returncode, 0)
            self.assertFalse(output.exists())
            accepted = subprocess.run(command + ['--synthetic'], cwd=cwd, capture_output=True, text=True, check=True)
            self.assertEqual(json.loads(accepted.stdout)['data_kind'], 'synthetic')
            before = (output/'result.json').read_bytes()
            with self.assertRaises(FileExistsError):evaluation.run_demo(output)
            self.assertEqual((output/'result.json').read_bytes(), before)
