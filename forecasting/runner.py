"""Adapter expected by backend.app.forecast_service."""

from __future__ import annotations

from datetime import datetime

from forecasting.forecast import forecast


def run_forecast(turbine_id: str, issued_at: datetime, horizon_hours: int) -> dict[str, object]:
    result = forecast(turbine_id, issued_at, horizon_hours)
    return {key: result[key] for key in (
        "input_data_cutoff_at", "weather_source", "weather_run_id",
        "weather_run_issued_at", "model_version", "points",
    )}
