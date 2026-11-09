import unittest
from daily_data.nse_universe import parse_master

class NSEUniverseTests(unittest.TestCase):
    def test_series_and_rights_are_retained_for_review(self):
        raw=b'SYMBOL,NAME OF COMPANY, SERIES, DATE OF LISTING, ISIN NUMBER\nABC,ABC Ltd,BE,01-JAN-2024,INE123456789\nABC-RE,ABC Rights,ST,04-Nov-26,INE123456788\n'
        rows=parse_master(raw,'sme')
        self.assertEqual(rows[0]['series'],'BE')
        self.assertEqual(rows[1]['listing_date'],'2026-11-04')
        self.assertEqual(rows[1]['instrument_review'],'rights_candidate')
        self.assertFalse(any(r['training_eligible'] for r in rows))
    def test_bad_identity_and_duplicates_fail(self):
        h=b'SYMBOL,NAME_OF_COMPANY,SERIES,DATE_OF_LISTING,ISIN_NUMBER\n'
        r=b'ABC,ABC Ltd,EQ,01-Jan-24,INE123456789\n'
        with self.assertRaises(ValueError):parse_master(h+r+r,'main_board')
        with self.assertRaises(ValueError):parse_master(h+b'ABC,ABC Ltd,EQ,01-Jan-24,\n','main_board')
