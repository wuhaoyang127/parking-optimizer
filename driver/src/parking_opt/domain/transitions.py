"""Pure, atomic event reduction for the approved stage B state machines."""
from __future__ import annotations
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any
from parking_opt.domain.enums import ActionStatus, ActionType
from parking_opt.domain.invariants import assert_state_invariants
from parking_opt.domain.records import (
    Action,
    ChannelZoneResourceState,
    ExecutorResourceState,
    PendingRequest,
    PositionReservation,
    PositionState,
    RelocationTransaction,
    ResourceLock,
    VehicleState,
)
from parking_opt.domain.state import AuthoritativeState
class StateTransitionError(ValueError):
    """Raised when a confirmed event is not legal from the current state."""
def _require(condition: bool, message: str) -> None:
    if not condition:
        raise StateTransitionError(message)
@dataclass(slots=True)
class _WorkingState:
    """Private mutable copy committed only after all checks and invariants pass."""
    source: AuthoritativeState
    vehicles: dict[str, VehicleState]
    positions: dict[str, PositionState]
    reservations: dict[str, PositionReservation]
    locks: dict[str, ResourceLock]
    actions: dict[str, Action]
    transactions: dict[str, RelocationTransaction]
    executor_resource: ExecutorResourceState
    channel_resources: dict[str, ChannelZoneResourceState]
    pending_requests: dict[str, PendingRequest]
    @classmethod
    def from_state(cls, state: AuthoritativeState) -> _WorkingState:
        return cls(
            source=state,
            vehicles={item.anonymous_vehicle_id: item for item in state.vehicles},
            positions={item.position_id: item for item in state.positions},
            reservations={item.reservation_id: item for item in state.reservations},
            locks={item.lock_id: item for item in state.locks},
            actions={item.action_id: item for item in state.actions},
            transactions={item.transaction_id: item for item in state.transactions},
            executor_resource=state.executor_resource,
            channel_resources={item.channel_zone_id: item for item in state.channel_zone_resources},
            pending_requests={item.request_id: item for item in state.pending_requests},
        )
    def freeze(self, *, sequence_no: int, sim_time_s: int) -> AuthoritativeState:
        state = replace(
            self.source,
            sequence_no=sequence_no,
            sim_time_s=sim_time_s,
            vehicles=tuple(sorted(self.vehicles.values(), key=lambda item: item.anonymous_vehicle_id)),
            positions=tuple(sorted(self.positions.values(), key=lambda item: item.position_id)),
            reservations=tuple(sorted(self.reservations.values(), key=lambda item: item.reservation_id)),
            locks=tuple(sorted(self.locks.values(), key=lambda item: item.lock_id)),
            actions=tuple(sorted(self.actions.values(), key=lambda item: item.action_id)),
            transactions=tuple(sorted(self.transactions.values(), key=lambda item: item.transaction_id)),
            executor_resource=self.executor_resource,
            channel_zone_resources=tuple(sorted(self.channel_resources.values(), key=lambda item: item.channel_zone_id)),
            pending_requests=tuple(sorted(self.pending_requests.values(), key=lambda item: (item.event_sequence_no, item.request_id))),
        )
        assert_state_invariants(state)
        return state
from parking_opt.domain.transitions_arrival import (  # noqa: E402
    _apply_arrival,
    _apply_assign_recommended,
    _apply_assignment_accepted,
    _apply_departure_requested,
    _apply_wait,
)
from parking_opt.domain.transitions_transaction import (  # noqa: E402
    _apply_transaction_created,
)
from parking_opt.domain.transitions_action import (  # noqa: E402
    _apply_action_accepted,
    _apply_action_completed,
    _apply_action_recommended,
    _apply_action_started,
    _apply_action_waiting,
)
from parking_opt.domain.transitions_failure import (  # noqa: E402
    _apply_aborted,
    _apply_action_failed_known,
    _apply_action_failed_unknown,
    _apply_position_reconciled,
    _apply_transaction_cancelled,
    _apply_transaction_reconciled,
    _apply_transaction_stage,
)
from parking_opt.domain.transitions_request import (  # noqa: E402
    _apply_information_updated,
    _apply_manual,
    _apply_reject,
    _apply_user_cancelled,
)
def apply_event(state: AuthoritativeState, event: Mapping[str, Any]) -> AuthoritativeState:
    """Atomically reduce one validated v1 event into a new immutable state."""
    _require(event["schema_version"] == "1.0.0", "unsupported event schema version")
    _require(event["run_id"] == state.run_id, "event run_id differs from state")
    _require(event["scenario_id"] == state.scenario_id, "event scenario_id differs from state")
    _require(event["sequence_no"] == state.sequence_no + 1, "event sequence_no must be exactly the next integer")
    _require(event["sim_time_s"] >= state.sim_time_s, "event time moved backwards")
    work = _WorkingState.from_state(state)
    event_type = event["event_type"]
    if event_type == "ARRIVAL_REQUESTED":
        _apply_arrival(work, event)
    elif event_type == "WAIT_DECIDED":
        _apply_wait(work, event)
    elif event_type == "ASSIGN_RECOMMENDED":
        _apply_assign_recommended(state, work, event)
    elif event_type == "ASSIGNMENT_ACCEPTED":
        _apply_assignment_accepted(state, work, event)
    elif event_type == "DEPARTURE_REQUESTED":
        _apply_departure_requested(work, event)
    elif event_type == "RELOCATION_TRANSACTION_CREATED":
        _apply_transaction_created(state, work, event)
    elif event_type == "ACTION_RECOMMENDED":
        _apply_action_recommended(state, work, event)
    elif event_type == "ACTION_ACCEPTED":
        _apply_action_accepted(work, event)
    elif event_type == "ACTION_WAITING_FOR_RESOURCES":
        _apply_action_waiting(work, event)
    elif event_type == "ACTION_STARTED":
        _apply_action_started(state, work, event)
    elif event_type == "ACTION_COMPLETED":
        _apply_action_completed(work, event)
    elif event_type == "ACTION_FAILED_KNOWN_POSITION":
        _apply_action_failed_known(work, event)
    elif event_type == "ACTION_FAILED_POSITION_UNKNOWN":
        _apply_action_failed_unknown(work, event)
    elif event_type == "ABORTED_BEFORE_START":
        _apply_aborted(work, event)
    elif event_type == "POSITION_RECONCILED":
        _apply_position_reconciled(work, event)
    elif event_type == "TRANSACTION_STAGE_ADVANCED":
        _apply_transaction_stage(work, event)
    elif event_type == "TRANSACTION_CANCELLED_BEFORE_EXECUTION":
        _apply_transaction_cancelled(work, event)
    elif event_type == "TRANSACTION_RECONCILED":
        _apply_transaction_reconciled(work, event)
    elif event_type == "REJECT_DECIDED":
        _apply_reject(work, event)
    elif event_type == "USER_CANCELLED":
        _apply_user_cancelled(work, event)
    elif event_type in {"MANUAL_INTERVENTION_REQUESTED", "MANUAL_STATUS_CHANGED"}:
        _apply_manual(work, event)
    elif event_type == "INFORMATION_UPDATED":
        _apply_information_updated(work, event)
    elif event_type in {"FALLBACK_USED", "DECISION_TIMER_TRIGGERED"}:
        pass
    else:
        raise StateTransitionError(f"unsupported event type: {event_type}")
    return work.freeze(sequence_no=event["sequence_no"], sim_time_s=event["sim_time_s"])
def replay_events(
    initial_state: AuthoritativeState,
    events: Sequence[Mapping[str, Any]],
) -> AuthoritativeState:
    """Replay an ordered event sequence with no hidden state or side effects."""
    state = initial_state
    for event in events:
        state = apply_event(state, event)
    return state
from parking_opt.domain.transitions_helpers import (  # noqa: E402
    _active_claim_owners,
    _assert_action_path,
    _assert_entry_clear,
    _metadata_by_position,
    _path_for_action,
    _path_for_nodes,
    _replace_action,
    _same_action_definition,
    _shallower_occupants,
)
from parking_opt.domain.transitions_resources import (  # noqa: E402
    _acquire_resources,
    _assert_lock_access,
    _release_resources,
    _release_transaction_protection,
    _remove_pending_for_vehicle,
    _resources_available,
)
from parking_opt.domain.transitions_action import (  # noqa: E402
    _assert_predecessors_complete,
    _fail_transaction_if_needed,
)
from parking_opt.domain.transitions_transaction import _expected_transaction_actions  # noqa: E402
