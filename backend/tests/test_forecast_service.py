from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from pydantic import ValidationError

from backend.app.db import save_run
from backend.app.forecast_service import EngineNotReady, InvalidForecast, run_forecast
from backend.app.schemas import ForecastRunRequest


class ForecastServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.issued_at = datetime(2026, 1, 31, tzinfo=timezone.utc)
        self.request = ForecastRunRequest(
            turbine_id="turbine_1",
            issued_at=self.issued_at,
            horizon_hours=24,
        )

    def payload(self) -> dict:
        return {
            "input_data_cutoff_at": self.issued_at - timedelta(hours=1),
            "weather_source": "test_archive",
            "weather_run_id": "test_run",
            "weather_run_issued_at": self.issued_at - timedelta(hours=6),
            "weather_run_initialized_at": self.issued_at - timedelta(hours=6),
            "weather_run_usable_after_at": self.issued_at,
            "weather_actual_publication_at": None,
            "model_version": "test_model",
            "points": [
                {"time": self.issued_at + timedelta(hours=index), "normalized_power": 0.5}
                for index in range(1, 25)
            ],
        }

    def run_with_payload(self, payload: dict):
        module = SimpleNamespace(run_forecast=lambda **_: payload)
        with patch("backend.app.forecast_service.importlib.util.find_spec", return_value=object()):
            with patch("backend.app.forecast_service.importlib.import_module", return_value=module):
                return run_forecast(self.request)

    def test_valid_result_is_utc_and_can_be_saved(self) -> None:
        result = self.run_with_payload(self.payload())
        body = result.model_dump(mode="json")
        self.assertEqual(body["issued_at"], "2026-01-31T00:00:00Z")
        self.assertEqual(body["weather_run_initialized_at"], "2026-01-30T18:00:00Z")
        self.assertEqual(body["weather_run_usable_after_at"], "2026-01-31T00:00:00Z")
        self.assertIsNone(body["weather_actual_publication_at"])
        self.assertEqual(len(body["points"]), 24)
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "runs.sqlite3"
            with patch.dict(os.environ, {"RUNS_DB_PATH": str(database)}):
                save_run(result)
            with closing(sqlite3.connect(database)) as connection:
                stored = connection.execute("SELECT result_json FROM forecast_runs").fetchone()
            self.assertIsNotNone(stored)
            self.assertEqual(json.loads(stored[0])["run_id"], str(result.run_id))

    def test_future_weather_is_rejected(self) -> None:
        payload = self.payload()
        payload["weather_run_issued_at"] = self.issued_at + timedelta(hours=1)
        with self.assertRaises(InvalidForecast):
            self.run_with_payload(payload)

    def test_future_usability_is_rejected(self) -> None:
        payload = self.payload()
        payload["weather_run_usable_after_at"] = self.issued_at + timedelta(hours=1)
        with self.assertRaises(InvalidForecast):
            self.run_with_payload(payload)

    def test_issued_at_must_match_initialization(self) -> None:
        payload = self.payload()
        payload["weather_run_issued_at"] = self.issued_at - timedelta(hours=7)
        with self.assertRaises(InvalidForecast):
            self.run_with_payload(payload)

    def test_wrong_number_of_points_is_rejected(self) -> None:
        payload = self.payload()
        payload["points"].pop()
        with self.assertRaises(InvalidForecast):
            self.run_with_payload(payload)

    def test_missing_runner_is_explicit(self) -> None:
        with patch("backend.app.forecast_service.importlib.util.find_spec", return_value=None):
            with self.assertRaises(EngineNotReady):
                run_forecast(self.request)

    def test_request_requires_utc_hour_boundary(self) -> None:
        with self.assertRaisesRegex(ValidationError, "начало часа"):
            ForecastRunRequest(
                turbine_id="turbine_1",
                issued_at="2026-02-01T12:30:00Z",
                horizon_hours=24,
            )
        request = ForecastRunRequest(
            turbine_id="turbine_1",
            issued_at="2026-02-01T17:30:00+05:30",
            horizon_hours=24,
        )
        self.assertEqual(request.issued_at.isoformat(), "2026-02-01T12:00:00+00:00")


if __name__ == "__main__":
    unittest.main()
