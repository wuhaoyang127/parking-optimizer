"""Third-party-free atomic resource availability checks."""

from parking_opt.domain.records import Action
from parking_opt.domain.state import AuthoritativeState


def runtime_resources_available(state: AuthoritativeState, action: Action) -> bool:
    """Return true only when executor and every channel can be acquired together."""

    if state.executor_resource.used + action.executor_units > state.executor_resource.capacity:
        return False
    zones = {item.channel_zone_id: item for item in state.channel_zone_resources}
    return all(
        zone_id in zones and zones[zone_id].used + 1 <= zones[zone_id].capacity
        for zone_id in action.channel_zone_ids
    )
