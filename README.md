# MarketTrace

**MarketTrace is an evidence-driven stock-market research project that aims to turn market data into transparent, testable forecasts.** It starts with NSE equities and is being developed to connect validated price and announcement data, machine-learning evaluation, and risk-controlled paper trading.

The current repository provides the data-ingestion foundation: daily-price adapters, input validation and SQLite storage that preserves original source data and integrity hashes. Forecasting and paper-trading components are under development; reliable predictive performance and profitability have not been demonstrated.

## Run the offline checks

Use Python 3.12 with an available IANA timezone database. No third-party Python packages are required for the current importer on systems with timezone data installed.

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m unittest discover -s daily_data -p 'test_*.py' -v
python -m daily_data.ingest --help
```

On Windows, activate with `.venv\Scripts\Activate.ps1`. If Python cannot find IANA timezones, install `tzdata` in your virtual environment. The tests run offline using synthetic data and temporary databases.

## Included functionality

- NSE full-report, classic bhavcopy and UDiFF daily EQ parsers.
- Bounded CSV/ZIP/single-worksheet XLSX decoding without evaluating formulas.
- A research adapter for Yahoo daily equity chart responses, with currency and exchange-timezone checks.
- Positive finite prices, integer volume, OHLC consistency, completed-date cutoffs and duplicate rejection.
- Original payload bytes and SHA-256 digests retained in SQLite; repeated imports are idempotent and revised payloads remain separate.
- Raw close and provider-adjusted close remain distinct.

See [daily-data ingestion](docs/ingestion.md) for usage and boundaries.

## Data and research boundaries

No raw exchange data, issuer documents, private information or large research databases are distributed here. Use data only under its source's applicable terms. The original full research database is a separate dependency and is unnecessary for these synthetic tests.

An imported row is not automatically cleared for training. Historical identity, corporate actions, exchange calendars, source availability and execution assumptions require separate validation. No reliable predictive edge or profitability has been established. The Yahoo research adapter is not a licensed real-time feed.

## Attribution

This project reuses work derived from [jakeschincariol/day-trader-skill](https://github.com/jakeschincariol/day-trader-skill), originally reviewed at commit `3d0f4ef6986f4984b7c6bd46f7ff4f87744c3abd`. Its inherited [MIT license](LICENSE) and copyright notice are preserved. That license does not grant redistribution rights over third-party market data.
