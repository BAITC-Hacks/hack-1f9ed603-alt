"""Чтение предоставленных рядов без догадок о часовом поясе."""

from __future__ import annotations

import csv
import math
from collections.abc import Iterator
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from forecasting.sites import SITES

TURBINE_IDS = ("turbine_1", "turbine_2")
STEP_SECONDS = 600
FIELDS = (
    "ID",
    "Статистическое время",
    "Средняя скорость ветра(m/s)",
    "Нормализованная активная мощность",
    "Средняя температура окружающей среды(°C)",
)


def iter_observations(data_dir: Path, turbine_id: str) -> Iterator[tuple[datetime, float, float, float]]:
    """Use the same CSV validation in the API inventory and model preparation."""
    if turbine_id not in TURBINE_IDS:
        raise ValueError(f"Неизвестная турбина: {turbine_id}")
    path = data_dir / f"{turbine_id}.csv"
    previous = None
    with path.open(encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        if tuple(reader.fieldnames or ()) != FIELDS:
            raise ValueError(f"Неверная схема CSV: {path.name}")
        for line_number, row in enumerate(reader, start=2):
            try:
                if None in row or any(row[field] is None for field in FIELDS):
                    raise ValueError("Неверное число столбцов")
                moment = datetime.strptime(row[FIELDS[1]], "%Y-%m-%d %H:%M:%S")
                wind, power, temperature = (float(row[field]) for field in FIELDS[2:])
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(f"Неверное значение в {path.name}:{line_number}") from exc
            if (previous is not None and moment <= previous) or moment.minute % 10 or moment.second:
                raise ValueError(f"Неверное время в {path.name}:{line_number}")
            if not all(map(math.isfinite, (wind, power, temperature))) or wind < 0 or not 0 <= power <= 1:
                raise ValueError(f"Значение вне допустимого диапазона в {path.name}:{line_number}")
            previous = moment
            yield moment, wind, power, temperature
    if previous is None:
        raise ValueError(f"CSV пуст: {path.name}")


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
    for moment, _, _, _ in iter_observations(data_dir, turbine_id):
        if previous is not None:
            missing += int((moment - previous).total_seconds()) // STEP_SECONDS - 1
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
