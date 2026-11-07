"""Schema-checked exact event replay without a simulation clock."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from parking_opt.contracts.schema_validation import SchemaCatalog
from parking_opt.domain.state import AuthoritativeState
from parking_opt.domain.transitions import replay_events


def replay_validated_events(
    initial_state: AuthoritativeState,
    events: Sequence[Mapping[str, Any]],
    *,
    schema_catalog: SchemaCatalog,
) -> AuthoritativeState:
    """Validate each event structure, then use the pure reducer for exact replay."""

    for event in events:
        schema_catalog.validate("event.schema.json", event)
    return replay_events(initial_state, events)
