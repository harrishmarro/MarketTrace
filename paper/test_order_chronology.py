"""Synthetic regression tests for proposal clocks and legacy database upgrades."""
import sqlite3
import tempfile
import unittest
from pathlib import Path

from paper.ledger import Ledger


class OrderChronologyTests(unittest.TestCase):
    def ledger(self, path=':memory:'):
        ledger = Ledger(path)
        self.addCleanup(ledger.db.close)
        ledger.seed_cash('US', 100000)
        ledger.configure_limits('US', max_value=100000, max_shares=10,
                                daily_value=1000000, daily_trades=10)
        ledger.configure_portfolio_limits('US', concentration_bps=10000, daily_loss=100000)
        ledger.capture_day_start('US', 100)
        return ledger

    def proposal(self, ledger):
        return ledger.propose('US', 'SYNTHETIC', 'buy', 1, 9900, 10100, 100, 160)

    def test_proposal_clock_is_stored_and_backdated_decisions_roll_back(self):
        ledger = self.ledger()
        order = self.proposal(ledger)
        self.assertEqual(ledger.snapshot()['orders'][0]['created_at'], 100)
        before = ledger.snapshot()
        for approved in (True, False):
            with self.subTest(approved=approved):
                with self.assertRaisesRegex(ValueError, 'predates proposal'):
                    ledger.decide(order, approved, 99, 10000, 99)
                self.assertEqual(ledger.snapshot(), before)
        self.assertEqual(ledger.decide(order, True, 100, 10000, 100), 'filled')

    def test_legacy_pending_order_stays_unfilled_until_replaced(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'legacy.sqlite'
            with sqlite3.connect(path) as db:
                db.execute('CREATE TABLE orders(id TEXT PRIMARY KEY,market TEXT,symbol TEXT,'
                           'side TEXT,qty INTEGER,low INTEGER,high INTEGER,expires INTEGER,status TEXT)')
                db.execute("INSERT INTO orders VALUES ('legacy','US','SYNTHETIC','buy',1,9900,10100,160,'pending')")
            ledger = self.ledger(path)
            self.assertIsNone(ledger.snapshot()['orders'][0]['created_at'])
            before = ledger.snapshot()
            with self.assertRaisesRegex(ValueError, 'Legacy proposal'):
                ledger.decide('legacy', True, 110, 10000, 110)
            self.assertEqual(ledger.snapshot(), before)
            self.assertEqual(ledger.decide('legacy', False, 110), 'rejected')
            replacement = self.proposal(ledger)
            self.assertEqual(ledger.decide(replacement, True, 110, 10000, 110), 'filled')

    def test_restart_preserves_proposal_clock(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'ledger.sqlite'
            first = self.ledger(path)
            order = self.proposal(first)
            first.db.close()
            resumed = Ledger(path)
            self.addCleanup(resumed.db.close)
            with self.assertRaisesRegex(ValueError, 'predates proposal'):
                resumed.decide(order, True, 99, 10000, 99)
            self.assertEqual(resumed.decide(order, True, 110, 10000, 110), 'filled')

    def test_fill_checks_current_risk_policy_instead_of_proposal_policy(self):
        ledger = self.ledger()
        order = self.proposal(ledger)
        ledger.configure_limits('US', max_value=9999, max_shares=10,
                                daily_value=1000000, daily_trades=10)
        before = ledger.snapshot()
        with self.assertRaisesRegex(ValueError, 'limit exceeded'):
            ledger.decide(order, True, 110, 10000, 110)
        self.assertEqual(ledger.snapshot(), before)

    def test_rejection_needs_no_quote_even_while_halted(self):
        ledger = self.ledger()
        order = self.proposal(ledger)
        ledger.halt('US')
        self.assertEqual(ledger.decide(order, False, 110), 'rejected')
        self.assertEqual(ledger.snapshot()['fills'], [])
