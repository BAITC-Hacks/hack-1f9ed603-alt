"""Схемы ответа API; значения прогноза создаёт пакет forecasting."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class ForecastPoint(BaseModel):
    time: datetime
    normalized_power: float = Field(ge=0.0, le=1.0)


class ForecastRunResponse(BaseModel):
    run_id: str
    status: Literal["completed"]
    turbine_id: Literal["turbine_1", "turbine_2"]
    issued_at: datetime
    horizon_hours: Literal[24, 48]
    unit: Literal["normalized_power"]
    input_data_cutoff_at: datetime
    weather_source: str
    weather_run_id: str
    weather_run_issued_at: datetime
    model_version: str
    points: list[ForecastPoint]
