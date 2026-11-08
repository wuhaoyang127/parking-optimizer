"""Transaction and action lifecycle mixin for the deterministic engine."""

from __future__ import annotations

from dataclasses import replace

from parking_opt.domain.enums import ActionStatus, ActionType, TransactionStatus
from parking_opt.simulation.engine_types import _DecisionTrigger
from parking_opt.simulation.resources import runtime_resources_available


class EngineTransactionMixin:
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
            self._schedule(time_s + action.modeled_duration_s, 0, "action_complete", action_id)
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
        completed = replace(action, status=ActionStatus.COMPLETED, ended_at_s=time_s)
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
            item.action_id: item for item in self.state.actions if item.transaction_id == transaction_id
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
                for vehicle_id in (transaction.target_vehicle_id, *transaction.blocker_vehicle_ids):
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
            action = next((item for item in self.state.actions if item.action_id == action_id), None)
            if action is None or action.status not in {ActionStatus.ACCEPTED, ActionStatus.WAITING_FOR_RESOURCES}:
                self._waiting_action_ids.discard(action_id)
                continue
            if action.transaction_id is not None:
                transaction = next(
                    item for item in self.state.transactions if item.transaction_id == action.transaction_id
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
