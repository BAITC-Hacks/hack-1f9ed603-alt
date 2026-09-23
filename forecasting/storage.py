"""Publish complete JSON files so concurrent readers never see partial writes."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path


def write_json(path: Path, value: object, *, indent: int | None = 2) -> None:
    # Serialize before touching disk; non-finite values must never enter artifacts.
    text = json.dumps(value, ensure_ascii=False, allow_nan=False, indent=indent) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=f".{path.name}.", suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
