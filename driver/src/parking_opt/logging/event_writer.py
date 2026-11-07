"""Append-first event logging with atomic authoritative-state commit."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Protocol

from parking_opt.contracts.canonical import canonical_json_bytes
from parking_opt.contracts.schema_validation import SchemaCatalog
from parking_opt.domain.state import AuthoritativeState
from parking_opt.domain.transitions import apply_event


class EventSink(Protocol):
    """Minimal flush-before-commit append interface."""

    def append_and_flush(self, line: bytes) -> None:
        """Append one complete JSON line or raise without partial state commit."""
        ...


class FileEventSink:
    """Binary append sink that flushes every confirmed event."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._handle = path.open("ab")

    def append_and_flush(self, line: bytes) -> None:
        self._handle.write(line)
        self._handle.flush()

    def close(self) -> None:
        self._handle.close()

    def __enter__(self) -> FileEventSink:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


class MemoryEventSink:
    """In-memory flushed-line sink for deterministic tests and small cases."""

    def __init__(self) -> None:
        self.lines: list[bytes] = []

    def append_and_flush(self, line: bytes) -> None:
        self.lines.append(bytes(line))


class AtomicEventLog:
    """Validate and trial-reduce before logging; commit state only after flush."""

    def __init__(
        self,
        *,
        initial_state: AuthoritativeState,
        schema_catalog: SchemaCatalog,
        sink: EventSink,
    ) -> None:
        self._state = initial_state
        self._catalog = schema_catalog
        self._sink = sink
        self._events: list[dict[str, Any]] = []

    @property
    def state(self) -> AuthoritativeState:
        return self._state

    @property
    def events(self) -> tuple[dict[str, Any], ...]:
        return tuple(self._events)

    def append(self, event: Mapping[str, Any]) -> AuthoritativeState:
        """Append one event and atomically publish its trial-reduced state."""

        self._catalog.validate("event.schema.json", event)
        next_state = apply_event(self._state, event)
        line = canonical_json_bytes(event) + b"\n"
        self._sink.append_and_flush(line)
        stable_event = json.loads(line)
        if not isinstance(stable_event, dict):
            raise TypeError("serialized ParkingEvent did not remain an object")
        self._events.append(stable_event)
        self._state = next_state
        return next_state
