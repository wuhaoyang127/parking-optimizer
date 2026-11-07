from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from datetime import datetime
from typing import Any

import pytest
from pydantic import ValidationError

from parking_opt.api.models import CostSnapshot, DriverRequest, Layout, Recommendation
from parking_opt.api.scenarios import built_in_scenarios


def _layout_payload() -> dict[str, object]:
    return deepcopy(
        built_in_scenarios()["school-demo"].layout.model_dump(mode="json")
    )


Mutation = Callable[[dict[str, Any]], None]


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: value["buffers"][0].update(parking_lot_id="lot-foreign"),
        lambda value: value["buffers"][0].update(access_node_id="missing-node"),
        lambda value: value["edges"][0].update(channel_zone_ids=["missing-zone"]),
        lambda value: value["edges"][0].update(
            channel_zone_ids=[
                value["channel_zones"][0]["channel_zone_id"],
                value["channel_zones"][0]["channel_zone_id"],
            ]
        ),
        lambda value: value["channel_zones"].append(deepcopy(value["channel_zones"][0])),
        lambda value: value["buffers"].append(deepcopy(value["buffers"][0])),
        lambda value: value["buffers"][0].update(buffer_id=value["spaces"][0]["space_id"]),
        lambda value: value["buffers"][0].update(channel_zone_ids=["missing-zone"]),
        lambda value: value["tandem_groups"].append(
            deepcopy(value["tandem_groups"][0])
        ),
        lambda value: value["tandem_groups"][0]["space_ids_near_to_deep"].__setitem__(
            1, "missing-space"
        ),
        lambda value: value["nodes"][0].update(kind="junction"),
    ],
)
def test_layout_rejects_invalid_cross_references(mutate: Mutation) -> None:
    value = _layout_payload()
    mutate(value)
    with pytest.raises(ValidationError):
        Layout.model_validate(value)


def test_layout_rejects_tandem_depth_gaps() -> None:
    value = _layout_payload()
    group = value["tandem_groups"][0]
    far_space_id = group["space_ids_near_to_deep"][1]
    next(item for item in value["spaces"] if item["space_id"] == far_space_id)["depth"] = 3
    with pytest.raises(ValidationError):
        Layout.model_validate(value)


def test_layout_rejects_incomplete_tandem_membership() -> None:
    value = _layout_payload()
    value["tandem_groups"][0]["space_ids_near_to_deep"] = [
        value["tandem_groups"][0]["space_ids_near_to_deep"][0],
        value["spaces"][0]["space_id"],
    ]
    with pytest.raises(ValidationError):
        Layout.model_validate(value)


def test_contract_rejects_naive_datetimes_and_non_finite_costs() -> None:
    bundle = built_in_scenarios()["school-demo"]
    with pytest.raises(ValidationError):
        DriverRequest(
            request_id="request-naive",
            idempotency_key="idem-naive",
            session_id="session-naive",
            parking_lot_id=bundle.parking_lot.parking_lot_id,
            entrance_node_id="entry",
            requested_at=datetime(2026, 8, 12, 9, 1),
        )
    values = dict(bundle.cost_snapshot.edge_travel_time_s)
    values[next(iter(values))] = float("inf")
    with pytest.raises(ValidationError):
        CostSnapshot(
            parking_lot_id=bundle.parking_lot.parking_lot_id,
            layout_version=bundle.layout.layout_version,
            cost_version="cost-infinite",
            observed_at=bundle.cost_snapshot.observed_at,
            edge_travel_time_s=values,
        )


def test_failed_recommendation_rejects_partial_success_payload() -> None:
    bundle = built_in_scenarios()["school-demo"]
    with pytest.raises(ValidationError):
        Recommendation(
            recommendation_id="recommendation-invalid-failure",
            request_id="request-invalid-failure",
            parking_lot_id=bundle.parking_lot.parking_lot_id,
            algorithm_id="online-rule-v2",
            algorithm_version="2.0.0",
            data_source=bundle.parking_lot.data_source,
            solver_status="failed",
            failure_code="V1_ASSESSMENT_FAILED",
            recommended_space_id="A-01",
            assessments=(),
            explanation_codes=("V1_ASSESSMENT_FAILED",),
        )
