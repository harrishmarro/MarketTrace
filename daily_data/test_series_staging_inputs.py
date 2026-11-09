"""Synthetic integration checks for portable, input-driven series staging."""
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

from daily_data.ingest import ingest
from daily_data.nse_series import run


MASTER = 'SYMBOL,NAME_OF_COMPANY,SERIES,DATE_OF_LISTING,ISIN_NUMBER\n'
REPORT = (b'SYMBOL,SERIES,DATE1,OPEN_PRICE,HIGH_PRICE,LOW_PRICE,CLOSE_PRICE,TTL_TRD_QNTY\n'
          b'DEMO,EQ,30-Oct-2026,10,12,9,11,20\n'
          b'DEMO,BE,30-Oct-2026,10,12,9,11,30\n'
          b'NEW,SM,30-Oct-2026,10,12,9,11,40\n'
          b'BAD,SM,30-Oct-2026,10,8,9,11,50\n')


class StagingInputTests(unittest.TestCase):
    def inputs(self, folder):
        folder = Path(folder)
        main, sme = folder/'main.csv', folder/'sme.csv'
        main.write_text(MASTER + 'DEMO,Demo,EQ,01-Jan-2020,INE123456789\n'
                        'DEMO,Demo,BE,01-Jan-2020,INE123456789\n')
        sme.write_text(MASTER + 'NEW,New,SM,01-Nov-2026,INE123456788\n')
        db = folder/'daily.sqlite'
        ingest(db, 'nse', REPORT, 'synthetic-fixture', date(2026, 11, 1))
        return db, main, sme

    def test_explicit_paths_series_listing_cutoff_and_quarantine(self):
        with tempfile.TemporaryDirectory() as folder:
            db, main, sme = self.inputs(folder)
            report = run(db, Path(folder)/'nested/report.json', main, sme)
            rows = {(r['symbol'], r['series']): r for r in report['securities']}
            self.assertEqual(report['staged_unique_stock_series_days'], 3)
            self.assertEqual(report['quarantined_source_rows'], 1)
            self.assertEqual(rows['NEW', 'SM']['official_distinct_sessions'], 1)
            self.assertEqual(rows['NEW', 'SM']['sessions_on_or_after_listing'], 0)
            self.assertEqual(report['training_eligible_entries'], 0)
            with sqlite3.connect(db) as connection:
                volumes = dict(connection.execute(
                    "SELECT series,json_extract(payload,'$.volume') FROM nse_series_bars WHERE symbol='DEMO'"))
            self.assertEqual(volumes, {'EQ': '20', 'BE': '30'})

    def test_missing_master_does_not_mutate_database(self):
        with tempfile.TemporaryDirectory() as folder:
            db, main, _ = self.inputs(folder)
            before = db.read_bytes()
            with self.assertRaises(FileNotFoundError):
                run(db, Path(folder)/'report.json', main, Path(folder)/'absent.csv')
            self.assertEqual(db.read_bytes(), before)

    def test_missing_database_is_not_created(self):
        with tempfile.TemporaryDirectory() as folder:
            _, main, sme = self.inputs(folder)
            absent = Path(folder)/'absent.sqlite'
            with self.assertRaises(FileNotFoundError):
                run(absent, Path(folder)/'report.json', main, sme)
            self.assertFalse(absent.exists())

    def test_cli_accepts_explicit_input_and_output_locations(self):
        with tempfile.TemporaryDirectory() as folder:
            db, main, sme = self.inputs(folder)
            output = Path(folder)/'report.json'
            result = subprocess.run(
                [sys.executable, '-m', 'daily_data.nse_series', '--db', str(db),
                 '--main', str(main), '--sme', str(sme), '--output', str(output)],
                cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, check=True)
            self.assertEqual(json.loads(result.stdout)['inventory_entries'], 3)
            self.assertEqual(json.loads(output.read_text())['training_eligible_entries'], 0)
