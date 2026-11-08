"""Truth-event handling mixin for the deterministic engine."""

from __future__ import annotations

from parking_opt.demand.truth_store import ScheduledTruth
from parking_opt.domain.enums import ArrivalStatus, LocationKind
from parking_opt.simulation.engine_types import _DecisionTrigger


class EngineTruthMixin:
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
                in {ArrivalStatus.PENDING, ArrivalStatus.RECOMMENDED, ArrivalStatus.ADMITTED}
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

    def _request_departure_or_defer(self, truth: ScheduledTruth, time_s: int) -> None:
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
