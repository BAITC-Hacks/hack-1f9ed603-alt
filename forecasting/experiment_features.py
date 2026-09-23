"""Compare extended archived weather against the baseline using supplied CSV targets.

Downloads are disabled. First run forecasting.feature_weather explicitly.
Selection uses December only; January is a retrospective confirmation period.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from forecasting.baseline import Example, fit_curve
from forecasting.feature_weather import CACHE, PROFILE, FeatureWeatherRun, fetch_feature_run
from forecasting.hourly import load_hourly
from forecasting.storage import write_json
from forecasting.time_alignment import time_alignment_metadata
from forecasting.train_baseline import power_by_hour_end
from forecasting.weather import UTC, fetch_run

ROOT = Path(__file__).resolve().parents[1]
FEATURES = {
    'wind': ['wind_speed_100m'],
    'weather': ['wind_speed_100m', 'direction_sin', 'direction_cos', 'wind_speed_10m',
                'temperature_2m', 'surface_pressure'],
}
FEATURES['derived'] = FEATURES['weather'] + [
    'wind_shear', 'air_density_proxy', 'wind_mean_3h', 'wind_ramp_3h',
    'target_hour_sin', 'target_hour_cos', 'forecast_lead_hours']
# Added as a diagnostic ablation after the initial comparison. Excluded from
# model selection to keep the initial December selection rule unchanged.
FEATURES['wind_context'] = ['wind_speed_100m', 'wind_mean_3h', 'wind_ramp_3h',
                            'target_hour_sin', 'target_hour_cos', 'forecast_lead_hours']
CONFIG = {'learning_rate': 0.05, 'max_iter': 120, 'max_leaf_nodes': 7,
          'min_samples_leaf': 30, 'l2_regularization': 1.0,
          'early_stopping': False, 'random_state': 42}


@dataclass(frozen=True)
class FeatureRow:
    example: Example
    features: dict[str, float]


def feature_values(run: FeatureWeatherRun, turbine: str, issued: datetime, target: datetime) -> dict[str, float]:
    if run.usable_after_at > issued or target <= issued:
        raise ValueError('Weather or target violates historical launch boundary')
    points = run.points[turbine]
    current = points[target]
    wind = current['wind_speed_100m']
    angle = math.radians(current['wind_direction_100m'])
    clock = 2 * math.pi * target.hour / 24
    return {'wind_speed_100m': wind, 'direction_sin': math.sin(angle), 'direction_cos': math.cos(angle),
            'wind_speed_10m': current['wind_speed_10m'], 'temperature_2m': current['temperature_2m'],
            'surface_pressure': current['surface_pressure'],
            'wind_shear': wind-current['wind_speed_10m'],
            'air_density_proxy': current['surface_pressure']*100/(287.05*(current['temperature_2m']+273.15)),
            'wind_mean_3h': statistics.mean(points[target-timedelta(hours=k)]['wind_speed_100m'] for k in range(3)),
            'wind_ramp_3h': wind-points[target-timedelta(hours=3)]['wind_speed_100m'],
            'target_hour_sin': math.sin(clock), 'target_hour_cos': math.cos(clock),
            'forecast_lead_hours': (target-run.initialized_at).total_seconds()/3600}


def training_rows(rows: list[FeatureRow], turbine: str, cutoff: datetime) -> list[FeatureRow]:
    return [r for r in rows if r.example.turbine_id == turbine
            and r.example.target_end_at < cutoff and r.example.forecast_issued_at < cutoff
            and r.example.target_end_at-r.example.forecast_issued_at <= timedelta(hours=24)]


def build_rows(root: Path = ROOT, cache: Path = CACHE) -> tuple[list[FeatureRow], dict]:
    raw_hashes = {}
    power = {}
    for turbine in ('turbine_1', 'turbine_2'):
        path = root / 'data/raw' / f'{turbine}.csv'
        raw_hashes[turbine] = hashlib.sha256(path.read_bytes()).hexdigest()
        power[turbine] = power_by_hour_end(load_hourly(root/'data/raw', turbine))
    rows, manifest = [], []
    day = datetime(2025, 11, 1, tzinfo=UTC)
    matched, missing_power = 0, 0
    while day <= datetime(2026, 1, 31, tzinfo=UTC):
        issued = day + timedelta(hours=12)
        extended = fetch_feature_run(day, cache, download=False)
        original_path = root/'data/weather/ecmwf_ifs'/f'ecmwf_ifs_{day:%Y%m%dT%H%MZ}.json'
        if not original_path.exists():
            raise FileNotFoundError(original_path)
        original = fetch_run(day, original_path.parent)
        path = cache / original_path.name
        manifest.append({'initialized_at': day.isoformat(), 'usable_after_at': extended.usable_after_at.isoformat(),
                         'weather_run_id': original.run_id, 'file':path.name,
                         'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
        for turbine in power:
            for step in range(1, 49):
                target = issued + timedelta(hours=step)
                features = feature_values(extended, turbine, issued, target)
                if abs(features['wind_speed_100m']-original.points[turbine][target]) > 1e-9:
                    raise ValueError('Extended archive changes baseline wind; cannot isolate added-feature effect')
                if target not in power[turbine]:
                    missing_power += 1
                    continue
                rows.append(FeatureRow(Example(turbine, issued, target, features['wind_speed_100m'],
                                               power[turbine][target]), features))
                matched += 1
        day += timedelta(days=1)
    return rows, {'raw_csv_sha256':raw_hashes, 'weather_runs':manifest,
                  'matched_launch_lead_pairs':matched, 'missing_power_pairs_excluded':missing_power,
                  'target_source':'data/raw/turbine_1.csv and turbine_2.csv; complete hourly means only',
                  'baseline_wind_exactly_matches_extended_archive':True}


def metrics(actual: list[float], predicted: list[float]) -> dict:
    errors = [p-y for p,y in zip(predicted,actual,strict=True)]
    return {'n':len(errors), 'mae':statistics.mean(abs(e) for e in errors),
            'rmse':math.sqrt(statistics.mean(e*e for e in errors)), 'bias':statistics.mean(errors)}


def run_experiment(root: Path = ROOT, cache: Path = CACHE) -> dict:
    import sklearn
    import numpy
    import scipy
    from sklearn.ensemble import HistGradientBoostingRegressor
    from threadpoolctl import threadpool_limits
    rows, provenance = build_rows(root, cache)
    reference_path=root/'data/processed/backtest_report.json'
    reference=json.loads(reference_path.read_text(encoding='utf-8'))
    provenance['baseline_report_sha256']=hashlib.sha256(reference_path.read_bytes()).hexdigest()
    provenance['code_sha256']={name:hashlib.sha256((root/'forecasting'/name).read_bytes()).hexdigest()
                               for name in ('experiment_features.py','feature_weather.py','baseline.py',
                                            'hourly.py','dataset.py','time_alignment.py')}
    details, aggregate = [], {}
    for period, start, end in [('2025-12', datetime(2025,12,1,tzinfo=UTC), datetime(2026,1,1,tzinfo=UTC)),
                               ('2026-01', datetime(2026,1,1,tzinfo=UTC), datetime(2026,2,1,tzinfo=UTC))]:
        aggregate[period] = {}
        for turbine in ('turbine_1','turbine_2'):
            train = training_rows(rows, turbine, start)
            curve = fit_curve([r.example for r in train], start)
            fitted = {}
            for group, names in FEATURES.items():
                x = [[r.features[f] for f in names] for r in train]
                y = [r.example.normalized_power for r in train]
                for loss in ('squared_error', 'absolute_error'):
                    model = HistGradientBoostingRegressor(loss=loss, **CONFIG)
                    with threadpool_limits(limits=2):
                        model.fit(x,y)
                    fitted[f'hgb_{group}_{loss}'] = (model,names)
            for horizon in (24,48):
                test = [r for r in rows if r.example.turbine_id==turbine
                        and start<=r.example.target_end_at<end and r.example.forecast_issued_at>=start
                        and r.example.target_end_at-r.example.forecast_issued_at<=timedelta(hours=horizon)]
                actual = [r.example.normalized_power for r in test]
                predictions = {'baseline':[curve.predict(r.example.wind_speed_ms) for r in test]}
                for name,(model,names) in fitted.items():
                    with threadpool_limits(limits=2):
                        values=model.predict([[r.features[f] for f in names] for r in test])
                    predictions[name]=[float(min(1,max(0,p))) for p in values]
                scores = {}
                for name, pred in predictions.items():
                    scores[name] = metrics(actual,pred)
                    pool = aggregate[period].setdefault(name, {'actual':[], 'predicted':[]})
                    pool['actual'].extend(actual)
                    pool['predicted'].extend(pred)
                expected=next(r for r in reference['results'] if r['period']==period
                              and r['turbine_id']==turbine and r['horizon_hours']==horizon)
                if abs(scores['baseline']['mae']-expected['mae']) > 1e-10:
                    raise ValueError('Baseline comparison does not reproduce the checked-in backtest')
                details.append({'period':period,'turbine':turbine,'horizon_hours':horizon,
                                'training_count':len(train), 'training_cutoff_exclusive':start.isoformat(),
                                'last_training_target':max(r.example.target_end_at for r in train).isoformat(),
                                'results':scores})
            print(f'Evaluated {period} {turbine}', flush=True)
    summary={p:{n:metrics(v['actual'],v['predicted']) for n,v in pools.items()} for p,pools in aggregate.items()}
    candidates=[n for n in summary['2025-12'] if not n.startswith('hgb_wind_context_')]
    selected=min(candidates, key=lambda n:summary['2025-12'][n]['mae'])
    for turbine, expected in provenance['raw_csv_sha256'].items():
        if hashlib.sha256((root/'data/raw'/f'{turbine}.csv').read_bytes()).hexdigest()!=expected:
            raise ValueError('Raw CSV changed during the experiment')
    return {'experiment':'archived_weather_features_v1','feature_profile':PROFILE,
            'time_alignment':time_alignment_metadata(), 'provenance':provenance,
            'feature_groups':FEATURES, 'model_config':CONFIG,
            'software':{'scikit_learn':sklearn.__version__,'numpy':numpy.__version__,'scipy':scipy.__version__},
            'selection_rule':'minimum pooled December MAE; no January tuning',
            'selection_candidates':candidates,
            'diagnostic_only_models':[n for n in summary['2025-12'] if n not in candidates],
            'selected_on_december':selected,'summary':summary,'details':details,
            'limitations':['January was already used for project evaluation and is not a new untouched holdout.',
                           'Pooled horizons share target hours; samples are not independent.',
                           'February actual power is unavailable; no February accuracy claim.',
                           'No future observed wind, temperature or power used as predictors.',
                           'Experiment only; production runner still uses the baseline.']}


def main() -> None:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache-dir',type=Path,default=CACHE)
    parser.add_argument('--output',type=Path,default=ROOT/'data/processed/feature_experiment.json')
    args=parser.parse_args()
    report=run_experiment(cache=args.cache_dir)
    write_json(args.output,report)
    for name in report['summary']['2025-12']:
        print(name, 'December', round(report['summary']['2025-12'][name]['mae'],5),
              'January', round(report['summary']['2026-01'][name]['mae'],5))
    print('Selected on December:',report['selected_on_december'])


if __name__=='__main__':
    main()
