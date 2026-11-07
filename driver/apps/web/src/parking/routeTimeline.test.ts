import { describe, expect, it } from "vitest";

import type { Route } from "../api/recommendationClient";
import { routeTimeline } from "./routeTimeline";

const route = {
  schema_version: "2.0.0",
  parking_lot_id: "lot-school",
  layout_version: "layout-1",
  cost_version: "cost-1",
  from_node_id: "entry",
  to_node_id: "space-a",
  node_ids: ["entry", "turn", "space-a"],
  edge_ids: ["edge-1", "edge-2"],
  distance_m: 40,
  dynamic_eta_s: 40,
  instructions: [
    { sequence: 1, edge_id: "edge-1", text: "前往转弯点", distance_m: 10, travel_time_s: 10 },
    { sequence: 2, edge_id: "edge-2", text: "前往车位", distance_m: 30, travel_time_s: 30 },
  ],
} satisfies Route;

describe("routeTimeline", () => {
  it("按每段服务端行驶时间推进车辆与文字步骤", () => {
    expect(routeTimeline(route, 5)).toEqual({ activeStep: 0, edgeProgress: 0.5, progress: 0.125 });
    expect(routeTimeline(route, 20)).toEqual({ activeStep: 1, edgeProgress: 1 / 3, progress: 0.5 });
  });

  it("在边界外钳制进度且不触发停车状态", () => {
    expect(routeTimeline(route, -1)).toEqual({ activeStep: 0, edgeProgress: 0, progress: 0 });
    expect(routeTimeline(route, 80)).toEqual({ activeStep: 1, edgeProgress: 1, progress: 1 });
  });

  it("将全零时长路线直接钳制到末段终点", () => {
    const zeroRoute = { ...route, instructions: route.instructions.map((instruction) => ({ ...instruction, travel_time_s: 0 })) };
    expect(routeTimeline(zeroRoute, 0)).toEqual({ activeStep: 1, edgeProgress: 1, progress: 1 });
  });
});
