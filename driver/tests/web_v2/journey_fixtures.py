from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from parking_opt.api.adapters.v1 import V1OnlineRuleAdapter
from parking_opt.api.models import DriverRequest
from parking_opt.api.routing import RouteCostService
from parking_opt.api.services.journey import JourneyRecommendationService
from parking_opt.api.services.online_rule import OnlineRuleServiceV2
from parking_opt.api.sessions import InMemorySessionStore, SessionTiming

REPO_ROOT = Path(__file__).resolve().parents[2]


def _store() -> InMemorySessionStore:
    return InMemorySessionStore(
        timing=SessionTiming(
            driver_idle_ttl_s=1800,
            defense_idle_ttl_s=7200,
            soft_hold_ttl_s=30,
            driver_reservation_ttl_s=300,
            defense_reservation_ttl_s=60,
        )
    )


def _clocked_store() -> tuple[InMemorySessionStore, list[float]]:
    elapsed = [0.0]
    origin = datetime(2026, 8, 13, tzinfo=UTC)
    return (
        InMemorySessionStore(
            timing=SessionTiming(
                driver_idle_ttl_s=1800,
                defense_idle_ttl_s=7200,
                soft_hold_ttl_s=30,
                driver_reservation_ttl_s=300,
                defense_reservation_ttl_s=60,
            ),
            monotonic_clock=lambda: elapsed[0],
            utc_clock=lambda: origin + timedelta(seconds=elapsed[0]),
        ),
        elapsed,
    )


def _service(store: InMemorySessionStore) -> JourneyRecommendationService:
    routes = RouteCostService()
    online = OnlineRuleServiceV2(
        v1_adapter=V1OnlineRuleAdapter(schema_dir=REPO_ROOT / "schemas" / "v1", route_service=routes),
        route_service=routes,
    )
    return JourneyRecommendationService(
        online_rule=online,
        route_service=routes,
        session_store=store,
        eta_safety_margin_s=60,
        driver_reservation_ttl_s=300,
    )


def _driver(request_id: str, *, session_id: str = "session-1") -> DriverRequest:
    return DriverRequest(
        request_id=request_id,
        idempotency_key=f"idem-{request_id}",
        session_id=session_id,
        parking_lot_id="lot-school",
        entrance_node_id="entry",
        requested_at=datetime(2026, 8, 13, tzinfo=UTC),
    )
