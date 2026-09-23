from __future__ import annotations

import csv
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from forecasting.baseline import MODEL_VERSION, Example, PowerCurve, fit_curve, score
from forecasting.forecast import ForecastUnavailable, forecast
from forecasting.hourly import FIELDS, load_hourly
from forecasting.train_baseline import build_examples, parse_offset, power_by_utc_end
from forecasting.weather import SOURCE, WeatherRun, fetch_run, select_run

UTC = timezone.utc


class HourlyTests(unittest.TestCase):
    def test_missing_samples_remain_visible_and_incomplete(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "turbine_1.csv"
            with path.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.writer(stream)
                writer.writerow(FIELDS)
                for hour, minute in [(0, 0), (0, 10), (2, 0)]:
                    writer.writerow([1, f"2025-01-01 {hour}:{minute:02}:00", 5, 0.4, 12])
            rows = load_hourly(Path(temp), "turbine_1")
        self.assertEqual([row.sample_count for row in rows], [2, 0, 1])
        self.assertEqual([row.complete for row in rows], [False, False, False])
        self.assertIsNone(rows[1].normalized_power)

    def test_invalid_power_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "turbine_1.csv"
            with path.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.writer(stream)
                writer.writerow(FIELDS)
                writer.writerow([1, "2025-01-01 0:00:00", 5, 1.5, 12])
            with self.assertRaisesRegex(ValueError, "диапазона"):
                load_hourly(Path(temp), "turbine_1")

    def test_explicit_offset_sets_hour_end(self):
        from forecasting.hourly import HourlyObservation

        row = HourlyObservation(datetime(2025, 1, 1, 0), 6, 5, 0.4, 12)
        result = power_by_utc_end([row], parse_offset("+05:00"))
        self.assertEqual(result, {datetime(2024, 12, 31, 20, tzinfo=UTC): 0.4})


class WeatherTests(unittest.TestCase):
    def test_run_selection_uses_conservative_availability(self):
        self.assertEqual(select_run(datetime(2026, 1, 15, 11, tzinfo=UTC)),
                         datetime(2026, 1, 14, 18, tzinfo=UTC))
        self.assertEqual(select_run(datetime(2026, 1, 15, 12, tzinfo=UTC)),
                         datetime(2026, 1, 15, 0, tzinfo=UTC))
        with self.assertRaises(ValueError):
            select_run(datetime(2026, 1, 15, 12))

    def test_cached_run_preserves_model_time_and_source(self):
        with tempfile.TemporaryDirectory() as temp:
            cache = Path(temp)
            stamp = datetime(2026, 1, 15, tzinfo=UTC)
            payload = {
                "source": SOURCE, "model": "ecmwf_ifs", "initialized_at": stamp.isoformat(),
                "site_ids": ["turbine_1", "turbine_2"],
                "responses": [{
                    "latitude": 43.62, "longitude": 78.47,
                    "hourly_units": {"wind_speed_100m": "m/s"},
                    "hourly": {"time": ["2026-01-15T13:00"], "wind_speed_100m": [4.2]},
                }] * 2,
            }
            (cache / "ecmwf_ifs_20260115T0000Z.json").write_text(json.dumps(payload))
            run = fetch_run(stamp, cache)
        self.assertEqual(run.usable_after_at, datetime(2026, 1, 15, 12, tzinfo=UTC))
        self.assertEqual(run.points["turbine_1"][datetime(2026, 1, 15, 13, tzinfo=UTC)], 4.2)

    def test_future_weather_run_is_rejected(self):
        issued = datetime(2026, 1, 15, 12, tzinfo=UTC)
        run = WeatherRun(issued, issued + timedelta(hours=12), {"turbine_1": {}, "turbine_2": {}}, {})
        with self.assertRaisesRegex(ValueError, "ещё не разрешён"):
            build_examples(run, issued, {"turbine_1": {}, "turbine_2": {}}, 24)


class BaselineTests(unittest.TestCase):
    def test_fit_excludes_targets_on_or_after_cutoff(self):
        cutoff = datetime(2026, 1, 1, tzinfo=UTC)
        examples = [
            Example("turbine_1", cutoff - timedelta(days=2), cutoff - timedelta(days=1), 4, 0.2),
            Example("turbine_1", cutoff - timedelta(days=1), cutoff, 4, 1.0),
        ]
        curve = fit_curve(examples, cutoff)
        self.assertEqual(curve.training_count, 1)
        self.assertEqual(curve.mean_power, 0.2)
        self.assertEqual(curve.trained_through, cutoff - timedelta(days=1))
        self.assertAlmostEqual(score(curve, examples[:1])["mae"], 0.0)
        self.assertEqual(PowerCurve.from_dict(curve.to_dict()), curve)

    def test_public_forecast_has_hourly_points_and_blocks_future_training(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            model = root / "model.json"
            cache = root / "weather"
            cache.mkdir()
            issue = datetime(2026, 2, 1, 12, tzinfo=UTC)
            curve = PowerCurve(0.3, {8: 0.4}, 12, issue - timedelta(hours=1))
            model.write_text(json.dumps({
                "model_version": MODEL_VERSION, "weather_source": SOURCE,
                "curves": {"turbine_1": curve.to_dict()},
            }))
            stamps = [(issue - timedelta(hours=12) + timedelta(hours=step)).strftime("%Y-%m-%dT%H:%M")
                      for step in range(72)]
            response = {"latitude": 43.62, "longitude": 78.47,
                        "hourly_units": {"wind_speed_100m": "m/s"},
                        "hourly": {"time": stamps, "wind_speed_100m": [4.0] * 72}}
            (cache / "ecmwf_ifs_20260201T0000Z.json").write_text(json.dumps({
                "source": SOURCE, "model": "ecmwf_ifs", "initialized_at": (issue - timedelta(hours=12)).isoformat(),
                "site_ids": ["turbine_1", "turbine_2"], "responses": [response, response],
            }))
            result = forecast("turbine_1", issue, 24, model_path=model, weather_cache=cache)
            self.assertEqual(len(result["points"]), 24)
            self.assertEqual(result["points"][0]["time"], "2026-02-01T13:00:00Z")
            self.assertEqual(result["weather_run_issued_at"], "2026-02-01T00:00:00Z")
            self.assertEqual(result["points"][0]["normalized_power"], 0.4)
            curve = PowerCurve(0.3, {8: 0.4}, 12, issue + timedelta(hours=1))
            model.write_text(json.dumps({
                "model_version": MODEL_VERSION, "weather_source": SOURCE,
                "curves": {"turbine_1": curve.to_dict()},
            }))
            with self.assertRaisesRegex(ForecastUnavailable, "обученная до"):
                forecast("turbine_1", issue, 24, model_path=model, weather_cache=cache)


if __name__ == "__main__":
    unittest.main()
