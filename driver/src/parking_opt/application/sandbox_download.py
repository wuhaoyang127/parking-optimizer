"""Sandbox decision download artifacts and action-route coordinates."""

from __future__ import annotations

import csv
import html
import io
import json

from parking_opt.application.sandbox_types import _SCHEMA_VERSION, SandboxDecision
from parking_opt.contracts.snapshot_projection import observed_snapshot_to_mapping
from parking_opt.domain.conversion import decision_result_to_mapping
from parking_opt.domain.records import Action
from parking_opt.layout.model import Layout, layout_to_mapping


def decision_downloads(decision: SandboxDecision, layout: Layout) -> dict[str, bytes]:
    """Build browser-download artifacts without writing to the repository."""

    scenario = {
        "schema_version": _SCHEMA_VERSION,
        "data_source": "synthetic",
        "purpose": "interactive_demo",
        "layout": layout_to_mapping(layout),
        "observed_snapshot": observed_snapshot_to_mapping(decision.request.observed_snapshot),
    }
    decision_mapping = decision_result_to_mapping(decision.result)
    csv_buffer = io.StringIO(newline="")
    writer = csv.writer(csv_buffer)
    writer.writerow(
        (
            "rank",
            "position_id",
            "feasible",
            "reason_codes",
            "distance_m",
            "incremental_blocked_vehicle_count",
            "remaining_one_step_assignable_capacity",
        )
    )
    for item in decision.candidates:
        writer.writerow(
            (
                item.rank or "",
                item.position_id,
                item.feasible,
                "|".join(item.reason_codes),
                "" if item.distance_m is None else item.distance_m,
                "" if item.incremental_blocked_vehicle_count is None else item.incremental_blocked_vehicle_count,
                "" if item.remaining_one_step_assignable_capacity is None else item.remaining_one_step_assignable_capacity,
            )
        )
    selected = decision.selected_position_id or "未选择车位"
    summary = f"""<!doctype html>
<html lang="zh-CN"><meta charset="utf-8"><title>智能停车沙盒决策摘要</title>
<style>body{{font-family:system-ui,sans-serif;max-width:860px;margin:40px auto;line-height:1.7}}
table{{border-collapse:collapse;width:100%}}
th,td{{border:1px solid #cbd5e1;padding:8px;text-align:left}}
.note{{background:#eff6ff;padding:12px;border-radius:8px}}</style>
<h1>智能停车沙盒决策摘要</h1>
<p class="note">SYNTHETIC｜仅用于算法流程演示，不构成真实停车场效果或性能优越性结论。</p>
<p><strong>匿名车辆：</strong>{html.escape(decision.result.target_anonymous_vehicle_id)}</p>
<p><strong>主决定：</strong>{html.escape(decision.result.primary_decision.value)}</p>
<p><strong>选择位置：</strong>{html.escape(selected)}</p>
<h2>过程说明</h2>
<ol>{"".join(f"<li>{html.escape(step)}</li>" for step in decision.story_steps)}</ol>
</html>"""
    return {
        "scenario.json": json.dumps(scenario, ensure_ascii=False, indent=2).encode("utf-8"),
        "decision-result.json": json.dumps(decision_mapping, ensure_ascii=False, indent=2).encode("utf-8"),
        "candidate-comparison.csv": ("\ufeff" + csv_buffer.getvalue()).encode("utf-8"),
        "decision-summary.html": summary.encode("utf-8"),
    }


def action_route_coordinates(layout: Layout, action: Action) -> tuple[tuple[float, float], ...]:
    """Return management-level route coordinates from saved path edge IDs."""

    normal = {item.position_id: item for item in layout.slots}
    buffers = {item.position_id: item for item in layout.buffer_slots}
    nodes = {item.road_node_id: item for item in layout.road_nodes}
    edges = {item.road_edge_id: item for item in layout.road_edges}
    trailing: tuple[tuple[float, float], ...]
    if action.origin_position_id is None:
        start_node_id = next(item.road_node_id for item in layout.road_nodes if item.node_kind == "entrance")
        leading: tuple[tuple[float, float], ...] = ()
    else:
        origin = normal.get(action.origin_position_id) or buffers.get(action.origin_position_id)
        if origin is None:
            return ()
        start_node_id = origin.access_node_id
        leading = ((origin.x_m, origin.y_m),)
    if action.destination_position_id is not None:
        destination = normal.get(action.destination_position_id) or buffers.get(action.destination_position_id)
        if destination is None:
            return ()
        end_node_id = destination.access_node_id
        trailing = ((destination.x_m, destination.y_m),)
    elif action.destination_exit_id is not None:
        end_node_id = action.destination_exit_id
        trailing = ()
    else:
        return ()
    path = next(
        (item for item in layout.path_costs if item.from_node_id == start_node_id and item.to_node_id == end_node_id),
        None,
    )
    if path is None:
        return ()
    current = start_node_id
    ordered_nodes = [current]
    for edge_id in path.road_edge_ids:
        edge = edges[edge_id]
        if edge.from_node_id == current:
            current = edge.to_node_id
        elif not edge.directed and edge.to_node_id == current:
            current = edge.from_node_id
        else:
            return ()
        ordered_nodes.append(current)
    road_points = tuple((nodes[node_id].x_m, nodes[node_id].y_m) for node_id in ordered_nodes)
    return (*leading, *road_points, *trailing)
