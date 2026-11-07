import type { components } from "./schema";
import { ApiError } from "./client";
import { getDriverSessionId } from "./sessionIdentity";

export type ParkingFacilityLayout = components["schemas"]["ParkingFacilityLayout"];
export type ParkingFacilityState = components["schemas"]["ParkingFacilityStateSnapshot"];
export type FacilitySpace = components["schemas"]["FacilitySpace"];
export type FacilitySpaceState = components["schemas"]["FacilitySpaceState"];
export type RoutePreview = components["schemas"]["RoutePreview"];
export type FacilityRoute = components["schemas"]["Route"];

export interface FacilitySnapshot {
  layout: ParkingFacilityLayout;
  state: ParkingFacilityState;
}

function record(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function finite(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

interface CoordinateValue { x_m: number; y_m: number }
interface BoundsValue { min_x_m: number; min_y_m: number; max_x_m: number; max_y_m: number }
interface RectangleValue { center: CoordinateValue; width_m: number; length_m: number; heading_deg: number }

function coordinate(value: unknown): value is CoordinateValue {
  return record(value) && finite(value.x_m) && finite(value.y_m);
}

function bounds(value: unknown): value is BoundsValue {
  return record(value) && finite(value.min_x_m) && finite(value.min_y_m) && finite(value.max_x_m) && finite(value.max_y_m) && value.min_x_m < value.max_x_m && value.min_y_m < value.max_y_m;
}

function within(point: unknown, area: BoundsValue): boolean {
  return coordinate(point) && point.x_m >= area.min_x_m && point.x_m <= area.max_x_m && point.y_m >= area.min_y_m && point.y_m <= area.max_y_m;
}

function nonEmpty(value: unknown): value is string {
  return typeof value === "string" && value.length > 0;
}

function demoProfile(value: unknown): boolean {
  return record(value) && value.schema_version === "1.0.0" && nonEmpty(value.profile_id) &&
    nonEmpty(value.label) && nonEmpty(value.description) && Number.isInteger(value.ordinal) &&
    Number(value.ordinal) >= 1 && Number.isInteger(value.total) && Number(value.total) >= Number(value.ordinal);
}

function dateTime(value: unknown): value is string {
  return nonEmpty(value) && Number.isFinite(Date.parse(value));
}

function sameCoordinate(left: unknown, right: unknown): boolean {
  return coordinate(left) && coordinate(right) && left.x_m === right.x_m && left.y_m === right.y_m;
}

function uniqueStrings(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === "string") && new Set(value).size === value.length;
}

function rectangle(value: unknown): value is RectangleValue {
  return (
    record(value) &&
    coordinate(value.center) &&
    finite(value.width_m) && value.width_m > 0 &&
    finite(value.length_m) && value.length_m > 0 &&
    finite(value.heading_deg) && value.heading_deg >= 0 && value.heading_deg < 360
  );
}

function rectangleWithin(value: unknown, area: BoundsValue): boolean {
  if (!rectangle(value)) return false;
  const radians = value.heading_deg * Math.PI / 180;
  const cos = Math.cos(radians);
  const sin = Math.sin(radians);
  return [-1, 1].every((widthSign) => [-1, 1].every((lengthSign) => {
    const dx = widthSign * value.width_m / 2;
    const dy = lengthSign * value.length_m / 2;
    return within({ x_m: value.center.x_m + dx * cos - dy * sin, y_m: value.center.y_m + dx * sin + dy * cos }, area);
  }));
}

export function isParkingFacilityLayout(value: unknown): value is ParkingFacilityLayout {
  if (!record(value) || value.schema_version !== "1.0.0" || !nonEmpty(value.parking_lot_id) || !nonEmpty(value.layout_version) || value.coordinate_system !== "local_meters" || !nonEmpty(value.coordinate_origin_note) || !bounds(value.bounds)) return false;
  if (!record(value.provenance) || !["synthetic", "imported", "real"].includes(String(value.provenance.source_kind)) || !nonEmpty(value.provenance.source_name) || !nonEmpty(value.provenance.source_revision) || !dateTime(value.provenance.published_at)) return false;
  const facilityBounds = value.bounds;
  if (!Array.isArray(value.floors) || value.floors.length === 0 || !Array.isArray(value.inter_floor_connections) || !Array.isArray(value.zones) || !Array.isArray(value.nodes) || !Array.isArray(value.edges) || !Array.isArray(value.channel_zones) || !Array.isArray(value.entrances) || !Array.isArray(value.exits) || !Array.isArray(value.spaces) || !Array.isArray(value.tandem_groups) || !Array.isArray(value.buffers) || !Array.isArray(value.restricted_areas)) return false;
  const floors = new Map<string, BoundsValue>();
  if (!value.floors.every((item) => {
    if (!record(item) || !nonEmpty(item.floor_id) || floors.has(item.floor_id) || !nonEmpty(item.label) || !finite(item.elevation_m) || !bounds(item.bounds)) return false;
    if (item.bounds.min_x_m < facilityBounds.min_x_m || item.bounds.min_y_m < facilityBounds.min_y_m || item.bounds.max_x_m > facilityBounds.max_x_m || item.bounds.max_y_m > facilityBounds.max_y_m) return false;
    floors.set(item.floor_id, item.bounds);
    return true;
  }) || !nonEmpty(value.default_floor_id) || !floors.has(value.default_floor_id)) return false;
  const zoneKinds = new Set(["parking", "charging", "tandem", "buffer", "restricted", "service", "pedestrian"]);
  const zones = new Map<string, Record<string, unknown>>();
  if (!value.zones.every((item) => {
    if (!record(item) || !nonEmpty(item.zone_id) || zones.has(item.zone_id) || !nonEmpty(item.floor_id) || !nonEmpty(item.label) || !zoneKinds.has(String(item.kind)) || !Array.isArray(item.polygon) || item.polygon.length < 3) return false;
    const floorBounds = floors.get(item.floor_id);
    if (floorBounds === undefined || !item.polygon.every((point) => within(point, floorBounds))) return false;
    zones.set(item.zone_id, item);
    return true;
  })) return false;
  const restrictedIds = new Set<string>();
  if (!value.restricted_areas.every((item) => {
    if (!record(item) || !nonEmpty(item.area_id) || restrictedIds.has(item.area_id) || !nonEmpty(item.floor_id) || !nonEmpty(item.label) || !Array.isArray(item.polygon) || item.polygon.length < 3) return false;
    const floorBounds = floors.get(item.floor_id);
    if (floorBounds === undefined || !item.polygon.every((point) => within(point, floorBounds))) return false;
    restrictedIds.add(item.area_id);
    return true;
  })) return false;
  const nodeKinds = new Set(["entrance", "exit", "junction", "space_access", "buffer_access", "inter_floor"]);
  const nodes = new Map<string, Record<string, unknown>>();
  if (!value.nodes.every((item) => {
    if (!record(item) || !nonEmpty(item.node_id) || nodes.has(item.node_id) || !nonEmpty(item.floor_id) || !nonEmpty(item.label) || !nodeKinds.has(String(item.kind))) return false;
    const floorBounds = floors.get(item.floor_id);
    if (floorBounds === undefined || !within(item.coordinate, floorBounds)) return false;
    nodes.set(item.node_id, item);
    return true;
  })) return false;
  const channelIds = new Set<string>();
  if (!value.channel_zones.every((item) => {
    if (!record(item) || !nonEmpty(item.channel_zone_id) || channelIds.has(item.channel_zone_id) || !Number.isInteger(item.capacity) || Number(item.capacity) < 1) return false;
    channelIds.add(item.channel_zone_id);
    return true;
  })) return false;
  const edgeIds = new Set<string>();
  if (!value.edges.every((item) => {
    if (!record(item) || !nonEmpty(item.edge_id) || !nonEmpty(item.from_node_id) || !nonEmpty(item.to_node_id) || edgeIds.has(item.edge_id) || !nodes.has(item.from_node_id) || !nodes.has(item.to_node_id) || !Array.isArray(item.centerline) || item.centerline.length < 2 || !item.centerline.every((point) => within(point, facilityBounds)) || !finite(item.width_m) || item.width_m <= 0 || !finite(item.distance_m) || item.distance_m <= 0 || !finite(item.base_travel_time_s) || item.base_travel_time_s <= 0 || typeof item.directed !== "boolean" || !["drive", "ramp", "lift"].includes(String(item.traversal_kind)) || !uniqueStrings(item.channel_zone_ids) || !item.channel_zone_ids.every((id) => channelIds.has(id))) return false;
    if (!sameCoordinate(item.centerline[0], nodes.get(item.from_node_id)?.coordinate) || !sameCoordinate(item.centerline.at(-1), nodes.get(item.to_node_id)?.coordinate)) return false;
    edgeIds.add(item.edge_id);
    return true;
  })) return false;
  const connectionIds = new Set<string>();
  if (!value.inter_floor_connections.every((item) => {
    if (!record(item) || !nonEmpty(item.connection_id) || connectionIds.has(item.connection_id) || !nonEmpty(item.from_floor_id) || !nonEmpty(item.to_floor_id) || item.from_floor_id === item.to_floor_id || !floors.has(item.from_floor_id) || !floors.has(item.to_floor_id) || !["ramp", "lift"].includes(String(item.kind)) || !uniqueStrings(item.edge_ids) || item.edge_ids.length === 0 || !item.edge_ids.every((id) => edgeIds.has(id))) return false;
    connectionIds.add(item.connection_id);
    return true;
  })) return false;
  const spaceIds = new Set<string>();
  const spaces = new Map<string, Record<string, unknown>>();
  if (!value.spaces.every((item) => {
    if (!record(item)) return false;
    const floorBounds = nonEmpty(item.floor_id) ? floors.get(item.floor_id) : undefined;
    if (!nonEmpty(item.space_id) || spaceIds.has(item.space_id) || item.parking_lot_id !== value.parking_lot_id || floorBounds === undefined || !nonEmpty(item.zone_id) || zones.get(item.zone_id)?.floor_id !== item.floor_id || !nonEmpty(item.access_node_id) || nodes.get(item.access_node_id)?.kind !== "space_access" || nodes.get(item.access_node_id)?.floor_id !== item.floor_id || !rectangle(item.geometry) || !rectangleWithin(item.geometry, floorBounds) || typeof item.charging !== "boolean" || !(item.stack_group_id === null || nonEmpty(item.stack_group_id)) || !Number.isInteger(item.depth) || Number(item.depth) < 1) return false;
    spaceIds.add(item.space_id);
    spaces.set(item.space_id, item);
    return true;
  })) return false;
  const bufferIds = new Set<string>();
  const buffers = new Map<string, Record<string, unknown>>();
  if (!value.buffers.every((item) => {
    if (!record(item)) return false;
    const floorBounds = nonEmpty(item.floor_id) ? floors.get(item.floor_id) : undefined;
    if (!nonEmpty(item.buffer_id) || bufferIds.has(item.buffer_id) || item.parking_lot_id !== value.parking_lot_id || floorBounds === undefined || !nonEmpty(item.zone_id) || zones.get(item.zone_id)?.floor_id !== item.floor_id || !nonEmpty(item.access_node_id) || nodes.get(item.access_node_id)?.kind !== "buffer_access" || nodes.get(item.access_node_id)?.floor_id !== item.floor_id || !rectangle(item.geometry) || !rectangleWithin(item.geometry, floorBounds) || item.purpose !== "tandem_recovery" || !uniqueStrings(item.stack_group_ids) || item.stack_group_ids.length === 0) return false;
    bufferIds.add(item.buffer_id);
    buffers.set(item.buffer_id, item);
    return true;
  })) return false;
  const groupIds = new Set<string>();
  if (!value.tandem_groups.every((item) => {
    if (!record(item) || typeof item.stack_group_id !== "string" || groupIds.has(item.stack_group_id) || !uniqueStrings(item.space_ids_near_to_deep) || !uniqueStrings(item.buffer_ids)) return false;
    const groupId = item.stack_group_id;
    const groupFloor = spaces.get(item.space_ids_near_to_deep[0] ?? "")?.floor_id;
    if (typeof groupFloor !== "string" || item.space_ids_near_to_deep.length < 2 || !item.space_ids_near_to_deep.every((id, index) => spaces.get(id)?.stack_group_id === groupId && spaces.get(id)?.depth === index + 1 && spaces.get(id)?.floor_id === groupFloor)) return false;
    if (item.buffer_ids.length === 0 || !item.buffer_ids.every((id) => {
      const groupRefs = buffers.get(id)?.stack_group_ids;
      return bufferIds.has(id) && buffers.get(id)?.floor_id === groupFloor && uniqueStrings(groupRefs) && groupRefs.includes(groupId);
    })) return false;
    groupIds.add(groupId);
    return true;
  })) return false;
  if (![...spaces.values()].every((item) => item.stack_group_id === null ? item.depth === 1 : typeof item.stack_group_id === "string" && groupIds.has(item.stack_group_id))) return false;
  if (![...buffers.values()].every((item) => uniqueStrings(item.stack_group_ids) && item.stack_group_ids.every((id) => groupIds.has(id)))) return false;
  const entranceIds = new Set(value.entrances.flatMap((item) => record(item) && nonEmpty(item.entrance_id) && nonEmpty(item.node_id) && nonEmpty(item.label) && nodes.get(item.node_id)?.kind === "entrance" && finite(item.initial_heading_deg) && item.initial_heading_deg >= 0 && item.initial_heading_deg < 360 ? [item.entrance_id] : []));
  const exitIds = new Set(value.exits.flatMap((item) => record(item) && nonEmpty(item.exit_id) && nonEmpty(item.node_id) && nonEmpty(item.label) && nodes.get(item.node_id)?.kind === "exit" ? [item.exit_id] : []));
  if (entranceIds.size !== value.entrances.length || exitIds.size !== value.exits.length) return false;
  if (!nonEmpty(value.default_entrance_id) || !entranceIds.has(value.default_entrance_id)) return false;
  if (value.image_registration !== null && value.image_registration !== undefined) {
    if (!record(value.image_registration) || !Number.isInteger(value.image_registration.pixel_width) || Number(value.image_registration.pixel_width) < 1 || !Number.isInteger(value.image_registration.pixel_height) || Number(value.image_registration.pixel_height) < 1 || !Array.isArray(value.image_registration.meters_to_pixels_affine) || value.image_registration.meters_to_pixels_affine.length !== 6 || !value.image_registration.meters_to_pixels_affine.every(finite)) return false;
  }
  return true;
}

export function isParkingFacilityState(value: unknown, layout?: ParkingFacilityLayout): value is ParkingFacilityState {
  if (!record(value) || value.schema_version !== "1.0.0" || !nonEmpty(value.parking_lot_id) || !nonEmpty(value.layout_version) || !nonEmpty(value.scenario_id) || !nonEmpty(value.scenario_version) || !nonEmpty(value.state_version) || !dateTime(value.observed_at) || !record(value.source) || !Array.isArray(value.spaces) || !Array.isArray(value.buffers)) return false;
  if (value.demo_profile !== null && value.demo_profile !== undefined && !demoProfile(value.demo_profile)) return false;
  const sourceKinds = new Set(["synthetic", "imported", "real"]);
  const healthStatuses = new Set(["healthy", "degraded", "unavailable"]);
  if (!sourceKinds.has(String(value.source.source_kind)) || !healthStatuses.has(String(value.source.health)) || !nonEmpty(value.source.source_name) || !Array.isArray(value.source.missing_fields) || !value.source.missing_fields.every((item) => typeof item === "string") || !dateTime(value.source.updated_at) || !(value.source.fail_reason === null || typeof value.source.fail_reason === "string")) return false;
  const statuses = new Set(["available", "occupied", "unavailable", "unknown"]);
  const claims = new Set(["none", "soft_held", "session_reserved", "navigating"]);
  const observations = new Set(["synthetic_truth", "observation", "user_override"]);
  const spaceIds = new Set<string>();
  if (!value.spaces.every((item) => {
    if (!record(item) || !nonEmpty(item.space_id) || spaceIds.has(item.space_id) || !statuses.has(String(item.observed_status)) || !observations.has(String(item.observation_source)) || !statuses.has(String(item.effective_status)) || !claims.has(String(item.claim_status)) || typeof item.assignable !== "boolean" || !Array.isArray(item.reason_codes) || !item.reason_codes.every((reason) => typeof reason === "string")) return false;
    spaceIds.add(item.space_id);
    return true;
  })) return false;
  const bufferIds = new Set(value.buffers.flatMap((item) => record(item) && nonEmpty(item.buffer_id) && statuses.has(String(item.status)) && observations.has(String(item.observation_source)) && Array.isArray(item.reason_codes) && item.reason_codes.every((reason) => typeof reason === "string") ? [item.buffer_id] : []));
  if (bufferIds.size !== value.buffers.length) return false;
  return layout === undefined || (value.parking_lot_id === layout.parking_lot_id && value.layout_version === layout.layout_version && spaceIds.size === layout.spaces.length && layout.spaces.every((item) => spaceIds.has(item.space_id)) && bufferIds.size === layout.buffers.length && layout.buffers.every((item) => bufferIds.has(item.buffer_id)));
}

export function isRoutePreview(value: unknown, snapshot?: FacilitySnapshot, expected?: { entranceId: string; targetSpaceId: string }): value is RoutePreview {
  if (!record(value) || value.schema_version !== "1.0.0" || !nonEmpty(value.parking_lot_id) || !nonEmpty(value.layout_version) || !nonEmpty(value.scenario_version) || !nonEmpty(value.state_version) || !dateTime(value.observed_at) || !nonEmpty(value.entrance_id) || !nonEmpty(value.target_space_id) || !record(value.route)) return false;
  const route = value.route;
  if (route.schema_version !== "2.0.0" || route.parking_lot_id !== value.parking_lot_id || route.layout_version !== value.layout_version || !nonEmpty(route.from_node_id) || !nonEmpty(route.to_node_id) || !uniqueStrings(route.node_ids) || !uniqueStrings(route.edge_ids) || route.node_ids.length !== route.edge_ids.length + 1 || route.node_ids[0] !== route.from_node_id || route.node_ids.at(-1) !== route.to_node_id || !finite(route.distance_m) || route.distance_m < 0 || !finite(route.dynamic_eta_s) || route.dynamic_eta_s < 0 || !Array.isArray(route.instructions)) return false;
  const routeNodeIds = route.node_ids;
  const routeEdgeIds = route.edge_ids;
  if (expected !== undefined && (value.entrance_id !== expected.entranceId || value.target_space_id !== expected.targetSpaceId)) return false;
  if (snapshot === undefined) return true;
  const edgeIds = new Set(snapshot.layout.edges.map((item) => item.edge_id));
  const nodeIds = new Set(snapshot.layout.nodes.map((item) => item.node_id));
  const entrance = snapshot.layout.entrances.find((item) => item.entrance_id === value.entrance_id);
  const target = snapshot.layout.spaces.find((item) => item.space_id === value.target_space_id);
  if (entrance === undefined || target === undefined || route.from_node_id !== entrance.node_id || route.to_node_id !== target.access_node_id) return false;
  if (value.parking_lot_id !== snapshot.layout.parking_lot_id || value.layout_version !== snapshot.layout.layout_version || value.scenario_version !== snapshot.state.scenario_version || value.state_version !== snapshot.state.state_version || value.observed_at !== snapshot.state.observed_at || !routeEdgeIds.every((id) => edgeIds.has(id)) || !routeNodeIds.every((id) => nodeIds.has(id))) return false;
  const edges = new Map(snapshot.layout.edges.map((item) => [item.edge_id, item]));
  if (!routeEdgeIds.every((id, index) => {
    const edge = edges.get(id);
    const from = routeNodeIds[index];
    const to = routeNodeIds[index + 1];
    return edge !== undefined && (edge.from_node_id === from && edge.to_node_id === to || !edge.directed && edge.from_node_id === to && edge.to_node_id === from);
  })) return false;
  return route.instructions.every((instruction, index) => record(instruction) && instruction.sequence === index + 1 && nonEmpty(instruction.edge_id) && routeEdgeIds.includes(instruction.edge_id) && nonEmpty(instruction.text) && finite(instruction.distance_m) && instruction.distance_m >= 0 && finite(instruction.travel_time_s) && instruction.travel_time_s >= 0);
}

async function request(path: string, signal: AbortSignal, init?: RequestInit): Promise<unknown> {
  let response: Response;
  try {
    const headers = new Headers(init?.headers);
    headers.set("Accept", "application/json");
    headers.set("Content-Type", "application/json");
    headers.set("X-Session-ID", getDriverSessionId());
    response = await fetch(path, {
      ...init,
      signal,
      headers,
    });
  } catch (error) {
    if (record(error) && error.name === "AbortError") throw error;
    throw new ApiError(0, "NETWORK_UNAVAILABLE", "无法连接停车场布局服务");
  }
  const payload: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    const message = record(payload) && typeof payload.message === "string" ? payload.message : "停车场布局服务暂时不可用";
    const code = record(payload) && typeof payload.code === "string" ? payload.code : "UNEXPECTED_API_ERROR";
    throw new ApiError(response.status, code, message, response.headers.get("X-Request-ID"));
  }
  return payload;
}

export async function loadFacilitySnapshot(parkingLotId: string, signal: AbortSignal): Promise<FacilitySnapshot> {
  const encoded = encodeURIComponent(parkingLotId);
  const [layoutPayload, statePayload] = await Promise.all([
    request(`/api/v2/parking-lots/${encoded}/facility-layout`, signal),
    request(`/api/v2/parking-lots/${encoded}/facility-state`, signal),
  ]);
  if (!isParkingFacilityLayout(layoutPayload) || !isParkingFacilityState(statePayload, layoutPayload)) throw new ApiError(200, "FACILITY_CONTRACT_MISMATCH", "完整布局数据未通过契约校验");
  return { layout: layoutPayload, state: statePayload };
}

export async function loadFacilityState(parkingLotId: string, layout: ParkingFacilityLayout, signal: AbortSignal): Promise<ParkingFacilityState> {
  const payload = await request(`/api/v2/parking-lots/${encodeURIComponent(parkingLotId)}/facility-state`, signal);
  if (!isParkingFacilityState(payload, layout)) throw new ApiError(200, "FACILITY_STATE_MISMATCH", "停车场状态与布局不一致");
  return payload;
}

export async function loadRoutePreview(snapshot: FacilitySnapshot, entranceId: string, targetSpaceId: string, signal: AbortSignal): Promise<RoutePreview> {
  const payload = await request(`/api/v2/parking-lots/${encodeURIComponent(snapshot.layout.parking_lot_id)}/route-previews`, signal, {
    method: "POST",
    body: JSON.stringify({ schema_version: "1.0.0", layout_version: snapshot.layout.layout_version, scenario_version: snapshot.state.scenario_version, state_version: snapshot.state.state_version, entrance_id: entranceId, target_space_id: targetSpaceId }),
  });
  if (!isRoutePreview(payload, snapshot, { entranceId, targetSpaceId })) throw new ApiError(200, "ROUTE_PREVIEW_MISMATCH", "路线预览与当前布局、状态或目标不一致");
  return payload;
}
