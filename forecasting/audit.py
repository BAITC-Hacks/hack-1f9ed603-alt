"""Audit replay integrity and prediction realism against the chronological backtest.

Run train_baseline first to refresh the backtest, then: python -m forecasting.audit
This audit never downloads weather or reads February observations.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

from forecasting.baseline import BIN_WIDTH_MS, PowerCurve
from forecasting.replay_february import launches
from forecasting.storage import write_json
from forecasting.weather import SAFE_DELAY, fetch_run, select_run
from forecasting.time_alignment import time_alignment_metadata

ROOT = Path(__file__).resolve().parents[1]


def distribution(values: list[float]) -> dict[str, float | int]:
    return {"count": len(values), "min": min(values), "max": max(values),
            "mean": statistics.mean(values), "stddev": statistics.pstdev(values)}


def audit(root: Path = ROOT) -> dict[str, object]:
    manifest_path = root / "data/processed/february_replay.json"
    backtest_path = root / "data/processed/backtest_report.json"
    manifest = json.loads(manifest_path.read_text())
    backtest = json.loads(backtest_path.read_text())
    if any(report.get("time_alignment") != time_alignment_metadata() for report in (manifest, backtest)):
        raise ValueError("Отчёты используют устаревшее правило сопоставления времени CSV")
    models = {}
    for path in sorted((root / "forecasting/artifacts").glob("baseline*.json")):
        artifact = json.loads(path.read_text())
        if artifact.get("time_alignment") != time_alignment_metadata():
            raise ValueError("Артефакт использует устаревшее правило сопоставления времени CSV")
        models[artifact["model_version"]] = artifact
    expected = {(site, issued, horizon) for site, issued, horizon in launches()}
    seen = set()
    values, winds, ramps = defaultdict(list), defaultdict(list), defaultdict(list)
    outside_support = defaultdict(int)
    errors = []
    weather = {}
    large_ramps = []
    for record in manifest["runs"]:
        issued = datetime.fromisoformat(record["issued_at"])
        site, horizon = record["turbine_id"], record["horizon_hours"]
        key = (site, issued, horizon)
        if key in seen or key not in expected:
            raise ValueError(f"Повторный или неожиданный запуск: {key}")
        seen.add(key)
        if record["status"] != "completed":
            errors.append(record["launch_id"])
            continue
        artifact = models[record["model_version"]]
        curve = PowerCurve.from_dict(artifact["curves"][site])
        cutoff = datetime.fromisoformat(artifact["training_cutoff_exclusive"])
        if not curve.trained_through < cutoff <= issued:
            raise ValueError(f"Обучение пересекает момент запуска: {key}")
        if datetime.fromisoformat(record["input_data_cutoff_at"]) != curve.trained_through:
            raise ValueError(f"Неверная граница входных данных: {key}")
        initialized = select_run(issued)
        run_id = f"ecmwf_ifs_{initialized:%Y%m%dT%H%MZ}"
        if record["weather_run_id"] != run_id:
            raise ValueError(f"Выбран неверный погодный выпуск: {key}")
        if (datetime.fromisoformat(record["weather_run_initialized_at"]) != initialized
                or datetime.fromisoformat(record["weather_run_usable_after_at"]) != initialized + SAFE_DELAY
                or initialized + SAFE_DELAY > issued):
            raise ValueError(f"Неверное происхождение погоды: {key}")
        if run_id not in weather:
            cache = root / "data/weather/ecmwf_ifs"
            if not (cache / f"{run_id}.json").is_file():
                raise ValueError(f"Нет локального погодного выпуска {run_id}")
            weather[run_id] = fetch_run(initialized, cache)
        run = weather[run_id]
        if len(record["points"]) != horizon:
            raise ValueError(f"Неверное число точек: {key}")
        previous = None
        previous_wind = None
        for step, point in enumerate(record["points"], 1):
            moment = datetime.fromisoformat(point["time"])
            value = point["normalized_power"]
            if moment != issued + timedelta(hours=step) or not math.isfinite(value) or not 0 <= value <= 1:
                raise ValueError(f"Неверная почасовая точка: {key}")
            wind = run.points[site][moment]
            if value != round(curve.predict(wind), 6):
                raise ValueError(f"Сохранённая мощность отличается от результата модели: {key}")
            # 24-hour points also occur in the 48-hour run; count each launch/lead once.
            if horizon == 48:
                values[site].append(value)
                winds[site].append(wind)
                outside_support[site] += not min(curve.bin_values) <= round(wind / BIN_WIDTH_MS) <= max(curve.bin_values)
                if previous is not None:
                    ramps[site].append(abs(value - previous))
                    if abs(value - previous) > 0.5:
                        large_ramps.append({
                            "turbine_id": site, "issued_at": record["issued_at"], "time": point["time"],
                            "power_before": previous, "power_after": value,
                            "forecast_wind_before_ms": previous_wind, "forecast_wind_after_ms": wind,
                        })
                previous = value
                previous_wind = wind
    if seen != expected or manifest["launch_count"] != len(expected):
        raise ValueError("Манифест не покрывает все 116 запусков")
    if errors or manifest["completed_count"] != 116 or manifest["error_count"] != 0:
        raise ValueError(f"Есть неуспешные запуски: {errors}")
    comparisons = []
    for result in backtest["results"]:
        comparisons.append({
            **result,
            "mae_skill_vs_constant_mean": 1 - result["mae"] / result["constant_mean_mae"],
            "mae_skill_vs_persistence": 1 - result["model_mae_on_persistence_points"] / result["persistence_mae"],
        })
    return {
        "time_alignment": time_alignment_metadata(),
        "replay_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        "backtest_sha256": hashlib.sha256(backtest_path.read_bytes()).hexdigest(),
        "validated_launches": len(seen),
        "validated_weather_runs": len(weather),
        "forecast_statistics_48h": {
            site: {"normalized_power": distribution(values[site]), "forecast_wind_ms": distribution(winds[site]),
                   "max_hourly_power_change": max(ramps[site]),
                   "outside_training_wind_bins_count": outside_support[site]}
            for site in sorted(values)
        },
        "chronological_backtest": comparisons,
        "hourly_changes_above_50_percentage_points": large_ramps,
        "limitations": [
            "Power is normalized to 0–1; MAE 0.20 means 20 percentage points, not 20% relative error.",
            "No February actual power is available; February bounds and reproducibility do not prove forecast accuracy.",
            "This statistical curve maps forecast grid wind to observed power; it is not a manufacturer's physical power curve.",
            "Rare wind bins are shrunk toward the training mean; peaks and shutdowns are not resolved reliably.",
            "Large hourly power changes accompany large wind changes in the archived forecast; they are retained and flagged, not treated as verified turbine behavior.",
            "Both turbines share the weather grid cell, so similar forecast profiles are expected.",
            "The 48-hour distributions count launch/lead pairs; successive launches overlap in valid time.",
            "Source clock labels are matched to the weather/API axis without a timezone shift per user instruction; source timezone is unspecified.",
            "Hourly interval labeling and the 12-hour weather usability delay remain explicit assumptions.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "data/processed/validation_report.json")
    args = parser.parse_args()
    report = audit()
    write_json(args.output, report)
    print(f"Проверены {report['validated_launches']} запусков и {report['validated_weather_runs']} погодных выпусков")
    print(args.output)


if __name__ == "__main__":
    main()
