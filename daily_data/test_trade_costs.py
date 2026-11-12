import unittest
from decimal import Decimal
from daily_data.trade_costs import round_trip,assert_strategy_ready

class CostTests(unittest.TestCase):
    def test_delivery_stt_both_sides_and_stamp_buy_only(self):
        r=round_trip(100000,110000,'2023-06-01');c=r['components_inr']
        self.assertEqual(Decimal(c['stt']),Decimal('210'))
        self.assertEqual(Decimal(c['stamp_duty']),Decimal('15'))
        self.assertEqual(Decimal(c['exchange_first_tier']),Decimal('6.825'))
    def test_schedule_does_not_leak_into_unreviewed_years(self):
        for day in ('2023-03-31','2024-01-01','2026-11-05'):
            with self.assertRaises(ValueError):round_trip(100000,100000,day)
    def test_slippage_and_broker_dp_are_explicit_additive_costs(self):
        a=round_trip(100000,100000,'2023-06-01');b=round_trip(100000,100000,'2023-06-01',20,20,5)
        self.assertEqual(Decimal(b['total_cost_inr'])-Decimal(a['total_cost_inr']),Decimal('170.8'))
    def test_forecast_release_cannot_be_used_as_strategy_approval(self):
        with self.assertRaises(ValueError):assert_strategy_ready({'strategy_evaluation_eligible':False},{})
        with self.assertRaises(ValueError):assert_strategy_ready({'strategy_evaluation_eligible':True},{})
    def test_nonfinite_negative_and_zero_notional_rejected(self):
        for value in ('NaN','Infinity','-1','0'):
            with self.assertRaises(ValueError):round_trip(value,100000,'2023-06-01')
