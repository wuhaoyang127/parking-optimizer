"""Driver demo profile scenarios for public facilities."""

from __future__ import annotations

from parking_opt.api.facility_scenarios_bundle import _project_bundle
from parking_opt.api.facility_scenarios_types import (
    DRIVER_DEMO_PROFILE_SPECS,
    PUBLIC_SPECS,
    PublishedDriverDemoScenario,
    PublishedFacilityScenario,
)
from parking_opt.api.models import DriverDemoProfile, FacilitySpaceState, SpaceStatus


def _profile_occupied_ids(profile_id: str, scenario: PublishedFacilityScenario) -> frozenset[str]:
    spaces = scenario.layout.spaces
    if profile_id == "normal-flow":
        return frozenset(
            item.space_id
            for item in scenario.base_state.spaces
            if item.observed_status is SpaceStatus.OCCUPIED
        )
    if profile_id == "peak-remote":
        far_independent = sorted(
            (item for item in spaces if item.stack_group_id is None and not item.charging),
            key=lambda item: (item.geometry.center.x_m, item.space_id),
            reverse=True,
        )[:3]
        far_charging = sorted(
            (item for item in spaces if item.charging),
            key=lambda item: (item.geometry.center.x_m, item.space_id),
            reverse=True,
        )[:1]
        available_ids = {item.space_id for item in (*far_independent, *far_charging)}
        return frozenset(item.space_id for item in spaces if item.space_id not in available_ids)
    if profile_id == "charging-tight":
        base_occupied = {
            item.space_id
            for item in scenario.base_state.spaces
            if item.observed_status is SpaceStatus.OCCUPIED
        }
        return frozenset(base_occupied | {item.space_id for item in spaces if item.charging})
    if profile_id == "tandem-focus":
        return frozenset(item.space_id for item in spaces if item.stack_group_id is None)
    raise ValueError(f"unsupported driver demo profile: {profile_id}")


def _profile_space_state(
    item: FacilitySpaceState,
    *,
    occupied_ids: frozenset[str],
    reserved_outer_ids: frozenset[str],
) -> FacilitySpaceState:
    if item.space_id in reserved_outer_ids:
        return item.model_copy(
            update={
                "observed_status": SpaceStatus.UNAVAILABLE,
                "effective_status": SpaceStatus.UNAVAILABLE,
                "assignable": False,
                "reason_codes": ("DEMO_TANDEM_OUTER_RESERVED",),
            }
        )
    occupied = item.space_id in occupied_ids
    return item.model_copy(
        update={
            "observed_status": SpaceStatus.OCCUPIED if occupied else SpaceStatus.AVAILABLE,
            "effective_status": SpaceStatus.OCCUPIED if occupied else SpaceStatus.AVAILABLE,
            "assignable": not occupied,
            "reason_codes": ("SPACE_OCCUPIED",) if occupied else (),
        }
    )


def _build_driver_demo_scenarios(
    scenario: PublishedFacilityScenario,
) -> tuple[PublishedDriverDemoScenario, ...]:
    result = []
    total = len(DRIVER_DEMO_PROFILE_SPECS)
    for index, profile_spec in enumerate(DRIVER_DEMO_PROFILE_SPECS):
        profile = DriverDemoProfile(
            profile_id=profile_spec.profile_id,
            label=profile_spec.label,
            description=profile_spec.description,
            ordinal=index + 1,
            total=total,
        )
        occupied_ids = _profile_occupied_ids(profile.profile_id, scenario)
        reserved_outer_ids = (
            frozenset(group.space_ids_near_to_deep[0] for group in scenario.layout.tandem_groups)
            if profile.profile_id == "tandem-focus"
            else frozenset()
        )
        state = scenario.base_state.model_copy(
            update={
                "state_version": f"state-{profile.profile_id}-base-1",
                "demo_profile": profile,
                "spaces": tuple(
                    _profile_space_state(item, occupied_ids=occupied_ids, reserved_outer_ids=reserved_outer_ids)
                    for item in scenario.base_state.spaces
                ),
            }
        ).require_layout(scenario.layout)
        bundle = _project_bundle(
            next(item for item in PUBLIC_SPECS if item.lot_id == scenario.layout.parking_lot_id),
            scenario.layout,
            state,
        )
        bundle = bundle.model_copy(
            update={
                "seed": bundle.seed + index,
                "cost_snapshot": bundle.cost_snapshot.model_copy(
                    update={"cost_version": f"cost-{profile.profile_id}-1"}
                ),
            }
        )
        result.append(
            PublishedDriverDemoScenario(
                demo_profile=profile,
                layout=scenario.layout,
                base_state=state,
                bundle=bundle,
            )
        )
    return tuple(result)
