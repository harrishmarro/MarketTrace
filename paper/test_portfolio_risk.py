import sqlite3
import unittest

from paper import test_ledger


class PortfolioRiskTests(unittest.TestCase):
    def setUp(self):
        helper = test_ledger.PaperTests()
        helper.setUp()
        self.ledger = helper.ledger
        self.order = helper.order

    def policy(self, concentration=10000, loss=1000000):
        self.ledger.configure_portfolio_limits('US', concentration_bps=concentration, daily_loss=loss)

    def fill(self, **changes):
        return self.ledger.decide(self.order(**changes), True, 110, 10000, 110)

    def test_concentration_exact_boundary_and_split_orders(self):
        self.policy(concentration=2000)
        self.fill()  # 20,000 / 100,000 = 20%.
        with self.assertRaisesRegex(ValueError, 'concentration'):
            self.fill(qty=1)
        self.assertEqual(len(self.ledger.snapshot()['fills']), 1)

    def test_current_marks_not_purchase_cost(self):
        self.fill()  # Own 2 shares; cash 80,000.
        self.policy(concentration=3000)
        self.ledger.mark('US', 'DEMO', 20000, 120)
        # Existing holding worth 40,000: another share makes 60,000 / 120,000 = 50%.
        with self.assertRaisesRegex(ValueError, 'concentration'):
            self.ledger.decide(self.order(symbol='DEMO', qty=1, low=19000, high=21000),
                               True, 120, 20000, 120)

    def test_unrealized_loss_blocks_buy_but_allows_sale(self):
        self.fill()
        self.policy(loss=1000)
        self.ledger.mark('US', 'DEMO', 9500, 120)
        with self.assertRaisesRegex(ValueError, 'Daily equity loss'):
            self.ledger.decide(self.order(symbol='OTHER', qty=1), True, 120, 10000, 120)
        self.assertEqual(self.ledger.decide(self.order(side='sell', qty=1, low=9000),
                                          True, 120, 9500, 120), 'filled')
        # Remaining 500 loss plus realized 500 loss still reaches the 1,000 threshold.
        with self.assertRaisesRegex(ValueError, 'Daily equity loss'):
            self.ledger.decide(self.order(symbol='OTHER', qty=1), True, 120, 10000, 120)

    def test_missing_stale_and_future_marks_block_other_buys(self):
        self.fill()
        for at in (None, 100, 121):
            if at is not None:
                self.ledger.mark('US', 'DEMO', 10000, at)
            with self.assertRaisesRegex(ValueError, 'Fresh marks'):
                self.ledger.decide(self.order(symbol='OTHER', qty=1), True, 120, 10000, 120)
        self.assertEqual(len(self.ledger.snapshot()['fills']), 1)

    def test_baseline_cannot_be_reset(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.ledger.capture_day_start('US', 120)
        self.fill()  # A failed reset doesn't leave an open transaction.

    def test_next_day_needs_new_baseline(self):
        with self.assertRaisesRegex(ValueError, 'session baseline'):
            self.ledger.decide(self.order(now=86400, expires=86500), True, 86410, 10000, 86410)
        self.ledger.capture_day_start('US', 86400)
        self.assertEqual(self.ledger.decide(self.order(now=86400, expires=86500),
                                          True, 86410, 10000, 86410), 'filled')

    def test_no_policy_cannot_fill_buy(self):
        self.ledger.db.execute('DELETE FROM portfolio_limits')
        with self.assertRaisesRegex(ValueError, 'Portfolio limits'):
            self.fill()


if __name__ == '__main__':
    unittest.main()
