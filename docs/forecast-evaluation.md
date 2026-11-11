# Reproducible forecasting-evaluation demonstration

This module adapts the seven trailing-bar features, ridge fit and baseline metrics
from the research diagnostic into a public, self-contained demonstration. It
ships no captured prices, private dataset-release files or historical forecasts.
Its command-line interface supports **generated synthetic data only**.

## Install and run

Activate a Python 3.12 virtual environment, then install the optional dependency:

```bash
python -m pip install -r requirements-forecast.txt
python -m unittest discover -s daily_data -p 'test_*.py' -v
python -m daily_data.forecast_evaluation --synthetic --output local-output/forecast-demo
```

The demo uses a fixed seed and 360 invented OHLCV observations on consecutive
artificial dates. These dates do not assert an exchange trading calendar. Use a
new output directory for each run; existing output directories are rejected.
Nothing is downloaded, no broker is contacted and no real security is evaluated.

The standard-library ingestion/provenance checks can still run without NumPy.
Forecasting tests are explicitly skipped if the optional NumPy dependency is
absent; a run with skipped tests is not a full forecasting verification.

## Evaluation mechanics

- Features use only observations up to the origin: one-, five- and twenty-record
  returns, relative high-low range, trailing mean/standard deviation of returns,
  and relative trailing volume.
- The target is the raw return from an origin close to the next observed close.
  Both the origin and target must fall within the same validation/test partition.
  Labels spanning boundaries are excluded. Twenty observations warm up features.
- The fixed ridge coefficient penalty is 1.0. Feature centering and scaling,
  coefficients and the constant mean-return baseline are fit on training samples
  only. Validation and test samples do not refit them.
- The demo yields 199 training, 69 validation and 69 test samples, with two
  boundary-spanning labels excluded. These counts describe generated data only.
- Report MAE and RMSE alongside zero-return and training-mean baselines. Returns
  are fractional units: multiply an error by 100 for percentage points. Zero
  predictions abstain from direction, so direction accuracy is null when every
  prediction is zero. The directional-prediction count is always reported.

## Artifacts and reproduction

`registration.json` is written before fitting and records the feature/partition
protocol, generator seed, NumPy version, input hash and source-code hash.
`predictions.csv` retains origin, target, partition, outcome and baseline/model
predictions. `result.json` records metrics, the fitted parameters and limitations.
Each artifact identifies the data as synthetic. Local outputs are excluded by Git.

Tests check future-bar isolation, label boundaries, training-only scaling,
invalid inputs, baseline abstention, register-before-fit order, CLI behavior and
identical artifact replay within the same environment. Bitwise equality across
different numerical libraries or platforms is not promised.

## Research boundaries

The numerical functions are evaluation primitives, not a source-authentication or
dataset-eligibility system. This demo does not load or modify the separately
gated research datasets, prior registrations or inspected historical results.
There is no real-data CLI, hyperparameter search or model promotion path.

Generated-data metrics establish software behavior only. They are not evidence
of actual market predictability, independent validation or profitable trading.
Raw close returns exclude dividends, cash timing, fees, slippage, taxes and
execution. Completed-close features cannot justify an executable fill at that
same past closing price. Any future real-data study needs its own verified input
release, predeclared protocol, chronological evaluation and honest record of
previously inspected data.
