"""Публичные схемы API и проверка временной целостности прогноза."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator, model_validator


def require_aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Укажите часовой пояс")
    try:
        return value.astimezone(timezone.utc)
    except OverflowError as exc:
        raise ValueError("Время выходит за поддерживаемый диапазон UTC") from exc


def utc_string(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


class ForecastRunRequest(BaseModel):
    turbine_id: Literal["turbine_1", "turbine_2"]
    issued_at: datetime
    horizon_hours: Literal[24, 48]

    @field_validator("issued_at", mode="before")
    @classmethod
    def require_iso_timestamp(cls, value: object) -> object:
        if not isinstance(value, (str, datetime)):
            raise ValueError("issued_at должен быть ISO 8601 с часовым поясом")
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError as exc:
                raise ValueError("issued_at должен быть ISO 8601 с часовым поясом") from exc
        return value

    @field_validator("issued_at")
    @classmethod
    def validate_issued_at(cls, value: datetime) -> datetime:
        issued_at = require_aware_utc(value)
        if issued_at.minute or issued_at.second or issued_at.microsecond:
            raise ValueError("Время запуска должно приходиться на начало часа по UTC")
        return issued_at

    @model_validator(mode="after")
    def validate_date_range(self) -> ForecastRunRequest:
        try:
            self.issued_at + timedelta(hours=self.horizon_hours)
            self.issued_at - timedelta(hours=18)
        except OverflowError as exc:
            raise ValueError("Дата запуска выходит за поддерживаемый диапазон") from exc
        return self


class AssistantParametersRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    message: str = Field(min_length=1, max_length=4000, strict=True)
    defaults: ForecastRunRequest
    language: Literal["ru", "kk", "en"] = "ru"


class AssistantParametersResponse(BaseModel):
    status: Literal["ready", "clarification"]
    request: ForecastRunRequest | None
    message: str | None


class ForecastPoint(BaseModel):
    time: datetime
    normalized_power: float = Field(ge=0.0, le=1.0, allow_inf_nan=False, strict=True)

    @field_validator("time")
    @classmethod
    def validate_time(cls, value: datetime) -> datetime:
        return require_aware_utc(value)

    @field_serializer("time")
    def serialize_time(self, value: datetime) -> str:
        return utc_string(value)


class ForecastRunResponse(BaseModel):
    run_id: UUID
    status: Literal["completed"]
    turbine_id: Literal["turbine_1", "turbine_2"]
    issued_at: datetime
    horizon_hours: Literal[24, 48]
    unit: Literal["normalized_power"]
    input_data_cutoff_at: datetime
    weather_source: str = Field(min_length=1)
    weather_run_id: str = Field(min_length=1)
    weather_run_issued_at: datetime
    weather_run_initialized_at: datetime
    weather_run_usable_after_at: datetime
    weather_actual_publication_at: datetime | None
    model_version: str = Field(min_length=1)
    points: list[ForecastPoint]

    @field_validator("issued_at", "input_data_cutoff_at", "weather_run_issued_at", "weather_run_initialized_at", "weather_run_usable_after_at", "weather_actual_publication_at")
    @classmethod
    def validate_timestamp(cls, value: datetime | None) -> datetime | None:
        return require_aware_utc(value) if value is not None else None

    @model_validator(mode="after")
    def validate_history_and_horizon(self) -> ForecastRunResponse:
        if self.input_data_cutoff_at > self.issued_at:
            raise ValueError("Исторические данные получены после момента прогноза")
        if self.weather_run_issued_at > self.issued_at:
            raise ValueError("Погодный прогноз выпущен после момента прогноза")
        if self.weather_run_issued_at != self.weather_run_initialized_at:
            raise ValueError("Время погодного цикла не совпадает с инициализацией модели")
        if not self.weather_run_initialized_at <= self.weather_run_usable_after_at <= self.issued_at:
            raise ValueError("Погодный выпуск не был доступен к моменту прогноза")
        if self.weather_actual_publication_at is not None and not self.weather_run_initialized_at <= self.weather_actual_publication_at <= self.issued_at:
            raise ValueError("Фактическая публикация погоды вне временных границ прогноза")
        if len(self.points) != self.horizon_hours:
            raise ValueError("Неверное число почасовых точек")
        for index, point in enumerate(self.points, start=1):
            if point.time != self.issued_at + timedelta(hours=index):
                raise ValueError("Почасовые точки не соответствуют горизонту")
        return self

    @field_serializer("issued_at", "input_data_cutoff_at", "weather_run_issued_at", "weather_run_initialized_at", "weather_run_usable_after_at", "weather_actual_publication_at")
    def serialize_timestamp(self, value: datetime | None) -> str | None:
        return utc_string(value) if value is not None else None
