"""NSE-first inventory and coverage; current masters are not historical membership."""
import argparse
import csv
import hashlib
import io
import json
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

SOURCES = {'main_board': 'https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv',
           'sme': 'https://nsearchives.nseindia.com/emerge/corporates/content/SME_EQUITY_L.csv'}


def validate_report_output(output, *source_paths):
    """Refuse aliases of source files before a report can overwrite them."""
    target = Path(output)
    for path in source_paths:
        source = Path(path)
        if (target.resolve() == source.resolve()
                or (target.exists() and source.exists() and target.samefile(source))):
            raise ValueError('Report output must not overwrite the database or master inputs')


def parse_master(raw, board):
    reader = csv.DictReader(io.StringIO(raw.decode('utf-8-sig')))
    rows, seen = [], set()
    for original in reader:
        r = {k.strip().replace(' ', '_'): (v or '').strip() for k,v in original.items() if k}
        required = ('SYMBOL', 'SERIES', 'ISIN_NUMBER', 'DATE_OF_LISTING', 'NAME_OF_COMPANY')
        if any(not r.get(k) for k in required):
            raise ValueError('Missing master identity field')
        day = None
        for fmt in ('%d-%b-%Y', '%d-%b-%y'):
            try: day = datetime.strptime(r['DATE_OF_LISTING'],fmt).date().isoformat(); break
            except ValueError: pass
        if day is None: raise ValueError('Unrecognized listing date')
        key = (r['SYMBOL'],r['SERIES'],r['ISIN_NUMBER'])
        if key in seen: raise ValueError('Duplicate master identity')
        seen.add(key)
        rows.append(dict(board=board, symbol=r['SYMBOL'], series=r['SERIES'], isin=r['ISIN_NUMBER'],
                         name=r['NAME_OF_COMPANY'], listing_date=day,
                         instrument_review='rights_candidate' if r['SYMBOL'].endswith('-RE') else 'equity_master_candidate',
                         training_eligible=False))
    if not rows: raise ValueError('Empty master')
    return rows


def run(db_path, main_path, sme_path, output):
    validate_report_output(output, db_path, main_path, sme_path)
    inventory, provenance = [], []
    for board,path in [('main_board',main_path),('sme',sme_path)]:
        p=Path(path);raw=p.read_bytes();rows=parse_master(raw,board);inventory.extend(rows)
        provenance.append(dict(board=board,source=SOURCES[board],sha256=hashlib.sha256(raw).hexdigest(),rows=len(rows)))
    official, provider = defaultdict(set), defaultdict(set)
    with sqlite3.connect(Path(db_path).resolve().as_uri()+'?mode=ro',uri=True) as db:
        for source,symbol,day in db.execute("SELECT b.provider,o.symbol,o.day FROM observations o JOIN batches b ON b.id=o.batch WHERE b.provider IN ('nse','yahoo_india')"):
            (official if source=='nse' else provider)[symbol.removesuffix('.NS') if source=='yahoo_india' else symbol].add(day)
    for row in inventory:
        days=official[row['symbol']];pdays=provider[row['symbol']]
        row.update(official_observed_sessions=len(days),provider_observed_sessions=len(pdays),
                   official_first_day=min(days) if days else None,official_last_day=max(days) if days else None,
                   coverage_status='partial_observations' if days or pdays else 'not_downloaded',
                   validation_status='pending',identity_match='symbol_only_requires_ISIN_and_history_review')
    report=dict(scope='NSE first; BSE after NSE milestone',created_at=datetime.now(timezone.utc).isoformat(),
                inventory_rows=len(inventory),unique_symbols=len({r['symbol'] for r in inventory}),
                board_counts=dict(Counter(r['board'] for r in inventory)),
                series_counts=dict(Counter(r['series'] for r in inventory)),
                rows_with_official_observations=sum(bool(r['official_observed_sessions']) for r in inventory),
                rows_with_provider_observations=sum(bool(r['provider_observed_sessions']) for r in inventory),
                rights_candidates=sum(r['instrument_review']=='rights_candidate' for r in inventory),
                validated_rows=0,training_eligible_rows=0,provenance=provenance,securities=inventory,
                limitations=['Current downloaded master is not point-in-time historical membership or an authoritative as-of cutoff',
                             'Inventory rows require instrument and ISIN/symbol-change review before stock counts are certified',
                             'Existing NSE importer accepts EQ only; BE/BZ and SME series need separate ingestion support',
                             'Observed sessions do not mean complete histories, independent validation, or training eligibility',
                             'New listings, suspended/delisted securities and symbol changes require historical lifecycle treatment',
                             'No market-cap labels inferred; no training or local GPU execution performed'])
    Path(output).write_text(json.dumps(report,indent=2)+'\n');return report


if __name__=='__main__':
    p=argparse.ArgumentParser(__doc__)
    p.add_argument('--db',default='research-data/daily.sqlite')
    p.add_argument('--main',default='research-data/nse-equity-master.csv')
    p.add_argument('--sme',default='research-data/nse-sme-master.csv')
    p.add_argument('--output',default='research-data/nse-universe-coverage.json')
    a=p.parse_args()
    try:
        r=run(a.db,a.main,a.sme,a.output)
    except (ValueError, FileNotFoundError) as error:
        p.error(str(error))
    print(json.dumps({k:v for k,v in r.items() if k not in ('securities',)},indent=2))
