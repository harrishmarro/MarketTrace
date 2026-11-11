"""Normalize captured NSE records; all feature/release approvals remain false."""
import argparse
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
from urllib.parse import urlsplit,parse_qs
from zoneinfo import ZoneInfo
from daily_data.announcement_snapshot import aware


def normalize(raw, provenance, symbol='INFY', isin='INE009A01021'):
    if not isinstance(raw, bytes) or not raw.strip() or not isinstance(provenance, dict):
        raise ValueError('Expected response bytes and capture metadata')
    if not isinstance(symbol, str) or not symbol.strip() or not isinstance(isin, str) or not isin.strip():
        raise ValueError('Expected symbol and ISIN')
    for field in ('size_bytes', 'row_count'):
        if type(provenance.get(field)) is not int or provenance[field] <= 0:
            raise ValueError('Invalid capture count')
    if hashlib.sha256(raw).hexdigest()!=provenance.get('sha256'):
        raise ValueError('Response hash mismatch')
    if provenance.get('size_bytes')!=len(raw):raise ValueError('Response size mismatch')
    if provenance.get('status')!='captured':raise ValueError('Unsuccessful capture')
    url=urlsplit(provenance.get('url',''));query=parse_qs(url.query,keep_blank_values=True)
    if url.scheme!='https' or url.hostname!='www.nseindia.com' or url.username or url.password or url.port not in (None,443) or url.fragment or url.path!='/api/corporate-announcements' or query.get('symbol')!=[symbol] or query.get('index')!=['equities']:
        raise ValueError('Unexpected source')
    dates=[]
    for key in ('from_date','to_date'):
        values=query.get(key,[])
        if len(values)!=1:raise ValueError('Missing/ambiguous query date')
        try:date=datetime.strptime(values[0],'%d-%m-%Y').date()
        except ValueError as e:raise ValueError('Invalid query date') from e
        if date.strftime('%d-%m-%Y')!=values[0]:raise ValueError('Invalid query date format')
        dates.append(date)
    if dates[1]<dates[0]:raise ValueError('Reversed query interval')
    captured=aware(provenance['capture_completed_at'])
    started=aware(provenance['request_started_at'])
    if captured<started:raise ValueError('Capture clock reversed')
    rows=json.loads(raw)
    if not isinstance(rows,list) or not rows:raise ValueError('Missing row array')
    if provenance.get('row_count')!=len(rows):raise ValueError('Row count mismatch')
    identity={k:provenance[k] for k in ('url','sha256','size_bytes','row_count','request_started_at','capture_completed_at')}
    capture_id=hashlib.sha256(json.dumps(identity,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    results=[];seen=set()
    for r in rows:
        if not isinstance(r, dict):raise ValueError('Expected announcement object')
        if r.get('symbol')!=symbol or r.get('sm_isin')!=isin:raise ValueError('Identity mismatch')
        seq=r.get('seq_id')
        if not isinstance(seq,str) or not seq or seq in seen:raise ValueError('Missing/duplicate sequence')
        seen.add(seq)
        received=datetime.strptime(r['an_dt'],'%d-%b-%Y %H:%M:%S').replace(tzinfo=ZoneInfo('Asia/Kolkata'))
        if not dates[0]<=received.date()<=dates[1]:raise ValueError('Record outside requested interval')
        disseminated=datetime.strptime(r['exchdisstime'],'%d-%b-%Y %H:%M:%S').replace(tzinfo=ZoneInfo('Asia/Kolkata'))
        if disseminated<received or disseminated>captured:raise ValueError('Invalid dissemination clock')
        if not isinstance(r.get('difference'), str):raise ValueError('Invalid delay')
        pieces=r['difference'].split(':')
        if len(pieces)!=3 or not all(v.isdigit() for v in pieces):raise ValueError('Invalid delay')
        h,m,s=map(int,pieces)
        if m>=60 or s>=60 or disseminated-received!=timedelta(hours=h,minutes=m,seconds=s):raise ValueError('Delay mismatch')
        attachment=urlsplit(r.get('attchmntFile',''))
        if attachment.scheme!='https' or attachment.hostname not in ('nsearchives.nseindia.com','archives.nseindia.com'):
            raise ValueError('Invalid attachment source')
        row_hash=hashlib.sha256(json.dumps(r,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        results.append(dict(sequence_id=seq,symbol=symbol,isin=isin,subject=r.get('desc'),
            received_at=received.isoformat(),disseminated_at=disseminated.isoformat(),
            captured_at=captured.isoformat(),available_to_this_pipeline_at=max(captured,disseminated).isoformat(),
            source_response_sha256=provenance['sha256'],source_url=provenance['url'],
            capture_started_at=provenance['request_started_at'],capture_id=capture_id,row_sha256=row_hash,
            attachment_url=r['attchmntFile'],timezone_interpretation='Asia/Kolkata; explicit assumption, not certified by captured schema',
            historical_feature_approved=False,model_feature_approved=False))
    return sorted(results,key=lambda r:(r['disseminated_at'],r['sequence_id']))


def normalize_capture(payload_path, provenance_path, output_path, symbol, isin):
    """Validate a caller-supplied capture and write derived records locally."""
    payload_path = Path(payload_path)
    provenance_path = Path(provenance_path)
    output_path = Path(output_path)
    if output_path.resolve() in (payload_path.resolve(), provenance_path.resolve()):
        raise ValueError('Output must not overwrite source evidence')
    raw = payload_path.read_bytes()
    provenance = json.loads(provenance_path.read_text(encoding='utf-8'))
    result = {
        'rows': normalize(raw, provenance, symbol, isin),
        'coverage_verified': False,
        'historical_point_in_time_verified': False,
        'original_timezone_verified': False,
        'training_approved': False,
        'limitation': 'Metadata validation does not authenticate original availability or exhaustive coverage.'
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--file', required=True, type=Path, help='Local captured JSON response')
    parser.add_argument('--provenance', required=True, type=Path, help='Local capture metadata JSON')
    parser.add_argument('--symbol', required=True)
    parser.add_argument('--isin', required=True)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    result = normalize_capture(args.file, args.provenance, args.output, args.symbol, args.isin)
    print(json.dumps({'records': len(result['rows']), 'training_approved': False}, indent=2))


if __name__ == '__main__':
    main()
