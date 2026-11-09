# Daily-data ingestion

For retaining additional NSE series from saved source batches, see
[series-preserving staging](series-staging.md). The basic EQ importer below
remains unchanged.

## Offline import

The CLI accepts a locally available provider file and stores source bytes and parsed observations in a local SQLite database:

```bash
python -m daily_data.ingest --provider nse --file /path/to/report.csv --db local-output/daily.sqlite
```

For a US daily equity chart JSON response, use `--provider yahoo`. The Python API also accepts `yahoo_india`; this option is not exposed by the current CLI. The default database path is `research-data/daily.sqlite`, excluded from Git.

The CLI cutoff is the current date in the provider's exchange timezone. Rows on or after that date are excluded. For reproducible historical cutoffs, call `ingest(db_path, provider, raw_bytes, source, cutoff)` with an explicit `datetime.date`. Store the actual source identifier; it is provenance metadata, not independent source authentication.

## Storage behavior

`batches` retains the provider, content hash, retrieval timestamp, cutoff and original payload. `observations` retains parsed OHLCV, currency and any separately supplied adjusted close. A content/provider/cutoff key prevents repeated imports of the same batch; revised bytes create a separate batch. Downstream consumers must resolve revisions deliberately rather than concatenate all batches as independent market observations.

The NSE adapter imports the EQ series only. Other series are excluded; this importer alone does not establish full NSE instrument coverage. Invalid OHLC, nonfinite values and duplicate security/date records block the import. Container decoding supports a bounded ZIP with one CSV or a single XLSX worksheet with supported value types, rejecting formulas and ambiguous members.

## Network access

`--provider nse --day YYYY-MM-DD` downloads a completed-date report, validates its reported date and imports it. `--provider yahoo --symbol SYMBOL` requests a recent daily chart and checks the returned symbol. These are optional network operations; tests do not invoke them. Access failures or upstream response changes require investigation. Follow source usage terms and do not interpret a successful download as permission to redistribute it.

## Research limitations

A date cutoff excludes incomplete dates; it does not prove when historical data were first published. Retrieval timestamps are collection times. Corporate actions, historical security identities, calendar amendments, survivorship and executable fills are outside this module. Adjusted close must not substitute for an executable raw price.
