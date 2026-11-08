"""Action construction for bounded selection."""

from __future__ import annotations

import math
from collections.abc import Mapping

from parking_opt.domain.enums import ActionStatus, ActionType, ExecutorType
from parking_opt.domain.records import Action, DecisionRequest


def _action(
    *,
    request: DecisionRequest,
    action_id: str,
    vehicle_id: str,
    action_type: ActionType,
    path: Mapping[str, Any],
    origin_position_id: str | None,
    destination_position_id: str | None,
    destination_exit_id: str | None,
    transaction_id: str | None = None,
) -> Action:
    config = request.approved_config
    distance_m = float(path["distance_m"])
    if action_type in {ActionType.RELOCATE_TO_BUFFER, ActionType.RESTORE_ORIGINAL}:
        duration = math.ceil(
            float(config["relocation_setup_s"]) + distance_m / float(config["relocation_speed_mps"])
        )
        executor_units = 1
    else:
        duration = int(path["travel_time_s"])
        executor_units = 0
    return Action(
        action_id=action_id,
        transaction_id=transaction_id,
        anonymous_vehicle_id=vehicle_id,
        action_type=action_type,
        status=ActionStatus.RECOMMENDED,
        origin_position_id=origin_position_id,
        destination_position_id=destination_position_id,
        destination_exit_id=destination_exit_id,
        distance_m=distance_m,
        modeled_duration_s=duration,
        executor_type=ExecutorType(str(config["executor_type"])),
        executor_units=executor_units,
        channel_zone_ids=tuple(path["channel_zone_ids"]),
        reason="deterministic online C3 recommendation",
        recommended_at_s=request.decision_time_s,
    )
