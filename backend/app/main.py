"""Тонкий API поверх прогнозного ядра."""

from __future__ import annotations

import logging
import os
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, field_validator

from forecasting.dataset import TURBINE_IDS, TurbineSummary, summarize_turbine

LOGGER = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.getenv("DATA_DIR", str(ROOT / "data" / "raw")))

app = FastAPI(title="Прогноз выработки ВЭС", version="0.1.0")


class ForecastRunRequest(BaseModel):
    turbine_id: Literal["turbine_1", "turbine_2"]
    issued_at: datetime
    horizon_hours: Literal[24, 48]

    @field_validator("issued_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Укажите часовой пояс в issued_at")
        return value


@app.exception_handler(HTTPException)
async def http_error(_, exc: HTTPException) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"error": str(exc.detail)})


@app.exception_handler(RequestValidationError)
async def validation_error(_, exc: RequestValidationError) -> JSONResponse:
    messages = "; ".join(str(item["msg"]) for item in exc.errors())
    return JSONResponse(status_code=422, content={"error": messages})


@lru_cache(maxsize=1)
def load_summaries() -> tuple[TurbineSummary, ...]:
    return tuple(summarize_turbine(DATA_DIR, turbine_id) for turbine_id in TURBINE_IDS)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/turbines")
def turbines() -> dict[str, list[dict[str, str | int]]]:
    try:
        summaries = load_summaries()
    except (OSError, ValueError) as exc:
        LOGGER.exception("Не удалось прочитать CSV")
        raise HTTPException(status_code=503, detail="Исходные данные недоступны или повреждены") from exc
    return {"turbines": [summary.to_dict() for summary in summaries]}


@app.post("/api/forecast-runs")
def create_forecast_run(request: ForecastRunRequest) -> None:
    del request
    raise HTTPException(status_code=501, detail="Прогнозная модель пока не подключена")
