"""Exercise HTTP validation, the real forecasting engine, and SQLite together."""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime, timedelta
from functools import partial
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.app.main import app, load_summaries
from forecasting.forecast import forecast
from forecasting.runner import run_forecast

ROOT = Path(__file__).resolve().parents[2]


class ApiIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.database = Path(self.temp.name) / "runs.sqlite3"
        self.env = patch.dict(os.environ, {"RUNS_DB_PATH": str(self.database)})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.network = patch("forecasting.weather.urlopen", side_effect=AssertionError("Tests must use archived cache"))
        self.network.start()
        self.addCleanup(self.network.stop)
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        self.logs = patch("backend.app.main.LOGGER")
        self.logs.start()
        self.addCleanup(self.logs.stop)

    def request(self, **overrides):
        payload = dict(turbine_id="turbine_1", issued_at="2026-02-01T12:00:00Z", horizon_hours=24)
        payload.update(overrides)
        return self.client.post("/api/forecast-runs", json=payload)

    def assert_error(self, response, status):
        self.assertEqual(response.status_code, status, response.text)
        self.assertEqual(set(response.json()), {"error"})
        self.assertIsInstance(response.json()["error"], str)

    def test_all_116_replays_match_http_results_and_persist(self):
        manifest = json.loads((ROOT / "data/processed/february_replay.json").read_text())
        run_ids = set()
        for expected in manifest["runs"]:
            with self.subTest(launch=expected["launch_id"]):
                response = self.request(**{key: expected[key] for key in ("turbine_id", "issued_at", "horizon_hours")})
                self.assertEqual(response.status_code, 201, response.text)
                result = response.json()
                run_ids.add(result["run_id"])
                for key in ("model_version", "input_data_cutoff_at", "weather_run_id", "weather_run_initialized_at",
                            "weather_run_usable_after_at", "weather_actual_publication_at", "points"):
                    self.assertEqual(result[key], expected[key])
                issued = datetime.fromisoformat(result["issued_at"])
                self.assertLess(datetime.fromisoformat(result["input_data_cutoff_at"]), issued)
                for index, point in enumerate(result["points"], 1):
                    self.assertEqual(datetime.fromisoformat(point["time"]), issued + timedelta(hours=index))
                    self.assertTrue(0 <= point["normalized_power"] <= 1)
        self.assertEqual(len(run_ids), 116)
        # New DB connections and clients must retain every saved result.
        with closing(sqlite3.connect(self.database)) as connection:
            rows = connection.execute("SELECT run_id, result_json FROM forecast_runs").fetchall()
        self.assertEqual({row[0] for row in rows}, run_ids)
        for run_id, text in rows:
            self.assertEqual(json.loads(text)["run_id"], run_id)

    def test_invalid_requests_fail_before_forecasting(self):
        changes = [dict(issued_at="2026-02-01T12:30:00Z"), dict(issued_at="2026-02-01T12:00:00"),
                   dict(issued_at=1769947200), dict(issued_at="1769947200"),
                   dict(issued_at="9999-12-31T23:00:00Z"), dict(issued_at="0001-01-01T00:00:00Z"),
                   dict(turbine_id="unknown"), dict(horizon_hours=25)]
        with patch("backend.app.main.run_forecast") as runner:
            for change in changes:
                with self.subTest(change=change): self.assert_error(self.request(**change), 422)
            self.assert_error(self.client.post("/api/forecast-runs", content="{broken", headers={"Content-Type": "application/json"}), 422)
            runner.assert_not_called()
        self.assertFalse(self.database.exists())

    def test_offsets_normalize_to_same_forecast(self):
        utc = self.request().json()
        local = self.request(issued_at="2026-02-01T17:00:00+05:00").json()
        self.assertEqual(local["issued_at"], utc["issued_at"])
        self.assertEqual(local["points"], utc["points"])

    def test_unavailable_or_corrupt_sources_return_503_without_saving(self):
        self.assert_error(self.request(issued_at="2026-01-01T12:00:00Z"), 503)
        for problem in ("model", "weather", "network"):
            with self.subTest(problem=problem):
                directory = Path(self.temp.name) / problem
                directory.mkdir()
                if problem == "model":
                    (directory / "baseline_model.json").write_text('{"model_family": null}')
                    engine = partial(forecast, model_dir=directory)
                else:
                    if problem == "weather":
                        (directory / "ecmwf_ifs_20260201T0000Z.json").write_text("[]")
                    engine = partial(forecast, weather_cache=directory)
                with patch("forecasting.runner.forecast", side_effect=engine), \
                        patch("forecasting.weather.urlopen", side_effect=TimeoutError("weather timeout")):
                    self.assert_error(self.request(), 503)
        self.assertFalse(self.database.exists())

    def test_invalid_model_output_returns_502_without_saving(self):
        payload = run_forecast("turbine_1", datetime.fromisoformat("2026-02-01T12:00:00Z"), 24)
        for value in (float("nan"), float("inf"), -0.1, 1.1, True, "0.5"):
            with self.subTest(value=value):
                payload["points"][0]["normalized_power"] = value
                with patch("forecasting.runner.run_forecast", return_value=payload):
                    self.assert_error(self.request(), 502)
        self.assertFalse(self.database.exists())

    def test_storage_failure_is_explicit(self):
        with patch("backend.app.main.save_run", side_effect=sqlite3.OperationalError("read-only database")):
            self.assert_error(self.request(), 503)

    def test_concurrent_forecasts_are_saved_independently(self):
        with ThreadPoolExecutor(max_workers=6) as pool:
            responses = list(pool.map(lambda _: self.request(), range(12)))
        self.assertTrue(all(response.status_code == 201 for response in responses))
        self.assertEqual(len({response.json()["run_id"] for response in responses}), 12)
        with closing(sqlite3.connect(self.database)) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM forecast_runs").fetchone()[0], 12)

    def test_framework_errors_use_api_error_format(self):
        self.assert_error(self.client.get("/api/unknown"), 404)
        response = self.client.get("/api/forecast-runs")
        self.assert_error(response, 405)
        self.assertIn("POST", response.headers["allow"])

    def test_corrupt_csv_inventory_returns_503(self):
        directory = Path(self.temp.name)
        (directory / "turbine_1.csv").write_text("a,b,c,d,e\n1\n")
        load_summaries.cache_clear()
        self.addCleanup(load_summaries.cache_clear)
        with patch("backend.app.main.DATA_DIR", directory):
            self.assert_error(self.client.get("/api/turbines"), 503)


if __name__ == "__main__":
    unittest.main()
