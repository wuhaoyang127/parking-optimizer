from __future__ import annotations

from copy import deepcopy

import pytest
from pydantic import ValidationError

from parking_opt.api.models import (
    FacilityClaimStatus,
    FacilityObservationSource,
    FacilitySpaceState,
    ParkingFacilityLayout,
    ParkingFacilityStateSnapshot,
    RoutePreview,
    RoutePreviewRequest,
    SpaceStatus,
)
from facility_layout_fixture import _facility_layout
from facility_state_fixture import _facility_state, _route_preview, _two_floor_layout


def test_facility_layout_accepts_complete_meter_geometry() -> None:
    layout = _facility_layout()
    assert layout.coordinate_system == "local_meters"
    assert layout.spaces[1].depth == 2
    assert layout.tandem_groups[0].buffer_ids == ("buffer-1",)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: value["spaces"][0].update(access_node_id="missing-node"),
        lambda value: value["spaces"][0].update(access_node_id="entry"),
        lambda value: value["spaces"][1].update(depth=3),
        lambda value: value["buffers"][0].update(stack_group_ids=["missing-group"]),
        lambda value: value["edges"][0].update(
            centerline=[{"x_m": 1, "y_m": 1}, {"x_m": 10, "y_m": 10}]
        ),
        lambda value: value["zones"][0]["polygon"][0].update(x_m=-1),
    ],
)
def test_facility_layout_rejects_invalid_geometry_and_references(mutate) -> None:  # type: ignore[no-untyped-def]
    payload = deepcopy(_facility_layout().model_dump(mode="json"))
    mutate(payload)
    with pytest.raises(ValidationError):
        ParkingFacilityLayout.model_validate(payload)


def test_inter_floor_connection_matches_edge_direction_and_traversal_kind() -> None:
    layout = _two_floor_layout()
    assert layout.inter_floor_connections[0].kind == "ramp"
    wrong_kind = layout.model_dump(mode="json")
    wrong_kind["inter_floor_connections"][0]["kind"] = "lift"
    with pytest.raises(ValidationError, match="traversal kind mismatch"):
        ParkingFacilityLayout.model_validate(wrong_kind)
    wrong_direction = layout.model_dump(mode="json")
    connection = wrong_direction["inter_floor_connections"][0]
    connection["from_floor_id"], connection["to_floor_id"] = (
        connection["to_floor_id"],
        connection["from_floor_id"],
    )
    with pytest.raises(ValidationError, match="direction mismatch"):
        ParkingFacilityLayout.model_validate(wrong_direction)


def test_facility_state_keeps_observation_claim_and_effective_status_separate() -> None:
    claimed = FacilitySpaceState(
        space_id="T-01",
        observed_status=SpaceStatus.AVAILABLE,
        observation_source=FacilityObservationSource.SYNTHETIC_TRUTH,
        claim_status=FacilityClaimStatus.SOFT_HELD,
        effective_status=SpaceStatus.UNAVAILABLE,
        assignable=False,
        reason_codes=("SOFT_HELD",),
    )
    assert claimed.observed_status is SpaceStatus.AVAILABLE
    assert claimed.effective_status is SpaceStatus.UNAVAILABLE
    with pytest.raises(ValidationError):
        FacilitySpaceState(
            space_id="T-unknown",
            observed_status=SpaceStatus.UNKNOWN,
            observation_source=FacilityObservationSource.OBSERVATION,
            effective_status=SpaceStatus.AVAILABLE,
            assignable=True,
        )
    with pytest.raises(ValidationError, match="must remain effectively available"):
        FacilitySpaceState(
            space_id="T-conflict",
            observed_status=SpaceStatus.AVAILABLE,
            observation_source=FacilityObservationSource.SYNTHETIC_TRUTH,
            effective_status=SpaceStatus.OCCUPIED,
            assignable=False,
            reason_codes=("CONFLICT",),
        )


def test_real_facility_state_requires_healthy_observed_truth() -> None:
    synthetic_payload = _facility_state().model_dump(mode="json")
    synthetic_payload["source"]["source_kind"] = "real"
    with pytest.raises(ValidationError, match="cannot contain synthetic"):
        ParkingFacilityStateSnapshot.model_validate(synthetic_payload)
    observed_payload = deepcopy(synthetic_payload)
    for item in (*observed_payload["spaces"], *observed_payload["buffers"]):
        item["observation_source"] = "observation"
    observed_payload["source"].update(
        health="degraded", missing_fields=["spaces.T-03"], fail_reason=None
    )
    with pytest.raises(ValidationError, match="must be healthy"):
        ParkingFacilityStateSnapshot.model_validate(observed_payload)


def test_facility_state_must_cover_layout_exactly() -> None:
    payload = _facility_state().model_dump(mode="json")
    payload["spaces"] = payload["spaces"][:-1]
    incomplete = ParkingFacilityStateSnapshot.model_validate(payload)
    with pytest.raises(ValueError, match="cover layout spaces exactly"):
        incomplete.require_layout(_facility_layout())


def _request() -> RoutePreviewRequest:
    return RoutePreviewRequest(
        layout_version="facility-school-v1",
        scenario_version="scenario-school-v1",
        state_version="state-1",
        entrance_id="entrance-south",
        target_space_id="T-01",
    )


def test_route_preview_requires_route_scope_and_layout_identity() -> None:
    payload = _route_preview().model_dump(mode="json")
    payload["route"]["layout_version"] = "other-layout"
    with pytest.raises(ValidationError):
        RoutePreview.model_validate(payload)
    invalid_path = _route_preview().model_copy(
        update={"route": _route_preview().route.model_copy(update={"edge_ids": ("edge-exit",)})}
    )
    with pytest.raises(ValueError, match="sequence lengths differ"):
        invalid_path.require_context(request=_request(), layout=_facility_layout(), state=_facility_state())
    mismatched_layout = _facility_layout().model_copy(update={"layout_version": "other-v1"})
    with pytest.raises(ValueError, match="layout version mismatch"):
        _route_preview().require_context(
            request=_request(), layout=mismatched_layout, state=_facility_state()
        )
    wrong_endpoints = _route_preview().model_copy(
        update={"route": _route_preview().route.model_copy(update={"node_ids": ("junction", "access-1", "entry")})}
    )
    with pytest.raises(ValueError, match="sequence endpoints"):
        wrong_endpoints.require_context(request=_request(), layout=_facility_layout(), state=_facility_state())
    instructions = list(_route_preview().route.instructions)
    instructions[1] = instructions[1].model_copy(update={"sequence": 3})
    wrong_sequence = _route_preview().model_copy(
        update={"route": _route_preview().route.model_copy(update={"instructions": tuple(instructions)})}
    )
    with pytest.raises(ValueError, match="instruction sequence"):
        wrong_sequence.require_context(request=_request(), layout=_facility_layout(), state=_facility_state())
