import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { App } from "./App";
import type { DiscoveryArea, ParkingLot } from "./api/client";

const lot = {
  schema_version: "2.0.0",
  parking_lot_id: "lot-school",
  name: "大学创新园停车场",
  region_label: "学校",
  venue_type: "school",
  synthetic: true,
  opening_status: "open",
  total_spaces: 8,
  available_spaces: 6,
  charging_spaces: 2,
  pricing: { currency: "CNY", first_hour_yuan: 2, additional_hour_yuan: 3, daily_cap_yuan: 30, note: "模拟价格" },
  updated_at: "2026-08-12T09:00:00Z",
  data_source: { schema_version: "2.0.0", parking_lot_id: "lot-school", mode: "synthetic", health: "healthy", source_name: "test", missing_fields: [], updated_at: "2026-08-12T09:00:00Z", fail_reason: null },
} as const satisfies ParkingLot;

const area = {
  schema_version: "1.0.0",
  area_id: "test-area",
  display_version: "test-v1",
  coordinate_system: "percentage_top_left",
  synthetic: true,
  source_mode: "synthetic",
  source_health: "healthy",
  default_reference_id: "south",
  references: [{ reference_id: "south", label: "南侧参考点", position: { x_pct: 46, y_pct: 84 } }],
  lots: [{ parking_lot_id: "lot-school", opening_hours_label: "每日开放", position: { x_pct: 53, y_pct: 39 }, offsite_estimates: [{ reference_id: "south", distance_m: 680, eta_s: 150 }] }],
  updated_at: "2026-08-13T09:00:00Z",
} as const satisfies DiscoveryArea;

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
    const url = input instanceof Request ? input.url : input instanceof URL ? input.href : input;
    const payload = url.endsWith("current-journey")
      ? { schema_version: "1.0.0", observed_at: "2026-08-13T09:00:00Z", journey: null, recommendation: null, driver: null, waiting_since: null }
      : url.endsWith("current-trip")
        ? { schema_version: "1.0.0", observed_at: "2026-08-13T09:00:00Z", journey: null, driver: null, current_route: null, current_node_id: null, last_replan: null, started_at: null, parked_at: null, ended_at: null, recent_events: [], recent_trips: [], tandem_arrival_replay_enabled: false, tandem_arrival_replay: null, tandem_departure_replay_enabled: false, tandem_departure_replay: null }
      : url.endsWith("discovery-area") ? area : [lot];
    return Promise.resolve(new Response(JSON.stringify(payload), { status: 200, headers: { "Content-Type": "application/json" } }));
  }));
});

afterEach(() => {
  vi.unstubAllGlobals();
});

test("renders the driver shell with visible data-source boundary", async () => {
  render(<App />, { wrapper: MemoryRouter });
  expect(screen.getByText("数据来源已标注")).toBeInTheDocument();
  expect(screen.getByRole("note")).toHaveTextContent("Synthetic");
  expect(await screen.findByText("固定 synthetic 场景")).toBeInTheDocument();
  expect(screen.queryByText("答辩模式")).not.toBeInTheDocument();
});

test("all three driver pages are reachable", async () => {
  const user = userEvent.setup();
  render(<App />, { wrapper: MemoryRouter });
  await user.click(screen.getByRole("link", { name: "智能停车" }));
  expect(await screen.findByRole("heading", { name: "请先选择停车场" })).toBeInTheDocument();
  await user.click(screen.getByRole("link", { name: "当前行程" }));
  expect(await screen.findByRole("heading", { name: "还没有进行中的停车行程" })).toBeInTheDocument();
});
