"""Координаты турбин из ссылок на карту в условии задачи."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TurbineSite:
    latitude: float
    longitude: float


SITES = {
    "turbine_1": TurbineSite(latitude=43.645150, longitude=78.535604),
    "turbine_2": TurbineSite(latitude=43.643198, longitude=78.538828),
}
