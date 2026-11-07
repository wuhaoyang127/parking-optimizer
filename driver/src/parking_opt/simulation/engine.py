"""Deterministic discrete-event engine using only standard-library scheduling."""

from __future__ import annotations

import heapq
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from time import monotonic
from typing import Any

from parking_opt.contracts.canonical import canonical_sha256
from parking_opt.contracts.schema_validation import SchemaCatalog
from parking_opt.contracts.snapshot_projection import project_observed_snapshot
from parking_opt.demand.truth_store import ScheduledTruth, TruthStore
from parking_opt.domain.conversion import (
    action_to_mapping,
    decision_result_to_mapping,
    fallback_record_to_mapping,
    transaction_to_mapping,
)
from parking_opt.domain.enums import (
    ActionStatus,
    ActionType,
    ArrivalStatus,
    LocationKind,
    ManualStatus,
    PrimaryDecision,
    TransactionStatus,
)
from parking_opt.domain.records import (
    Action,
    DecisionRequest,
    DecisionResult,
    RelocationTransaction,
)
from parking_opt.domain.state import AuthoritativeState
from parking_opt.layout.model import Layout, layout_to_mapping
from parking_opt.layout.state_adapter import initial_state_from_layout
from parking_opt.logging.event_writer import AtomicEventLog, EventSink
from parking_opt.simulation.resources import runtime_resources_available
from parking_opt.strategies.protocol import DecisionPolicy

_BASE_RECORDED_AT = datetime(2026, 7, 28, tzinfo=UTC)


@dataclass(order=True, slots=True)
class _ScheduledItem:
    time_s: int
    priority: int
    stable_order: int
    kind: str = field(compare=False)
    payload: Any = field(compare=False)


@dataclass(frozen=True, slots=True)
class _DecisionTrigger:
    event_id: str
    event_type: str
    request_id: str | None
    vehicle_id: str | None


@dataclass(frozen=True, slots=True)
class SimulationResult:
    """Replayable C3 simulation result and its isolated decision records."""

    initial_state: AuthoritativeState
    final_state: AuthoritativeState
    events: tuple[dict[str, Any], ...]
    decisions: tuple[dict[str, Any], ...]
    event_log_path: Path | None


def approved_config_from_scenario(scenario: dict[str, Any]) -> dict[str, Any]:
    """Expand the scenario config into the frozen v1 decision configuration."""

    source = scenario["config"]
    return {
        "recoverability_policy": source["recoverability_policy"],
        "rolling_enabled": False,
        "arrival_wait_capacity": source["arrival_wait_capacity"],
        "max_arrival_wait_s": source["max_arrival_wait_s"],
        "max_departure_wait_s": source["max_departure_wait_s"],
        "use_soft_departure_information": False,
        "rolling_window_s": 900,
        "optimization_budget_s": 1.0,
        "fallback_target_s": source["fallback_target_s"],
        "minimum_logging_reserve_s": source["minimum_logging_reserve_s"],
        "max_requests_per_solve": 12,
        "max_positions_per_arrival": 8,
        "max_buffer_matchings_per_departure": 4,
        "max_action_plans_total": 64,
        "max_soft_future_records": 20,
        "buffer_count": source["buffer_count"],
        "relocation_executor_capacity": source["relocation_executor_capacity"],
        "executor_type": source["executor_type"],
        "relocation_setup_s": source["relocation_setup_s"],
        "relocation_speed_mps": source["relocation_speed_mps"],
        "active_buffer_position_ids": list(source["active_buffer_position_ids"]),
    }


class DeterministicSimulation:
    """Advance truth, confirmations, resources, policy decisions, and event logs."""

    def __init__(
        self,
        *,
        run_id: str,
        layout: Layout,
        scenario: dict[str, Any],
        policy: DecisionPolicy,
        schema_catalog: SchemaCatalog,
        event_sink: EventSink,
        event_log_path: Path | None = None,
        initial_state: AuthoritativeState | None = None,
        decision_config_overrides: Mapping[str, Any] | None = None,
        algorithm_id: str = "online-rule-v1",
        algorithm_version: str = "1.0.0",
        decision_target_s: float = 1.0,
        decision_deadline_s: float = 3.0,
    ) -> None:
        self.run_id = run_id
        self.layout = layout
        self.scenario = scenario
        self.policy = policy
        self.catalog = schema_catalog
        self.truth_store = TruthStore(scenario)
        self.config = approved_config_from_scenario(scenario)
        if decision_config_overrides is not None:
            unknown = set(decision_config_overrides) - set(self.config)
            if unknown:
                raise ValueError(f"unknown decision config overrides: {sorted(unknown)}")
            self.config.update(decision_config_overrides)
        if not algorithm_id or not algorithm_version:
            raise ValueError("algorithm ID and version must be non-empty")
        if not 0 < decision_target_s <= decision_deadline_s:
            raise ValueError("decision target must be positive and no greater than deadline")
        self.algorithm_id = algorithm_id
        self.algorithm_version = algorithm_version
        self.decision_target_s = decision_target_s
        self.decision_deadline_s = decision_deadline_s
        self.layout_mapping = layout_to_mapping(layout)
        self.layout_sha256 = canonical_sha256(self.layout_mapping)
        self.config_sha256 = canonical_sha256(self.config)
        initial = initial_state
        if initial is None:
            initial = initial_state_from_layout(
                layout,
                run_id=run_id,
                scenario_id=scenario["scenario_id"],
                active_buffer_position_ids=tuple(self.config["active_buffer_position_ids"]),
                relocation_executor_capacity=int(self.config["relocation_executor_capacity"]),
                arrival_wait_capacity=int(self.config["arrival_wait_capacity"]),
                max_arrival_wait_s=int(self.config["max_arrival_wait_s"]),
            )
        if (
            initial.run_id != run_id
            or initial.scenario_id != scenario["scenario_id"]
            or initial.layout_id != layout.layout_id
            or initial.sequence_no != 0
        ):
            raise ValueError("initial_state identifiers or sequence do not match the run")
        self.initial_state = initial
        self.event_log = AtomicEventLog(
            initial_state=initial,
            schema_catalog=schema_catalog,
            sink=event_sink,
        )
        self.event_log_path = event_log_path
        self._queue: list[_ScheduledItem] = []
        self._order = 0
        self._decision_counter = 0
        self._decisions: list[dict[str, Any]] = []
        self._waiting_action_ids: set[str] = set()
        self._scheduled_timers: set[tuple[str, str]] = set()
        self._deferred_departures: dict[str, ScheduledTruth] = {}
        for truth in self.truth_store.scheduled_items():
            self._schedule(truth.event_time_s, 20, "truth", truth)

    @property
    def state(self) -> AuthoritativeState:
        return self.event_log.state

    def _schedule(self, time_s: int, priority: int, kind: str, payload: Any) -> None:
        self._order += 1
        heapq.heappush(
            self._queue,
            _ScheduledItem(
                time_s=time_s,
                priority=priority,
                stable_order=self._order,
                kind=kind,
                payload=payload,
            ),
        )

    def _recorded_at(self, sim_time_s: int) -> str:
        return (_BASE_RECORDED_AT + timedelta(seconds=sim_time_s)).isoformat()

    def _emit(
        self,
        *,
        time_s: int,
        event_type: str,
        vehicle_id: str | None,
        action: Action | None = None,
        transaction_id: str | None = None,
        transaction: RelocationTransaction | None = None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        sequence = self.state.sequence_no + 1
        event = {
            "schema_version": "1.0.0",
            "event_id": f"{self.run_id}-event-{sequence:06d}",
            "run_id": self.run_id,
            "scenario_id": self.scenario["scenario_id"],
            "sequence_no": sequence,
            "sim_time_s": time_s,
            "recorded_at": self._recorded_at(time_s),
            "event_type": event_type,
            "anonymous_vehicle_id": vehicle_id,
            "action": action_to_mapping(action) if action is not None else None,
            "transaction_id": transaction_id,
            "transaction": (
                transaction_to_mapping(transaction) if transaction is not None else None
            ),
            "payload": payload or {},
        }
        self.event_log.append(event)
        return event

    def _enqueue_decision(
        self,
        *,
        time_s: int,
        trigger: _DecisionTrigger,
    ) -> None:
        self._schedule(time_s, 50, "decision", trigger)

    def _handle_truth(self, truth: ScheduledTruth, time_s: int) -> None:
        if truth.kind == "ARRIVAL_REQUESTED":
            event = self._emit(
                time_s=time_s,
                event_type="ARRIVAL_REQUESTED",
                vehicle_id=truth.payload["anonymous_vehicle_id"],
                payload={
                    "pending_request": {
                        "request_id": truth.payload["request_id"],
                        "anonymous_vehicle_id": truth.payload["anonymous_vehicle_id"],
                        "request_type": "ARRIVAL",
                        "requested_at_s": time_s,
                        "event_sequence_no": self.state.sequence_no + 1,
                        "entrance_node_id": truth.payload["entrance_node_id"],
                    }
                },
            )
            self._enqueue_decision(
                time_s=time_s,
                trigger=_DecisionTrigger(
                    event_id=event["event_id"],
                    event_type=event["event_type"],
                    request_id=truth.payload["request_id"],
                    vehicle_id=truth.payload["anonymous_vehicle_id"],
                ),
            )
            return
        if truth.kind == "DEPARTURE_REQUEST":
            self._request_departure_or_defer(truth, time_s)
            return
        if truth.kind == "USER_CANCELLED":
            vehicle = next(
                (
                    item
                    for item in self.state.vehicles
                    if item.anonymous_vehicle_id == truth.payload["anonymous_vehicle_id"]
                ),
                None,
            )
            if (
                vehicle is not None
                and vehicle.arrival_status
                in {
                    ArrivalStatus.PENDING,
                    ArrivalStatus.RECOMMENDED,
                    ArrivalStatus.ADMITTED,
                }
                and vehicle.location_state.kind is LocationKind.ENTRY_QUEUE
            ):
                self._emit(
                    time_s=time_s,
                    event_type="USER_CANCELLED",
                    vehicle_id=vehicle.anonymous_vehicle_id,
                    payload={"request_id": f"cancel-{truth.stable_id}"},
                )
            return
        if truth.kind == "INFORMATION_UPDATED":
            self._emit(
                time_s=time_s,
                event_type="INFORMATION_UPDATED",
                vehicle_id=truth.payload["anonymous_vehicle_id"],
                payload={
                    "departure_information": truth.payload["departure_information"],
                    "reservation_status": truth.payload["reservation_status"],
                },
            )

    def _request_departure_or_defer(
        self,
        truth: ScheduledTruth,
        time_s: int,
    ) -> None:
        vehicle_id = truth.payload["anonymous_vehicle_id"]
        vehicle = next(
            (item for item in self.state.vehicles if item.anonymous_vehicle_id == vehicle_id),
            None,
        )
        if vehicle is None:
            self._deferred_departures[vehicle_id] = truth
            return
        if vehicle.location_state.kind in {LocationKind.REJECTED, LocationKind.EXITED}:
            self._deferred_departures.pop(vehicle_id, None)
            return
        if vehicle.location_state.kind is not LocationKind.AT_POSITION:
            self._deferred_departures[vehicle_id] = truth
            return
        position_id = vehicle.location_state.position_id
        position = next(item for item in self.state.positions if item.position_id == position_id)
        if position.position_kind.value != "normal":
            self._deferred_departures[vehicle_id] = truth
            return
        if vehicle.departure_status.value != "NONE":
            return
        request_id = f"departure-{truth.stable_id}"
        event = self._emit(
            time_s=time_s,
            event_type="DEPARTURE_REQUESTED",
            vehicle_id=vehicle_id,
            payload={
                "pending_request": {
                    "request_id": request_id,
                    "anonymous_vehicle_id": vehicle_id,
                    "request_type": "DEPARTURE",
                    "requested_at_s": truth.event_time_s,
                    "event_sequence_no": self.state.sequence_no + 1,
                    "entrance_node_id": None,
                }
            },
        )
        self._deferred_departures.pop(vehicle_id, None)
        self._enqueue_decision(
            time_s=time_s,
            trigger=_DecisionTrigger(
                event_id=event["event_id"],
                event_type=event["event_type"],
                request_id=request_id,
                vehicle_id=vehicle_id,
            ),
        )
        deadline = truth.event_time_s + int(self.config["max_departure_wait_s"])
        key = ("DEPARTURE_SLA_DEADLINE", request_id)
        if deadline <= int(self.scenario["drain_deadline_s"]) and key not in self._scheduled_timers:
            self._scheduled_timers.add(key)
            self._schedule(deadline, 30, "timer", key)

    def _build_request(
        self,
        *,
        time_s: int,
        trigger: _DecisionTrigger,
    ) -> DecisionRequest | None:
        if not self.state.pending_requests:
            return None
        if trigger.event_type == "ARRIVAL_REQUESTED" and not any(
            item.request_id == trigger.request_id for item in self.state.pending_requests
        ):
            return None
        self._decision_counter += 1
        snapshot = project_observed_snapshot(
            self.state,
            snapshot_id=f"{self.run_id}-snapshot-{self._decision_counter:06d}",
            decision_time_s=time_s,
        )
        return DecisionRequest(
            request_id=f"{self.run_id}-decision-request-{self._decision_counter:06d}",
            algorithm_id=self.algorithm_id,
            algorithm_version=self.algorithm_version,
            trigger_event_id=trigger.event_id,
            trigger_event_type=trigger.event_type,
            trigger_request_id=trigger.request_id,
            trigger_anonymous_vehicle_id=trigger.vehicle_id,
            decision_time_s=time_s,
            layout=self.layout_mapping,
            approved_config=self.config,
            observed_snapshot=snapshot,
            config_sha256=self.config_sha256,
            layout_sha256=self.layout_sha256,
            visible_snapshot_sha256=snapshot.snapshot_content_sha256,
            decision_target_s=self.decision_target_s,
            decision_deadline_s=self.decision_deadline_s,
        )

    def _handle_decision(self, trigger: _DecisionTrigger, time_s: int) -> None:
        cycle_started = monotonic()
        request = self._build_request(time_s=time_s, trigger=trigger)
        if request is None:
            return
        result = self.policy.decide(request)
        result_mapping = decision_result_to_mapping(result)
        self.catalog.validate("decision.schema.json", result_mapping)
        if result.fallback_record is not None:
            self._emit(
                time_s=time_s,
                event_type="FALLBACK_USED",
                vehicle_id=result.target_anonymous_vehicle_id,
                payload={
                    "decision_id": result.decision_id,
                    "fallback_record": fallback_record_to_mapping(result.fallback_record),
                },
            )
        self._apply_result(result, time_s)
        cycle_elapsed = max(0.0, monotonic() - cycle_started)
        result = replace(
            result,
            timing=replace(result.timing, end_to_end_s=cycle_elapsed),
        )
        result_mapping = decision_result_to_mapping(result)
        self.catalog.validate("decision.schema.json", result_mapping)
        self._decisions.append(result_mapping)

    def _apply_result(self, result: DecisionResult, time_s: int) -> None:
        if result.primary_decision is PrimaryDecision.WAIT:
            target = next(
                (
                    item
                    for item in self.state.pending_requests
                    if item.request_id == result.target_request_id
                ),
                None,
            )
            if target is not None and target.request_type == "ARRIVAL":
                self._emit(
                    time_s=time_s,
                    event_type="WAIT_DECIDED",
                    vehicle_id=result.target_anonymous_vehicle_id,
                    payload={
                        "request_id": result.target_request_id,
                        "decision_id": result.decision_id,
                    },
                )
                deadline = target.requested_at_s + int(self.config["max_arrival_wait_s"])
                key = ("ARRIVAL_WAIT_DEADLINE", target.request_id)
                if (
                    deadline <= int(self.scenario["drain_deadline_s"])
                    and key not in self._scheduled_timers
                ):
                    self._scheduled_timers.add(key)
                    self._schedule(deadline, 30, "timer", key)
            return
        if result.primary_decision is PrimaryDecision.REJECT:
            self._emit(
                time_s=time_s,
                event_type="REJECT_DECIDED",
                vehicle_id=result.target_anonymous_vehicle_id,
                payload={
                    "request_id": result.target_request_id,
                    "decision_id": result.decision_id,
                },
            )
            self._deferred_departures.pop(result.target_anonymous_vehicle_id, None)
            return
        if result.primary_decision is PrimaryDecision.REQUEST_MANUAL_INTERVENTION:
            vehicle = next(
                item
                for item in self.state.vehicles
                if item.anonymous_vehicle_id == result.target_anonymous_vehicle_id
            )
            if vehicle.manual_status in {ManualStatus.NONE, ManualStatus.FAILED}:
                self._emit(
                    time_s=time_s,
                    event_type="MANUAL_INTERVENTION_REQUESTED",
                    vehicle_id=result.target_anonymous_vehicle_id,
                    payload={
                        "request_id": result.target_request_id,
                        "decision_id": result.decision_id,
                        "reason": ",".join(result.explanation_codes),
                    },
                )
            return
        if result.candidate_transaction is not None:
            self._accept_transaction(result, time_s)
        else:
            self._accept_single_action(result.recommended_actions[0], result.decision_id, time_s)

    def _accept_single_action(
        self,
        action: Action,
        decision_id: str,
        time_s: int,
    ) -> None:
        if action.action_type is ActionType.ASSIGN:
            self._emit(
                time_s=time_s,
                event_type="ASSIGN_RECOMMENDED",
                vehicle_id=action.anonymous_vehicle_id,
                action=action,
                payload={"decision_id": decision_id},
            )
            accepted = replace(
                action,
                status=ActionStatus.ACCEPTED,
                accepted_at_s=time_s,
            )
            self._emit(
                time_s=time_s,
                event_type="ASSIGNMENT_ACCEPTED",
                vehicle_id=action.anonymous_vehicle_id,
                action=accepted,
                payload={
                    "decision_id": decision_id,
                    "created_reservations": [
                        {
                            "reservation_id": f"reservation-{action.action_id}",
                            "position_id": action.destination_position_id,
                            "owner_vehicle_id": action.anonymous_vehicle_id,
                            "transaction_id": None,
                            "purpose": "admitted_assignment",
                            "created_at_s": time_s,
                        }
                    ],
                },
            )
            self._start_or_wait(action.action_id, time_s)
            return
        self._emit(
            time_s=time_s,
            event_type="ACTION_RECOMMENDED",
            vehicle_id=action.anonymous_vehicle_id,
            action=action,
            transaction_id=action.transaction_id,
            payload={"decision_id": decision_id},
        )
        accepted = replace(action, status=ActionStatus.ACCEPTED, accepted_at_s=time_s)
        self._emit(
            time_s=time_s,
            event_type="ACTION_ACCEPTED",
            vehicle_id=action.anonymous_vehicle_id,
            action=accepted,
            transaction_id=action.transaction_id,
            payload={"decision_id": decision_id},
        )
        self._start_or_wait(action.action_id, time_s)

    def _accept_transaction(self, result: DecisionResult, time_s: int) -> None:
        proposed = result.candidate_transaction
        assert proposed is not None
        accepted_actions = tuple(
            replace(item, status=ActionStatus.ACCEPTED, accepted_at_s=time_s)
            for item in result.recommended_actions
        )
        reserved = replace(
            proposed,
            status=TransactionStatus.RESERVED,
            created_at_s=time_s,
        )
        reservations = [
            record
            for assignment in proposed.buffer_assignments
            for record in (
                {
                    "reservation_id": (
                        f"{proposed.transaction_id}-reserve-buffer-{assignment.blocker_vehicle_id}"
                    ),
                    "position_id": assignment.buffer_position_id,
                    "owner_vehicle_id": assignment.blocker_vehicle_id,
                    "transaction_id": proposed.transaction_id,
                    "purpose": "buffer_destination",
                    "created_at_s": time_s,
                },
                {
                    "reservation_id": (
                        f"{proposed.transaction_id}-reserve-original-"
                        f"{assignment.blocker_vehicle_id}"
                    ),
                    "position_id": assignment.original_position_id,
                    "owner_vehicle_id": assignment.blocker_vehicle_id,
                    "transaction_id": proposed.transaction_id,
                    "purpose": "restore_original",
                    "created_at_s": time_s,
                },
            )
        ]
        target = next(
            item
            for item in self.state.vehicles
            if item.anonymous_vehicle_id == proposed.target_vehicle_id
        )
        assert target.location_state.position_id is not None
        target_slot = next(
            item
            for item in self.layout.slots
            if item.position_id == target.location_state.position_id
        )
        lock_resources = [
            ("vehicle", proposed.target_vehicle_id),
            *(("vehicle", item) for item in proposed.blocker_vehicle_ids),
            ("stack_group", target_slot.stack_group_id),
        ]
        locks = [
            {
                "lock_id": (f"{proposed.transaction_id}-lock-{resource_type}-{resource_id}"),
                "resource_type": resource_type,
                "resource_id": resource_id,
                "transaction_id": proposed.transaction_id,
                "created_at_s": time_s,
            }
            for resource_type, resource_id in lock_resources
        ]
        self._emit(
            time_s=time_s,
            event_type="RELOCATION_TRANSACTION_CREATED",
            vehicle_id=None,
            transaction_id=proposed.transaction_id,
            transaction=reserved,
            payload={
                "decision_id": result.decision_id,
                "transaction_actions": [action_to_mapping(item) for item in accepted_actions],
                "created_reservations": reservations,
                "created_locks": locks,
            },
        )
        moving = replace(reserved, status=TransactionStatus.MOVING_BLOCKERS_OUT)
        self._emit(
            time_s=time_s,
            event_type="TRANSACTION_STAGE_ADVANCED",
            vehicle_id=None,
            transaction_id=proposed.transaction_id,
            transaction=moving,
        )
        self._start_ready_transaction_action(proposed.transaction_id, time_s)

    def _start_or_wait(self, action_id: str, time_s: int) -> None:
        action = next(item for item in self.state.actions if item.action_id == action_id)
        if runtime_resources_available(self.state, action):
            started = replace(
                action,
                status=ActionStatus.STARTED,
                accepted_at_s=action.accepted_at_s or time_s,
                started_at_s=time_s,
            )
            self._emit(
                time_s=time_s,
                event_type="ACTION_STARTED",
                vehicle_id=action.anonymous_vehicle_id,
                action=started,
                transaction_id=action.transaction_id,
            )
            self._waiting_action_ids.discard(action_id)
            self._schedule(
                time_s + action.modeled_duration_s,
                0,
                "action_complete",
                action_id,
            )
            return
        if action.status is ActionStatus.ACCEPTED:
            waiting = replace(
                action,
                status=ActionStatus.WAITING_FOR_RESOURCES,
                accepted_at_s=action.accepted_at_s or time_s,
            )
            self._emit(
                time_s=time_s,
                event_type="ACTION_WAITING_FOR_RESOURCES",
                vehicle_id=action.anonymous_vehicle_id,
                action=waiting,
                transaction_id=action.transaction_id,
            )
        self._waiting_action_ids.add(action_id)

    def _handle_action_complete(self, action_id: str, time_s: int) -> None:
        action = next(item for item in self.state.actions if item.action_id == action_id)
        if action.status is not ActionStatus.STARTED:
            return
        completed = replace(
            action,
            status=ActionStatus.COMPLETED,
            ended_at_s=time_s,
        )
        event = self._emit(
            time_s=time_s,
            event_type="ACTION_COMPLETED",
            vehicle_id=action.anonymous_vehicle_id,
            action=completed,
            transaction_id=action.transaction_id,
        )
        if action.transaction_id is not None:
            self._advance_transaction(action.transaction_id, time_s)
        else:
            self._try_deferred_departure(action.anonymous_vehicle_id, time_s)
            if self.state.pending_requests:
                self._enqueue_decision(
                    time_s=time_s,
                    trigger=_DecisionTrigger(
                        event_id=event["event_id"],
                        event_type="ACTION_COMPLETED",
                        request_id=None,
                        vehicle_id=None,
                    ),
                )
        self._retry_waiting_actions(time_s)

    def _advance_transaction(self, transaction_id: str, time_s: int) -> None:
        transaction = next(
            item for item in self.state.transactions if item.transaction_id == transaction_id
        )
        actions = {
            item.action_id: item
            for item in self.state.actions
            if item.transaction_id == transaction_id
        }
        next_status: TransactionStatus | None = None
        if transaction.status is TransactionStatus.MOVING_BLOCKERS_OUT and all(
            item.status is ActionStatus.COMPLETED
            for item in actions.values()
            if item.action_type is ActionType.RELOCATE_TO_BUFFER
        ):
            next_status = TransactionStatus.TARGET_EXITING
        elif transaction.status is TransactionStatus.TARGET_EXITING and all(
            item.status is ActionStatus.COMPLETED
            for item in actions.values()
            if item.action_type is ActionType.DIRECT_EXIT
        ):
            next_status = TransactionStatus.RESTORING_ORIGINALS
        elif transaction.status is TransactionStatus.RESTORING_ORIGINALS and all(
            item.status is ActionStatus.COMPLETED
            for item in actions.values()
            if item.action_type is ActionType.RESTORE_ORIGINAL
        ):
            next_status = TransactionStatus.COMPLETED
        if next_status is not None:
            incoming = replace(
                transaction,
                status=next_status,
                ended_at_s=time_s if next_status is TransactionStatus.COMPLETED else None,
            )
            event = self._emit(
                time_s=time_s,
                event_type="TRANSACTION_STAGE_ADVANCED",
                vehicle_id=None,
                transaction_id=transaction_id,
                transaction=incoming,
            )
            if next_status is TransactionStatus.COMPLETED:
                for vehicle_id in (
                    transaction.target_vehicle_id,
                    *transaction.blocker_vehicle_ids,
                ):
                    self._try_deferred_departure(vehicle_id, time_s)
                if self.state.pending_requests:
                    self._enqueue_decision(
                        time_s=time_s,
                        trigger=_DecisionTrigger(
                            event_id=event["event_id"],
                            event_type="TRANSACTION_STAGE_ADVANCED",
                            request_id=None,
                            vehicle_id=None,
                        ),
                    )
                return
        self._start_ready_transaction_action(transaction_id, time_s)

    def _start_ready_transaction_action(self, transaction_id: str, time_s: int) -> None:
        transaction = next(
            item for item in self.state.transactions if item.transaction_id == transaction_id
        )
        actions = {item.action_id: item for item in self.state.actions}
        allowed_types = {
            TransactionStatus.MOVING_BLOCKERS_OUT: {ActionType.RELOCATE_TO_BUFFER},
            TransactionStatus.TARGET_EXITING: {ActionType.DIRECT_EXIT},
            TransactionStatus.RESTORING_ORIGINALS: {ActionType.RESTORE_ORIGINAL},
        }.get(transaction.status, set())
        for action_id in transaction.action_ids:
            action = actions[action_id]
            if action.action_type not in allowed_types or action.status not in {
                ActionStatus.ACCEPTED,
                ActionStatus.WAITING_FOR_RESOURCES,
            }:
                continue
            predecessors = {
                edge.before_action_id
                for edge in transaction.precedence_edges
                if edge.after_action_id == action_id
            }
            if all(actions[item].status is ActionStatus.COMPLETED for item in predecessors):
                self._start_or_wait(action_id, time_s)
                return

    def _retry_waiting_actions(self, time_s: int) -> None:
        for action_id in sorted(tuple(self._waiting_action_ids)):
            action = next(
                (item for item in self.state.actions if item.action_id == action_id),
                None,
            )
            if action is None or action.status not in {
                ActionStatus.ACCEPTED,
                ActionStatus.WAITING_FOR_RESOURCES,
            }:
                self._waiting_action_ids.discard(action_id)
                continue
            if action.transaction_id is not None:
                transaction = next(
                    item
                    for item in self.state.transactions
                    if item.transaction_id == action.transaction_id
                )
                predecessors = {
                    edge.before_action_id
                    for edge in transaction.precedence_edges
                    if edge.after_action_id == action_id
                }
                actions = {item.action_id: item for item in self.state.actions}
                if not all(actions[item].status is ActionStatus.COMPLETED for item in predecessors):
                    continue
            if runtime_resources_available(self.state, action):
                self._start_or_wait(action_id, time_s)

    def _try_deferred_departure(self, vehicle_id: str, time_s: int) -> None:
        truth = self._deferred_departures.get(vehicle_id)
        if truth is not None:
            self._request_departure_or_defer(truth, time_s)

    def _handle_timer(self, key: tuple[str, str], time_s: int) -> None:
        reason, request_id = key
        if not any(item.request_id == request_id for item in self.state.pending_requests):
            return
        event = self._emit(
            time_s=time_s,
            event_type="DECISION_TIMER_TRIGGERED",
            vehicle_id=None,
            payload={"timer_reason": reason},
        )
        self._enqueue_decision(
            time_s=time_s,
            trigger=_DecisionTrigger(
                event_id=event["event_id"],
                event_type=event["event_type"],
                request_id=None,
                vehicle_id=None,
            ),
        )

    def run(self) -> SimulationResult:
        """Run every scheduled item through the fixed drain deadline."""

        drain_deadline = int(self.scenario["drain_deadline_s"])
        while self._queue:
            item = heapq.heappop(self._queue)
            if item.time_s > drain_deadline:
                break
            if item.kind == "truth":
                self._handle_truth(item.payload, item.time_s)
            elif item.kind == "decision":
                self._handle_decision(item.payload, item.time_s)
            elif item.kind == "action_complete":
                self._handle_action_complete(item.payload, item.time_s)
            elif item.kind == "timer":
                self._handle_timer(item.payload, item.time_s)
            else:
                raise RuntimeError(f"unknown simulation schedule kind: {item.kind}")
        return SimulationResult(
            initial_state=self.initial_state,
            final_state=self.state,
            events=self.event_log.events,
            decisions=tuple(self._decisions),
            event_log_path=self.event_log_path,
        )
