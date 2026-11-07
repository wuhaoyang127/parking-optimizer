import type { FacilitySnapshot, ParkingFacilityLayout, ParkingFacilityState, RoutePreview } from "../api/facilityClient";

export const facilityLayout = {
  schema_version: "1.0.0", parking_lot_id: "lot-school", layout_version: "school-layout-1",
  provenance: { source_kind: "synthetic", source_name: "test", source_revision: "r1", published_at: "2026-08-20T09:00:00Z" },
  coordinate_system: "local_meters", coordinate_origin_note: "test origin",
  bounds: { min_x_m: 0, min_y_m: 0, max_x_m: 40, max_y_m: 30 }, default_floor_id: "floor-1",
  floors: [{ floor_id: "floor-1", label: "地面层", elevation_m: 0, bounds: { min_x_m: 0, min_y_m: 0, max_x_m: 40, max_y_m: 30 } }],
  inter_floor_connections: [],
  zones: [{ zone_id: "parking", floor_id: "floor-1", label: "停车区", kind: "parking", polygon: [{ x_m: 2, y_m: 2 }, { x_m: 38, y_m: 2 }, { x_m: 38, y_m: 28 }, { x_m: 2, y_m: 28 }] }, { zone_id: "buffer", floor_id: "floor-1", label: "缓冲区", kind: "buffer", polygon: [{ x_m: 25, y_m: 20 }, { x_m: 35, y_m: 20 }, { x_m: 35, y_m: 28 }, { x_m: 25, y_m: 28 }] }], restricted_areas: [],
  nodes: [
    { node_id: "entry", floor_id: "floor-1", coordinate: { x_m: 2, y_m: 15 }, kind: "entrance", label: "南入口" },
    { node_id: "access", floor_id: "floor-1", coordinate: { x_m: 20, y_m: 15 }, kind: "space_access", label: "车位接入" },
    { node_id: "buffer-access", floor_id: "floor-1", coordinate: { x_m: 30, y_m: 15 }, kind: "buffer_access", label: "缓冲接入" },
    { node_id: "exit", floor_id: "floor-1", coordinate: { x_m: 38, y_m: 15 }, kind: "exit", label: "北出口" },
  ],
  edges: [
    { edge_id: "entry-access", from_node_id: "entry", to_node_id: "access", centerline: [{ x_m: 2, y_m: 15 }, { x_m: 20, y_m: 15 }], width_m: 5, distance_m: 18, base_travel_time_s: 5, directed: true, traversal_kind: "drive", channel_zone_ids: [] },
    { edge_id: "access-exit", from_node_id: "access", to_node_id: "exit", centerline: [{ x_m: 20, y_m: 15 }, { x_m: 38, y_m: 15 }], width_m: 5, distance_m: 18, base_travel_time_s: 5, directed: true, traversal_kind: "drive", channel_zone_ids: [] },
  ], channel_zones: [],
  entrances: [{ entrance_id: "south", node_id: "entry", label: "南入口", initial_heading_deg: 0 }],
  exits: [{ exit_id: "north", node_id: "exit", label: "北出口" }], default_entrance_id: "south",
  spaces: [
    { parking_lot_id: "lot-school", space_id: "P-01", floor_id: "floor-1", zone_id: "parking", geometry: { center: { x_m: 17, y_m: 9 }, width_m: 2.6, length_m: 5.2, heading_deg: 90 }, access_node_id: "access", charging: true, stack_group_id: "stack-1", depth: 1 },
    { parking_lot_id: "lot-school", space_id: "P-02", floor_id: "floor-1", zone_id: "parking", geometry: { center: { x_m: 23, y_m: 9 }, width_m: 2.6, length_m: 5.2, heading_deg: 90 }, access_node_id: "access", charging: false, stack_group_id: "stack-1", depth: 2 },
  ],
  tandem_groups: [{ stack_group_id: "stack-1", space_ids_near_to_deep: ["P-01", "P-02"], buffer_ids: ["BUF-01"] }],
  buffers: [{ parking_lot_id: "lot-school", buffer_id: "BUF-01", floor_id: "floor-1", zone_id: "buffer", geometry: { center: { x_m: 30, y_m: 24 }, width_m: 3, length_m: 6, heading_deg: 90 }, access_node_id: "buffer-access", purpose: "tandem_recovery", stack_group_ids: ["stack-1"] }], image_registration: null,
} as const satisfies ParkingFacilityLayout;

export const facilityState = {
  schema_version: "1.0.0", parking_lot_id: "lot-school", layout_version: "school-layout-1", scenario_id: "school-full-v1", scenario_version: "scenario-1", state_version: "state-1", observed_at: "2026-08-20T10:00:00Z",
  source: { source_kind: "synthetic", health: "healthy", source_name: "test", missing_fields: [], updated_at: "2026-08-20T10:00:00Z", fail_reason: null },
  spaces: [
    { space_id: "P-01", observed_status: "available", observation_source: "synthetic_truth", claim_status: "none", effective_status: "available", assignable: true, reason_codes: [] },
    { space_id: "P-02", observed_status: "occupied", observation_source: "synthetic_truth", claim_status: "none", effective_status: "occupied", assignable: false, reason_codes: ["SPACE_OCCUPIED"] },
  ], buffers: [{ buffer_id: "BUF-01", status: "available", observation_source: "synthetic_truth", reason_codes: [] }],
} as const satisfies ParkingFacilityState;

export const facilitySnapshot = { layout: facilityLayout, state: facilityState } satisfies FacilitySnapshot;

export const routePreview = {
  schema_version: "1.0.0", parking_lot_id: "lot-school", layout_version: "school-layout-1", scenario_version: "scenario-1", state_version: "state-1", observed_at: "2026-08-20T10:00:00Z", entrance_id: "south", target_space_id: "P-01",
  route: { schema_version: "2.0.0", parking_lot_id: "lot-school", layout_version: "school-layout-1", cost_version: "cost-1", from_node_id: "entry", to_node_id: "access", node_ids: ["entry", "access"], edge_ids: ["entry-access"], distance_m: 18, dynamic_eta_s: 5, instructions: [{ sequence: 1, edge_id: "entry-access", text: "沿入口通道行驶", distance_m: 18, travel_time_s: 5 }] },
} as const satisfies RoutePreview;
