"""Public forecasting entry point for backend integration."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from forecasting.baseline import MODEL_VERSION, PowerCurve
from forecasting.dataset import TURBINE_IDS
from forecasting.weather import SOURCE, fetch_run, select_run

ROOT = Path(__file__).resolve().parents[1]
UTC = timezone.utc


class ForecastUnavailable(OSError):
    """Required trained model or point-in-time weather is unavailable."""


def forecast(
    turbine_id: str,
    issued_at: datetime,
    horizon_hours: int,
    *,
    model_path: Path = ROOT / "forecasting" / "artifacts" / "baseline_model.json",
    weather_cache: Path = ROOT / "data" / "weather" / "ecmwf_ifs",
) -> dict[str, object]:
    if turbine_id not in TURBINE_IDS:
        raise ValueError(f"Неизвестная турбина: {turbine_id}")
    if issued_at.tzinfo is None or issued_at.utcoffset() is None:
        raise ValueError("issued_at должен содержать часовой пояс")
    if horizon_hours not in (24, 48):
        raise ValueError("Горизонт должен быть 24 или 48 часов")
    issued = issued_at.astimezone(UTC)
    if issued.minute or issued.second or issued.microsecond:
        raise ForecastUnavailable("Архив погоды поддерживает запуск только в начале часа")
    try:
        artifact = json.loads(model_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ForecastUnavailable("Обученная модель недоступна") from exc
    if artifact.get("model_version") != MODEL_VERSION or artifact.get("weather_source") != SOURCE:
        raise ForecastUnavailable("Версия обученной модели несовместима с погодным источником")
    try:
        curve = PowerCurve.from_dict(artifact["curves"][turbine_id])
    except (KeyError, TypeError, ValueError) as exc:
        raise ForecastUnavailable("Артефакт модели повреждён") from exc
    if curve.trained_through > issued:
        raise ForecastUnavailable("Для исторического запуска нужна модель, обученная до момента запуска")

    try:
        run = fetch_run(select_run(issued), weather_cache)
    except (OSError, ValueError) as exc:
        raise ForecastUnavailable("Архивный прогноз погоды недоступен") from exc
    if run.usable_after_at > issued:
        raise ForecastUnavailable("Погодный выпуск ещё не был доступен к моменту запуска")

    points = []
    for step in range(1, horizon_hours + 1):
        end = issued + timedelta(hours=step)
        wind = run.points[turbine_id].get(end)
        if wind is None:
            raise ForecastUnavailable(f"В погодном выпуске нет прогноза на {end.isoformat()}")
        points.append({"time": end.isoformat().replace("+00:00", "Z"),
                       "normalized_power": round(curve.predict(wind), 6)})
    to_iso = lambda stamp: stamp.astimezone(UTC).isoformat().replace("+00:00", "Z")
    return {
        "run_id": str(uuid4()),
        "status": "completed",
        "turbine_id": turbine_id,
        "issued_at": to_iso(issued),
        "horizon_hours": horizon_hours,
        "unit": "normalized_power",
        "input_data_cutoff_at": to_iso(curve.trained_through),
        "weather_source": SOURCE,
        "weather_run_id": run.run_id,
        # Nominal issue/cycle time. Historical *publication* is not in the archive;
        # the separate 12-hour availability rule is enforced above.
        "weather_run_issued_at": to_iso(run.initialized_at),
        "model_version": MODEL_VERSION,
        "points": points,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a 24/48-hour forecast from the trained baseline")
    parser.add_argument("turbine_id", choices=TURBINE_IDS)
    parser.add_argument("issued_at", type=datetime.fromisoformat, help="ISO 8601 with UTC offset")
    parser.add_argument("horizon_hours", type=int, choices=(24, 48))
    args = parser.parse_args()
    print(json.dumps(forecast(args.turbine_id, args.issued_at, args.horizon_hours),
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
