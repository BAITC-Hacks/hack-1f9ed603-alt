from __future__ import annotations

import csv
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from forecasting.baseline import MODEL_VERSION, Example, PowerCurve, fit_curve, score
from forecasting.forecast import ForecastUnavailable, forecast
from forecasting.hourly import FIELDS, load_hourly
from forecasting.replay_february import launches, replay
from forecasting.train_baseline import build_examples, build_model_artifact, parse_offset, power_by_utc_end
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
                "training_cutoff_exclusive": issue.isoformat(),
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
                "training_cutoff_exclusive": issue.isoformat(),
                "curves": {"turbine_1": curve.to_dict()},
            }))
            with self.assertRaisesRegex(ForecastUnavailable, "обученная до"):
                forecast("turbine_1", issue, 24, model_path=model, weather_cache=cache)

    def test_pre_january_model_excludes_later_targets(self):
        issue = datetime(2026, 1, 31, 12, tzinfo=UTC)
        examples = []
        for turbine_id in ("turbine_1", "turbine_2"):
            examples.extend([
                Example(turbine_id, issue - timedelta(days=1), issue - timedelta(hours=1), 4, 0.2),
                Example(turbine_id, issue - timedelta(hours=1), issue, 4, 1.0),
            ])
        artifact = build_model_artifact(examples, issue, parse_offset("+05:00"), "pre-test")
        for curve in artifact["curves"].values():
            self.assertEqual(curve["training_count"], 1)
            self.assertEqual(curve["mean_power"], 0.2)
            self.assertLess(datetime.fromisoformat(curve["trained_through"]), issue)

    def test_issued_at_selects_latest_eligible_model(self):
        early = datetime(2026, 1, 31, 12, tzinfo=UTC)
        late = datetime(2026, 2, 1, 12, tzinfo=UTC)
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            for name, cutoff, training_cutoff, value in (
                ("pre", early - timedelta(hours=1), early, 0.2),
                ("final", early + timedelta(hours=7), late - timedelta(hours=12), 0.8),
            ):
                curve = PowerCurve(value, {8: value}, 12, cutoff)
                (directory / f"baseline_{name}.json").write_text(json.dumps({
                    "model_family": MODEL_VERSION, "model_version": name, "weather_source": SOURCE,
                    "training_cutoff_exclusive": training_cutoff.isoformat(),
                    "curves": {"turbine_1": curve.to_dict()},
                }))

            def fake_fetch(initialized_at, _cache_dir):
                points = {initialized_at + timedelta(hours=step): 4.0 for step in range(72)}
                return WeatherRun(initialized_at, initialized_at + timedelta(hours=12),
                                  {"turbine_1": points}, {})

            with patch("forecasting.forecast.fetch_run", side_effect=fake_fetch):
                pre = forecast("turbine_1", early, 24, model_dir=directory)
                final = forecast("turbine_1", late, 48, model_dir=directory)
        self.assertEqual((pre["model_version"], final["model_version"]), ("pre", "final"))
        self.assertEqual((len(pre["points"]), len(final["points"])), (24, 48))
        self.assertLess(pre["input_data_cutoff_at"], pre["issued_at"])


class ReplayTests(unittest.TestCase):
    def test_full_schedule_has_both_turbines_and_horizons(self):
        schedule = list(launches())
        self.assertEqual(len(schedule), 116)
        self.assertEqual(schedule[0], ("turbine_1", datetime(2026, 1, 31, 12, tzinfo=UTC), 24))
        self.assertEqual(schedule[-1], ("turbine_2", datetime(2026, 2, 28, 12, tzinfo=UTC), 48))

    def test_replay_records_unavailable_run_without_fake_points(self):
        def fake_forecast(turbine_id, issued_at, horizon):
            if turbine_id == "turbine_2" and horizon == 48:
                raise ForecastUnavailable("Нет погодного выпуска")
            return {
                "model_version": "test", "input_data_cutoff_at": "2026-01-30T00:00:00Z",
                "weather_source": SOURCE, "weather_run_id": "test-run",
                "weather_run_issued_at": "2026-01-31T00:00:00Z",
                "weather_run_usable_after_at": "2026-01-31T12:00:00Z",
                "points": [{"time": issued_at.isoformat(), "normalized_power": 0.4}] * horizon,
            }

        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "manifest.json"
            manifest = replay(path, start=datetime(2026, 1, 31).date(),
                              end=datetime(2026, 1, 31).date(), forecast_fn=fake_forecast)
            saved = json.loads(path.read_text())
        self.assertEqual((manifest["launch_count"], manifest["completed_count"], manifest["error_count"]),
                         (4, 3, 1))
        self.assertEqual(saved["runs"][-1]["status"], "error")
        self.assertEqual(saved["runs"][-1]["points"], [])


if __name__ == "__main__":
    unittest.main()
