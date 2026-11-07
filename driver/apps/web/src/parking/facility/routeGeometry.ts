import type { FacilityRoute, ParkingFacilityLayout } from "../../api/facilityClient";
import type { RouteTimeline } from "../routeTimeline";

interface Coordinate { x_m: number; y_m: number }

export interface FacilityVehiclePosition extends Coordinate { floor_id: string }

function orientedCenterline(layout: ParkingFacilityLayout, route: FacilityRoute, edgeIndex: number): Coordinate[] | null {
  const edgeId = route.edge_ids[edgeIndex];
  const fromNodeId = route.node_ids[edgeIndex];
  const toNodeId = route.node_ids[edgeIndex + 1];
  const edge = layout.edges.find((candidate) => candidate.edge_id === edgeId);
  if (edge === undefined || fromNodeId === undefined || toNodeId === undefined) return null;
  if (edge.from_node_id === fromNodeId && edge.to_node_id === toNodeId) return [...edge.centerline];
  if (!edge.directed && edge.from_node_id === toNodeId && edge.to_node_id === fromNodeId) return [...edge.centerline].reverse();
  return null;
}

export function routeSegmentsForFloor(layout: ParkingFacilityLayout, route: FacilityRoute, floorId: string): Coordinate[][] {
  const nodes = new Map(layout.nodes.map((node) => [node.node_id, node]));
  return route.edge_ids.flatMap((_, edgeIndex) => {
    const fromNode = nodes.get(route.node_ids[edgeIndex] ?? "");
    const toNode = nodes.get(route.node_ids[edgeIndex + 1] ?? "");
    const centerline = orientedCenterline(layout, route, edgeIndex);
    return centerline !== null && (fromNode?.floor_id === floorId || toNode?.floor_id === floorId) ? [centerline] : [];
  });
}

function interpolate(points: Coordinate[], progress: number): Coordinate | null {
  if (points.length === 0) return null;
  if (points.length === 1) return points[0] ?? null;
  const lengths = points.slice(1).map((point, index) => {
    const previous = points[index];
    return previous === undefined ? 0 : Math.hypot(point.x_m - previous.x_m, point.y_m - previous.y_m);
  });
  const total = lengths.reduce((sum, length) => sum + length, 0);
  if (total <= 0) return points.at(-1) ?? null;
  let remaining = Math.min(1, Math.max(0, progress)) * total;
  for (let index = 0; index < lengths.length; index += 1) {
    const length = lengths[index];
    if (length === undefined) continue;
    if (remaining <= length || index === lengths.length - 1) {
      const from = points[index];
      const to = points[index + 1];
      if (from === undefined || to === undefined) return null;
      const ratio = length <= 0 ? 1 : remaining / length;
      return { x_m: from.x_m + (to.x_m - from.x_m) * ratio, y_m: from.y_m + (to.y_m - from.y_m) * ratio };
    }
    remaining -= length;
  }
  return points.at(-1) ?? null;
}

export function routeVehiclePosition(layout: ParkingFacilityLayout, route: FacilityRoute, timeline: RouteTimeline): FacilityVehiclePosition | null {
  const centerline = orientedCenterline(layout, route, timeline.activeStep);
  const fromNode = layout.nodes.find((node) => node.node_id === route.node_ids[timeline.activeStep]);
  const toNode = layout.nodes.find((node) => node.node_id === route.node_ids[timeline.activeStep + 1]);
  const coordinate = centerline === null ? null : interpolate(centerline, timeline.edgeProgress);
  if (coordinate === null || fromNode === undefined || toNode === undefined) return null;
  const floorId = fromNode.floor_id === toNode.floor_id || timeline.edgeProgress < 0.5 ? fromNode.floor_id : toNode.floor_id;
  return { ...coordinate, floor_id: floorId };
}
