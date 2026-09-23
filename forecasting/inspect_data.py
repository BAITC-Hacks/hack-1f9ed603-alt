"""Проверка входных рядов: python -m forecasting.inspect_data."""

from __future__ import annotations

import json
import os
from pathlib import Path

from forecasting.dataset import TURBINE_IDS, summarize_turbine


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    data_dir = Path(os.getenv("DATA_DIR", str(root / "data" / "raw")))
    summaries = [summarize_turbine(data_dir, turbine_id).to_dict() for turbine_id in TURBINE_IDS]
    print(json.dumps({"turbines": summaries}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
