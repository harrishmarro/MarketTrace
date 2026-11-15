# Offline verification and synthetic reproducibility

The public project can be checked without the original market database,
historical research outputs, issuer documents, credentials or broker access.
`scripts/verify_project.py` adapts the research verifier to public unit tests,
CLI smoke checks and generated-data replay. It does not verify private source
inventories, authenticate market inputs or rerun historical model studies.

## Core checks

Use Python 3.12 with an IANA timezone database. From the repository root:

```bash
python scripts/verify_project.py --mode core
```

This runs the data-ingestion, provenance, cost, verification-harness and paper
tests. The optional forecasting test module is deliberately excluded, with the
count printed. Other skipped tests, an empty suite, failures or import errors
make the command fail. No third-party Python package is required for this mode
when the operating system supplies timezone data. On a system without IANA data,
install `tzdata` in the active environment before running these checks.

The checker resolves project paths from its own location, so it can also be
invoked by absolute path from another working directory. Test fixtures use
invented inputs and temporary databases. CLI `--help` checks cover ingestion,
NSE series staging, announcement normalization and historical cost scenarios.

## Full checks and replay

In an isolated Python 3.12 environment:

```bash
python -m pip install -r requirements-forecast.txt
python scripts/verify_project.py --mode full
```

Full mode requires NumPy and runs every discovered test, including the optional
forecasting tests. Missing NumPy is an error; skipped forecasting tests cannot
produce a successful full-verification result. The checker prints the Python
and NumPy versions and adds a help check for the forecast CLI.

After the tests pass, it runs the fixed synthetic forecasting demo twice in
separate temporary directories and compares all three artifacts:

- `registration.json`
- `predictions.csv`
- `result.json`

The comparison requires identical bytes, explicit synthetic-data labels,
nonempty synthetic prediction records and false market/strategy/profitability
flags. Temporary replay outputs are removed when the check completes. The
forecasts describe generated data only and establish no market performance.

This is same-environment replay. Identical bytes across operating systems,
Python patches, NumPy versions or numerical-library builds are not guaranteed.
The dependency file pins the optional NumPy version; the workflow uses one
thread for the common BLAS/OpenMP controls in its full job. These controls do
not turn synthetic replay into independent market validation.

## GitHub Actions

[Offline validation](../.github/workflows/tests.yml) runs on pull requests
targeting `main`, pushes to `main`, and manual dispatch. It has two Ubuntu 24.04 /
Python 3.12 jobs:

| Job | Dependency setup | Checks |
| --- | --- | --- |
| Core tests | No optional package installation | Core suites and core CLI help |
| Forecast tests and replay | Install `requirements-forecast.txt` | All suites, CLI help and synthetic replay |

Checkout and Python setup actions are pinned to reviewed upstream commit SHAs.
The workflow grants only `contents: read`, does not persist checkout credentials,
uses ordinary `pull_request` events and has a 15-minute timeout per job. It
does not use repository secrets, fetch market data, upload research artifacts,
publish a package, deploy a service or merge a pull request. Installation may
contact the Python package index; the tests and replay use local synthetic data.

A local verification result and a hosted Actions result are separate evidence.
The presence of a workflow file does not establish that GitHub has executed it
or that branch-protection checks are configured. No repository settings are
changed by this workflow.
