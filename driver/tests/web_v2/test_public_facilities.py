from __future__ import annotations

from collections import deque
from math import cos, radians, sin

from parking_opt.api.facility_scenarios import PUBLIC_SPECS, build_public_facility_scenarios
from parking_opt.api.models import SpaceStatus
from parking_opt.api.sessions import InMemorySessionStore, SessionTiming


def _store() -> InMemorySessionStore:
    return InMemorySessionStore(
        timing=SessionTiming(
            driver_idle_ttl_s=600,
            defense_idle_ttl_s=600,
            soft_hold_ttl_s=30,
            driver_reservation_ttl_s=300,
            defense_reservation_ttl_s=300,
        )
    )


def _reachable(layout, start: str) -> set[str]:  # type: ignore[no-untyped-def]
    adjacent: dict[str, list[str]] = {item.node_id: [] for item in layout.nodes}
    for edge in layout.edges:
        adjacent[edge.from_node_id].append(edge.to_node_id)
        if not edge.directed:
            adjacent[edge.to_node_id].append(edge.from_node_id)
    found, queue = {start}, deque([start])
    while queue:
        for target in adjacent[queue.popleft()]:
            if target not in found:
                found.add(target)
                queue.append(target)
    return found


def _rectangle_axes(rectangle):  # type: ignore[no-untyped-def]
    angle = radians(rectangle.heading_deg)
    return ((cos(angle), sin(angle)), (-sin(angle), cos(angle)))


def _rectangle_corners(rectangle):  # type: ignore[no-untyped-def]
    axes = _rectangle_axes(rectangle)
    return tuple(
        (
            rectangle.center.x_m
            + width_sign * rectangle.width_m / 2 * axes[0][0]
            + length_sign * rectangle.length_m / 2 * axes[1][0],
            rectangle.center.y_m
            + width_sign * rectangle.width_m / 2 * axes[0][1]
            + length_sign * rectangle.length_m / 2 * axes[1][1],
        )
        for width_sign in (-1, 1)
        for length_sign in (-1, 1)
    )


def _overlap(left, right) -> bool:  # type: ignore[no-untyped-def]
    for axis in (*_rectangle_axes(left), *_rectangle_axes(right)):
        left_projection = tuple(x * axis[0] + y * axis[1] for x, y in _rectangle_corners(left))
        right_projection = tuple(x * axis[0] + y * axis[1] for x, y in _rectangle_corners(right))
        if max(left_projection) <= min(right_projection) or max(right_projection) <= min(
            left_projection
        ):
            return False
    return True


def _segment_crosses_rectangle(left, right, rectangle) -> bool:  # type: ignore[no-untyped-def]
    axes = _rectangle_axes(rectangle)

    def local(point):  # type: ignore[no-untyped-def]
        dx = point.x_m - rectangle.center.x_m
        dy = point.y_m - rectangle.center.y_m
        return (dx * axes[0][0] + dy * axes[0][1], dx * axes[1][0] + dy * axes[1][1])

    start, end = local(left), local(right)
    minimum, maximum = 0.0, 1.0
    for start_value, end_value, half_extent in (
        (start[0], end[0], rectangle.width_m / 2),
        (start[1], end[1], rectangle.length_m / 2),
    ):
        delta = end_value - start_value
        if delta == 0:
            if abs(start_value) < half_extent:
                continue
            return False
        lower = (-half_extent - start_value) / delta
        upper = (half_extent - start_value) / delta
        minimum = max(minimum, min(lower, upper))
        maximum = min(maximum, max(lower, upper))
        if minimum >= maximum:
            return False
    return True


def test_public_facility_counts_types_and_compatibility_projection_are_exact() -> None:
    scenarios = build_public_facility_scenarios()
    for spec in PUBLIC_SPECS:
        scenario = scenarios[spec.lot_id]
        assert len(scenario.layout.spaces) == spec.spaces
        assert sum(item.charging for item in scenario.layout.spaces) == spec.charging
        assert len(scenario.layout.tandem_groups) == spec.tandem_groups
        assert (
            sum(len(item.space_ids_near_to_deep) for item in scenario.layout.tandem_groups)
            == spec.tandem_groups * 2
        )
        assert len(scenario.layout.buffers) == spec.buffers
        assert (
            sum(item.observed_status is SpaceStatus.OCCUPIED for item in scenario.base_state.spaces)
            == spec.occupied
        )
        assert {item.space_id for item in scenario.layout.spaces} == {
            item.space_id for item in scenario.bundle.layout.spaces
        }
        assert scenario.layout.layout_version == scenario.bundle.layout.layout_version
        assert not any(item.charging and item.stack_group_id for item in scenario.layout.spaces)


def test_space_and_buffer_rectangles_do_not_overlap() -> None:
    for scenario in build_public_facility_scenarios().values():
        rectangles = [
            *((item.space_id, item.geometry) for item in scenario.layout.spaces),
            *((item.buffer_id, item.geometry) for item in scenario.layout.buffers),
        ]
        for index, (left_id, left) in enumerate(rectangles):
            for right_id, right in rectangles[index + 1 :]:
                assert not _overlap(left, right), f"{left_id} overlaps {right_id}"


def test_roads_do_not_cross_positions_and_access_nodes_are_near_targets() -> None:
    for scenario in build_public_facility_scenarios().values():
        nodes = {item.node_id: item for item in scenario.layout.nodes}
        positions = [
            *(
                (item.space_id, item.geometry, item.access_node_id)
                for item in scenario.layout.spaces
            ),
            *(
                (item.buffer_id, item.geometry, item.access_node_id)
                for item in scenario.layout.buffers
            ),
        ]
        for position_id, rectangle, access_node_id in positions:
            access = nodes[access_node_id].coordinate
            distance = (
                (access.x_m - rectangle.center.x_m) ** 2 + (access.y_m - rectangle.center.y_m) ** 2
            ) ** 0.5
            assert distance <= 12, f"{position_id} access is {distance:.2f}m away"
            for edge in scenario.layout.edges:
                assert not _segment_crosses_rectangle(
                    edge.centerline[0], edge.centerline[-1], rectangle
                ), f"{edge.edge_id} crosses {position_id}"


def test_parking_lanes_are_genuinely_one_way_without_reverse_edge_pairs() -> None:
    for scenario in build_public_facility_scenarios().values():
        lane_edges = [item for item in scenario.layout.edges if item.edge_id.startswith("lane-")]
        assert lane_edges and all(item.directed for item in lane_edges)
        pairs = {(item.from_node_id, item.to_node_id) for item in lane_edges}
        assert not any((right, left) in pairs for left, right in pairs)
