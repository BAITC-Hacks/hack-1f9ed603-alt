"""Convert the supplied ten-minute observations to an explicit hourly grid.

The source timestamps have no interval-position metadata. Six samples labelled
HH:00,...,HH:50 are grouped as the hour starting HH:00; the original local
labels remain naive. Missing samples are never imputed.
"""

from __future__ import annotations

import csv
import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from forecasting.dataset import TURBINE_IDS

FIELDS = (
    "ID",
    "Статистическое время",
    "Средняя скорость ветра(m/s)",
    "Нормализованная активная мощность",
    "Средняя температура окружающей среды(°C)",
)


@dataclass(frozen=True)
class HourlyObservation:
    hour_start_local: datetime
    sample_count: int
    wind_speed_ms: float | None
    normalized_power: float | None
    temperature_c: float | None

    @property
    def complete(self) -> bool:
        return self.sample_count == 6


def load_hourly(data_dir: Path, turbine_id: str) -> list[HourlyObservation]:
    if turbine_id not in TURBINE_IDS:
        raise ValueError(f"Неизвестная турбина: {turbine_id}")
    path = data_dir / f"{turbine_id}.csv"
    grouped: dict[datetime, list[tuple[float, float, float]]] = {}
    previous: datetime | None = None
    with path.open(encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        if tuple(reader.fieldnames or ()) != FIELDS:
            raise ValueError(f"Неверная схема CSV: {path.name}")
        for line_number, row in enumerate(reader, start=2):
            try:
                moment = datetime.strptime(row[FIELDS[1]], "%Y-%m-%d %H:%M:%S")
                wind = float(row[FIELDS[2]])
                power = float(row[FIELDS[3]])
                temperature = float(row[FIELDS[4]])
            except (TypeError, ValueError) as exc:
                raise ValueError(f"Неверное значение в {path.name}:{line_number}") from exc
            if (previous is not None and moment <= previous) or moment.minute % 10 or moment.second:
                raise ValueError(f"Неверное время в {path.name}:{line_number}")
            if not all(map(math.isfinite, (wind, power, temperature))) or wind < 0 or not 0 <= power <= 1:
                raise ValueError(f"Значение вне допустимого диапазона в {path.name}:{line_number}")
            grouped.setdefault(moment.replace(minute=0), []).append((wind, power, temperature))
            previous = moment
    if not grouped:
        raise ValueError(f"CSV пуст: {path.name}")

    result: list[HourlyObservation] = []
    hour = min(grouped)
    last = max(grouped)
    while hour <= last:
        samples = grouped.get(hour, [])
        count = len(samples)
        if count > 6:
            raise ValueError(f"Более шести наблюдений в час {hour}: {path.name}")
        result.append(
            HourlyObservation(
                hour_start_local=hour,
                sample_count=count,
                wind_speed_ms=sum(s[0] for s in samples) / count if count else None,
                normalized_power=sum(s[1] for s in samples) / count if count else None,
                temperature_c=sum(s[2] for s in samples) / count if count else None,
            )
        )
        hour += timedelta(hours=1)
    return result


def write_hourly_csv(rows: list[HourlyObservation], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as target:
        writer = csv.writer(target, lineterminator="\n")
        writer.writerow(("hour_start_local", "sample_count", "complete", "wind_speed_ms", "normalized_power", "temperature_c"))
        for row in rows:
            writer.writerow((
                row.hour_start_local.isoformat(), row.sample_count, int(row.complete),
                "" if row.wind_speed_ms is None else f"{row.wind_speed_ms:.6f}",
                "" if row.normalized_power is None else f"{row.normalized_power:.6f}",
                "" if row.temperature_c is None else f"{row.temperature_c:.6f}",
            ))
