import { describe, expect, test } from "vitest";

import type {
  DriverTandemArrivalReplay,
  DriverTandemDepartureReplay,
} from "../api/recommendationClient";
import { facilityLayout, facilityState } from "../test/facilityFixture";
import { tandemReplayFrame } from "./tandemReplay";

const route = {
  schema_version: "2.0.0" as const,
  parking_lot_id: facilityLayout.parking_lot_id,
  layout_version: facilityLayout.layout_version,
  cost_version: "cost-r6",
  from_node_id: "entry",
  to_node_id: "space-a",
  node_ids: ["entry", "junction", "space-a"],
  edge_ids: ["edge-entry", "edge-space"],
  distance_m: 20,
  dynamic_eta_s: 4,
  instructions: [
    { sequence: 1, edge_id: "edge-entry", text: "第一段", distance_m: 10, travel_time_s: 2 },
    { sequence: 2, edge_id: "edge-space", text: "第二段", distance_m: 10, travel_time_s: 2 },
  ],
};

function location<const Kind extends "space" | "buffer" | "exit" | "approach">(
  kind: Kind,
  id: string,
  nodeId: string,
  x: number,
  y: number,
) {
  return { kind, location_id: id, node_id: nodeId, floor_id: "floor-1", coordinate: { x_m: x, y_m: y } };
}

const replay = {
  schema_version: "1.0.0",
  replay_id: "replay-1",
  created_at: "2026-08-21T09:00:00Z",
  journey_id: "journey-1",
  parking_lot_id: facilityLayout.parking_lot_id,
  layout_version: facilityLayout.layout_version,
  scenario_version: "scenario-r6",
  state_version: "state-r6",
  cost_version: "cost-r6",
  profile_id: "tandem-focus",
  stack_group_id: "stack-1",
  target_space_id: "A-01",
  blocker_vehicle_ids: ["blocker-B-01"],
  buffer_ids: ["BUF-01"],
  steps: [
    { sequence: 1, action: "relocate_to_buffer", actor_id: "blocker-B-01", actor_role: "blocker", label: "移至缓冲位", from_location: location("space", "B-01", "entry", 5, 5), to_location: location("buffer", "BUF-01", "space-a", 25, 10), route, starts_at_s: 0, duration_s: 4 },
    { sequence: 2, action: "direct_exit", actor_id: "journey-1", actor_role: "driver", label: "当前车辆离场", from_location: location("space", "A-01", "entry", 8, 5), to_location: location("exit", "exit-1", "space-a", 25, 10), route, starts_at_s: 4, duration_s: 4 },
    { sequence: 3, action: "restore_original", actor_id: "blocker-B-01", actor_role: "blocker", label: "返回原位", from_location: location("buffer", "BUF-01", "entry", 25, 10), to_location: location("space", "B-01", "space-a", 5, 5), route, starts_at_s: 8, duration_s: 4 },
  ],
  total_duration_s: 12,
  before_sha256: "1".repeat(64),
  after_sha256: "2".repeat(64),
  facility_state: {
    ...facilityState,
    scenario_version: "scenario-r6",
    state_version: "state-r6",
    demo_profile: { schema_version: "1.0.0", profile_id: "tandem-focus", label: "纵深协同", description: "测试回放快照", ordinal: 4, total: 4 },
  },
  final_journey: {
    schema_version: "2.0.0", journey_id: "journey-1", attempt_id: "attempt-1", session_id: "session-1", namespace: "driver", scenario_id: "scenario-r6", parking_lot_id: facilityLayout.parking_lot_id, state: "departed", version: 5, space_id: "A-01", recommendation_id: "recommendation-1", updated_at: "2026-08-21T09:00:12Z", expires_at: null, terminal_reason: "NORMAL_DEPARTURE", legal_operations: [],
  },
} satisfies DriverTandemDepartureReplay;

const entryRoute = {
  ...route,
  from_node_id: "entry",
  to_node_id: "entry",
  node_ids: ["entry"],
  edge_ids: [],
  distance_m: 0,
  dynamic_eta_s: 0,
  instructions: [],
};

const arrivalReplay = {
  schema_version: "1.0.0",
  replay_id: "arrival-replay-1",
  created_at: "2026-08-21T08:59:00Z",
  journey_id: "journey-1",
  parking_lot_id: facilityLayout.parking_lot_id,
  layout_version: facilityLayout.layout_version,
  scenario_version: "scenario-r6",
  before_state_version: "state-r6-before",
  after_state_version: "state-r6-after",
  cost_version: "cost-r6",
  profile_id: "tandem-focus",
  stack_group_id: "stack-1",
  target_space_id: "A-01",
  blocker_vehicle_ids: ["blocker-B-01"],
  buffer_ids: ["BUF-01"],
  steps: [
    { sequence: 1, action: "relocate_to_buffer", actor_id: "blocker-B-01", actor_role: "blocker", label: "移至缓冲位", from_location: location("space", "B-01", "entry", 5, 5), to_location: location("buffer", "BUF-01", "space-a", 25, 10), route, starts_at_s: 0, duration_s: 4 },
    { sequence: 2, action: "direct_entry", actor_id: "journey-1", actor_role: "driver", label: "当前车辆入位", from_location: location("approach", "A-01:approach", "entry", 2, 5), to_location: location("space", "A-01", "entry", 8, 5), route: entryRoute, starts_at_s: 4, duration_s: 4 },
    { sequence: 3, action: "restore_original", actor_id: "blocker-B-01", actor_role: "blocker", label: "返回原位", from_location: location("buffer", "BUF-01", "entry", 25, 10), to_location: location("space", "B-01", "space-a", 5, 5), route, starts_at_s: 8, duration_s: 4 },
  ],
  total_duration_s: 12,
  before_sha256: "3".repeat(64),
  after_sha256: "4".repeat(64),
  before_facility_state: {
    ...facilityState,
    scenario_version: "scenario-r6",
    state_version: "state-r6-before",
    demo_profile: { schema_version: "1.0.0", profile_id: "tandem-focus", label: "纵深协同", description: "入位前", ordinal: 4, total: 4 },
  },
  after_facility_state: {
    ...facilityState,
    scenario_version: "scenario-r6",
    state_version: "state-r6-after",
    demo_profile: { schema_version: "1.0.0", profile_id: "tandem-focus", label: "纵深协同", description: "入位后", ordinal: 4, total: 4 },
  },
  final_journey: {
    schema_version: "2.0.0", journey_id: "journey-1", attempt_id: "attempt-1", session_id: "session-1", namespace: "driver", scenario_id: "scenario-r6", parking_lot_id: facilityLayout.parking_lot_id, state: "occupied", version: 4, space_id: "A-01", recommendation_id: "recommendation-1", updated_at: "2026-08-21T09:00:00Z", expires_at: null, terminal_reason: null, legal_operations: ["depart", "reset_demo"],
  },
} satisfies DriverTandemArrivalReplay;

describe("tandemReplayFrame", () => {
  test("moves blocker, then driver, then restores blocker in server order", () => {
    const first = tandemReplayFrame(facilityLayout, replay, 2);
    expect(first.activeStep).toBe(0);
    expect(first.actors.find((actor) => actor.role === "blocker")).toBeDefined();
    const second = tandemReplayFrame(facilityLayout, replay, 6);
    expect(second.activeStep).toBe(1);
    const final = tandemReplayFrame(facilityLayout, replay, 12);
    expect(final.complete).toBe(true);
    expect(final.actors.find((actor) => actor.role === "blocker")).toMatchObject({ x_m: 5, y_m: 5 });
    expect(final.hiddenOccupiedSpaceIds).toEqual(["A-01", "B-01"]);
  });

  test("supports reduced-motion manual stage snapshots", () => {
    expect(tandemReplayFrame(facilityLayout, replay, 0, 0).completedSteps).toBe(0);
    expect(tandemReplayFrame(facilityLayout, replay, 0, 1).completedSteps).toBe(1);
    expect(tandemReplayFrame(facilityLayout, replay, 0, 3).complete).toBe(true);
  });

  test("interpolates the explicit deep-space entry even when both locations share one access node", () => {
    const entering = tandemReplayFrame(facilityLayout, arrivalReplay, 6);
    expect(entering.activeStep).toBe(1);
    expect(entering.actors.find((actor) => actor.role === "driver")).toMatchObject({
      x_m: 5,
      y_m: 5,
    });
    const complete = tandemReplayFrame(facilityLayout, arrivalReplay, 12);
    expect(complete.complete).toBe(true);
    expect(complete.actors.find((actor) => actor.role === "driver")).toMatchObject({
      x_m: 8,
      y_m: 5,
    });
  });
});
