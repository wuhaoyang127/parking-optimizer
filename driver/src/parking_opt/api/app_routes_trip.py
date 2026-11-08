"""Current-trip snapshot route for web-v2."""

from __future__ import annotations

from typing import Literal

from fastapi import FastAPI, Request, Response

from parking_opt.api.app_contracts import ERROR_RESPONSES, RequiredSessionIdHeader
from parking_opt.api.models import (
    DriverTandemArrivalReplay,
    DriverTandemDepartureReplay,
    DriverTripEvent,
    DriverTripRecord,
    DriverTripSnapshot,
)
from parking_opt.api.services.journey import journey_to_contract
from parking_opt.api.sessions import InMemorySessionStore, SessionNamespace


def register_trip_routes(app: FastAPI) -> None:
    @app.get(
        "/api/v2/driver-session/current-trip",
        response_model=DriverTripSnapshot,
        responses={422: ERROR_RESPONSES[422]},
        tags=["journeys"],
    )
    def current_driver_trip(
        request: Request,
        response: Response,
        session_id: RequiredSessionIdHeader,
    ) -> DriverTripSnapshot:
        response.headers["Cache-Control"] = "no-store"
        store: InMemorySessionStore = request.app.state.session_store
        with store.atomic():
            recovery = request.app.state.journey_service.current_driver_recovery(session_id)
            if recovery is None:
                return DriverTripSnapshot(observed_at=store.current_wall_time())
            record = recovery.result.journey
            stored_arrival_replay = store.tandem_arrival_replay(record.journey_id)
            if stored_arrival_replay is not None and not isinstance(stored_arrival_replay, DriverTandemArrivalReplay):
                raise RuntimeError("stored tandem arrival replay has an invalid type")
            stored_replay = store.tandem_departure_replay(record.journey_id)
            if stored_replay is not None and not isinstance(stored_replay, DriverTandemDepartureReplay):
                raise RuntimeError("stored tandem departure replay has an invalid type")
            navigation = request.app.state.replan_service.recover_navigation(record.journey_id)
            all_events = store.events()
            events = tuple(item for item in all_events if item.journey_id == record.journey_id)

            def lifecycle_times(journey_id: str):  # type: ignore[no-untyped-def]
                scoped = tuple(item for item in all_events if item.journey_id == journey_id)
                started_at = next((item.wall_time for item in scoped if item.event_type == "NAVIGATING"), None)
                parked_at = next((item.wall_time for item in scoped if item.event_type == "OCCUPIED"), None)
                ended_at = next((item.wall_time for item in reversed(scoped) if item.event_type in {"DEPARTED", "FAILED", "CANCELLED", "EXPIRED"}), None)
                return started_at, parked_at, ended_at

            started, parked, ended = lifecycle_times(record.journey_id)
            route_visible = record.state.value in {"session_reserved", "navigating"}
            recent_trips = []
            record_states: dict[str, Literal["occupied", "departed", "cancelled", "expired", "failed"]] = {
                "occupied": "occupied",
                "departed": "departed",
                "cancelled": "cancelled",
                "expired": "expired",
                "failed": "failed",
            }
            for item in store.session_journeys(session_id, SessionNamespace.DRIVER):
                record_state = record_states.get(item.state.value)
                if record_state is None:
                    continue
                item_started, item_parked, item_ended = lifecycle_times(item.journey_id)
                recent_trips.append(
                    DriverTripRecord(
                        journey_id=item.journey_id,
                        parking_lot_id=item.parking_lot_id,
                        space_id=item.space_id,
                        state=record_state,
                        started_at=item_started,
                        parked_at=item_parked,
                        ended_at=item_ended,
                        terminal_reason=item.terminal_reason,
                    )
                )
            return DriverTripSnapshot(
                observed_at=recovery.observed_at,
                journey=journey_to_contract(record, recommendation_id=recovery.result.recommendation.recommendation_id),
                driver=recovery.driver,
                current_route=(navigation.current_route if route_visible and navigation is not None else None),
                current_node_id=(navigation.current_node_id if route_visible and navigation is not None else None),
                last_replan=(navigation.last_replan if route_visible and navigation is not None else None),
                started_at=started,
                parked_at=parked,
                ended_at=ended,
                recent_events=tuple(
                    DriverTripEvent(sequence_no=item.sequence_no, event_type=item.event_type, reason_code=item.reason_code, occurred_at=item.wall_time)
                    for item in events[-8:]
                ),
                recent_trips=tuple(recent_trips[:5]),
                tandem_arrival_replay_enabled=request.app.state.driver_tandem_arrival_replay_enabled,
                tandem_arrival_replay=(stored_arrival_replay if isinstance(stored_arrival_replay, DriverTandemArrivalReplay) else None),
                tandem_departure_replay_enabled=request.app.state.driver_tandem_departure_replay_enabled,
                tandem_departure_replay=(stored_replay if isinstance(stored_replay, DriverTandemDepartureReplay) else None),
            )
