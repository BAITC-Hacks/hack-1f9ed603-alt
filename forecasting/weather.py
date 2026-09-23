"""Point-in-time ECMWF IFS weather runs from Open-Meteo Single Runs.

`run` is model initialisation, not actual publication. We only permit use after
an explicitly conservative 12-hour delay and preserve both timestamps. Exact
historical availability is not supplied by this archive.
"""

from __future__ import annotations

import json
import os
import ssl
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen

from forecasting.sites import SITES

SOURCE = "open_meteo_single_runs_ecmwf_ifs"
MODEL = "ecmwf_ifs"
BASE_URL = "https://single-runs-api.open-meteo.com/v1/forecast"
SAFE_DELAY = timedelta(hours=12)
UTC = timezone.utc


@dataclass(frozen=True)
class WeatherRun:
    initialized_at: datetime
    usable_after_at: datetime
    points: dict[str, dict[datetime, float]]
    grid_coordinates: dict[str, tuple[float, float]]

    @property
    def run_id(self) -> str:
        return f"ecmwf_ifs_{self.initialized_at:%Y%m%dT%H%MZ}"


def select_run(issued_at: datetime) -> datetime:
    if issued_at.tzinfo is None or issued_at.utcoffset() is None:
        raise ValueError("issued_at должен содержать часовой пояс")
    latest = issued_at.astimezone(UTC) - SAFE_DELAY
    return latest.replace(hour=(latest.hour // 6) * 6, minute=0, second=0, microsecond=0)


def _ssl_context() -> ssl.SSLContext:
    cafile = os.getenv("SSL_CERT_FILE")
    if not cafile and Path("/etc/ssl/cert.pem").is_file():
        cafile = "/etc/ssl/cert.pem"
    return ssl.create_default_context(cafile=cafile)


def fetch_run(initialized_at: datetime, cache_dir: Path) -> WeatherRun:
    if initialized_at.tzinfo is None or initialized_at.utcoffset() is None:
        raise ValueError("Время погодного запуска должно содержать часовой пояс")
    initialized_at = initialized_at.astimezone(UTC)
    if initialized_at.minute or initialized_at.second or initialized_at.hour % 6:
        raise ValueError("ECMWF IFS запускается каждые шесть часов")
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / f"ecmwf_ifs_{initialized_at:%Y%m%dT%H%MZ}.json"
    if path.exists():
        payload = json.loads(path.read_text(encoding="utf-8"))
    else:
        params = {
            "latitude": ",".join(f"{site.latitude:.6f}" for site in SITES.values()),
            "longitude": ",".join(f"{site.longitude:.6f}" for site in SITES.values()),
            "run": initialized_at.strftime("%Y-%m-%dT%H:%M"),
            "hourly": "wind_speed_100m",
            "wind_speed_unit": "ms",
            "models": MODEL,
            "forecast_hours": 72,
            "timezone": "UTC",
        }
        url = BASE_URL + "?" + urlencode(params)
        with urlopen(url, timeout=30, context=_ssl_context()) as response:
            responses = json.load(response)
        if not isinstance(responses, list) or len(responses) != len(SITES):
            raise ValueError("Погодный архив вернул неожиданный набор координат")
        payload = {
            "source": SOURCE,
            "model": MODEL,
            "url": url,
            "initialized_at": initialized_at.isoformat(),
            "usable_after_at": (initialized_at + SAFE_DELAY).isoformat(),
            "availability_basis": "conservative 12-hour delay; exact publication time unknown",
            "site_ids": list(SITES),
            "responses": responses,
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    if (payload.get("initialized_at") != initialized_at.isoformat()
            or payload.get("source") != SOURCE
            or payload.get("model") != MODEL
            or payload.get("site_ids") != list(SITES)
            or len(payload.get("responses", [])) != len(SITES)):
        raise ValueError(f"Повреждён погодный кэш: {path}")
    points: dict[str, dict[datetime, float]] = {}
    grid_coordinates: dict[str, tuple[float, float]] = {}
    for site_id, response in zip(payload["site_ids"], payload["responses"], strict=True):
        hourly = response["hourly"]
        if response["hourly_units"]["wind_speed_100m"] != "m/s":
            raise ValueError("Погодный архив вернул другую единицу скорости ветра")
        site_points = {}
        for stamp, wind in zip(hourly["time"], hourly["wind_speed_100m"], strict=True):
            if wind is None:
                continue
            moment = datetime.fromisoformat(stamp)
            if moment.tzinfo is not None:
                raise ValueError("Погодный архив вернул время с неожиданным смещением")
            site_points[moment.replace(tzinfo=UTC)] = float(wind)
        points[site_id] = site_points
        grid_coordinates[site_id] = (float(response["latitude"]), float(response["longitude"]))
    return WeatherRun(initialized_at, initialized_at + SAFE_DELAY, points, grid_coordinates)
