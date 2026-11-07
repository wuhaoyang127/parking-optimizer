import { memo, useId } from "react";

import type { FacilityRoute, ParkingFacilityLayout, ParkingFacilityState } from "../../api/facilityClient";
import { points } from "./viewModel";
import { routeSegmentsForFloor } from "./routeGeometry";

export const FacilityBaseLayers = memo(function FacilityBaseLayers({ layout, floorId }: { layout: ParkingFacilityLayout; floorId: string }) {
  const laneArrowId = useId();
  const floor = layout.floors.find((item) => item.floor_id === floorId);
  const nodes = new Map(layout.nodes.map((item) => [item.node_id, item]));
  if (floor === undefined) return null;
  return (
    <g className="facility-base-layers">
      <rect className="facility-floor" x={floor.bounds.min_x_m} y={floor.bounds.min_y_m} width={floor.bounds.max_x_m - floor.bounds.min_x_m} height={floor.bounds.max_y_m - floor.bounds.min_y_m} />
      {layout.zones.filter((zone) => zone.floor_id === floorId).map((zone) => <polygon key={zone.zone_id} className={`facility-zone zone-${zone.kind}`} points={points(zone.polygon)}><title>{zone.label}</title></polygon>)}
      {layout.restricted_areas.filter((area) => area.floor_id === floorId).map((area) => <polygon key={area.area_id} className="facility-restricted" points={points(area.polygon)}><title>{area.label}</title></polygon>)}
      <defs><marker id={laneArrowId} className="facility-lane-marker" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="3.2" markerHeight="3.2" markerUnits="userSpaceOnUse" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" /></marker></defs>
      {layout.edges.filter((edge) => nodes.get(edge.from_node_id)?.floor_id === floorId && nodes.get(edge.to_node_id)?.floor_id === floorId).map((edge) => <polyline key={edge.edge_id} className={`facility-lane ${edge.directed ? "directed" : ""}`} points={points(edge.centerline)} markerEnd={edge.directed ? `url(#${laneArrowId})` : undefined}><title>{edge.directed ? "单向通道" : "双向通道"} · {edge.distance_m.toFixed(0)} 米</title></polyline>)}
    </g>
  );
});

export const FacilitySpaceLayer = memo(function FacilitySpaceLayer({ layout, state, floorId, selectedSpaceId, targetSpaceId, hiddenOccupiedSpaceIds = [], zoomLevel, onSelect, onTouchSelect }: { layout: ParkingFacilityLayout; state: ParkingFacilityState; floorId: string; selectedSpaceId: string | null; targetSpaceId: string | null; hiddenOccupiedSpaceIds?: readonly string[]; zoomLevel: number; onSelect: (spaceId: string) => void; onTouchSelect: (spaceId: string) => void }) {
  const states = new Map(state.spaces.map((item) => [item.space_id, item]));
  const hiddenOccupied = new Set(hiddenOccupiedSpaceIds);
  return (
    <g className="facility-space-layer">
      {layout.tandem_groups.flatMap((group) => {
        const members = layout.spaces.filter((item) => item.floor_id === floorId && group.space_ids_near_to_deep.includes(item.space_id));
        if (members.length === 0) return [];
        const minX = Math.min(...members.map((item) => item.geometry.center.x_m - item.geometry.width_m / 2)) - 1;
        const maxX = Math.max(...members.map((item) => item.geometry.center.x_m + item.geometry.width_m / 2)) + 1;
        const minY = Math.min(...members.map((item) => item.geometry.center.y_m - item.geometry.length_m / 2)) - 1;
        const maxY = Math.max(...members.map((item) => item.geometry.center.y_m + item.geometry.length_m / 2)) + 1;
        return [<rect key={group.stack_group_id} className="tandem-outline" x={minX} y={minY} width={maxX - minX} height={maxY - minY} rx="1"><title>纵深组 {group.stack_group_id}</title></rect>];
      })}
      {layout.buffers.filter((buffer) => buffer.floor_id === floorId).map((buffer) => <g key={buffer.buffer_id} transform={`translate(${String(buffer.geometry.center.x_m)} ${String(buffer.geometry.center.y_m)}) rotate(${String(buffer.geometry.heading_deg)})`}><rect className="facility-buffer" x={-buffer.geometry.width_m / 2} y={-buffer.geometry.length_m / 2} width={buffer.geometry.width_m} height={buffer.geometry.length_m} rx=".5" /><text className="buffer-label" y=".7">缓</text></g>)}
      {layout.spaces.filter((space) => space.floor_id === floorId).map((space) => {
        const current = states.get(space.space_id);
        const status = current?.effective_status ?? "unknown";
        return (
          <g key={space.space_id} role="button" tabIndex={0} data-space-id={space.space_id} aria-label={`${space.space_id}，${status}${targetSpaceId === space.space_id ? "，当前行程目标" : ""}`} className={`facility-space status-${status} ${space.charging ? "charging" : ""} ${space.stack_group_id == null ? "" : "tandem"} ${selectedSpaceId === space.space_id ? "selected" : ""} ${targetSpaceId === space.space_id ? "journey-target" : ""}`} transform={`translate(${String(space.geometry.center.x_m)} ${String(space.geometry.center.y_m)}) rotate(${String(space.geometry.heading_deg)})`} onPointerDown={(event) => { if (event.pointerType === "mouse") { event.stopPropagation(); onSelect(space.space_id); } }} onPointerUp={(event) => { if (event.pointerType !== "mouse") onTouchSelect(space.space_id); }} onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") onSelect(space.space_id); }}>
            <rect x={-space.geometry.width_m / 2} y={-space.geometry.length_m / 2} width={space.geometry.width_m} height={space.geometry.length_m} rx=".45" />
            {status === "occupied" && !hiddenOccupied.has(space.space_id) ? <path className="parked-vehicle" d="M-0.75 -1.6h1.5l.45.8v2.2h-2.4V-.8z" /> : null}
            {space.charging ? <text className="space-symbol" y=".7">⚡</text> : null}
            {zoomLevel >= 1.45 ? <text className="space-id" transform={`rotate(${String(-space.geometry.heading_deg)})`} y={space.geometry.length_m / 2 + 2.3}>{space.space_id}</text> : null}
          </g>
        );
      })}
      {layout.entrances.map((item) => {
        const node = layout.nodes.find((candidate) => candidate.node_id === item.node_id);
        return node?.floor_id !== floorId ? null : <g key={item.entrance_id} className="facility-gate entrance" transform={`translate(${String(node.coordinate.x_m)} ${String(node.coordinate.y_m)})`}><circle r="2.2" /><text x="3.2" y="1">入口</text></g>;
      })}
      {layout.exits.map((item) => {
        const node = layout.nodes.find((candidate) => candidate.node_id === item.node_id);
        return node?.floor_id !== floorId ? null : <g key={item.exit_id} className="facility-gate exit" transform={`translate(${String(node.coordinate.x_m)} ${String(node.coordinate.y_m)})`}><circle r="2.2" /><text x="3.2" y="1">出口</text></g>;
      })}
    </g>
  );
});

export const FacilityRouteLayer = memo(function FacilityRouteLayer({ layout, floorId, route, motion }: { layout: ParkingFacilityLayout; floorId: string; route: FacilityRoute | null; motion: boolean }) {
  if (route === null) return null;
  const segments = routeSegmentsForFloor(layout, route, floorId);
  const start = layout.nodes.find((node) => node.node_id === route.from_node_id && node.floor_id === floorId);
  const end = layout.nodes.find((node) => node.node_id === route.to_node_id && node.floor_id === floorId);
  if (segments.length === 0) return null;
  return <g className={`facility-route-layer ${motion ? "motion" : ""}`}>
    {segments.map((segment, index) => <g key={String(index)}><polyline className="preview-route-shadow" points={points(segment)} /><polyline className="preview-route" points={points(segment)} /><polyline className="preview-route-flow" points={points(segment)} /></g>)}
    {start === undefined ? null : <g className="route-endpoint route-origin" transform={`translate(${String(start.coordinate.x_m)} ${String(start.coordinate.y_m)})`}><title>路线起点 · {start.label}</title><circle r="2.3" /><circle className="route-origin-dot" r=".85" /></g>}
    {end === undefined ? null : <g className="route-endpoint route-destination" transform={`translate(${String(end.coordinate.x_m)} ${String(end.coordinate.y_m)})`}><title>路线终点 · {end.label}</title><circle r="2.7" /><path d="m-1.1 0 .7 .7 1.5-1.5" /></g>}
  </g>;
});

export function FacilityVehicleLayer({ x, y, role = "driver", label = "当前车辆" }: { x?: number; y?: number; role?: "driver" | "blocker"; label?: string }) {
  return x === undefined || y === undefined ? null : <g className={`facility-vehicle ${role}`} transform={`translate(${String(x)} ${String(y)})`}><title>{label}</title><circle className="vehicle-halo" r="3.1" /><circle r="2.2" /><path d="M-.85-1.25h1.7l.35.5v1.5H-1.2v-1.5z" /></g>;
}
