import copy
import hashlib
import json
from pathlib import Path
import unittest
import subprocess
import sys
import tempfile
from urllib.parse import urlencode,urlsplit,urlunsplit,parse_qsl
from daily_data.nse_announcement_records import normalize, normalize_capture

class NSEAnnouncementRecordsTests(unittest.TestCase):
    def setUp(self):
        # Invented records and attachment locations; no exchange captures bundled.
        self.records = [dict(
            symbol='INFY', sm_isin='INE009A01021', seq_id='synthetic-' + str(i),
            an_dt='12-Oct-2023 15:59:00', exchdisstime='12-Oct-2023 15:59:10',
            difference='00:00:10', desc='Synthetic announcement',
            attchmntFile='https://nsearchives.nseindia.com/synthetic-example.pdf')
            for i in range(2)]
        self.raw = json.dumps(self.records).encode()
        self.p = dict(
            url='https://www.nseindia.com/api/corporate-announcements?index=equities&symbol=INFY&from_date=12-10-2023&to_date=12-10-2023',
            status='captured', sha256=hashlib.sha256(self.raw).hexdigest(),
            size_bytes=len(self.raw), row_count=len(self.records),
            request_started_at='2026-11-06T12:00:00+00:00',
            capture_completed_at='2026-11-06T12:00:01+00:00')
    def test_synthetic_rows_and_conservative_availability(self):
        rows=normalize(self.raw,self.p)
        self.assertEqual(len(rows),2)
        self.assertEqual(rows[0]['disseminated_at'],'2023-10-12T15:59:10+05:30')
        self.assertTrue(all(r['available_to_this_pipeline_at']==self.p['capture_completed_at'] for r in rows))
        self.assertTrue(all(not r['historical_feature_approved'] for r in rows))
    def test_changed_payload_rejected(self):
        with self.assertRaises(ValueError):normalize(self.raw+b' ',self.p)
    def test_row_corruption_rejected(self):
        for field,value in [('symbol','SBIN'),('sm_isin','wrong'),('exchdisstime',None),('difference','00:00:59'),('attchmntFile','https://example.com/a')]:
            with self.subTest(field=field):
                rows=json.loads(self.raw);rows[0][field]=value
                raw=json.dumps(rows).encode();p=dict(self.p,sha256=hashlib.sha256(raw).hexdigest(),size_bytes=len(raw),row_count=len(rows))
                with self.assertRaises((ValueError,TypeError)):normalize(raw,p)
    def test_duplicate_rejected(self):
        rows=json.loads(self.raw);rows.append(rows[0]);raw=json.dumps(rows).encode()
        with self.assertRaises(ValueError):normalize(raw,dict(self.p,sha256=hashlib.sha256(raw).hexdigest(),size_bytes=len(raw),row_count=len(rows)))
    def test_bad_source_and_capture_clock(self):
        for key,value in [('url','https://example.com/api/corporate-announcements?symbol=INFY'),('capture_completed_at','2020-01-01T00:00:00Z'),('status','failed')]:
            with self.subTest(key=key):
                with self.assertRaises(ValueError):normalize(self.raw,dict(self.p,**{key:value}))

    def test_provenance_consistency_and_identity(self):
        for key in ('size_bytes','row_count'):
            with self.assertRaises(ValueError):normalize(self.raw,dict(self.p,**{key:1}))
        first=normalize(self.raw,self.p)[0]
        later=dict(self.p,capture_completed_at='2026-11-09T00:00:00Z')
        self.assertNotEqual(first['capture_id'],normalize(self.raw,later)[0]['capture_id'])
        self.assertEqual(first['source_url'],self.p['url'])

    def query_url(self,pairs):
        url=urlsplit(self.p['url'])
        return urlunsplit(url._replace(query=urlencode(pairs)))

    def test_required_unambiguous_query_fields(self):
        original=parse_qsl(urlsplit(self.p['url']).query,keep_blank_values=True)
        for key in ('index','symbol','from_date','to_date'):
            cases=[[(k,v) for k,v in original if k!=key],original+[(key,dict(original)[key])]]
            for pairs in cases:
                with self.subTest(key=key,pairs=pairs):
                    with self.assertRaises(ValueError):normalize(self.raw,dict(self.p,url=self.query_url(pairs)))
        for value in ('debt','', 'Equities'):
            pairs=[(k,value if k=='index' else v) for k,v in original]
            with self.subTest(index=value):
                with self.assertRaises(ValueError):normalize(self.raw,dict(self.p,url=self.query_url(pairs)))

    def test_invalid_reversed_and_unmatched_query_dates(self):
        original=dict(parse_qsl(urlsplit(self.p['url']).query))
        for changes in ({'from_date':''},{'to_date':'31-02-2023'},
                        {'from_date':'2023-10-12'},
                        {'from_date':'13-10-2023','to_date':'12-10-2023'},
                        {'from_date':'01-01-2000','to_date':'01-01-2000'}):
            with self.subTest(changes=changes):
                pairs=list(dict(original,**changes).items())
                with self.assertRaises(ValueError):normalize(self.raw,dict(self.p,url=self.query_url(pairs)))

    def test_receipt_interval_inclusive_and_midnight_dissemination(self):
        row=copy.deepcopy(json.loads(self.raw)[0])
        row.update(an_dt='12-Oct-2023 23:59:59',exchdisstime='13-Oct-2023 00:00:01',difference='00:00:02')
        raw=json.dumps([row]).encode()
        p=dict(self.p,sha256=hashlib.sha256(raw).hexdigest(),size_bytes=len(raw),row_count=1)
        result=normalize(raw,p)
        self.assertEqual(result[0]['disseminated_at'],'2023-10-13T00:00:01+05:30')
        for date in ('11-Oct-2023','13-Oct-2023'):
            row['an_dt']=date+' 23:59:59'
            raw=json.dumps([row]).encode()
            with self.subTest(received=date):
                with self.assertRaisesRegex(ValueError,'outside requested interval'):
                    normalize(raw,dict(p,sha256=hashlib.sha256(raw).hexdigest(),size_bytes=len(raw)))

    def test_count_types_and_nonobject_rows_are_rejected(self):
        for field in ('size_bytes', 'row_count'):
            for value in (True, 0, -1, '2'):
                with self.subTest(field=field, value=value):
                    with self.assertRaises(ValueError):
                        normalize(self.raw, dict(self.p, **{field: value}))
        raw = json.dumps([None]).encode()
        meta = dict(self.p, sha256=hashlib.sha256(raw).hexdigest(), size_bytes=len(raw), row_count=1)
        with self.assertRaises(ValueError):
            normalize(raw, meta)

    def test_credential_urls_and_nonstandard_sources_are_rejected(self):
        for source in ('https://user:password@www.nseindia.com',
                       'https://www.nseindia.com:444',
                       'https://www.nseindia.com.example.org'):
            url = self.p['url'].replace('https://www.nseindia.com', source)
            with self.subTest(source=source):
                with self.assertRaises(ValueError):normalize(self.raw, dict(self.p, url=url))

    def test_cli_normalizes_local_synthetic_capture_and_preserves_inputs(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            raw_path, meta_path = root/'response.json', root/'capture.json'
            output = root/'derived/normalized.json'
            raw_path.write_bytes(self.raw)
            meta_path.write_text(json.dumps(self.p))
            original_meta = meta_path.read_bytes()
            result = subprocess.run(
                [sys.executable, '-m', 'daily_data.nse_announcement_records',
                 '--file', str(raw_path), '--provenance', str(meta_path),
                 '--symbol', 'INFY', '--isin', 'INE009A01021', '--output', str(output)],
                cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, check=True)
            self.assertEqual(json.loads(result.stdout)['records'], 2)
            stored = json.loads(output.read_text())
            self.assertFalse(stored['training_approved'])
            self.assertFalse(stored['original_timezone_verified'])
            self.assertEqual(raw_path.read_bytes(), self.raw)
            self.assertEqual(meta_path.read_bytes(), original_meta)
            for path in (raw_path, meta_path):
                with self.assertRaises(ValueError):
                    normalize_capture(raw_path, meta_path, path, 'INFY', 'INE009A01021')

    def test_failed_capture_validation_leaves_existing_output_untouched(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            raw_path, meta_path, output = root/'response.json', root/'capture.json', root/'output.json'
            raw_path.write_bytes(self.raw + b' ')
            meta_path.write_text(json.dumps(self.p))
            output.write_bytes(b'previous result')
            with self.assertRaises(ValueError):
                normalize_capture(raw_path, meta_path, output, 'INFY', 'INE009A01021')
            self.assertEqual(output.read_bytes(), b'previous result')
