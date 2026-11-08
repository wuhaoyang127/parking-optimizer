"""Session-aware state projection mixin for public facilities."""

from __future__ import annotations

import hashlib

from parking_opt.api.facility import FacilityDataUnavailableError
from parking_opt.api.models import (
    FacilityClaimStatus,
    FacilityObservationSource,
    ParkingFacilityStateSnapshot,
    SpaceStatus,
)
from parking_opt.api.sessions import JourneyState, SessionNamespace


class FacilityStateProjectionMixin:
    def get_state(self, parking_lot_id: str, *, session_id: str) -> ParkingFacilityStateSnapshot:
        scenario = self._driver_scenario(parking_lot_id, session_id=session_id)
        with self._session_store.atomic():
            availability = self._session_store.availability_snapshot(
                session_id=session_id,
                namespace=SessionNamespace.DRIVER,
                scopes=((scenario.base_state.scenario_id, parking_lot_id),),
            )
            active_claims = self._session_store.active_claims()
            coordination_records = self._session_store.tandem_coordination_records(
                session_id=session_id,
                scenario_id=scenario.base_state.scenario_id,
                parking_lot_id=parking_lot_id,
            )
            claimed_journeys = []
            for claim in active_claims:
                if (
                    claim.session_id == session_id
                    and claim.namespace is SessionNamespace.DRIVER
                    and claim.scenario_id == scenario.base_state.scenario_id
                    and claim.parking_lot_id == parking_lot_id
                ):
                    journey = self._session_store.get_journey(claim.journey_id)
                    if journey is None:
                        raise FacilityDataUnavailableError("active claim has no journey")
                    claimed_journeys.append((claim, journey))
        scope = availability.scopes[0]
        unavailable = dict(scope.unavailable_space_reasons)
        coordination_by_space = {
            space_id: record
            for record in coordination_records
            for space_id in record.blocker_space_ids
        }
        journeys = {}
        for claim, journey in claimed_journeys:
            journeys[claim.space_id] = journey
        claim_map = {
            JourneyState.SOFT_HELD: FacilityClaimStatus.SOFT_HELD,
            JourneyState.SESSION_RESERVED: FacilityClaimStatus.SESSION_RESERVED,
            JourneyState.NAVIGATING: FacilityClaimStatus.NAVIGATING,
        }
        projected = []
        for item in scenario.base_state.spaces:
            if item.space_id in scope.claimed_space_ids:
                claimed_journey = journeys.get(item.space_id)
                journey_state = None if claimed_journey is None else claimed_journey.state
                if journey_state is JourneyState.OCCUPIED:
                    projected.append(
                        item.model_copy(
                            update={
                                "observed_status": SpaceStatus.OCCUPIED,
                                "observation_source": FacilityObservationSource.SYNTHETIC_TRUTH,
                                "claim_status": FacilityClaimStatus.NONE,
                                "effective_status": SpaceStatus.OCCUPIED,
                                "assignable": False,
                                "reason_codes": ("SPACE_OCCUPIED",),
                            }
                        )
                    )
                    continue
                claim_status = claim_map[journey_state] if journey_state in claim_map else FacilityClaimStatus.SOFT_HELD
                projected.append(
                    item.model_copy(
                        update={
                            "claim_status": claim_status,
                            "effective_status": SpaceStatus.UNAVAILABLE,
                            "assignable": False,
                            "reason_codes": ("SESSION_CLAIMED",),
                        }
                    )
                )
            elif item.space_id in coordination_by_space:
                projected.append(
                    item.model_copy(
                        update={
                            "observed_status": SpaceStatus.OCCUPIED,
                            "observation_source": FacilityObservationSource.SYNTHETIC_TRUTH,
                            "claim_status": FacilityClaimStatus.NONE,
                            "effective_status": SpaceStatus.OCCUPIED,
                            "assignable": False,
                            "reason_codes": ("TANDEM_COORDINATION_BLOCKER",),
                        }
                    )
                )
            elif item.space_id in unavailable:
                projected.append(
                    item.model_copy(
                        update={
                            "observed_status": SpaceStatus.UNAVAILABLE,
                            "observation_source": FacilityObservationSource.USER_OVERRIDE,
                            "effective_status": SpaceStatus.UNAVAILABLE,
                            "assignable": False,
                            "reason_codes": (unavailable[item.space_id],),
                        }
                    )
                )
            else:
                projected.append(item)
        journey_identity = tuple(
            sorted(
                (space_id, journey.state.value, journey.updated_at.isoformat())
                for space_id, journey in journeys.items()
                if space_id in scope.claimed_space_ids
            )
        )
        token = hashlib.sha256(
            repr(
                (
                    scenario.demo_profile.profile_id,
                    journey_identity,
                    tuple(
                        (
                            item.journey_id,
                            item.stack_group_id,
                            item.blocker_space_ids,
                            item.buffer_ids,
                            item.created_at.isoformat(),
                        )
                        for item in coordination_records
                    ),
                    sorted(unavailable.items()),
                )
            ).encode("ascii")
        ).hexdigest()[:12]
        observed_at = max(
            (
                *(journey.updated_at for journey in journeys.values()),
                *(item.created_at for item in coordination_records),
            ),
            default=scenario.base_state.observed_at,
        )
        return scenario.base_state.model_copy(
            update={
                "state_version": f"state-{token}",
                "observed_at": observed_at,
                "spaces": tuple(projected),
            }
        )
