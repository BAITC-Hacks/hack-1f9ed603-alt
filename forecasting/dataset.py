"""Чтение предоставленных рядов без догадок о часовом поясе."""

from __future__ import annotations

import csv
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from forecasting.sites import SITES

TURBINE_IDS = ("turbine_1", "turbine_2")
STEP_SECONDS = 600


@dataclass(frozen=True)
class TurbineSummary:
    id: str
    latitude: float
    longitude: float
    rows: int
    first_observation: str
    last_observation: str
    expected_rows: int
    missing_intervals: int

    def to_dict(self) -> dict[str, str | int | float]:
        return asdict(self)


def summarize_turbine(data_dir: Path, turbine_id: str) -> TurbineSummary:
    if turbine_id not in TURBINE_IDS:
        raise ValueError(f"Неизвестная турбина: {turbine_id}")
    path = data_dir / f"{turbine_id}.csv"
    first: datetime | None = None
    previous: datetime | None = None
    count = 0
    missing = 0
    with path.open(encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        if reader.fieldnames is None or len(reader.fieldnames) != 5:
            raise ValueError(f"Неверная схема CSV: {path.name}")
        time_field = reader.fieldnames[1]
        for row in reader:
            moment = datetime.strptime(row[time_field], "%Y-%m-%d %H:%M:%S")
            if previous is not None:
                step = int((moment - previous).total_seconds())
                if step <= 0 or step % STEP_SECONDS:
                    raise ValueError(f"Неверный порядок или шаг времени: {path.name}")
                missing += step // STEP_SECONDS - 1
            first = moment if first is None else first
            previous = moment
            count += 1
    if first is None or previous is None:
        raise ValueError(f"CSV пуст: {path.name}")
    return TurbineSummary(
        id=turbine_id,
        latitude=SITES[turbine_id].latitude,
        longitude=SITES[turbine_id].longitude,
        rows=count,
        first_observation=first.isoformat(),
        last_observation=previous.isoformat(),
        expected_rows=count + missing,
        missing_intervals=missing,
    )
