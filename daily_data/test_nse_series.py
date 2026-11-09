import unittest
from datetime import date
from daily_data.nse_series import parse

HEADER=b'SYMBOL,SERIES,DATE1,OPEN_PRICE,HIGH_PRICE,LOW_PRICE,CLOSE_PRICE,TTL_TRD_QNTY\n'
class SeriesTests(unittest.TestCase):
    def test_series_do_not_overwrite_each_other(self):
        rows,bad=parse(HEADER+b'A,EQ,30-Oct-2026,10,12,9,11,20\nA,BE,30-Oct-2026,10,12,9,11,30\n',date(2026,11,1))
        self.assertEqual([r['series'] for r in rows],['EQ','BE'])
        self.assertEqual([r['volume'] for r in rows],['20','30'])
        self.assertFalse(bad)
    def test_invalid_row_quarantined_and_cutoff_enforced(self):
        rows,bad=parse(HEADER+b'A,EQ,30-Oct-2026,10,8,9,11,20\nB,SM,01-Nov-2026,10,12,9,11,30\nC,SM,30-Oct-2026,10,12,9,11,30\n',date(2026,11,1))
        self.assertEqual([r['symbol'] for r in rows],['C'])
        self.assertEqual(len(bad),2)
    def test_duplicate_identity_blocks_source(self):
        r=b'A,EQ,30-Oct-2026,10,12,9,11,20\n'
        with self.assertRaises(ValueError): parse(HEADER+r+r,date(2026,11,1))
    def test_udiff_isin_preserved(self):
        rows,bad=parse(b'TckrSymb,SctySrs,TradDt,OpnPric,HghPric,LwPric,ClsPric,TtlTradgVol,ISIN\nA,SM,2026-10-30,10,12,9,11,30,INE123456789\n',date(2026,11,1))
        self.assertEqual(rows[0]['isin'],'INE123456789')
        self.assertFalse(bad)

class StagingTests(unittest.TestCase):
    def test_restart_is_idempotent_and_conflicting_versions_are_excluded(self):
        import os, tempfile, sqlite3, json
        from pathlib import Path
        from daily_data.ingest import ingest
        from daily_data.nse_series import run
        with tempfile.TemporaryDirectory() as folder:
            original=os.getcwd()
            try:
                os.chdir(folder)
                Path('research-data').mkdir()
                master='SYMBOL,NAME_OF_COMPANY,SERIES,DATE_OF_LISTING,ISIN_NUMBER\n'
                Path('research-data/nse-equity-master.csv').write_text(master+'A,Alpha,EQ,01-Jan-2020,INE123456789\n')
                Path('research-data/nse-sme-master.csv').write_text(master+'B,Beta,SM,01-Jan-2020,INE123456788\n')
                db='research-data/daily.sqlite'
                raw=HEADER+b'A,EQ,30-Oct-2026,10,12,9,11,20\nB,SM,30-Oct-2026,10,12,9,11,30\n'
                ingest(db,'nse',raw,'fixture',date(2026,11,1))
                first=run()
                with sqlite3.connect(db) as c: before=c.execute('select * from observations').fetchall()
                second=run()
                self.assertEqual(first['staged_unique_stock_series_days'],2)
                self.assertEqual(first['entries_with_series_matched_observations'],2)
                self.assertEqual(first,second)
                changed=raw.replace(b',11,20',b',12,20')
                ingest(db,'nse',changed,'second',date(2026,11,1))
                report=run()
                self.assertEqual(len(report['conflicting_stock_series_days']),1)
                self.assertEqual(report['entries_with_series_matched_observations'],1)
                self.assertEqual(report['training_eligible_entries'],0)
                with sqlite3.connect(db) as c:
                    self.assertEqual(c.execute('select * from observations where batch=?',(before[0][0],)).fetchall(),before)
            finally: os.chdir(original)
