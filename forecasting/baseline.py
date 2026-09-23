"""Small, reproducible wind-to-power baseline with chronological evaluation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import isfinite

BIN_WIDTH_MS = 0.5
MODEL_VERSION = "ecmwf_ifs_100m_bin_curve_v2_no_shift"


def finite_number(value: object, name: str, *, maximum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name}: требуется число")
    if not isfinite(value) or value < 0 or (maximum is not None and value > maximum):
        raise ValueError(f"{name}: значение вне допустимого диапазона")
    return float(value)


def require_aware(value: datetime) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Время модели должно содержать часовой пояс")


@dataclass(frozen=True)
class Example:
    turbine_id: str
    forecast_issued_at: datetime
    target_end_at: datetime
    wind_speed_ms: float
    normalized_power: float

    def __post_init__(self) -> None:
        require_aware(self.forecast_issued_at)
        require_aware(self.target_end_at)
        if self.target_end_at <= self.forecast_issued_at:
            raise ValueError("Целевая мощность должна относиться к часу после запуска")
        finite_number(self.wind_speed_ms, "Скорость ветра")
        finite_number(self.normalized_power, "Мощность", maximum=1)


@dataclass(frozen=True)
class PowerCurve:
    mean_power: float
    bin_values: dict[int, float]
    training_count: int
    trained_through: datetime

    def __post_init__(self) -> None:
        require_aware(self.trained_through)
        finite_number(self.mean_power, "Средняя мощность", maximum=1)
        if type(self.training_count) is not int or self.training_count <= 0:
            raise ValueError("Число обучающих примеров должно быть положительным целым")
        if not self.bin_values:
            raise ValueError("Модель не обучена")
        for key, value in self.bin_values.items():
            if type(key) is not int or key < 0:
                raise ValueError("Неверный диапазон скорости ветра")
            finite_number(value, "Мощность в диапазоне ветра", maximum=1)

    def predict(self, wind_speed_ms: float) -> float:
        wind_speed_ms = finite_number(wind_speed_ms, "Скорость ветра")
        key = round(wind_speed_ms / BIN_WIDTH_MS)
        nearest = min(self.bin_values, key=lambda candidate: abs(candidate - key))
        return self.bin_values[nearest]

    def to_dict(self) -> dict[str, object]:
        return {
            "mean_power": self.mean_power,
            "bin_values": {str(key): value for key, value in sorted(self.bin_values.items())},
            "training_count": self.training_count,
            "trained_through": self.trained_through.isoformat(),
        }

    @classmethod
    def from_dict(cls, value: dict[str, object]) -> "PowerCurve":
        try:
            bins = value["bin_values"]
            if not isinstance(bins, dict) or any(str(int(key)) != key for key in bins):
                raise ValueError("Неверные ключи диапазонов ветра")
            return cls(
                mean_power=finite_number(value["mean_power"], "Средняя мощность", maximum=1),
                bin_values={int(key): finite_number(item, "Мощность", maximum=1) for key, item in bins.items()},
                training_count=value["training_count"],
                trained_through=datetime.fromisoformat(value["trained_through"]),
            )
        except (KeyError, TypeError, AttributeError, OverflowError) as exc:
            raise ValueError("Повреждена кривая мощности") from exc


def fit_curve(examples: list[Example], cutoff: datetime) -> PowerCurve:
    require_aware(cutoff)
    eligible = [example for example in examples if example.target_end_at < cutoff and example.forecast_issued_at < cutoff]
    if not eligible:
        raise ValueError("Нет обучающих примеров до временной границы")
    sums: dict[int, float] = {}
    counts: dict[int, int] = {}
    for example in eligible:
        key = max(0, round(example.wind_speed_ms / BIN_WIDTH_MS))
        sums[key] = sums.get(key, 0.0) + example.normalized_power
        counts[key] = counts.get(key, 0) + 1
    mean_power = sum(example.normalized_power for example in eligible) / len(eligible)
    # A small global-mean prior stabilizes bins with only one or two examples.
    values = {key: (total + 5 * mean_power) / (counts[key] + 5) for key, total in sums.items()}
    return PowerCurve(mean_power, values, len(eligible), max(example.target_end_at for example in eligible))


def score(curve: PowerCurve, examples: list[Example]) -> dict[str, float | int]:
    if not examples:
        raise ValueError("Нет проверочных примеров")
    predictions = [curve.predict(example.wind_speed_ms) for example in examples]
    signed_errors = [prediction - example.normalized_power for prediction, example in zip(predictions, examples)]
    errors = [abs(error) for error in signed_errors]
    mean_errors = [abs(curve.mean_power - example.normalized_power) for example in examples]
    return {
        "points": len(examples),
        "mae": sum(errors) / len(errors),
        "rmse": (sum(error ** 2 for error in signed_errors) / len(errors)) ** 0.5,
        "bias": sum(signed_errors) / len(errors),
        "prediction_mean": sum(predictions) / len(predictions),
        "observed_mean": sum(example.normalized_power for example in examples) / len(examples),
        "prediction_min": min(predictions),
        "prediction_max": max(predictions),
        "observed_min": min(example.normalized_power for example in examples),
        "observed_max": max(example.normalized_power for example in examples),
        "constant_mean_mae": sum(mean_errors) / len(mean_errors),
    }
