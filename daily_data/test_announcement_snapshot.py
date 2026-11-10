import hashlib
import unittest
from daily_data.announcement_snapshot import validate_snapshot

class AnnouncementSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.payload=b'issuer announcement'
        self.r=dict(symbol='INFY',source_url='https://www.nseindia.com/example',version_id='v1',broadcast_at='2026-11-06T16:00:00+05:30',captured_at='2026-11-06T10:31:00Z',sha256=hashlib.sha256(self.payload).hexdigest())
    def test_timezone_equivalence_and_later_decision(self):
        result=validate_snapshot(self.r,self.payload,'2026-11-06T10:32:00Z','INFY')
        self.assertFalse(result['model_feature_approved'])
    def test_unavailable_and_retrospective(self):
        for decision in ('2026-11-06T10:30:00Z','2026-11-06T10:31:00Z','2023-10-12T16:00:00Z'):
            with self.assertRaises(ValueError):validate_snapshot(self.r,self.payload,decision,'INFY')
    def test_hash_and_symbol(self):
        with self.assertRaises(ValueError):validate_snapshot(self.r,b'edited','2026-11-06T10:32:00Z','INFY')
        with self.assertRaises(ValueError):validate_snapshot(self.r,self.payload,'2026-11-06T10:32:00Z','SBI')
    def test_missing_naive_and_impossible_timestamps(self):
        for k,v in [('captured_at','2026-11-06T10:31:00'),('broadcast_at',None),('broadcast_at','2026-11-07T10:31:00Z'),('version_id','')]:
            r=dict(self.r);r[k]=v
            with self.assertRaises(ValueError):validate_snapshot(r,self.payload,'2026-11-08T10:32:00Z','INFY')

    def test_snapshot_identity(self):
        first=validate_snapshot(self.r,self.payload,'2026-11-06T10:32:00Z','INFY')
        r=dict(self.r);r['broadcast_at']='2026-11-06T10:30:00Z'
        self.assertEqual(first['snapshot_id'],validate_snapshot(r,self.payload,'2026-11-06T10:32:00Z','INFY')['snapshot_id'])
        payload=b'revision';r['sha256']=hashlib.sha256(payload).hexdigest()
        self.assertNotEqual(first['snapshot_id'],validate_snapshot(r,payload,'2026-11-06T10:32:00Z','INFY')['snapshot_id'])
    def test_invalid_source_url(self):
        r=dict(self.r);r['source_url']='https://'
        with self.assertRaises(ValueError):validate_snapshot(r,self.payload,'2026-11-06T10:32:00Z','INFY')
