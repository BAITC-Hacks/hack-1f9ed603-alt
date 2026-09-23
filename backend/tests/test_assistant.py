"""Check assistant HTTP boundaries and replay its parameters through the real engine."""

from __future__ import annotations

import io
import json
import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from fastapi.testclient import TestClient

from backend.app.main import app


ENDPOINT = "/api/assistant/forecast-parameters"
FAKE_KEY = "sk-test-assistant-never-a-real-key"
UPSTREAM_SECRET = "private upstream diagnostics " + FAKE_KEY


def extraction(**changes):
    result = {
        "status": "ready",
        "turbine_id": None,
        "issued_at": "2026-02-22T17:00:00Z",
        "horizon_hours": None,
        "reason": None,
    }
    result.update(changes)
    return result


def envelope(result):
    return {
        "status": "completed",
        "output": [{"type": "message", "content": [
            {"type": "output_text", "text": json.dumps(result)}
        ]}],
    }


class AssistantApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.database = Path(self.temp.name) / "runs.sqlite3"
        self.env = patch.dict(os.environ, {
            "OPENAI_API_KEY": FAKE_KEY,
            "OPENAI_MODEL": "gpt-4o-mini",
            "RUNS_DB_PATH": str(self.database),
        })
        self.env.start()
        self.addCleanup(self.env.stop)
        self.weather = patch("forecasting.weather.urlopen", side_effect=AssertionError("Use archived weather only"))
        self.weather.start()
        self.addCleanup(self.weather.stop)
        self.external = patch("backend.app.assistant_service.urlopen")
        self.urlopen = self.external.start()
        self.addCleanup(self.external.stop)
        self.client = TestClient(app)
        self.addCleanup(self.client.close)

    def request(self, **changes):
        payload = {
            "message": "22 февраля 17:00 2026 года",
            "defaults": {
                "turbine_id": "turbine_1",
                "issued_at": "2026-02-01T12:00:00Z",
                "horizon_hours": 24,
            },
        }
        payload.update(changes)
        return self.client.post(ENDPOINT, json=payload)

    def set_output(self, result=None, *, response=None, raw=None):
        if raw is None:
            response = envelope(extraction() if result is None else result) if response is None else response
            raw = json.dumps(response).encode("utf-8")
        self.urlopen.side_effect = lambda *args, **kwargs: io.BytesIO(raw)

    def assert_error(self, response, status, message=None):
        self.assertEqual(response.status_code, status, response.text)
        self.assertEqual(set(response.json()), {"error"})
        self.assertIsInstance(response.json()["error"], str)
        if message is not None:
            self.assertEqual(response.json()["error"], message)
        self.assertNotIn(FAKE_KEY, response.text)
        self.assertNotIn(UPSTREAM_SECRET, response.text)

    def assert_clarification(self, response):
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(set(body), {"status", "request", "message"})
        self.assertEqual(body["status"], "clarification")
        self.assertIsNone(body["request"])
        self.assertIsInstance(body["message"], str)
        self.assertTrue(body["message"].strip())
        self.assertNotIn(FAKE_KEY, response.text)

    def test_date_example_preserves_defaults_and_matches_real_manual_forecasts(self):
        run_ids = set()
        for turbine in ("turbine_1", "turbine_2"):
            for horizon in (24, 48):
                with self.subTest(turbine=turbine, horizon=horizon):
                    defaults = {"turbine_id": turbine, "issued_at": "2026-02-01T12:00:00Z", "horizon_hours": horizon}
                    self.set_output()
                    with patch("backend.app.main.run_forecast") as runner, patch("backend.app.main.save_run") as save:
                        response = self.request(defaults=defaults)
                        runner.assert_not_called()
                        save.assert_not_called()
                    expected = dict(defaults, issued_at="2026-02-22T17:00:00Z")
                    self.assertEqual(response.status_code, 200, response.text)
                    self.assertEqual(response.json(), {"status": "ready", "request": expected, "message": None})
                    assisted = self.client.post("/api/forecast-runs", json=response.json()["request"])
                    manual = self.client.post("/api/forecast-runs", json=expected)
                    self.assertEqual(assisted.status_code, 201, assisted.text)
                    self.assertEqual(manual.status_code, 201, manual.text)
                    assisted_body, manual_body = assisted.json(), manual.json()
                    assisted_id = assisted_body.pop("run_id")
                    manual_id = manual_body.pop("run_id")
                    self.assertNotEqual(assisted_id, manual_id)
                    run_ids.update((assisted_id, manual_id))
                    self.assertEqual(assisted_body, manual_body)
                    self.assertEqual(len(assisted_body["points"]), horizon)
        with closing(sqlite3.connect(self.database)) as connection:
            saved_ids = {row[0] for row in connection.execute("SELECT run_id FROM forecast_runs")}
        self.assertEqual(saved_ids, run_ids)
        self.assertEqual(len(saved_ids), 8)

    def test_explicit_parameters_override_selected_defaults_and_normalize_offset(self):
        self.set_output(extraction(turbine_id="turbine_2", horizon_hours=48, issued_at="2026-02-22T22:00:00+05:00"))
        response = self.request(message="Вторая ВЭС, 48 часов, 22 февраля 2026 в 22:00 +05:00")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), {
            "status": "ready",
            "request": {"turbine_id": "turbine_2", "issued_at": "2026-02-22T17:00:00Z", "horizon_hours": 48},
            "message": None,
        })
        self.assertFalse(self.database.exists())

    def test_transport_uses_responses_structured_output_and_trimmed_message(self):
        self.set_output()
        response = self.request(message="  22 февраля 17:00 2026 года  ", language="kk")
        self.assertEqual(response.status_code, 200, response.text)
        self.urlopen.assert_called_once()
        args, kwargs = self.urlopen.call_args
        request = args[0]
        self.assertEqual(request.full_url, "https://api.openai.com/v1/responses")
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.get_header("Authorization"), "Bearer " + FAKE_KEY)
        self.assertEqual(kwargs["timeout"], 30)
        payload = json.loads(request.data)
        self.assertEqual(payload["model"], "gpt-4o-mini")
        self.assertEqual(payload["text"]["format"]["type"], "json_schema")
        self.assertIs(payload["text"]["format"]["strict"], True)
        self.assertIn("22 февраля 17:00 2026 года", json.dumps(payload, ensure_ascii=False))
        self.assertNotIn("  22 февраля 17:00 2026 года  ", json.dumps(payload, ensure_ascii=False))
        self.assertNotIn(FAKE_KEY, json.dumps(payload))

    def test_model_can_be_configured_on_server(self):
        self.set_output()
        with patch.dict(os.environ, {"OPENAI_MODEL": "test-configured-model"}):
            response = self.request()
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(json.loads(self.urlopen.call_args.args[0].data)["model"], "test-configured-model")

    def test_bad_user_inputs_fail_before_external_call_or_forecast(self):
        bad_inputs = [
            {"message": ""}, {"message": " \t\n "}, {"message": "a" * 4001},
            {"message": None}, {"message": 42}, {"message": ["date"]},
            {"language": "de"}, {"language": None}, {"defaults": None},
            {"unexpected": "field"},
            {"defaults": {"turbine_id": "unknown", "issued_at": "2026-02-22T17:00:00Z", "horizon_hours": 24}},
            {"defaults": {"turbine_id": "turbine_1", "issued_at": "2026-02-22T17:30:00Z", "horizon_hours": 24}},
            {"defaults": {"turbine_id": "turbine_1", "issued_at": "2026-02-22T17:00:00", "horizon_hours": 24}},
            {"defaults": {"turbine_id": "turbine_1", "issued_at": "2026-02-22T17:00:00Z", "horizon_hours": 72}},
        ]
        with patch("backend.app.main.run_forecast") as runner, patch("backend.app.main.save_run") as save:
            for changes in bad_inputs:
                with self.subTest(changes=changes):
                    self.assert_error(self.request(**changes), 422)
            self.assert_error(self.client.post(ENDPOINT, json={"message": "date"}), 422)
            self.assert_error(self.client.post(ENDPOINT, content="{broken", headers={"Content-Type": "application/json"}), 422)
            runner.assert_not_called()
            save.assert_not_called()
        self.urlopen.assert_not_called()
        self.assertFalse(self.database.exists())

    def test_missing_date_requires_clarification_even_when_defaults_have_date(self):
        self.set_output(extraction(status="clarification", issued_at=None, reason="missing_datetime"))
        with patch("backend.app.main.run_forecast") as runner:
            self.assert_clarification(self.request(message="Сделай прогноз"))
            runner.assert_not_called()
        self.assertFalse(self.database.exists())

    def test_clarifications_have_safe_localized_messages(self):
        messages = set()
        for language in ("ru", "kk", "en"):
            with self.subTest(language=language):
                self.set_output(extraction(status="clarification", issued_at=None, reason="ambiguous"))
                response = self.request(message="Прогноз на завтра", language=language)
                self.assert_clarification(response)
                messages.add(response.json()["message"])
        self.assertEqual(len(messages), 3)
        self.assertFalse(self.database.exists())

    def test_unsupported_requests_and_refusals_return_clarification(self):
        for reason in ("unsupported_turbine", "unsupported_horizon", "unsupported_request"):
            with self.subTest(reason=reason):
                self.set_output(extraction(status="clarification", issued_at=None, reason=reason))
                self.assert_clarification(self.request())
        self.set_output(response={"status": "completed", "output": [{"type": "message", "content": [
            {"type": "refusal", "refusal": UPSTREAM_SECRET}
        ]}]})
        response = self.request()
        self.assert_clarification(response)
        self.assertNotIn(UPSTREAM_SECRET, response.text)
        self.assertFalse(self.database.exists())

    def test_invalid_recognizable_parameters_request_clarification_without_forecast(self):
        invalid = [
            {"issued_at": None}, {"issued_at": "2026-02-30T17:00:00Z"},
            {"issued_at": "2026-02-22T17:30:00Z"}, {"issued_at": "2026-02-22T17:00:00"},
            {"issued_at": "0001-01-01T00:00:00Z"}, {"issued_at": "9999-12-31T23:00:00Z"},
            {"issued_at": "2026-02-22T17:00:00+00:60"}, {"issued_at": "2026-02-22T17:00:00-00:60"},
            {"issued_at": "2026-02-22T17:00:00+24:00"},
        ]
        with patch("backend.app.main.run_forecast") as runner, patch("backend.app.main.save_run") as save:
            for changes in invalid:
                with self.subTest(changes=changes):
                    self.set_output(extraction(**changes))
                    self.assert_clarification(self.request())
            runner.assert_not_called()
            save.assert_not_called()
        self.assertFalse(self.database.exists())

    def test_malformed_and_incomplete_responses_are_rejected(self):
        incomplete_extraction = extraction()
        del incomplete_extraction["reason"]
        cases = [
            b"not-json " + UPSTREAM_SECRET.encode(),
            b"[]",
            json.dumps({"status": "incomplete", "output": []}).encode(),
            json.dumps({"status": "failed", "error": {"message": UPSTREAM_SECRET}}).encode(),
            json.dumps({"status": "completed", "output": []}).encode(),
            json.dumps({"status": "completed", "output": [{"type": "message", "content": [
                {"type": "output_text", "text": "{broken " + UPSTREAM_SECRET}
            ]}]}).encode(),
            json.dumps(envelope(incomplete_extraction)).encode(),
            json.dumps(envelope(extraction(unexpected=UPSTREAM_SECRET))).encode(),
            json.dumps(envelope(extraction(status="unknown"))).encode(),
            json.dumps(envelope(extraction(turbine_id="turbine_3"))).encode(),
            json.dumps(envelope(extraction(horizon_hours=72))).encode(),
            json.dumps(envelope(extraction(issued_at={"value": "2026-02-22T17:00:00Z"}))).encode(),
            json.dumps(envelope(extraction(horizon_hours=True))).encode(),
            json.dumps(envelope(extraction(reason="invalid_datetime"))).encode(),
            json.dumps(envelope(extraction(status="clarification", reason="ambiguous"))).encode(),
            json.dumps(envelope(extraction(status="clarification", issued_at=None))).encode(),
            json.dumps(envelope([extraction()])).encode(),
        ]
        with patch("backend.app.main.run_forecast") as runner, patch("backend.app.main.save_run") as save:
            for index, raw in enumerate(cases):
                with self.subTest(case=index):
                    self.set_output(raw=raw)
                    self.assert_error(self.request(), 502, "Сервис ИИ вернул некорректный ответ")
            runner.assert_not_called()
            save.assert_not_called()
        self.assertFalse(self.database.exists())

    def test_missing_key_returns_configuration_error_without_external_call(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "  "}):
            self.assert_error(self.request(), 503, "Сервис ИИ не настроен")
        self.urlopen.assert_not_called()
        self.assertFalse(self.database.exists())

    def test_upstream_http_failures_are_actionable_and_do_not_expose_diagnostics(self):
        statuses = {
            401: "Ключ сервиса ИИ отклонён",
            403: "Ключ сервиса ИИ отклонён",
            429: "Лимит сервиса ИИ исчерпан",
            500: "Сервис ИИ временно недоступен",
            503: "Сервис ИИ временно недоступен",
        }
        for status, message in statuses.items():
            with self.subTest(status=status):
                self.urlopen.side_effect = HTTPError(
                    "https://api.openai.com/v1/responses", status, UPSTREAM_SECRET, {}, io.BytesIO(UPSTREAM_SECRET.encode()),
                )
                self.assert_error(self.request(), 503, message)
        self.assertFalse(self.database.exists())

    def test_network_failures_return_safe_unavailability_errors(self):
        for error in (URLError(UPSTREAM_SECRET), TimeoutError(UPSTREAM_SECRET), OSError(UPSTREAM_SECRET)):
            with self.subTest(error=type(error).__name__):
                self.urlopen.side_effect = error
                self.assert_error(self.request(), 503, "Сервис ИИ временно недоступен")
        self.assertFalse(self.database.exists())


if __name__ == "__main__":
    unittest.main()
