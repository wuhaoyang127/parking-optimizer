"""C2 whitelist snapshot isolation and canonical-hash tests."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest
from c2_helpers import c2_initial_state

from parking_opt.contracts.canonical import canonical_json_bytes
from parking_opt.contracts.semantic_validation import (
    assert_no_forbidden_fields,
    validate_snapshot_semantics,
)
from parking_opt.contracts.snapshot_projection import (
    observed_snapshot_to_mapping,
    project_observed_snapshot,
)


def test_projected_snapshot_is_schema_valid_visible_and_immutable(
    schema_catalog,
) -> None:
    state = c2_initial_state()
    snapshot = project_observed_snapshot(state, snapshot_id="snapshot-c2")
    mapping = observed_snapshot_to_mapping(snapshot)

    schema_catalog.validate("snapshot.schema.json", mapping)
    validate_snapshot_semantics(mapping)
    assert_no_forbidden_fields(mapping)
    with pytest.raises(FrozenInstanceError):
        snapshot.decision_time_s = 1  # type: ignore[misc]


def test_different_hidden_future_cannot_change_snapshot_bytes() -> None:
    state = c2_initial_state()
    hidden_future_a = [{"actual_departure_time_s": 100}]
    hidden_future_b = [{"actual_departure_time_s": 999}]

    first = project_observed_snapshot(state, snapshot_id="same")
    second = project_observed_snapshot(state, snapshot_id="same")

    assert hidden_future_a != hidden_future_b
    assert canonical_json_bytes(observed_snapshot_to_mapping(first)) == canonical_json_bytes(
        observed_snapshot_to_mapping(second)
    )


def test_projection_rejects_truth_store_or_third_party_object() -> None:
    class TruthStore:
        pass

    with pytest.raises(TypeError, match="AuthoritativeState"):
        project_observed_snapshot(  # type: ignore[arg-type]
            TruthStore(),
            snapshot_id="forbidden",
        )
