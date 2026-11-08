"""Recoverable visible driver-input projection mixin for the journey service."""

from __future__ import annotations

from parking_opt.api.models import DriverRequest
from parking_opt.api.sessions import JourneyRecord, SessionNamespace


class JourneyVisibilityMixin:
    def visible_driver_inputs(
        self, session_id: str
    ) -> list[tuple[DriverRequest, JourneyRecord]]:
        """Return the session's recoverable (driver request, journey record) pairs."""
        pairs: list[tuple[DriverRequest, JourneyRecord]] = []
        for record in self._store.session_journeys(session_id, SessionNamespace.DRIVER):
            try:
                context = self._require_context(record.journey_id)
            except ValueError:
                continue
            pairs.append((context.driver, record))
        return pairs
