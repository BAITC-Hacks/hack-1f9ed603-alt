"""Адаптер к прогнозному ядру, принадлежащему участнику forecasting."""

from __future__ import annotations

import importlib
import importlib.util
from collections.abc import Mapping
from typing import Any
from uuid import uuid4

from pydantic import ValidationError

from backend.app.schemas import ForecastRunRequest, ForecastRunResponse


class EngineNotReady(Exception):
    """Модуль forecasting.runner ещё не реализован."""


class SourceUnavailable(Exception):
    """Историческая погода или входные данные временно недоступны."""


class InvalidForecast(Exception):
    """Ядро вернуло неполный или противоречивый результат."""


def run_forecast(request: ForecastRunRequest) -> ForecastRunResponse:
    """Вызвать forecasting.runner.run_forecast и проверить результат.

    Runner принимает turbine_id, issued_at (UTC) и horizon_hours.
    Он возвращает mapping с input_data_cutoff_at, weather_source,
    weather_run_id, weather_run_issued_at, weather_run_initialized_at,
    weather_run_usable_after_at, weather_actual_publication_at,
    model_version и points.
    Идентификатор запуска и неизменяемые поля ответа добавляет backend.
    """
    if importlib.util.find_spec("forecasting.runner") is None:
        raise EngineNotReady
    runner_module = importlib.import_module("forecasting.runner")
    runner = getattr(runner_module, "run_forecast", None)
    if not callable(runner):
        raise EngineNotReady

    try:
        payload = runner(
            turbine_id=request.turbine_id,
            issued_at=request.issued_at,
            horizon_hours=request.horizon_hours,
        )
    except (ConnectionError, TimeoutError, OSError) as exc:
        raise SourceUnavailable(str(exc)) from exc

    if not isinstance(payload, Mapping):
        raise InvalidForecast("Ядро должно вернуть словарь")
    data: dict[str, Any] = dict(payload)
    data.update(
        run_id=uuid4(),
        status="completed",
        turbine_id=request.turbine_id,
        issued_at=request.issued_at,
        horizon_hours=request.horizon_hours,
        unit="normalized_power",
    )
    try:
        return ForecastRunResponse.model_validate(data)
    except ValidationError as exc:
        raise InvalidForecast("Результат ядра не соответствует схеме API") from exc
