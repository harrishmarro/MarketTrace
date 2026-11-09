# Series-preserving NSE staging

The basic importer accepts EQ observations. Series staging reparses the original
NSE batch bytes and keeps each symbol, series and date separate, retaining BE,
SME and other series for review without treating every instrument as a stock.
It never grants training eligibility.

## Required local inputs

Use an existing database created by the daily importer and locally obtained
main-board and SME security-master CSVs. No data downloads happen in the staging
command. These source datasets are not distributed in the repository; obtain
and use them under their applicable terms.

```bash
python -m daily_data.nse_series \
  --db local-output/daily.sqlite \
  --main /path/to/nse-equity-master.csv \
  --sme /path/to/nse-sme-master.csv \
  --output local-output/series-coverage.json
```

Both masters require symbol, company name, series, listing date and ISIN fields.
The parser accepts the corresponding spaced or underscore-separated headers.
Master identity fields are parsed as supplied: they do not prove an ISIN checksum,
historical membership or legal-entity continuity. Required masters and the
existing database are checked before staging tables are created.

## Preservation and validation

- Original `batches` and EQ `observations` remain intact. Derived rows go into
  `nse_series_bars` with source-batch identity; outcomes go into `nse_series_jobs`.
- A valid symbol/series/date key is preserved even if the same symbol appears in
  a different series. Available ISIN fields are retained from classic and UDiFF
  formats; full-report rows can have no ISIN.
- Invalid numeric values, OHLC bounds, dates at or after the batch cutoff and
  missing fields are quarantined with source-row evidence. Duplicate keys inside
  one source reject that source rather than silently select one row.
- Completed batches resume without reinserting their rows. Multiple batches with
  identical normalized content count once. Conflicting normalized payloads for
  one symbol/series/date remain stored but are excluded from usable coverage.
- Counts on or after each supplied listing date are reported separately from all
  observed dates. A 252-session count is a coverage diagnostic, not clearance to
  train a model.

The separate `nse_universe` module supplies the master parser and a legacy
symbol-only overview. Use the series-staging report when series separation
matters; neither report establishes a historical, survivorship-free universe.
Zero-volume observations remain visible and need downstream liquidity review.
Corporate actions, missing-session explanations, source accuracy and historical
availability require independent checks.

## Offline verification

```bash
python -m unittest discover -s daily_data -p 'test_*.py' -v
```

Tests generate synthetic report/master bytes and temporary databases. They cover
series separation, cutoff and listing-date behavior, invalid-row quarantine,
revision conflicts, repeat imports, source preservation, explicit CLI paths,
missing inputs and the existing XLSX/ZIP container decoder. No market database
or captured exchange/issuer documents are needed.
