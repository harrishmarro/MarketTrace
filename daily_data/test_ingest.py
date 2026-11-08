import copy
import io
import json
import sqlite3
import tempfile
import unittest
import zipfile
from datetime import date
from pathlib import Path

from daily_data.ingest import ingest, parse_nse, parse_yahoo


NSE = (b'SYMBOL, SERIES, DATE1, OPEN_PRICE, HIGH_PRICE, LOW_PRICE, CLOSE_PRICE, TTL_TRD_QNTY\n'
       b'DEMO, EQ, 30-Oct-2026, 100, 110, 90, 105, 1234\n')


def yahoo():
    return {'chart': {'error': None, 'result': [{
        'meta': {'symbol': 'DEMO', 'currency': 'USD', 'instrumentType': 'EQUITY',
                 'exchangeTimezoneName': 'America/New_York', 'dataGranularity': '1d'},
        'timestamp': [1793367000],
        'indicators': {'quote': [{'open': [100], 'high': [110], 'low': [90],
                                  'close': [105], 'volume': [1234]}],
                       'adjclose': [{'adjclose': [52.5]}]}}]}}


class IngestTests(unittest.TestCase):
    def test_nse_whitespace_series_and_cutoff(self):
        rows, excluded = parse_nse(NSE + b'OTHER, BE, 30-Oct-2026, 1, 1, 1, 1, 1\n', date(2026, 11, 2))
        self.assertEqual(len(rows), 1)
        self.assertEqual(excluded, 1)
        self.assertEqual(rows[0]['currency'], 'INR')
        self.assertEqual(parse_nse(NSE, date(2026, 10, 30))[0], [])

    def test_udiff_zip(self):
        raw = (b'TckrSymb,SctySrs,TradDt,OpnPric,HghPric,LwPric,ClsPric,TtlTradgVol\n'
               b'DEMO,EQ,2026-10-30,100,110,90,105,1234\n')
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w') as archive:
            archive.writestr('sample.csv', raw)
        self.assertEqual(parse_nse(buffer.getvalue(), date(2026, 11, 2))[0][0]['close'], '105')

    def test_adjusted_close_is_separate(self):
        rows, _ = parse_yahoo(json.dumps(yahoo()).encode(), date(2026, 11, 2))
        self.assertEqual(rows[0]['close'], '105')
        self.assertEqual(rows[0]['adjusted_close'], '52.5')
        self.assertEqual(rows[0]['currency'], 'USD')

    def test_india_chart_currency_timezone_and_symbol_preserved(self):
        doc = yahoo()
        meta = doc['chart']['result'][0]['meta']
        meta.update(symbol='DEMO.NS', currency='INR', exchangeTimezoneName='Asia/Kolkata')
        rows, _ = parse_yahoo(json.dumps(doc).encode(), date(2026,11,2), market='IN')
        self.assertEqual(rows[0]['market'], 'IN')
        self.assertEqual(rows[0]['currency'], 'INR')
        self.assertEqual(rows[0]['symbol'], 'DEMO.NS')
        with self.assertRaises(ValueError):
            parse_yahoo(json.dumps(doc).encode(), date(2026,11,2))

    def test_bad_provider_data_fails(self):
        for field, value in [('currency', 'INR'), ('dataGranularity', '5m')]:
            doc = yahoo()
            doc['chart']['result'][0]['meta'][field] = value
            with self.assertRaises(ValueError):
                parse_yahoo(json.dumps(doc).encode(), date(2026, 11, 2))
        for value in (None, float('nan'), -1):
            doc = yahoo()
            doc['chart']['result'][0]['indicators']['quote'][0]['close'] = [value]
            with self.assertRaises(ValueError):
                parse_yahoo(json.dumps(doc).encode(), date(2026, 11, 2))
        with self.assertRaises(ValueError):
            parse_nse(b'<html>blocked</html>', date(2026, 11, 2))

    def test_invalid_ohlc_and_arrays(self):
        with self.assertRaises(ValueError):
            parse_nse(NSE.replace(b'110, 90', b'99, 90'), date(2026, 11, 2))
        doc = yahoo()
        doc['chart']['result'][0]['indicators']['quote'][0]['volume'] = []
        with self.assertRaises(ValueError):
            parse_yahoo(json.dumps(doc).encode(), date(2026, 11, 2))

    def test_idempotence_revisions_and_raw_preservation(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / 'daily.sqlite'
            first = ingest(db, 'nse', NSE, 'synthetic-test', date(2026, 11, 2))
            again = ingest(db, 'nse', NSE, 'synthetic-test', date(2026, 11, 2))
            self.assertFalse(first['already_imported'])
            self.assertTrue(again['already_imported'])
            revised = NSE.replace(b'105', b'106')
            ingest(db, 'nse', revised, 'synthetic-test', date(2026, 11, 2))
            with sqlite3.connect(db) as connection:
                self.assertEqual(connection.execute('SELECT count(*) FROM observations').fetchone()[0], 2)
                self.assertEqual(connection.execute('SELECT raw FROM batches WHERE id=?', (first['batch'],)).fetchone()[0], NSE)

    def test_duplicate_input_rejects_whole_batch(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / 'daily.sqlite'
            duplicate = NSE + NSE.splitlines(keepends=True)[1]
            with self.assertRaises(ValueError):
                ingest(db, 'nse', duplicate, 'synthetic-test', date(2026, 11, 2))
            self.assertFalse(db.exists())


if __name__ == '__main__':
    unittest.main()
