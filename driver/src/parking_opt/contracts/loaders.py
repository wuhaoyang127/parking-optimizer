"""UTF-8 JSON and JSON Lines readers with actionable locations."""

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any


def load_json(path: Path) -> Any:
    """Load one UTF-8 JSON document and preserve the parser location on failure."""

    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"invalid JSON in {path} at line {exc.lineno}, column {exc.colno}: {exc.msg}"
        ) from exc


def iter_jsonl(path: Path) -> Iterator[Any]:
    """Yield non-empty UTF-8 JSON Lines records and report the failing line."""

    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"invalid JSONL in {path} at line {line_number}, column {exc.colno}: {exc.msg}"
                ) from exc
