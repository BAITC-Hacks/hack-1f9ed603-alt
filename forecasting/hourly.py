"""Convert the supplied ten-minute observations to an explicit hourly grid.

The source timestamps have no interval-position metadata. Six samples labelled
HH:00,...,HH:50 are grouped as the hour starting HH:00; the original local
labels remain naive. Missing samples are never imputed.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from forecasting.dataset import FIELDS, TURBINE_IDS, iter_observations


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
    for moment, wind, power, temperature in iter_observations(data_dir, turbine_id):
        grouped.setdefault(moment.replace(minute=0), []).append((wind, power, temperature))
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
