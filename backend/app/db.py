"""Локальное хранилище только успешных запусков."""

from __future__ import annotations

import os
import sqlite3
from contextlib import closing
from pathlib import Path

from backend.app.schemas import ForecastRunResponse, utc_string

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = ROOT / "backend" / "runs.sqlite3"


def save_run(run: ForecastRunResponse) -> None:
    database = Path(os.getenv("RUNS_DB_PATH", str(DEFAULT_DB_PATH)))
    database.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(database, timeout=10)) as connection:
        with connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS forecast_runs (
                    run_id TEXT PRIMARY KEY,
                    turbine_id TEXT NOT NULL,
                    issued_at TEXT NOT NULL,
                    result_json TEXT NOT NULL
                )
                """
            )
            connection.execute(
                "INSERT INTO forecast_runs (run_id, turbine_id, issued_at, result_json) VALUES (?, ?, ?, ?)",
                (str(run.run_id), run.turbine_id, utc_string(run.issued_at), run.model_dump_json()),
            )
