"""Versioned multivariable archive for offline forecasting experiments."""
from __future__ import annotations

import argparse
import json
import math
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import urlopen

from forecasting.sites import SITES
from forecasting.storage import write_json
from forecasting.weather import BASE_URL, MODEL, SOURCE, SAFE_DELAY, UTC, _parse_run, _ssl_context

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / 'data/weather/ecmwf_ifs_features'
PROFILE = 'extended_weather_v1'
UNITS = {'wind_speed_100m': 'm/s', 'wind_direction_100m': '\u00b0',
         'wind_speed_10m': 'm/s', 'temperature_2m': '\u00b0C', 'surface_pressure': 'hPa'}


@dataclass(frozen=True)
class FeatureWeatherRun:
    initialized_at: datetime
    usable_after_at: datetime
    points: dict[str, dict[datetime, dict[str, float]]]


def parse_feature_run(payload: dict, initialized_at: datetime) -> FeatureWeatherRun:
    base = _parse_run(payload, initialized_at)
    if payload.get('feature_profile') != PROFILE or payload.get('requested_variables') != list(UNITS):
        raise ValueError('Incompatible extended weather profile')
    points = {}
    for site_id, response in zip(SITES, payload['responses'], strict=True):
        hourly = response['hourly']
        stamps = hourly['time']
        for name, unit in UNITS.items():
            if response['hourly_units'].get(name) != unit:
                raise ValueError(f'Unexpected units for {name}')
            if not isinstance(hourly.get(name), list) or len(hourly[name]) != len(stamps):
                raise ValueError(f'Missing or misaligned {name}')
        site_points = {}
        for index, stamp in enumerate(stamps):
            moment = datetime.fromisoformat(stamp).replace(tzinfo=UTC)
            values = {name: hourly[name][index] for name in UNITS}
            for name, value in values.items():
                if value is None:
                    continue
                if type(value) not in (int, float) or not math.isfinite(value):
                    raise ValueError(f'Non-finite {name}')
                if name.startswith('wind_speed') and value < 0:
                    raise ValueError(f'Negative {name}')
                if name == 'wind_direction_100m' and not 0 <= value <= 360:
                    raise ValueError('Invalid wind direction')
                if name == 'surface_pressure' and value <= 0:
                    raise ValueError('Invalid pressure')
                if name == 'temperature_2m' and value <= -273.15:
                    raise ValueError('Invalid temperature')
            if any(value is None for value in values.values()):
                continue  # No fabricated weather values or imputation.
            site_points[moment] = {k: float(v) for k, v in values.items()}
        points[site_id] = site_points
    return FeatureWeatherRun(base.initialized_at, base.usable_after_at, points)


def fetch_feature_run(initialized_at: datetime, cache_dir: Path = CACHE, *, download: bool = False) -> FeatureWeatherRun:
    if initialized_at.tzinfo is None or initialized_at.utcoffset() is None:
        raise ValueError('Weather initialization needs timezone')
    initialized_at = initialized_at.astimezone(UTC)
    if initialized_at.hour % 6 or initialized_at.minute or initialized_at.second or initialized_at.microsecond:
        raise ValueError('Weather initialization must match a six-hour cycle')
    path = cache_dir / f'ecmwf_ifs_{initialized_at:%Y%m%dT%H%MZ}.json'
    if path.exists():
        return parse_feature_run(json.loads(path.read_text(encoding='utf-8')), initialized_at)
    if not download:
        raise FileNotFoundError(f'Extended archive missing: {path}; run feature_weather explicitly')
    params = {'latitude': ','.join(f'{s.latitude:.6f}' for s in SITES.values()),
              'longitude': ','.join(f'{s.longitude:.6f}' for s in SITES.values()),
              'run': initialized_at.strftime('%Y-%m-%dT%H:%M'), 'hourly': ','.join(UNITS),
              'wind_speed_unit': 'ms', 'temperature_unit': 'celsius', 'models': MODEL,
              'forecast_hours': 72, 'timezone': 'UTC'}
    url = BASE_URL + '?' + urlencode(params)
    for attempt in range(3):
        try:
            with urlopen(url, timeout=45, context=_ssl_context()) as response:
                responses = json.load(response)
            break
        except HTTPError as exc:
            if attempt == 2 or exc.code not in (429, 500, 502, 503, 504):
                raise
            time.sleep(5 * (attempt + 1))
    payload = {'source': SOURCE, 'model': MODEL, 'feature_profile': PROFILE,
               'requested_variables': list(UNITS), 'url': url,
               'initialized_at': initialized_at.isoformat(),
               'usable_after_at': (initialized_at + SAFE_DELAY).isoformat(),
               'availability_basis': 'conservative 12-hour delay; exact publication time unknown',
               'site_ids': list(SITES), 'responses': responses}
    parsed = parse_feature_run(payload, initialized_at)
    write_json(path, payload, indent=None)
    return parsed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--start', type=date.fromisoformat, default=date(2025, 11, 1))
    parser.add_argument('--end', type=date.fromisoformat, default=date(2026, 1, 31))
    parser.add_argument('--cache-dir', type=Path, default=CACHE)
    args = parser.parse_args()
    if args.start > args.end:
        parser.error('start must precede end')
    day, count = args.start, 0
    while day <= args.end:
        stamp = datetime(day.year, day.month, day.day, tzinfo=UTC)
        fetch_feature_run(stamp, args.cache_dir, download=True)
        count += 1
        if count % 10 == 0 or day == args.end:
            print(f'Validated {count} runs through {day}', flush=True)
        day += timedelta(days=1)
        time.sleep(.15)


if __name__ == '__main__':
    main()
