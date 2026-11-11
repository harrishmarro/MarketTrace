"""Chronological evaluation primitives and a synthetic-only reproducibility demo.

Adapted from the saved research diagnostic. No market data loader, dataset
approval, strategy evaluation, network access or broker execution is provided.
"""
import argparse
import csv
import hashlib
import json
import math
import random
from datetime import date, timedelta
from pathlib import Path

import numpy as np

FEATURES = ['return_1', 'return_5', 'return_20', 'range_over_close',
            'mean_20_return', 'std_20_return', 'volume_over_mean_20_minus_1']


def build_samples(rows):
    for row in rows:
        day = row['day']
        if not isinstance(day, str) or date.fromisoformat(day).isoformat() != day:
            raise ValueError('Expected ISO observation dates')
    if [r['day'] for r in rows]!=sorted({r['day'] for r in rows}):raise ValueError('Dates must be unique and ascending')
    close=np.array([float(r['close']) for r in rows]);volume=np.array([float(r['volume']) for r in rows])
    if not np.isfinite(close).all() or not np.isfinite(volume).all() or (close<=0).any() or (volume<0).any():raise ValueError('Invalid bar values')
    if np.any(volume != np.floor(volume)):
        raise ValueError('Volume must contain whole shares')
    for row in rows:
        o, h, l, c = [float(row[k]) for k in ('open', 'high', 'low', 'close')]
        if not all(math.isfinite(v) and v > 0 for v in (o, h, l, c)) or l > min(o, c) or h < max(o, c):
            raise ValueError('Invalid OHLC bounds')
    result=[]
    for i in range(20,len(rows)-1):
        past=close[i-19:i+1]/close[i-20:i]-1
        mean_volume=volume[i-19:i+1].mean()
        if mean_volume<=0:raise ValueError('No positive trailing volume')
        x=[close[i]/close[i-1]-1,close[i]/close[i-5]-1,close[i]/close[i-20]-1,
           (float(rows[i]['high'])-float(rows[i]['low']))/close[i],past.mean(),past.std(),volume[i]/mean_volume-1]
        result.append(dict(origin=rows[i]['day'],target_day=rows[i+1]['day'],x=[float(v) for v in x],y=float(close[i+1]/close[i]-1)))
    return result

def partition(samples,p):
    bounds = [p[k] for k in ('training_end', 'validation_start', 'validation_end', 'test_start', 'test_end')]
    if any(not isinstance(d, str) or date.fromisoformat(d).isoformat() != d for d in bounds):
        raise ValueError('Expected ISO partition boundaries')
    a, b, c, d, e = bounds
    if not a < b <= c < d <= e:
        raise ValueError('Partitions must be ordered and disjoint')
    groups={k:[] for k in ('train','validation','test','excluded_boundary')}
    for r in samples:
        if r['origin'] >= r['target_day']:
            raise ValueError('Target must follow forecast origin')
        if r['target_day']<=p['training_end']:key='train'
        elif r['origin']>=p['validation_start'] and r['target_day']<=p['validation_end']:key='validation'
        elif r['origin']>=p['test_start'] and r['target_day']<=p['test_end']:key='test'
        else:key='excluded_boundary'
        groups[key].append(r)
    return groups

def fit(x,y,alpha=1.0):
    x=np.asarray(x,dtype=float);y=np.asarray(y,dtype=float)
    if x.ndim != 2 or y.ndim != 1 or x.shape[0] != y.size or not x.shape[1]:
        raise ValueError('Training arrays must be aligned matrix/vector inputs')
    if y.size<30 or not np.isfinite(x).all() or not np.isfinite(y).all():raise ValueError('Insufficient finite training samples')
    if not isinstance(alpha, (int, float)) or not math.isfinite(alpha) or alpha <= 0:
        raise ValueError('Positive finite regularization required')
    center=x.mean(axis=0);scale=x.std(axis=0);scale[scale==0]=1
    z=(x-center)/scale;intercept=float(y.mean())
    coef=np.linalg.solve(z.T@z+alpha*np.eye(z.shape[1]),z.T@(y-intercept))
    return dict(center=center.tolist(),scale=scale.tolist(),coefficients=coef.tolist(),intercept=intercept)

def predict(model,x):
    x = np.asarray(x, dtype=float)
    center, scale, coefficients = [np.asarray(model[k], dtype=float) for k in ('center', 'scale', 'coefficients')]
    if (x.ndim != 2 or center.ndim != 1 or scale.shape != center.shape
            or coefficients.shape != center.shape or x.shape[1] != center.size
            or not all(np.isfinite(v).all() for v in (x, center, scale, coefficients))
            or (scale <= 0).any() or not math.isfinite(model['intercept'])):
        raise ValueError('Invalid prediction inputs')
    return ((x-center)/scale)@coefficients+model['intercept']

def metrics(y,pred):
    y=np.asarray(y,dtype=float);pred=np.asarray(pred,dtype=float)
    if y.ndim != 1 or pred.shape != y.shape or not y.size or not np.isfinite(y).all() or not np.isfinite(pred).all():
        raise ValueError('Expected nonempty, finite, aligned metric vectors')
    active=pred!=0
    return dict(samples=len(y),mae=float(np.mean(np.abs(y-pred))),rmse=float(np.sqrt(np.mean((y-pred)**2))),
                directional_accuracy=float(np.mean(np.sign(y[active])==np.sign(pred[active]))) if active.any() else None,
                directional_predictions=int(active.sum()),correlation=float(np.corrcoef(y,pred)[0,1]) if np.std(y)>0 and np.std(pred)>1e-12 else None)


def synthetic_rows(count=360, seed=7):
    """Invented consecutive observations, not an exchange trading calendar."""
    rng = random.Random(seed)
    close = 100.0
    rows = []
    for i in range(count):
        opened = close * math.exp(rng.gauss(0, .002))
        close = opened * math.exp(.0002 + .003 * math.sin(i / 8) + rng.gauss(0, .008))
        rows.append(dict(
            day=(date(2020, 1, 1) + timedelta(days=i)).isoformat(),
            open=opened, close=close, high=max(opened, close) * 1.005,
            low=min(opened, close) * .995, volume=rng.randrange(1000, 10000)))
    return rows


def demo_protocol(rows):
    return dict(training_end=rows[219]['day'], validation_start=rows[220]['day'],
                validation_end=rows[289]['day'], test_start=rows[290]['day'],
                test_end=rows[-1]['day'])


def run_demo(output):
    """Write a fixed synthetic experiment to a new directory before fitting."""
    rows = synthetic_rows()
    protocol = demo_protocol(rows)
    samples = build_samples(rows)
    groups = partition(samples, protocol)
    if any(len(groups[k]) < 30 for k in ('train', 'validation', 'test')):
        raise ValueError('Insufficient partition sizes')
    digest = hashlib.sha256(json.dumps(rows, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    registration = dict(
        data_kind='synthetic', generated_observations=len(rows), seed=7,
        input_sha256=digest, protocol=protocol, features=FEATURES,
        model='ridge', alpha=1.0, numpy_version=np.__version__,
        code_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        target='next-observed-close raw price return',
        market_data_approved=False, strategy_evaluation_approved=False)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    (output/'registration.json').write_text(json.dumps(registration, indent=2) + '\n')
    train = groups['train']
    model = fit([r['x'] for r in train], [r['y'] for r in train], alpha=1.0)
    report = dict(
        data_kind='synthetic', input_sha256=digest, model=model,
        partition_counts={k: len(v) for k, v in groups.items()}, metrics={},
        market_performance_evaluated=False, profitability_evaluated=False,
        strategy_evaluation_approved=False,
        limitations=[
            'Generated data only; results say nothing about actual market predictability.',
            'Consecutive artificial dates are not a validated exchange calendar.',
            'Raw price returns exclude dividends, costs, execution and taxes.',
            'A close-based feature does not authorize a fill at that same closing price.',
            'Repeated synthetic demo runs are not independent market evidence.'])
    predictions = []
    for name in ('validation', 'test'):
        part = groups[name]
        actual = np.array([r['y'] for r in part])
        forecast = predict(model, [r['x'] for r in part])
        report['metrics'][name] = dict(
            ridge=metrics(actual, forecast),
            zero_return=metrics(actual, np.zeros(len(part))),
            training_mean=metrics(actual, np.full(len(part), model['intercept'])))
        for row, value in zip(part, forecast):
            predictions.append(dict(
                data_kind='synthetic', partition=name, origin=row['origin'],
                target_day=row['target_day'], actual_return=row['y'],
                ridge_prediction=float(value), zero_prediction=0.0,
                training_mean_prediction=model['intercept']))
    with (output/'predictions.csv').open('w', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(predictions[0]))
        writer.writeheader()
        writer.writerows(predictions)
    (output/'result.json').write_text(json.dumps(report, indent=2, allow_nan=False) + '\n')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--synthetic', action='store_true', help='Run the generated-data demonstration only')
    parser.add_argument('--output', required=True, type=Path, help='New local output directory')
    args = parser.parse_args()
    if not args.synthetic:
        parser.error('Only --synthetic is supported; real-data research release is separate')
    result = run_demo(args.output)
    print(json.dumps({k: result[k] for k in ('data_kind', 'partition_counts', 'market_performance_evaluated', 'profitability_evaluated')}, indent=2))


if __name__ == '__main__':
    main()

