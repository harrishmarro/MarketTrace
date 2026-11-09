"""Series-preserving staging from saved NSE batches; never grants training eligibility.

Run: python3 -m daily_data.nse_series
Original tables/bytes remain unchanged. Missing ISIN and historical membership
are explicit limitations; symbol/series matching is provisional.
"""
import argparse
import csv
import io
import json
import sqlite3
import zipfile
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path
from .ingest import bar
from .nse_universe import parse_master


def parse(raw, cutoff):
    from .nse_payload import csv_bytes
    raw = csv_bytes(raw)
    reader = csv.DictReader(io.StringIO(raw.decode('utf-8-sig')))
    headers = {k.strip() for k in reader.fieldnames or []}
    if {'SYMBOL','SERIES','DATE1','OPEN_PRICE','HIGH_PRICE','LOW_PRICE','CLOSE_PRICE','TTL_TRD_QNTY'} <= headers:
        cols = ['SYMBOL','SERIES','DATE1','OPEN_PRICE','HIGH_PRICE','LOW_PRICE','CLOSE_PRICE','TTL_TRD_QNTY']
        fmt, isin_col = '%d-%b-%Y', None
    elif {'TckrSymb','SctySrs','TradDt','OpnPric','HghPric','LwPric','ClsPric','TtlTradgVol'} <= headers:
        cols = ['TckrSymb','SctySrs','TradDt','OpnPric','HghPric','LwPric','ClsPric','TtlTradgVol']
        fmt, isin_col = '%Y-%m-%d', 'ISIN'
    elif {'SYMBOL','SERIES','TIMESTAMP','OPEN','HIGH','LOW','CLOSE','TOTTRDQTY'} <= headers:
        cols = ['SYMBOL','SERIES','TIMESTAMP','OPEN','HIGH','LOW','CLOSE','TOTTRDQTY']
        fmt, isin_col = '%d-%b-%Y', 'ISIN'
    else:
        raise ValueError('Unknown NSE schema')
    rows, rejected, seen = [], [], set()
    for line, source in enumerate(reader, 2):
        r = {k.strip():(v or '').strip() for k,v in source.items() if k}
        try:
            symbol, series, day, *values = [r[k] for k in cols]
            if not series: raise ValueError('Missing series')
            day = datetime.strptime(day, fmt).date()
            if day >= cutoff: raise ValueError('At or beyond cutoff')
            key = (symbol, series, day.isoformat())
            if key in seen: raise ValueError('Duplicate identity/date in source')
            seen.add(key)
            item = bar('IN',symbol,day.isoformat(),values)
            item.update(series=series, isin=r.get(isin_col) or None)
            rows.append(item)
        except (ValueError, KeyError) as e:
            rejected.append(dict(line=line,reason=str(e),source=r))
    # A duplicate makes the whole source ambiguous; never select its first value.
    if any(r['reason']=='Duplicate identity/date in source' for r in rejected):
        raise ValueError('Duplicate identity/date in source')
    return rows, rejected


def run(db_path='research-data/daily.sqlite', output='research-data/nse-series-coverage.json',
        main_path='research-data/nse-equity-master.csv', sme_path='research-data/nse-sme-master.csv'):
    # Resolve required inputs before creating tables or changing staging state.
    inventory = []
    for board, path in [('main_board', main_path), ('sme', sme_path)]:
        inventory.extend(parse_master(Path(path).read_bytes(), board))
    if not Path(db_path).is_file():
        raise FileNotFoundError('Import source batches before running series staging')
    with sqlite3.connect(db_path) as db:
        db.executescript('''
        CREATE TABLE IF NOT EXISTS nse_series_bars (
          batch TEXT, symbol TEXT, series TEXT, day TEXT, isin TEXT,
          payload TEXT, PRIMARY KEY(batch,symbol,series,day));
        CREATE TABLE IF NOT EXISTS nse_series_jobs (
          batch TEXT PRIMARY KEY, status TEXT, report TEXT);
        ''')
        for batch,raw,cutoff in db.execute("SELECT id,raw,cutoff FROM batches WHERE provider='nse'"):
            if db.execute('SELECT 1 FROM nse_series_jobs WHERE batch=? AND status=?',(batch,'complete')).fetchone(): continue
            try:
                rows,rejected = parse(raw,date.fromisoformat(cutoff))
                for r in rows:
                    db.execute('INSERT INTO nse_series_bars VALUES (?,?,?,?,?,?)',
                               (batch,r['symbol'],r['series'],r['day'],r['isin'],json.dumps(r,sort_keys=True)))
                status, report = 'complete',dict(rows=len(rows),quarantined=rejected)
            except ValueError as e:
                status, report = 'failed',dict(error=str(e))
            db.execute('INSERT OR REPLACE INTO nse_series_jobs VALUES (?,?,?)',(batch,status,json.dumps(report)))
        days=defaultdict(list)
        conflicts=[]
        series_counts=Counter()
        all_dates=set()
        unique_rows=0
        # Aggregate versions in SQLite so full-market history does not require
        # retaining every serialized payload in Python memory.
        for symbol,series,day,versions in db.execute(
                'SELECT symbol,series,day,count(DISTINCT payload) FROM nse_series_bars GROUP BY symbol,series,day'):
            unique_rows+=1
            series_counts[series]+=1
            all_dates.add(day)
            if versions>1:
                conflicts.append(dict(symbol=symbol,series=series,day=day,versions=versions))
            else: days[(symbol,series)].append(day)
        for r in inventory:
            observed=days[(r['symbol'],r['series'])]
            usable={d for d in observed if d>=r['listing_date']}
            r.update(official_distinct_sessions=len(observed),sessions_on_or_after_listing=len(usable),
                     first_day=min(observed) if observed else None,last_day=max(observed) if observed else None,
                     identity_status='provisional_symbol_series; historical_ISIN_review_required',
                     training_eligible=False)
        jobs=list(db.execute('SELECT status,report FROM nse_series_jobs'))
        result=dict(inventory_entries=len(inventory),
                    entries_with_series_matched_observations=sum(r['official_distinct_sessions']>0 for r in inventory),
                    entries_with_252_sessions=sum(r['sessions_on_or_after_listing']>=252 for r in inventory),
                    staged_unique_stock_series_days=unique_rows,nonconflicting_stock_series_days=sum(map(len,days.values())),
                    staged_series_counts=dict(series_counts),
                    distinct_report_dates=len(all_dates),
                    completed_source_batches=sum(s=='complete' for s,_ in jobs),
                    failed_source_batches=sum(s=='failed' for s,_ in jobs),
                    quarantined_source_rows=sum(len(json.loads(r).get('quarantined',[])) for _,r in jobs),
                    conflicting_stock_series_days=conflicts,training_eligible_entries=0,securities=inventory,
                    limitations=['252 sessions is a coverage diagnostic, not a training approval',
                      'Raw NSE prices have not been corporate-action reconciled',
                      'Series may include non-equity instruments; staging does not classify them as stocks',
                      'Current master is not historical membership; survivorship and ISIN/lifecycle review remain',
                      'Missing dates are not automatically holidays; historical ingestion remains incomplete'])
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result,indent=2)+'\n')
    return result

if __name__=='__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', default='research-data/daily.sqlite')
    parser.add_argument('--main', default='research-data/nse-equity-master.csv')
    parser.add_argument('--sme', default='research-data/nse-sme-master.csv')
    parser.add_argument('--output', default='research-data/nse-series-coverage.json')
    args = parser.parse_args()
    result = run(args.db, args.output, args.main, args.sme)
    print(json.dumps({k:v for k,v in result.items() if k!='securities'},indent=2))
