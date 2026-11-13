"""Offline public-project checks; no research captures or historical fitting.

Adapted from the checkpoint verifier, replacing private package/evidence files
with public unit suites and a generated-data replay in temporary directories.
"""
import argparse
import csv
import importlib.util
import json
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import unittest
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

FORECAST_PREFIX = 'daily_data.test_forecast_evaluation.'
DEMO_FILES = ('registration.json', 'predictions.csv', 'result.json')


def cases(suite):
    """Flatten discovery without hiding loader failures or test identities."""
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from cases(item)
        else:
            yield item


def select_tests(suite, mode):
    if mode not in ('core', 'full'):
        raise ValueError('Expected core or full mode')
    tests = list(cases(suite))
    excluded = [test for test in tests if mode == 'core' and test.id().startswith(FORECAST_PREFIX)]
    chosen = [test for test in tests if not (mode == 'core' and test.id().startswith(FORECAST_PREFIX))]
    return unittest.TestSuite(chosen), len(excluded)


def require_success(result):
    if result.testsRun == 0:
        raise RuntimeError('No tests were discovered')
    if not result.wasSuccessful():
        raise RuntimeError('Unit tests failed')
    if result.skipped:
        raise RuntimeError('Unexpected skipped tests: ' + ', '.join(reason for _, reason in result.skipped))


def compare_demo_outputs(first, second):
    """Compare complete artifacts and retain the synthetic-only boundaries."""
    first, second = Path(first), Path(second)
    for name in DEMO_FILES:
        if (first / name).read_bytes() != (second / name).read_bytes():
            raise ValueError('Synthetic replay differs: ' + name)
    registration = json.loads((first / 'registration.json').read_text())
    report = json.loads((first / 'result.json').read_text())
    if registration.get('data_kind') != 'synthetic' or report.get('data_kind') != 'synthetic':
        raise ValueError('Replay artifacts must identify synthetic data')
    if registration.get('market_data_approved') is not False:
        raise ValueError('Synthetic registration must not approve market data')
    for record in (registration, report):
        if record.get('strategy_evaluation_approved') is not False:
            raise ValueError('Synthetic replay must not approve strategy evaluation')
    if (report.get('market_performance_evaluated') is not False
            or report.get('profitability_evaluated') is not False):
        raise ValueError('Synthetic replay must not claim market performance')
    with (first / 'predictions.csv').open(newline='') as handle:
        predictions = list(csv.DictReader(handle))
    if not predictions or any(row.get('data_kind') != 'synthetic' for row in predictions):
        raise ValueError('Expected nonempty synthetic prediction records')


def verify_replay():
    from daily_data.forecast_evaluation import run_demo

    with tempfile.TemporaryDirectory(prefix='markettrace-synthetic-') as temporary:
        first, second = Path(temporary) / 'first', Path(temporary) / 'second'
        run_demo(first)
        run_demo(second)
        compare_demo_outputs(first, second)
    print('Synthetic replay: three artifacts identical within this environment.', flush=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=('core', 'full'), default='core',
                        help='Core excludes the optional forecast suite; full requires NumPy and runs replay')
    args = parser.parse_args(argv)
    if sys.version_info[:2] != (3, 12):
        raise RuntimeError('These checks are validated with Python 3.12')
    # Check the actual zones used by the ledger/importer before running tests.
    for name in ('Asia/Kolkata', 'America/New_York'):
        ZoneInfo(name)
    if args.mode == 'full' and importlib.util.find_spec('numpy') is None:
        raise RuntimeError('Full mode requires: python -m pip install -r requirements-forecast.txt')
    print(f'Python {platform.python_version()}; mode={args.mode}', flush=True)
    if args.mode == 'full':
        import numpy as np
        print(f'NumPy {np.__version__}', flush=True)
    discovered = unittest.TestSuite()
    for folder in ('daily_data', 'paper'):
        discovered.addTests(unittest.defaultTestLoader.discover(
            start_dir=str(ROOT / folder), pattern='test_*.py', top_level_dir=str(ROOT)))
    suite, excluded = select_tests(discovered, args.mode)
    print(f'Optional forecasting tests excluded: {excluded}', flush=True)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    require_success(result)
    modules = ['daily_data.ingest', 'daily_data.nse_series',
               'daily_data.nse_announcement_records', 'daily_data.trade_costs']
    if args.mode == 'full':
        modules.append('daily_data.forecast_evaluation')
    for module in modules:
        subprocess.run([sys.executable, '-m', module, '--help'], cwd=ROOT,
                       check=True, capture_output=True, text=True, timeout=30)
    print(f'CLI help checks: {len(modules)} passed.', flush=True)
    if args.mode == 'full':
        verify_replay()
    print(f'Verified {result.testsRun} tests with no skips.', flush=True)
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (RuntimeError, ValueError, OSError, subprocess.SubprocessError) as error:
        raise SystemExit(str(error)) from error
