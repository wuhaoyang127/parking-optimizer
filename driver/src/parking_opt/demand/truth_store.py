"""Simulation-only future truth store with no strategy import path."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class ScheduledTruth:
    """One future truth item ordered without exposing it to a policy."""

    event_time_s: int
    kind: str
    stable_id: str
    payload: dict[str, Any]


class TruthStore:
    """Own the complete scenario truth only on the simulation side."""

    def __init__(self, scenario: dict[str, Any]) -> None:
        items: list[ScheduledTruth] = []
        for request in scenario["vehicle_requests"]:
            items.append(
                ScheduledTruth(
                    event_time_s=request["arrival_time_s"],
                    kind="ARRIVAL_REQUESTED",
                    stable_id=request["request_id"],
                    payload=dict(request),
                )
            )
        for event in scenario["truth_events"]:
            items.append(
                ScheduledTruth(
                    event_time_s=event["event_time_s"],
                    kind=event["event_kind"],
                    stable_id=event["truth_event_id"],
                    payload=dict(event),
                )
            )
        for update in scenario["information_updates"]:
            items.append(
                ScheduledTruth(
                    event_time_s=update["departure_information"]["known_at_time_s"],
                    kind="INFORMATION_UPDATED",
                    stable_id=update["information_update_id"],
                    payload=dict(update),
                )
            )
        self._items = tuple(
            sorted(
                items,
                key=lambda item: (item.event_time_s, item.kind, item.stable_id),
            )
        )

    def scheduled_items(self) -> tuple[ScheduledTruth, ...]:
        """Return truth only to the simulation engine."""

        return self._items
