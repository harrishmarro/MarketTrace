"""Strict daily adapters, transactional storage and original-byte provenance.

python3 -m daily_data.ingest --help
Raw prices and adjusted close remain distinct. Neither source establishes
point-in-time historical availability or corporate-action correctness.
"""
import argparse
import csv
import hashlib
import io
import json
import sqlite3
import zipfile
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo


def number(value, integer=False):
    try:
        result = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        raise ValueError('Missing or invalid numeric field') from None
    if not result.is_finite() or result < 0 or (not integer and result == 0):
        raise ValueError('Invalid price or volume')
    if integer and result != result.to_integral_value():
        raise ValueError('Noninteger volume')
    return str(int(result)) if integer else format(result, 'f')


def bar(market, symbol, day, values, adjusted=None):
    date.fromisoformat(day)
    if not symbol or len(symbol) > 40:
        raise ValueError('Invalid symbol')
    o, h, l, c = [number(v) for v in values[:4]]
    v = number(values[4], integer=True)
    if Decimal(l) > min(Decimal(o), Decimal(c)) or Decimal(h) < max(Decimal(o), Decimal(c)):
        raise ValueError('OHLC bounds inconsistent')
    return dict(market=market, symbol=symbol, day=day, currency='INR' if market == 'IN' else 'USD',
                open=o, high=h, low=l, close=c, volume=v,
                adjusted_close=None if adjusted is None else number(adjusted))


def parse_nse(raw, cutoff):
    from .nse_payload import csv_bytes
    raw = csv_bytes(raw)
    reader = csv.DictReader(io.StringIO(raw.decode('utf-8-sig')))
    headers = {k.strip() for k in (reader.fieldnames or [])}
    full = {'SYMBOL', 'SERIES', 'DATE1', 'OPEN_PRICE', 'HIGH_PRICE', 'LOW_PRICE', 'CLOSE_PRICE', 'TTL_TRD_QNTY'}
    udiff = {'TckrSymb', 'SctySrs', 'TradDt', 'OpnPric', 'HghPric', 'LwPric', 'ClsPric', 'TtlTradgVol'}
    if full <= headers:
        columns = ['SYMBOL', 'SERIES', 'DATE1', 'OPEN_PRICE', 'HIGH_PRICE', 'LOW_PRICE', 'CLOSE_PRICE', 'TTL_TRD_QNTY']
        fmt = '%d-%b-%Y'
    elif udiff <= headers:
        columns = ['TckrSymb', 'SctySrs', 'TradDt', 'OpnPric', 'HghPric', 'LwPric', 'ClsPric', 'TtlTradgVol']
        fmt = '%Y-%m-%d'
    elif {'SYMBOL','SERIES','TIMESTAMP','OPEN','HIGH','LOW','CLOSE','TOTTRDQTY'} <= headers:
        columns = ['SYMBOL','SERIES','TIMESTAMP','OPEN','HIGH','LOW','CLOSE','TOTTRDQTY']
        fmt = '%d-%b-%Y'
    else:
        raise ValueError('Unrecognized NSE daily schema')
    rows, excluded = [], 0
    for source in reader:
        r = {k.strip(): (v or '').strip() for k, v in source.items() if k is not None}
        symbol, series, raw_day, *values = [r[k] for k in columns]
        if series != 'EQ':
            excluded += 1
            continue
        day = datetime.strptime(raw_day, fmt).date()
        if day >= cutoff:
            excluded += 1
            continue
        rows.append(bar('IN', symbol, day.isoformat(), values))
    return rows, excluded


def parse_yahoo(raw, cutoff, market='US'):
    if market not in ('US', 'IN'):
        raise ValueError('Unsupported chart market')
    doc = json.loads(raw)
    if doc.get('chart', {}).get('error'):
        raise ValueError('Provider returned chart error')
    results = doc.get('chart', {}).get('result')
    if not results or len(results) != 1:
        raise ValueError('Expected a single chart')
    result = results[0]
    meta = result['meta']
    currency, zone = ('USD', 'America/New_York') if market == 'US' else ('INR', 'Asia/Kolkata')
    if (meta.get('currency') != currency or meta.get('instrumentType') != 'EQUITY'
            or meta.get('exchangeTimezoneName') != zone
            or meta.get('dataGranularity') != '1d'):
        raise ValueError('Expected matching currency, exchange timezone and equity daily chart')
    stamps = result['timestamp']
    q = result['indicators']['quote'][0]
    fields = ['open', 'high', 'low', 'close', 'volume']
    adjusted = result['indicators'].get('adjclose', [{}])[0].get('adjclose')
    if any(len(q[k]) != len(stamps) for k in fields) or (adjusted is not None and len(adjusted) != len(stamps)):
        raise ValueError('Misaligned price arrays')
    if any(b <= a for a, b in zip(stamps, stamps[1:])):
        raise ValueError('Unordered timestamps')
    rows, excluded = [], 0
    for i, stamp in enumerate(stamps):
        day = datetime.fromtimestamp(stamp, ZoneInfo(zone)).date()
        if day >= cutoff:
            excluded += 1
            continue
        rows.append(bar(market, meta['symbol'], day.isoformat(), [q[k][i] for k in fields],
                        None if adjusted is None else adjusted[i]))
    return rows, excluded


def ingest(db_path, provider, raw, source, cutoff):
    if provider not in ('nse', 'yahoo', 'yahoo_india'):
        raise ValueError('Unsupported provider')
    if provider == 'nse':
        rows, excluded = parse_nse(raw, cutoff)
    else:
        rows, excluded = parse_yahoo(raw, cutoff, market='IN' if provider == 'yahoo_india' else 'US')
    if not rows:
        raise ValueError('No eligible daily bars; nothing stored')
    keys = [(r['market'], r['symbol'], r['day']) for r in rows]
    if len(keys) != len(set(keys)):
        raise ValueError('Duplicate security/date in source')
    digest = hashlib.sha256(raw).hexdigest()
    batch = hashlib.sha256((provider + digest + cutoff.isoformat()).encode()).hexdigest()
    with sqlite3.connect(db_path) as db:
        db.executescript('''
        CREATE TABLE IF NOT EXISTS batches(id TEXT PRIMARY KEY, provider TEXT, sha256 TEXT,
            source TEXT, retrieved_at TEXT, cutoff TEXT, raw BLOB);
        CREATE TABLE IF NOT EXISTS observations(batch TEXT, market TEXT, symbol TEXT, day TEXT,
            currency TEXT, open TEXT, high TEXT, low TEXT, close TEXT, volume TEXT,
            adjusted_close TEXT, PRIMARY KEY(batch,market,symbol,day));
        ''')
        seen = db.execute('SELECT 1 FROM batches WHERE id=?', (batch,)).fetchone() is not None
        if not seen:
            db.execute('INSERT INTO batches VALUES (?,?,?,?,?,?,?)',
                       (batch, provider, digest, source, datetime.now(timezone.utc).isoformat(), cutoff.isoformat(), raw))
            for row in rows:
                db.execute('INSERT INTO observations VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                           (batch, *[row[k] for k in ('market', 'symbol', 'day', 'currency',
                                                     'open', 'high', 'low', 'close', 'volume', 'adjusted_close')]))
    return dict(provider=provider, source=source, batch=batch, sha256=digest,
                bars=len(rows), symbols=len({r['symbol'] for r in rows}),
                first_day=min(r['day'] for r in rows), last_day=max(r['day'] for r in rows),
                excluded_rows=excluded, already_imported=seen)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--provider', required=True, choices=['nse', 'yahoo'])
    parser.add_argument('--file', type=Path, help='Import an existing provider file instead of downloading')
    parser.add_argument('--day', type=date.fromisoformat, help='NSE report day')
    parser.add_argument('--symbol', default='AAPL', help='US equity symbol')
    parser.add_argument('--db', type=Path, default=Path('research-data/daily.sqlite'))
    args = parser.parse_args()
    zone = 'Asia/Kolkata' if args.provider == 'nse' else 'America/New_York'
    cutoff = datetime.now(ZoneInfo(zone)).date()
    if args.file:
        raw, source = args.file.read_bytes(), str(args.file.resolve())
    else:
        if args.provider == 'nse':
            if args.day is None or args.day >= cutoff:
                parser.error('Supply a completed NSE --day YYYY-MM-DD before today')
            source = 'https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_' + args.day.strftime('%d%m%Y') + '.csv'
        else:
            source = 'https://query1.finance.yahoo.com/v8/finance/chart/' + quote(args.symbol, safe='') + '?range=1mo&interval=1d'
        request = Request(source, headers={'User-Agent': 'StockResearchPrototype/0.1'})
        with urlopen(request, timeout=15) as response:
            raw = response.read(50000001)
        if len(raw) > 50000000:
            raise ValueError('Response too large')
        if args.provider == 'nse':
            parsed, _ = parse_nse(raw, cutoff)
            if any(row['day'] != args.day.isoformat() for row in parsed):
                raise ValueError('Downloaded report does not match requested day')
        elif json.loads(raw)['chart']['result'][0]['meta']['symbol'].upper() != args.symbol.upper():
            raise ValueError('Downloaded symbol differs from requested symbol')
    args.db.parent.mkdir(parents=True, exist_ok=True)
    print(json.dumps(ingest(args.db, args.provider, raw, source, cutoff), indent=2))


if __name__ == '__main__':
    main()
