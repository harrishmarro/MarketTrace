"""Synthetic arithmetic, isolation and standalone-CLI cost regressions."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from decimal import Context, Decimal, Inexact, ROUND_UP, localcontext
from pathlib import Path

from daily_data.trade_costs import assert_strategy_ready, round_trip

ROOT = Path(__file__).resolve().parents[1]


class CostScenarioTests(unittest.TestCase):
    def test_historical_boundaries_inclusive(self):
        for day in ('2023-04-01', '2023-12-31'):
            self.assertEqual(round_trip('100000', '100000', day)['day'], day)

    def test_dates_are_canonical_and_explicit(self):
        for day in ('20230601', '2023-W22-4', '2023-02-30', '', None, 20230601):
            with self.subTest(day=day), self.assertRaises(ValueError):
                round_trip(100000, 100000, day)

    def test_all_amount_fields_reject_invalid_values(self):
        for index in range(5):
            for invalid in (True, False, None, 'NaN', 'sNaN', 'Infinity', '-1',
                            'not-money', '1e16', '1e-13', '1.0000000000000000000000000000'):
                args = [100000, 100000, 20, 20, 5]
                args[index] = invalid
                with self.subTest(field=index, value=invalid), self.assertRaises(ValueError):
                    round_trip(args[0], args[1], '2023-06-01', *args[2:])

    def test_complete_total_matches_hand_calculation(self):
        reference = round_trip('100000', '100000', '2023-06-01')
        expected = dict(stt='200', stamp_duty='15', exchange_first_tier='6.5',
                        sebi='.2', ipft='.2', brokerage='0', dp_fee='0',
                        gst_estimate='1.242', slippage_scenario='0')
        for name, value in expected.items():
            self.assertEqual(Decimal(reference['components_inr'][name]), Decimal(value))
        self.assertEqual(Decimal(reference['total_cost_inr']), Decimal('223.142'))
        self.assertEqual(Decimal(reference['cost_bps_of_buy']), Decimal('22.3142'))
        scenario = round_trip('100000', '100000', '2023-06-01', '20', '20', '5')
        self.assertEqual(Decimal(scenario['components_inr']['brokerage']), Decimal('40'))
        self.assertEqual(Decimal(scenario['components_inr']['gst_estimate']), Decimal('12.042'))
        self.assertEqual(Decimal(scenario['components_inr']['slippage_scenario']), Decimal('100'))
        self.assertEqual(Decimal(scenario['total_cost_inr']), Decimal('393.942'))

    def test_fractional_and_unequal_notionals_preserve_buy_denominator(self):
        result = round_trip('100.25', '125.50', '2023-06-01', '1.25', '.75', '2.5')
        parts = {key: Decimal(value) for key, value in result['components_inr'].items()}
        self.assertEqual(parts['stamp_duty'], Decimal('100.25') * Decimal('.00015'))
        self.assertEqual(parts['stt'], Decimal('225.75') * Decimal('.001'))
        self.assertEqual(parts['slippage_scenario'], Decimal('225.75') * Decimal('.00025'))
        self.assertEqual(Decimal(result['total_cost_inr']), sum(parts.values()))
        self.assertAlmostEqual(float(result['cost_as_fraction_of_buy']),
                               float(result['total_cost_inr']) / 100.25)

    def test_decimal_context_cannot_change_costs_or_leak(self):
        expected = round_trip('100000.123456', '110000.654321', '2023-06-01', '20', '20', '5')
        with localcontext() as caller:
            caller.prec = 4
            caller.rounding = ROUND_UP
            caller.traps[Inexact] = True
            actual = round_trip('100000.123456', '110000.654321', '2023-06-01', '20', '20', '5')
            self.assertEqual(actual, expected)
            self.assertEqual(caller.prec, 4)
            self.assertTrue(caller.traps[Inexact])

    def test_units_and_nonprofitability_flags_explicit(self):
        result = round_trip(100000, 100000, '2023-06-01')
        self.assertEqual((result['currency'], result['monetary_units']), ('INR', 'rupees'))
        self.assertEqual((result['schedule_start'], result['schedule_end']), ('2023-04-01', '2023-12-31'))
        self.assertFalse(result['profitability_evaluated'])
        self.assertFalse(result['ledger_fees_posted'])

    def test_maximum_fractional_inputs_keep_exact_component_arithmetic(self):
        value = '999999999999999.999999999999'
        result = round_trip(value, value, '2023-06-01', value, value, value)
        with localcontext(Context(prec=100)):
            turnover = Decimal(value) * 2
            expected_slippage = turnover * Decimal(value) / 10000
            self.assertEqual(Decimal(result['components_inr']['slippage_scenario']), expected_slippage)
            self.assertEqual(Decimal(result['total_cost_inr']),
                             sum(Decimal(v) for v in result['components_inr'].values()))

    def test_strategy_flags_require_literal_booleans(self):
        required = ('dividend_entitlement_and_cash_timing', 'decision_and_executable_fill_timing',
                    'cost_schedule_and_broker_profile', 'position_and_cash_constraints')
        review = dict.fromkeys(required, True)
        self.assertIsNone(assert_strategy_ready({'strategy_evaluation_eligible': True}, review))
        for truthy in (1, 'true'):
            with self.assertRaises(ValueError):
                assert_strategy_ready({'strategy_evaluation_eligible': truthy}, review)
            for key in required:
                with self.assertRaises(ValueError):
                    assert_strategy_ready({'strategy_evaluation_eligible': True}, {**review, key: truthy})

    def cli(self, folder, *args):
        return subprocess.run([sys.executable, '-m', 'daily_data.trade_costs', *args],
                              cwd=folder, env={**os.environ, 'PYTHONPATH': str(ROOT)},
                              capture_output=True, text=True, timeout=15)

    def test_cli_runs_in_empty_directory_without_research_files(self):
        with tempfile.TemporaryDirectory() as folder:
            result = self.cli(folder, '--buy-notional', '100000', '--sell-notional', '100000',
                              '--day', '2023-06-01', '--brokerage-per-order', '20',
                              '--dp-fee-ex-gst', '20', '--slippage-bps-each-side', '5')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(Decimal(json.loads(result.stdout)['total_cost_inr']), Decimal('393.942'))
            self.assertEqual(list(Path(folder).iterdir()), [])

    def test_cli_refuses_unsupported_dates_without_output_files(self):
        with tempfile.TemporaryDirectory() as folder:
            for day in ('2023-03-31', '2024-01-01', '2026-11-12'):
                result = self.cli(folder, '--buy-notional', '100000', '--sell-notional', '100000', '--day', day)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, '')
                self.assertIn('No reviewed cost schedule', result.stderr)
                self.assertNotIn('Traceback', result.stderr)
            self.assertEqual(list(Path(folder).iterdir()), [])


if __name__ == '__main__':
    unittest.main()
