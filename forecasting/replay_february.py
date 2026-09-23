"""Replay daily 12:00 UTC forecasts from 31 January through 28 February 2026."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Iterator
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from forecasting.dataset import TURBINE_IDS
from forecasting.forecast import ForecastUnavailable, forecast
from forecasting.weather import SAFE_DELAY, SOURCE, select_run
from forecasting.storage import write_json
from forecasting.time_alignment import time_alignment_metadata

ROOT = Path(__file__).resolve().parents[1]
UTC = timezone.utc
START = date(2026, 1, 31)
END = date(2026, 2, 28)


def launches(start: date = START, end: date = END) -> Iterator[tuple[str, datetime, int]]:
    if end < start:
        raise ValueError("Дата окончания раньше начала")
    day = start
    while day <= end:
        issued_at = datetime(day.year, day.month, day.day, 12, tzinfo=UTC)
        for turbine_id in TURBINE_IDS:
            for horizon in (24, 48):
                yield turbine_id, issued_at, horizon
        day += timedelta(days=1)


def replay(
    output_path: Path = ROOT / "data" / "processed" / "february_replay.json",
    *,
    start: date = START,
    end: date = END,
    forecast_fn: Callable[[str, datetime, int], dict[str, object]] = forecast,
) -> dict[str, object]:
    records = []
    for turbine_id, issued_at, horizon in launches(start, end):
        weather_initialized = select_run(issued_at)
        record: dict[str, object] = {
            "launch_id": f"{issued_at:%Y%m%dT%H%MZ}_{turbine_id}_{horizon}h",
            "turbine_id": turbine_id,
            "issued_at": issued_at.isoformat().replace("+00:00", "Z"),
            "horizon_hours": horizon,
            "requested_weather_source": SOURCE,
            "requested_weather_run_id": f"ecmwf_ifs_{weather_initialized:%Y%m%dT%H%MZ}",
            "weather_run_initialized_at": weather_initialized.isoformat().replace("+00:00", "Z"),
            "weather_run_usable_after_at": (weather_initialized + SAFE_DELAY).isoformat().replace("+00:00", "Z"),
            "weather_actual_publication_at": None,
        }
        try:
            result = forecast_fn(turbine_id, issued_at, horizon)
        except (ForecastUnavailable, OSError, ValueError) as exc:
            record.update(status="error", error=str(exc), model_version=None, points=[])
        else:
            record.update(
                status="completed",
                model_version=result["model_version"],
                input_data_cutoff_at=result["input_data_cutoff_at"],
                weather_source=result["weather_source"],
                weather_run_id=result["weather_run_id"],
                weather_run_issued_at=result["weather_run_issued_at"],
                weather_run_initialized_at=result["weather_run_initialized_at"],
                weather_run_usable_after_at=result["weather_run_usable_after_at"],
                weather_actual_publication_at=result["weather_actual_publication_at"],
                points=result["points"],
            )
        records.append(record)
    manifest = {
        "time_alignment": time_alignment_metadata(),
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "launch_hour_utc": 12,
        "launch_count": len(records),
        "completed_count": sum(record["status"] == "completed" for record in records),
        "error_count": sum(record["status"] == "error" for record in records),
        "runs": records,
    }
    write_json(output_path, manifest)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "data" / "processed" / "february_replay.json")
    args = parser.parse_args()
    manifest = replay(args.output)
    print(f"Запусков: {manifest['launch_count']}; успешно: {manifest['completed_count']}; ошибок: {manifest['error_count']}")
    print(args.output)
    if manifest["error_count"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
