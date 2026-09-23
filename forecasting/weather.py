"""Point-in-time ECMWF IFS weather runs from Open-Meteo Single Runs.

`run` is model initialisation, not actual publication. We only permit use after
an explicitly conservative 12-hour delay and preserve both timestamps. Exact
historical availability is not supplied by this archive.
"""

from __future__ import annotations

import json
import math
import os
import ssl
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from http.client import HTTPException
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen

from forecasting.sites import SITES
from forecasting.storage import write_json

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


def _parse_run(payload: object, initialized_at: datetime) -> WeatherRun:
    """Validate both disk and network data before using or caching a run."""
    try:
        if (not isinstance(payload, dict)
                or payload.get("initialized_at") != initialized_at.isoformat()
                or payload.get("source") != SOURCE
                or payload.get("model") != MODEL
                or payload.get("site_ids") != list(SITES)
                or not isinstance(payload.get("responses"), list)
                or len(payload["responses"]) != len(SITES)):
            raise ValueError("Неверные метаданные погодного выпуска")
        usable_after = initialized_at + SAFE_DELAY
        if ("usable_after_at" in payload
                and datetime.fromisoformat(payload["usable_after_at"]) != usable_after):
            raise ValueError("Неверное время доступности погодного выпуска")
        points: dict[str, dict[datetime, float]] = {}
        coordinates: dict[str, tuple[float, float]] = {}
        for site_id, response in zip(payload["site_ids"], payload["responses"], strict=True):
            if response["utc_offset_seconds"] != 0:
                raise ValueError("Погодный архив должен возвращать время UTC")
            if response["hourly_units"]["wind_speed_100m"] != "m/s":
                raise ValueError("Погодный архив вернул другую единицу скорости ветра")
            hourly = response["hourly"]
            stamps, winds = hourly["time"], hourly["wind_speed_100m"]
            if not isinstance(stamps, list) or not isinstance(winds, list) or not stamps:
                raise ValueError("Погодный архив вернул пустой или неверный часовой ряд")
            site_points = {}
            previous = None
            for stamp, wind in zip(stamps, winds, strict=True):
                moment = datetime.fromisoformat(stamp)
                if moment.tzinfo is not None or moment.minute or moment.second or moment.microsecond:
                    raise ValueError("Неверная часовая метка в погодном архиве")
                moment = moment.replace(tzinfo=UTC)
                if moment < initialized_at or (previous is not None and moment - previous != timedelta(hours=1)):
                    raise ValueError("Нарушена часовая сетка погодного выпуска")
                previous = moment
                if wind is None:
                    continue  # Missing weather stays missing; forecast() rejects missing target hours.
                if type(wind) not in (float, int) or not math.isfinite(wind) or wind < 0:
                    raise ValueError("Недопустимая скорость ветра в погодном архиве")
                site_points[moment] = float(wind)
            if not site_points:
                raise ValueError("В погодном выпуске нет значений скорости ветра")
            latitude, longitude = response["latitude"], response["longitude"]
            if (type(latitude) not in (float, int) or type(longitude) not in (float, int)
                    or not math.isfinite(latitude) or not math.isfinite(longitude)
                    or not -90 <= latitude <= 90 or not -180 <= longitude <= 180):
                raise ValueError("Неверные координаты погодной сетки")
            points[site_id] = site_points
            coordinates[site_id] = (float(latitude), float(longitude))
        return WeatherRun(initialized_at, usable_after, points, coordinates)
    except (KeyError, TypeError, AttributeError, OverflowError) as exc:
        raise ValueError("Повреждена структура погодного выпуска") from exc


def fetch_run(initialized_at: datetime, cache_dir: Path) -> WeatherRun:
    if initialized_at.tzinfo is None or initialized_at.utcoffset() is None:
        raise ValueError("Время погодного запуска должно содержать часовой пояс")
    initialized_at = initialized_at.astimezone(UTC)
    if initialized_at.minute or initialized_at.second or initialized_at.microsecond or initialized_at.hour % 6:
        raise ValueError("ECMWF IFS запускается каждые шесть часов")
    path = cache_dir / f"ecmwf_ifs_{initialized_at:%Y%m%dT%H%MZ}.json"
    if path.exists():
        payload = json.loads(path.read_text(encoding="utf-8"))
        return _parse_run(payload, initialized_at)
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
        try:
            with urlopen(url, timeout=30, context=_ssl_context()) as response:
                responses = json.load(response)
        except HTTPException as exc:
            raise OSError("Не удалось полностью получить погодный выпуск") from exc
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
        run = _parse_run(payload, initialized_at)
        write_json(path, payload, indent=None)
        return run
