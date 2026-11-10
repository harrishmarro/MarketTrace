"""Strict as-of guard for locally captured announcement bytes; no downloader or model."""
from datetime import datetime, timezone
import hashlib
import json
from urllib.parse import urlsplit


def aware(value):
    if not isinstance(value,str):raise ValueError('Timestamp required')
    try:t=datetime.fromisoformat(value.replace('Z','+00:00'))
    except ValueError as e:raise ValueError('Invalid timestamp') from e
    if t.tzinfo is None or t.utcoffset() is None:raise ValueError('Timezone required')
    return t


def validate_snapshot(record, payload, decision_at, symbol):
    required=('symbol','source_url','version_id','broadcast_at','captured_at','sha256')
    if any(not isinstance(record.get(k),str) or not record[k].strip() for k in required):
        raise ValueError('Missing snapshot evidence')
    if record['symbol'] != symbol:raise ValueError('Wrong symbol')
    url=urlsplit(record['source_url'])
    if url.scheme != 'https' or not url.hostname or url.username or url.password:
        raise ValueError('Valid HTTPS source required')
    if not isinstance(payload,bytes) or not payload.strip():raise ValueError('Missing payload bytes')
    if hashlib.sha256(payload).hexdigest()!=record['sha256']:raise ValueError('Payload hash mismatch')
    published=aware(record['broadcast_at']);captured=aware(record['captured_at']);decision=aware(decision_at)
    if captured < published:raise ValueError('Capture predates broadcast')
    available=max(published,captured)
    if decision <= available:raise ValueError('Snapshot unavailable at decision')
    identity={k:record[k] for k in required}
    identity['broadcast_at']=published.astimezone(timezone.utc).isoformat()
    identity['captured_at']=captured.astimezone(timezone.utc).isoformat()
    snapshot_id=hashlib.sha256(json.dumps(identity,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    return {'snapshot_id':snapshot_id,'symbol':symbol,'version_id':record['version_id'],'available_at':available.isoformat(),
            'sha256':record['sha256'],'model_feature_approved':False,
            'limitations':'Validates supplied metadata only; original broadcast authenticity/coverage and use rights require separate evidence.'}
