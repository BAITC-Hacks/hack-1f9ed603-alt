"""Train and backtest the archived-weather power curve: python -m forecasting.train_baseline."""

from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from forecasting.baseline import MODEL_VERSION, Example, PowerCurve, fit_curve, score
from forecasting.dataset import TURBINE_IDS
from forecasting.hourly import HourlyObservation, load_hourly, write_hourly_csv
from forecasting.weather import SOURCE, WeatherRun, fetch_run
from forecasting.storage import write_json

ROOT = Path(__file__).resolve().parents[1]
UTC = timezone.utc


def parse_offset(value: str) -> timezone:
    if (len(value) != 6 or value[0] not in "+-" or value[3] != ":"
            or not value[1:3].isdigit() or not value[4:6].isdigit()):
        raise argparse.ArgumentTypeError("Используйте смещение вида +05:00")
    try:
        hours, minutes = int(value[1:3]), int(value[4:6])
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Неверное смещение времени") from exc
    if hours > 14 or minutes > 59 or (hours == 14 and minutes):
        raise argparse.ArgumentTypeError("Неверное смещение времени")
    delta = timedelta(hours=hours, minutes=minutes)
    return timezone(delta if value[0] == "+" else -delta)


def power_by_utc_end(rows: list[HourlyObservation], offset: timezone) -> dict[datetime, float]:
    result = {}
    for row in rows:
        if row.complete and row.normalized_power is not None:
            end = (row.hour_start_local + timedelta(hours=1)).replace(tzinfo=offset).astimezone(UTC)
            result[end] = row.normalized_power
    return result


def build_examples(
    run: WeatherRun,
    issued_at: datetime,
    power: dict[str, dict[datetime, float]],
    horizon_hours: int,
) -> list[Example]:
    if run.usable_after_at > issued_at:
        raise ValueError("Погодный выпуск ещё не разрешён к использованию")
    examples = []
    for turbine_id in TURBINE_IDS:
        for step in range(1, horizon_hours + 1):
            end = issued_at + timedelta(hours=step)
            wind = run.points[turbine_id].get(end)
            actual = power[turbine_id].get(end)
            if wind is not None and actual is not None:
                examples.append(Example(turbine_id, issued_at, end, wind, actual))
    return examples


def persistence_score(examples: list[Example], power: dict[datetime, float], curve: PowerCurve) -> dict[str, float | int | None]:
    """Repeat the preceding 24-hour cycle; omit points with missing history."""
    errors = []
    model_errors = []
    for example in examples:
        step = int((example.target_end_at - example.forecast_issued_at).total_seconds() // 3600)
        reference = example.forecast_issued_at - timedelta(hours=23) + timedelta(hours=(step - 1) % 24)
        previous = power.get(reference)
        if previous is not None:
            errors.append(abs(previous - example.normalized_power))
            model_errors.append(abs(curve.predict(example.wind_speed_ms) - example.normalized_power))
    return {"persistence_points": len(errors),
            "persistence_mae": sum(errors) / len(errors) if errors else None,
            "model_mae_on_persistence_points": sum(model_errors) / len(model_errors) if model_errors else None}


def _days(start: date, end: date):
    day = start
    while day <= end:
        yield day
        day += timedelta(days=1)


def build_model_artifact(
    examples: list[Example], cutoff: datetime, offset: timezone, version: str,
) -> dict[str, object]:
    curves = {
        turbine_id: fit_curve([item for item in examples if item.turbine_id == turbine_id], cutoff).to_dict()
        for turbine_id in TURBINE_IDS
    }
    return {
        "model_family": MODEL_VERSION,
        "model_version": version,
        "weather_source": SOURCE,
        "csv_utc_offset_assumption": offset.utcoffset(None).total_seconds() / 3600,
        "training_cutoff_exclusive": cutoff.isoformat(),
        "hour_label_assumption": "six ten-minute samples HH:00 through HH:50 form hour (HH:00, HH+1:00]",
        "curves": curves,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv-utc-offset", required=True, type=parse_offset,
                        help="Явное рабочее допущение о часовом поясе CSV, например +05:00")
    parser.add_argument("--start", type=date.fromisoformat, default=date(2025, 11, 1))
    parser.add_argument("--end", type=date.fromisoformat, default=date(2026, 1, 31))
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data" / "raw")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "data" / "processed")
    parser.add_argument("--model-path", type=Path, default=ROOT / "forecasting" / "artifacts" / "baseline_model.json")
    parser.add_argument("--pre-model-path", type=Path, default=ROOT / "forecasting" / "artifacts" / "baseline_pre_20260131T1200Z.json")
    parser.add_argument("--weather-cache", type=Path, default=ROOT / "data" / "weather" / "ecmwf_ifs")
    args = parser.parse_args()
    if args.start >= date(2025, 12, 1) or args.end < date(2026, 1, 1):
        parser.error("Для двух проверочных срезов нужны ноябрь 2025 — январь 2026")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    power = {}
    quality = {}
    for turbine_id in TURBINE_IDS:
        hourly = load_hourly(args.data_dir, turbine_id)
        write_hourly_csv(hourly, args.output_dir / f"hourly_{turbine_id}.csv")
        power[turbine_id] = power_by_utc_end(hourly, args.csv_utc_offset)
        quality[turbine_id] = {
            "hours": len(hourly),
            "complete_hours": sum(row.complete for row in hourly),
            "partial_hours": sum(0 < row.sample_count < 6 for row in hourly),
            "empty_hours": sum(row.sample_count == 0 for row in hourly),
        }

    by_horizon: dict[int, list[Example]] = {24: [], 48: []}
    launches = []
    for day in _days(args.start, args.end):
        run_at = datetime(day.year, day.month, day.day, tzinfo=UTC)
        issued_at = run_at + timedelta(hours=12)
        run = fetch_run(run_at, args.weather_cache)
        for turbine_id in TURBINE_IDS:
            missing = [issued_at + timedelta(hours=step) for step in range(1, 49)
                       if issued_at + timedelta(hours=step) not in run.points[turbine_id]]
            if missing:
                raise ValueError(f"Неполный архивный выпуск {run.run_id} для {turbine_id}: {missing[0]}")
        for turbine_id in TURBINE_IDS:
            for horizon in (24, 48):
                launches.append({
                    "turbine_id": turbine_id,
                    "horizon_hours": horizon,
                    "issued_at": issued_at.isoformat(),
                    "weather_source": SOURCE,
                    "weather_run_id": run.run_id,
                    "weather_run_issued_at": run.initialized_at.isoformat(),
                    "weather_run_initialized_at": run.initialized_at.isoformat(),
                    "weather_run_usable_after_at": run.usable_after_at.isoformat(),
                    "weather_actual_publication_at": None,
                    "availability_basis": "nominal cycle time plus 12-hour conservative delay; exact historical publication unavailable",
                })
        for horizon in (24, 48):
            by_horizon[horizon].extend(build_examples(run, issued_at, power, horizon))
    write_json(args.output_dir / "historical_launches.json", launches)

    folds = [
        ("2025-12", datetime(2025, 12, 1, tzinfo=UTC), datetime(2026, 1, 1, tzinfo=UTC)),
        ("2026-01", datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 2, 1, tzinfo=UTC)),
    ]
    results = []
    for name, start, end in folds:
        for turbine_id in TURBINE_IDS:
            train = [item for item in by_horizon[24] if item.turbine_id == turbine_id]
            model = fit_curve(train, start)
            for horizon in (24, 48):
                test = [item for item in by_horizon[horizon]
                        if item.turbine_id == turbine_id and start <= item.target_end_at < end
                        and item.forecast_issued_at >= start]
                results.append({"period": name, "turbine_id": turbine_id, "horizon_hours": horizon,
                                "training_points": model.training_count, **score(model, test),
                                **persistence_score(test, power[turbine_id], model)})

    for path, cutoff, version in (
        (args.pre_model_path, datetime(2026, 1, 31, 12, tzinfo=UTC), f"{MODEL_VERSION}_pre_20260131T1200Z"),
        (args.model_path, datetime(2026, 2, 1, tzinfo=UTC), f"{MODEL_VERSION}_final_20260201T0000Z"),
    ):
        artifact = build_model_artifact(by_horizon[24], cutoff, args.csv_utc_offset, version)
        write_json(path, artifact)
    report = {"model_version": MODEL_VERSION, "quality": quality, "archive_run_count": len(launches) // 4,
              "historical_launch_count": len(launches),
              "weather_grid_coordinates": {site: run.grid_coordinates[site] for site in TURBINE_IDS},
              "results": results, "limitations": [
                  "CSV UTC offset is a user-provided working assumption, not confirmed by organizers.",
                  "Ten-minute timestamp interval position is unknown; hourly alignment is an assumption.",
                  "Exact historical weather publication times are not supplied; use is delayed 12 hours.",
                  "Weather is forecast wind at 100 m; height of CSV wind measurements is unknown.",
              ]}
    write_json(args.output_dir / "backtest_report.json", report)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
