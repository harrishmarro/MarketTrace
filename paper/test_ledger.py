import tempfile
import unittest
from pathlib import Path

from paper.ledger import Ledger


class PaperTests(unittest.TestCase):
    def setUp(self):
        self.ledger = Ledger()
        self.ledger.seed_cash('US', 100000)
        self.ledger.seed_cash('IN', 200000)
        self.limits(self.ledger)
        self.portfolio(self.ledger)

    @staticmethod
    def portfolio(ledger, concentration_bps=10000, daily_loss=1000000):
        ledger.configure_portfolio_limits('US', concentration_bps=concentration_bps, daily_loss=daily_loss)
        ledger.capture_day_start('US', 100)

    @staticmethod
    def limits(ledger, **changes):
        values = dict(max_value=1000000, max_shares=100, daily_value=10000000, daily_trades=100)
        ledger.configure_limits('US', **(values | changes))

    def order(self, **changes):
        args = dict(market='US', symbol='DEMO', side='buy', qty=2,
                    low=9900, high=10100, now=100, expires=160)
        return self.ledger.propose(**(args | changes))

    def test_explicit_approval_and_currency_isolation(self):
        oid = self.order()
        self.assertEqual(self.ledger.snapshot()['fills'], [])
        self.assertEqual(self.ledger.decide(oid, True, 110, 10000, 109), 'filled')
        self.assertEqual(self.ledger.snapshot()['cash'],
                         [{'market': 'US', 'amount': 80000}, {'market': 'IN', 'amount': 200000}])
        with self.assertRaises(ValueError):
            self.ledger.decide(oid, True, 111, 10000, 111)
        self.assertEqual(len(self.ledger.snapshot()['fills']), 1)

    def test_reject_expire_and_out_of_range_never_fill(self):
        for kwargs, approved, now, price, expected in [
            ({}, False, 110, 10000, 'rejected'),
            ({}, True, 160, 10000, 'expired'),
            ({}, True, 110, 10200, 'invalidated')]:
            oid = self.order(**kwargs)
            self.assertEqual(self.ledger.decide(oid, approved, now, price, now), expected)
        self.assertEqual(self.ledger.snapshot()['fills'], [])

    def test_bad_quote_and_funding_roll_back(self):
        for kwargs, price, quote_at in [({}, 10000, 100), ({}, 10000, 111),
                                        ({'qty': 20}, 10000, 110),
                                        ({'side': 'sell'}, 10000, 110)]:
            oid = self.order(**kwargs)
            before = self.ledger.snapshot()
            with self.assertRaises(ValueError):
                self.ledger.decide(oid, True, 110, price, quote_at)
            self.assertEqual(self.ledger.snapshot(), before)

    def test_buy_then_sell(self):
        self.ledger.decide(self.order(), True, 110, 10000, 110)
        self.ledger.decide(self.order(side='sell', qty=1), True, 120, 10100, 120)
        self.assertEqual(self.ledger.snapshot()['holdings'][0]['qty'], 1)
        self.assertEqual(self.ledger.snapshot()['cash'][0]['amount'], 90100)

    def test_restart_preserves_pending_and_fills(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / 'paper.db')
            first = Ledger(path)
            first.seed_cash('US', 100000)
            self.limits(first)
            self.portfolio(first)
            oid = first.propose('US', 'DEMO', 'buy', 1, 9900, 10100, 100, 160)
            first.db.close()
            second = Ledger(path)
            second.decide(oid, True, 110, 10000, 110)
            second.db.close()
            third = Ledger(path)
            self.assertEqual(len(third.snapshot()['fills']), 1)
            self.assertEqual(third.snapshot()['cash'][0]['amount'], 90000)
            third.db.close()

    def test_invalid_quantity_and_decision(self):
        for qty in (0, -1, 1.5, True):
            with self.assertRaises(ValueError):
                self.order(qty=qty)
        with self.assertRaises(ValueError):
            self.ledger.decide(self.order(), 'yes', 110, 10000, 110)

    def test_money_share_limits_and_missing_configuration(self):
        for changes in ({'max_value': 19999}, {'max_shares': 1}):
            self.limits(self.ledger, **changes)
            before = self.ledger.snapshot()
            oid = self.order()
            with self.assertRaises(ValueError):
                self.ledger.decide(oid, True, 110, 10000, 110)
            self.assertEqual(self.ledger.snapshot()['cash'], before['cash'])
            self.assertEqual(self.ledger.snapshot()['fills'], [])
        oid = self.order(market='IN')
        with self.assertRaisesRegex(ValueError, 'must be configured'):
            self.ledger.decide(oid, True, 110, 10000, 110)

    def test_splitting_orders_does_not_bypass_daily_value(self):
        self.limits(self.ledger, max_value=20000, daily_value=30000)
        self.ledger.decide(self.order(), True, 110, 10000, 110)
        with self.assertRaisesRegex(ValueError, 'Cumulative daily'):
            self.ledger.decide(self.order(), True, 120, 10000, 120)
        self.assertEqual(len(self.ledger.snapshot()['fills']), 1)

    def test_trade_count_and_kill_switch(self):
        self.limits(self.ledger, daily_trades=1)
        self.ledger.decide(self.order(), True, 110, 10000, 110)
        with self.assertRaisesRegex(ValueError, 'trade count'):
            self.ledger.decide(self.order(), True, 120, 10000, 120)
        self.ledger.halt('US')
        # Updating limits cannot silently clear the kill switch.
        self.limits(self.ledger)
        oid = self.order()
        with self.assertRaisesRegex(ValueError, 'halted'):
            self.ledger.decide(oid, True, 120, 10000, 120)
        self.assertEqual(self.ledger.decide(oid, False, 120), 'rejected')

    def test_daily_boundaries_are_exchange_local(self):
        from datetime import datetime
        def ts(value):
            return int(datetime.fromisoformat(value).timestamp())
        self.assertEqual(self.ledger.trading_date(ts('2026-11-02T01:00:00+00:00'), 'US').isoformat(),
                         '2026-11-01')
        self.assertEqual(self.ledger.trading_date(ts('2026-11-02T01:00:00+00:00'), 'IN').isoformat(),
                         '2026-11-02')

    def test_exact_limit_allowed(self):
        self.limits(self.ledger, max_value=20000, max_shares=2, daily_value=20000, daily_trades=1)
        self.assertEqual(self.ledger.decide(self.order(), True, 110, 10000, 110), 'filled')


if __name__ == '__main__':
    unittest.main()
