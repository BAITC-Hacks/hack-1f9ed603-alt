"""Тонкий API поверх прогнозного ядра."""

from __future__ import annotations

import logging
import os
import sqlite3
from functools import lru_cache
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from backend.app.db import save_run
from backend.app.forecast_service import EngineNotReady, InvalidForecast, SourceUnavailable, run_forecast
from backend.app.schemas import ForecastRunRequest, ForecastRunResponse
from forecasting.dataset import TURBINE_IDS, TurbineSummary, summarize_turbine

LOGGER = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.getenv("DATA_DIR", str(ROOT / "data" / "raw")))

app = FastAPI(title="Прогноз выработки ВЭС", version="0.1.0")


@app.exception_handler(HTTPException)
async def http_error(_, exc: HTTPException) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"error": str(exc.detail)})


@app.exception_handler(RequestValidationError)
async def validation_error(_, exc: RequestValidationError) -> JSONResponse:
    messages = "; ".join(str(item["msg"]) for item in exc.errors())
    return JSONResponse(status_code=422, content={"error": messages})


@app.exception_handler(Exception)
async def unexpected_error(_, exc: Exception) -> JSONResponse:
    LOGGER.error("Необработанная ошибка API", exc_info=(type(exc), exc, exc.__traceback__))
    return JSONResponse(status_code=500, content={"error": "Внутренняя ошибка сервера"})


@lru_cache(maxsize=1)
def load_summaries() -> tuple[TurbineSummary, ...]:
    return tuple(summarize_turbine(DATA_DIR, turbine_id) for turbine_id in TURBINE_IDS)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/turbines")
def turbines() -> dict[str, list[dict[str, str | int | float]]]:
    try:
        summaries = load_summaries()
    except (OSError, ValueError) as exc:
        LOGGER.exception("Не удалось прочитать CSV")
        raise HTTPException(status_code=503, detail="Исходные данные недоступны или повреждены") from exc
    return {"turbines": [summary.to_dict() for summary in summaries]}


@app.post("/api/forecast-runs", response_model=ForecastRunResponse, status_code=201)
def create_forecast_run(request: ForecastRunRequest) -> ForecastRunResponse:
    try:
        result = run_forecast(request)
    except EngineNotReady as exc:
        raise HTTPException(status_code=501, detail="Прогнозная модель пока не подключена") from exc
    except SourceUnavailable as exc:
        LOGGER.warning("Источник данных для прогноза недоступен: %s", exc)
        raise HTTPException(status_code=503, detail="Данные для прогноза временно недоступны") from exc
    except InvalidForecast as exc:
        LOGGER.error("Ядро вернуло некорректный прогноз: %s", exc)
        raise HTTPException(status_code=502, detail="Прогнозная модель вернула некорректный результат") from exc

    try:
        save_run(result)
    except (OSError, sqlite3.Error) as exc:
        LOGGER.exception("Не удалось сохранить прогноз")
        raise HTTPException(status_code=503, detail="Не удалось сохранить прогноз") from exc
    return result
