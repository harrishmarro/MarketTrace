"""Synthetic integration checks for portable, input-driven series staging."""
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

from daily_data.ingest import ingest
from daily_data.nse_series import run
from daily_data.nse_universe import run as universe_run


MASTER = 'SYMBOL,NAME_OF_COMPANY,SERIES,DATE_OF_LISTING,ISIN_NUMBER\n'
REPORT = (b'SYMBOL,SERIES,DATE1,OPEN_PRICE,HIGH_PRICE,LOW_PRICE,CLOSE_PRICE,TTL_TRD_QNTY\n'
          b'DEMO,EQ,30-Oct-2026,10,12,9,11,20\n'
          b'DEMO,BE,30-Oct-2026,10,12,9,11,30\n'
          b'NEW,SM,30-Oct-2026,10,12,9,11,40\n'
          b'BAD,SM,30-Oct-2026,10,8,9,11,50\n')


class StagingInputTests(unittest.TestCase):
    def reporters(self):
        return (
            ('series', lambda db, output, main, sme: run(db, output, main, sme)),
            ('universe', lambda db, output, main, sme: universe_run(db, main, sme, output)),
        )

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

    def test_report_cannot_overwrite_database_or_either_master(self):
        with tempfile.TemporaryDirectory() as folder:
            db, main, sme = self.inputs(folder)
            sources = (db, main, sme)
            before = {path: path.read_bytes() for path in sources}
            for name, reporter in self.reporters():
                for output in sources:
                    with self.subTest(reporter=name, output=output.name), self.assertRaisesRegex(ValueError, 'must not overwrite'):
                        reporter(db, output, main, sme)
                    self.assertEqual({path: path.read_bytes() for path in sources}, before)

    def test_normalized_report_path_alias_cannot_overwrite_database(self):
        with tempfile.TemporaryDirectory() as folder:
            db, main, sme = self.inputs(folder)
            nested = Path(folder) / 'nested'
            nested.mkdir()
            before = db.read_bytes()
            for name, reporter in self.reporters():
                with self.subTest(reporter=name), self.assertRaisesRegex(ValueError, 'must not overwrite'):
                    reporter(db, nested / '..' / db.name, main, sme)
                self.assertEqual(db.read_bytes(), before)

    def test_hardlinked_report_cannot_overwrite_source_files(self):
        with tempfile.TemporaryDirectory() as folder:
            db, main, sme = self.inputs(folder)
            sources = (db, main, sme)
            before = {path: path.read_bytes() for path in sources}
            output = Path(folder) / 'report.json'
            for source in sources:
                os.link(source, output)
                try:
                    for name, reporter in self.reporters():
                        with self.subTest(reporter=name, source=source.name), self.assertRaisesRegex(ValueError, 'must not overwrite'):
                            reporter(db, output, main, sme)
                        self.assertEqual({path: path.read_bytes() for path in sources}, before)
                finally:
                    output.unlink()

    def test_cli_rejects_destructive_output_before_mutating_sources(self):
        with tempfile.TemporaryDirectory() as folder:
            db, main, sme = self.inputs(folder)
            sources = (db, main, sme)
            before = {path: path.read_bytes() for path in sources}
            for module in ('daily_data.nse_series', 'daily_data.nse_universe'):
                result = subprocess.run(
                    [sys.executable, '-m', module, '--db', str(db),
                     '--main', str(main), '--sme', str(sme), '--output', str(db)],
                    cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True)
                self.assertEqual(result.returncode, 2, module)
                self.assertIn('must not overwrite', result.stderr)
                self.assertNotIn('Traceback', result.stderr)
                self.assertEqual(result.stdout, '')
                self.assertEqual({path: path.read_bytes() for path in sources}, before)

    def test_universe_separate_report_preserves_source_bytes(self):
        with tempfile.TemporaryDirectory() as folder:
            db, main, sme = self.inputs(folder)
            sources = (db, main, sme)
            before = {path: path.read_bytes() for path in sources}
            output = Path(folder) / 'universe.json'
            result = universe_run(db, main, sme, output)
            self.assertEqual(result['inventory_rows'], 3)
            self.assertEqual(result['training_eligible_rows'], 0)
            self.assertEqual(json.loads(output.read_text()), result)
            self.assertEqual({path: path.read_bytes() for path in sources}, before)

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
