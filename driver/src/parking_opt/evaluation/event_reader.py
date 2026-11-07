"""Strict UTF-8 JSONL reader for standard ParkingEvent records."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from parking_opt.contracts.schema_validation import SchemaCatalog


def read_validated_events(
    path: Path,
    *,
    schema_catalog: SchemaCatalog,
) -> tuple[dict[str, Any], ...]:
    """Read and validate each line while preserving exact log order."""

    events: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid event JSON at line {line_no}: {exc.msg}") from exc
            if not isinstance(value, dict):
                raise ValueError(f"event at line {line_no} is not an object")
            schema_catalog.validate("event.schema.json", value)
            events.append(value)
    return tuple(events)
