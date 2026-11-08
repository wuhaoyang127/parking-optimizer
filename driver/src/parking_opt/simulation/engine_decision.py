"""Decision handling and acceptance mixin for the deterministic engine."""
from __future__ import annotations
from dataclasses import replace
from time import monotonic
from parking_opt.domain.conversion import (
    action_to_mapping,
    decision_result_to_mapping,
    fallback_record_to_mapping,
)
from parking_opt.domain.enums import ActionStatus, ActionType, ManualStatus, PrimaryDecision, TransactionStatus
from parking_opt.domain.records import Action, DecisionResult
from parking_opt.simulation.engine_types import _DecisionTrigger
class EngineDecisionMixin:
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
        result = replace(result, timing=replace(result.timing, end_to_end_s=cycle_elapsed))
        result_mapping = decision_result_to_mapping(result)
        self.catalog.validate("decision.schema.json", result_mapping)
        self._decisions.append(result_mapping)
    def _apply_result(self, result: DecisionResult, time_s: int) -> None:
        if result.primary_decision is PrimaryDecision.WAIT:
            target = next(
                (item for item in self.state.pending_requests if item.request_id == result.target_request_id),
                None,
            )
            if target is not None and target.request_type == "ARRIVAL":
                self._emit(
                    time_s=time_s,
                    event_type="WAIT_DECIDED",
                    vehicle_id=result.target_anonymous_vehicle_id,
                    payload={"request_id": result.target_request_id, "decision_id": result.decision_id},
                )
                deadline = target.requested_at_s + int(self.config["max_arrival_wait_s"])
                key = ("ARRIVAL_WAIT_DEADLINE", target.request_id)
                if deadline <= int(self.scenario["drain_deadline_s"]) and key not in self._scheduled_timers:
                    self._scheduled_timers.add(key)
                    self._schedule(deadline, 30, "timer", key)
            return
        if result.primary_decision is PrimaryDecision.REJECT:
            self._emit(
                time_s=time_s,
                event_type="REJECT_DECIDED",
                vehicle_id=result.target_anonymous_vehicle_id,
                payload={"request_id": result.target_request_id, "decision_id": result.decision_id},
            )
            self._deferred_departures.pop(result.target_anonymous_vehicle_id, None)
            return
        if result.primary_decision is PrimaryDecision.REQUEST_MANUAL_INTERVENTION:
            vehicle = next(
                item for item in self.state.vehicles if item.anonymous_vehicle_id == result.target_anonymous_vehicle_id
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
    def _accept_single_action(self, action: Action, decision_id: str, time_s: int) -> None:
        if action.action_type is ActionType.ASSIGN:
            self._emit(time_s=time_s, event_type="ASSIGN_RECOMMENDED", vehicle_id=action.anonymous_vehicle_id, action=action, payload={"decision_id": decision_id})
            accepted = replace(action, status=ActionStatus.ACCEPTED, accepted_at_s=time_s)
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
        self._emit(time_s=time_s, event_type="ACTION_RECOMMENDED", vehicle_id=action.anonymous_vehicle_id, action=action, transaction_id=action.transaction_id, payload={"decision_id": decision_id})
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
        reserved = replace(proposed, status=TransactionStatus.RESERVED, created_at_s=time_s)
        reservations = [
            record
            for assignment in proposed.buffer_assignments
            for record in (
                {
                    "reservation_id": f"{proposed.transaction_id}-reserve-buffer-{assignment.blocker_vehicle_id}",
                    "position_id": assignment.buffer_position_id,
                    "owner_vehicle_id": assignment.blocker_vehicle_id,
                    "transaction_id": proposed.transaction_id,
                    "purpose": "buffer_destination",
                    "created_at_s": time_s,
                },
                {
                    "reservation_id": f"{proposed.transaction_id}-reserve-original-{assignment.blocker_vehicle_id}",
                    "position_id": assignment.original_position_id,
                    "owner_vehicle_id": assignment.blocker_vehicle_id,
                    "transaction_id": proposed.transaction_id,
                    "purpose": "restore_original",
                    "created_at_s": time_s,
                },
            )
        ]
        target = next(
            item for item in self.state.vehicles if item.anonymous_vehicle_id == proposed.target_vehicle_id
        )
        assert target.location_state.position_id is not None
        target_slot = next(
            item for item in self.layout.slots if item.position_id == target.location_state.position_id
        )
        lock_resources = [
            ("vehicle", proposed.target_vehicle_id),
            *(("vehicle", item) for item in proposed.blocker_vehicle_ids),
            ("stack_group", target_slot.stack_group_id),
        ]
        locks = [
            {
                "lock_id": f"{proposed.transaction_id}-lock-{resource_type}-{resource_id}",
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
