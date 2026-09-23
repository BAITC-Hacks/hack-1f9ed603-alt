"""Small, reproducible wind-to-power baseline with chronological evaluation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

BIN_WIDTH_MS = 0.5
MODEL_VERSION = "ecmwf_ifs_100m_bin_curve_v1"


@dataclass(frozen=True)
class Example:
    turbine_id: str
    forecast_issued_at: datetime
    target_end_at: datetime
    wind_speed_ms: float
    normalized_power: float


@dataclass(frozen=True)
class PowerCurve:
    mean_power: float
    bin_values: dict[int, float]
    training_count: int
    trained_through: datetime

    def predict(self, wind_speed_ms: float) -> float:
        if not self.bin_values:
            raise ValueError("Модель не обучена")
        key = max(0, round(wind_speed_ms / BIN_WIDTH_MS))
        nearest = min(self.bin_values, key=lambda candidate: abs(candidate - key))
        return min(1.0, max(0.0, self.bin_values[nearest]))

    def to_dict(self) -> dict[str, object]:
        return {
            "mean_power": self.mean_power,
            "bin_values": {str(key): value for key, value in sorted(self.bin_values.items())},
            "training_count": self.training_count,
            "trained_through": self.trained_through.isoformat(),
        }

    @classmethod
    def from_dict(cls, value: dict[str, object]) -> "PowerCurve":
        return cls(
            mean_power=float(value["mean_power"]),
            bin_values={int(key): float(item) for key, item in value["bin_values"].items()},
            training_count=int(value["training_count"]),
            trained_through=datetime.fromisoformat(str(value["trained_through"])),
        )


def fit_curve(examples: list[Example], cutoff: datetime) -> PowerCurve:
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
    errors = [abs(curve.predict(example.wind_speed_ms) - example.normalized_power) for example in examples]
    mean_errors = [abs(curve.mean_power - example.normalized_power) for example in examples]
    return {
        "points": len(examples),
        "mae": sum(errors) / len(errors),
        "constant_mean_mae": sum(mean_errors) / len(mean_errors),
    }
