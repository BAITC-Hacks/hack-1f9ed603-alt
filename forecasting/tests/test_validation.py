from __future__ import annotations

import copy
import csv
import io
import json
import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from http.client import IncompleteRead
from pathlib import Path
from unittest.mock import patch

from forecasting.baseline import PowerCurve
from forecasting.dataset import FIELDS, summarize_turbine
from forecasting.forecast import ForecastUnavailable, forecast
from forecasting.hourly import load_hourly
from forecasting.storage import write_json
from forecasting.time_alignment import source_hour_end_on_forecast_axis
from forecasting.weather import fetch_run

ROOT = Path(__file__).resolve().parents[2]
ISSUED = datetime(2026, 2, 1, 12, tzinfo=timezone.utc)
INITIALIZED = ISSUED.replace(hour=0)
CACHE_NAME = "ecmwf_ifs_20260201T0000Z.json"


class ValidationTests(unittest.TestCase):
    def setUp(self):
        self.weather = json.loads((ROOT / "data/weather/ecmwf_ifs" / CACHE_NAME).read_text())
        self.model = json.loads((ROOT / "forecasting/artifacts/baseline_model.json").read_text())

    def test_corrupt_weather_is_rejected_without_invented_power(self):
        for problem in ("root", "structure", "negative", "nan", "infinity", "duplicate", "units", "timezone", "missing"):
            with self.subTest(problem=problem), tempfile.TemporaryDirectory() as temp:
                payload = copy.deepcopy(self.weather)
                response = payload["responses"][0]
                if problem == "root": payload = []
                elif problem == "structure": response["hourly"] = None
                elif problem == "negative": response["hourly"]["wind_speed_100m"][13] = -1
                elif problem == "nan": response["hourly"]["wind_speed_100m"][13] = float("nan")
                elif problem == "infinity": response["hourly"]["wind_speed_100m"][13] = float("inf")
                elif problem == "duplicate": response["hourly"]["time"][13] = response["hourly"]["time"][12]
                elif problem == "units": response["hourly_units"]["wind_speed_100m"] = "km/h"
                elif problem == "timezone": response["utc_offset_seconds"] = 18000
                elif problem == "missing": response["hourly"]["wind_speed_100m"][13] = None
                (Path(temp) / CACHE_NAME).write_text(json.dumps(payload))
                with self.assertRaises(ForecastUnavailable):
                    forecast("turbine_1", ISSUED, 24, weather_cache=Path(temp))

    def test_invalid_network_response_is_not_cached(self):
        payload = self.weather["responses"]
        payload[0]["hourly"]["wind_speed_100m"][0] = -1
        with tempfile.TemporaryDirectory() as temp:
            with patch("forecasting.weather.urlopen", return_value=io.BytesIO(json.dumps(payload).encode())):
                with self.assertRaises(ValueError):
                    fetch_run(INITIALIZED, Path(temp))
            self.assertFalse((Path(temp) / CACHE_NAME).exists())

    def test_interrupted_http_response_is_unavailable(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch("forecasting.weather.urlopen", side_effect=IncompleteRead(b"partial")):
                with self.assertRaises(ForecastUnavailable):
                    forecast("turbine_1", ISSUED, 24, weather_cache=Path(temp))
            self.assertFalse((Path(temp) / CACHE_NAME).exists())

    def test_source_alignment_rejects_implicit_timezone_conversion(self):
        with self.assertRaises(ValueError):
            source_hour_end_on_forecast_axis(ISSUED)

    def test_corrupt_models_are_explicitly_unavailable(self):
        for problem in ("root", "curve", "empty", "nan", "out_of_range", "naive", "count", "version", "cutoff", "time_policy"):
            with self.subTest(problem=problem), tempfile.TemporaryDirectory() as temp:
                artifact = copy.deepcopy(self.model)
                curve = artifact["curves"]["turbine_1"]
                if problem == "root": artifact = []
                elif problem == "curve": artifact["curves"]["turbine_1"] = None
                elif problem == "empty": curve["bin_values"] = {}
                elif problem == "nan": curve["bin_values"]["1"] = float("nan")
                elif problem == "out_of_range": curve["bin_values"]["1"] = 1.5
                elif problem == "naive": curve["trained_through"] = "2026-01-31T19:00:00"
                elif problem == "count": curve["training_count"] = 2.5
                elif problem == "version": del artifact["model_version"]
                elif problem == "cutoff": artifact["training_cutoff_exclusive"] = curve["trained_through"]
                elif problem == "time_policy": artifact["time_alignment"]["source_clock_shift_hours"] = -5
                path = Path(temp) / "model.json"
                path.write_text(json.dumps(artifact))
                with self.assertRaises(ForecastUnavailable):
                    forecast("turbine_1", ISSUED, 24, model_path=path)

    def test_negative_or_nonfinite_wind_cannot_be_predicted(self):
        curve = PowerCurve.from_dict(self.model["curves"]["turbine_1"])
        for wind in (-1, float("nan"), float("inf"), True):
            with self.subTest(wind=wind), self.assertRaises(ValueError):
                curve.predict(wind)

    def test_csv_validation_agrees_between_inventory_and_training(self):
        for row in ([1, "2026-01-01 00:00:00"],
                    [1, "2026-01-01 00:00:00", 4, "nan", 10],
                    [1, "2026-01-01 00:01:00", 4, .2, 10],
                    [1, "2026-01-01 00:00:00", 4, .2, 10, "extra"]):
            with self.subTest(row=row), tempfile.TemporaryDirectory() as temp:
                path = Path(temp) / "turbine_1.csv"
                with path.open("w", newline="") as stream:
                    writer = csv.writer(stream)
                    writer.writerow(FIELDS)
                    writer.writerow(row)
                for load in (load_hourly, summarize_turbine):
                    with self.assertRaises(ValueError): load(Path(temp), "turbine_1")

    def test_atomic_replacement_preserves_old_file_on_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "cache.json"
            write_json(path, {"old": True})
            with patch("forecasting.storage.os.replace", side_effect=OSError("disk failure")):
                with self.assertRaises(OSError): write_json(path, {"new": True})
            self.assertEqual(json.loads(path.read_text()), {"old": True})
            self.assertEqual(list(Path(temp).iterdir()), [path])

    def test_concurrent_weather_requests_leave_a_valid_cache(self):
        responses = json.dumps(self.weather["responses"]).encode()
        with tempfile.TemporaryDirectory() as temp:
            with patch("forecasting.weather.urlopen", side_effect=lambda *a, **kw: io.BytesIO(responses)):
                with ThreadPoolExecutor(max_workers=8) as pool:
                    results = list(pool.map(lambda _: fetch_run(INITIALIZED, Path(temp)), range(16)))
            self.assertTrue(all(run == results[0] for run in results))
            self.assertEqual(fetch_run(INITIALIZED, Path(temp)), results[0])
            self.assertEqual(len(list(Path(temp).iterdir())), 1)

    @unittest.skipUnless(os.name == 'nt', 'Windows file-sharing retry')
    def test_atomic_replacement_retries_windows_reader_lock(self):
        from forecasting.storage import os as storage_os
        original_replace = storage_os.replace
        calls = 0
        def transient_lock(source, destination):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise PermissionError('Transient reader lock')
            return original_replace(source, destination)
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'cache.json'
            write_json(path, {'old': True})
            with patch('forecasting.storage.os.replace', side_effect=transient_lock):
                write_json(path, {'new': True})
            self.assertEqual(json.loads(path.read_text()), {'new': True})
            self.assertEqual(calls, 2)
            self.assertEqual(list(Path(temp).iterdir()), [path])


if __name__ == "__main__":
    unittest.main()
