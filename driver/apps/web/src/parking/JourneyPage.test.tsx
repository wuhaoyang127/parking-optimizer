import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { StrictMode } from "react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

import type { ParkingFacilityLayout, ParkingFacilityState } from "../api/facilityClient";
import type { DriverTripSnapshot, Journey, ParkingLot, Route } from "../api/recommendationClient";
import { facilityLayout as baseFacilityLayout, facilityState as baseFacilityState } from "../test/facilityFixture";
import { JourneyPage } from "./JourneyPage";
import { facilityForTandemReplay } from "./journeyReplayFacility";

const route = {
  schema_version: "2.0.0", parking_lot_id: "lot-school", layout_version: "layout-1", cost_version: "cost-1",
  from_node_id: "entry", to_node_id: "space-a", node_ids: ["entry", "turn", "space-a"], edge_ids: ["edge-1", "edge-2"],
  distance_m: 40, dynamic_eta_s: 40,
  instructions: [
    { sequence: 1, edge_id: "edge-1", text: "沿主通道前行", distance_m: 10, travel_time_s: 10 },
    { sequence: 2, edge_id: "edge-2", text: "前往目标车位", distance_m: 30, travel_time_s: 30 },
  ],
} satisfies Route;

const journey = {
  schema_version: "2.0.0", journey_id: "journey-1", attempt_id: "attempt-1", session_id: "driver-test", namespace: "driver",
  scenario_id: "school-demo", parking_lot_id: "lot-school", state: "session_reserved", version: 2, space_id: "A-01",
  recommendation_id: "recommendation-1", updated_at: "2026-08-13T09:00:00Z", expires_at: "2099-08-13T09:30:00Z",
  terminal_reason: null, legal_operations: ["start_navigation", "cancel"],
} satisfies Journey;

const driver = {
  schema_version: "2.0.0", request_id: "request-1", idempotency_key: "driver-1", session_id: "driver-test",
  parking_lot_id: "lot-school", entrance_node_id: "entry", requires_charging: false,
  requested_at: "2026-08-13T09:00:00Z", expected_departure_at: null,
} as const;

const snapshot = {
  schema_version: "1.0.0", observed_at: "2026-08-13T09:00:00Z", journey, driver, current_route: route,
  current_node_id: "entry", last_replan: null, started_at: null, parked_at: null, ended_at: null,
  recent_events: [], recent_trips: [], tandem_arrival_replay_enabled: false, tandem_arrival_replay: null,
  tandem_departure_replay_enabled: false, tandem_departure_replay: null,
} satisfies DriverTripSnapshot;

const layout = {
  ...baseFacilityLayout,
  layout_version: "layout-1",
  nodes: [
    { node_id: "entry", floor_id: "floor-1", label: "南入口", kind: "entrance", coordinate: { x_m: 2, y_m: 15 } },
    { node_id: "turn", floor_id: "floor-1", label: "中央转角", kind: "junction", coordinate: { x_m: 12, y_m: 15 } },
    { node_id: "space-a", floor_id: "floor-1", label: "A 区入口", kind: "space_access", coordinate: { x_m: 32, y_m: 15 } },
    { node_id: "exit", floor_id: "floor-1", label: "北出口", kind: "exit", coordinate: { x_m: 38, y_m: 15 } },
  ],
  edges: [
    { edge_id: "edge-1", from_node_id: "entry", to_node_id: "turn", centerline: [{ x_m: 2, y_m: 15 }, { x_m: 7, y_m: 18 }, { x_m: 12, y_m: 15 }], width_m: 5, distance_m: 10, base_travel_time_s: 10, directed: false, traversal_kind: "drive", channel_zone_ids: [] },
    { edge_id: "edge-2", from_node_id: "turn", to_node_id: "space-a", centerline: [{ x_m: 12, y_m: 15 }, { x_m: 22, y_m: 15 }, { x_m: 32, y_m: 15 }], width_m: 5, distance_m: 30, base_travel_time_s: 30, directed: false, traversal_kind: "drive", channel_zone_ids: [] },
    { edge_id: "edge-3", from_node_id: "space-a", to_node_id: "exit", centerline: [{ x_m: 32, y_m: 15 }, { x_m: 38, y_m: 15 }], width_m: 5, distance_m: 6, base_travel_time_s: 3, directed: true, traversal_kind: "drive", channel_zone_ids: [] },
  ],
  entrances: [{ entrance_id: "south", node_id: "entry", label: "南入口", initial_heading_deg: 0 }],
  exits: [{ exit_id: "north", node_id: "exit", label: "北出口" }],
  spaces: [
    { parking_lot_id: "lot-school", space_id: "A-01", floor_id: "floor-1", zone_id: "parking", geometry: { center: { x_m: 32, y_m: 9 }, width_m: 2.6, length_m: 5.2, heading_deg: 90 }, access_node_id: "space-a", charging: false, stack_group_id: null, depth: 1 },
    { parking_lot_id: "lot-school", space_id: "B-01", floor_id: "floor-1", zone_id: "parking", geometry: { center: { x_m: 25, y_m: 9 }, width_m: 2.6, length_m: 5.2, heading_deg: 90 }, access_node_id: "space-a", charging: false, stack_group_id: null, depth: 1 },
  ],
  tandem_groups: [], buffers: [],
} satisfies ParkingFacilityLayout;

interface TripStateProjection { journey?: { state: string } | null }

function facilityStateFor(trip: TripStateProjection): ParkingFacilityState {
  const journeyState = trip.journey?.state;
  const target = journeyState === "occupied"
    ? { observed_status: "occupied" as const, claim_status: "none" as const, effective_status: "occupied" as const, assignable: false, reason_codes: ["SPACE_OCCUPIED"] }
    : { observed_status: "available" as const, claim_status: journeyState === "navigating" ? "navigating" as const : "session_reserved" as const, effective_status: "unavailable" as const, assignable: false, reason_codes: ["SESSION_CLAIMED"] };
  return {
    ...baseFacilityState,
    layout_version: "layout-1",
    scenario_id: "school-demo",
    spaces: [
      { space_id: "A-01", observation_source: "synthetic_truth", ...target },
      { space_id: "B-01", observed_status: "occupied", observation_source: "synthetic_truth", claim_status: "none", effective_status: "occupied", assignable: false, reason_codes: ["SPACE_OCCUPIED"] },
    ],
    buffers: [],
  };
}

const lot = {
  schema_version: "2.0.0", parking_lot_id: "lot-school", name: "大学创新园停车场", region_label: "学校", venue_type: "school",
  synthetic: true, opening_status: "open", total_spaces: 8, available_spaces: 6, charging_spaces: 2,
  pricing: { currency: "CNY", first_hour_yuan: 2, additional_hour_yuan: 3, daily_cap_yuan: 30, note: "模拟价格" },
  updated_at: "2026-08-13T09:00:00Z",
  data_source: { schema_version: "2.0.0", parking_lot_id: "lot-school", mode: "synthetic", health: "healthy", source_name: "test", missing_fields: [], updated_at: "2026-08-13T09:00:00Z", fail_reason: null },
} satisfies ParkingLot;

function response(payload: unknown): Response {
  return new Response(JSON.stringify(payload), { status: 200, headers: { "Content-Type": "application/json" } });
}

function urlOf(input: RequestInfo | URL): string {
  return input instanceof Request ? input.url : input instanceof URL ? input.href : input;
}

function fixtureFor(url: string, trip: TripStateProjection = snapshot, facilityLayout: ParkingFacilityLayout = layout): unknown {
  if (url.endsWith("facility-layout")) return facilityLayout;
  if (url.endsWith("facility-state")) return facilityStateFor(trip);
  if (url.endsWith("lot-school")) return lot;
  throw new Error(`unexpected ${url}`);
}

beforeEach(() => {
  localStorage.setItem("parksim.driver-session-id.v1", "driver-test");
  Object.defineProperty(document, "visibilityState", { configurable: true, value: "visible" });
});
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); vi.useRealTimers(); localStorage.clear(); });

describe("JourneyPage", () => {
  test("renders recovered tandem replay against its embedded authoritative facility state", () => {
    const replayState = {
      ...facilityStateFor({ journey: { state: "occupied" } }),
      state_version: "state-r6",
      scenario_version: "scenario-r6",
      demo_profile: { schema_version: "1.0.0", profile_id: "tandem-focus", label: "纵深协同", description: "权威回放快照", ordinal: 4, total: 4 },
    } satisfies ParkingFacilityState;
    const replaySnapshot = {
      tandem_departure_replay: {
        parking_lot_id: "lot-school",
        layout_version: "layout-1",
        scenario_version: "scenario-r6",
        state_version: "state-r6",
        profile_id: "tandem-focus",
        facility_state: replayState,
      },
    } as unknown as DriverTripSnapshot;
    const result = facilityForTandemReplay(replaySnapshot, {
      layout,
      state: { ...replayState, state_version: "state-normal-flow", demo_profile: { ...replayState.demo_profile, profile_id: "normal-flow", label: "平峰通行", ordinal: 1 } },
    });
    expect(result.state).toBe(replayState);
    expect(result.state.demo_profile?.profile_id).toBe("tandem-focus");

    const mismatched = {
      ...replaySnapshot,
      tandem_departure_replay: { ...replaySnapshot.tandem_departure_replay, state_version: "state-other" },
    } as DriverTripSnapshot;
    expect(() => facilityForTandemReplay(mismatched, { layout, state: replayState })).toThrow("回放与权威设施快照不一致");
  });

  test("renders one authoritative route and starts navigation only after user action", async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = urlOf(input);
      if (init?.method === "POST") return Promise.resolve(response({ ...journey, state: "navigating", version: 3, legal_operations: ["replan", "occupy"] }));
      if (url.endsWith("current-trip")) return Promise.resolve(response(snapshot));
      return Promise.resolve(response(fixtureFor(url)));
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<MemoryRouter><JourneyPage /></MemoryRouter>);
    expect(await screen.findByRole("heading", { name: "车位已预留" })).toBeInTheDocument();
    expect(screen.getByText("南入口 → A-01")).toBeInTheDocument();
    expect(within(screen.getByLabelText("当前指引")).getByText("沿主通道前行")).toBeInTheDocument();
    expect(screen.getByRole("progressbar", { name: "路线演示进度" })).toHaveAttribute("aria-valuenow", "0");
    expect(screen.getByRole("application", { name: "当前行程完整停车场布局" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /A-01.*当前行程目标/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /B-01.*occupied/ })).toBeInTheDocument();
    expect(screen.getByText("当前行程目标 A-01 · 已为本行程预留")).toBeInTheDocument();
    expect(fetchMock.mock.calls.some((call) => call[1]?.method === "POST")).toBe(false);
    await userEvent.click(screen.getByRole("button", { name: "开始场内指引" }));
    await waitFor(() => { expect(fetchMock.mock.calls.some((call) => call[1]?.method === "POST")).toBe(true); });
    await waitFor(() => { expect(fetchMock.mock.calls.filter((call) => urlOf(call[0]).endsWith("current-trip")).length).toBeGreaterThanOrEqual(4); });
  });

  test("inspects another space locally without changing the journey target or posting", async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = urlOf(input);
      void init;
      return Promise.resolve(response(url.endsWith("current-trip") ? snapshot : fixtureFor(url)));
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<MemoryRouter><JourneyPage /></MemoryRouter>);
    await userEvent.click(await screen.findByRole("button", { name: /B-01.*occupied/ }));
    expect(screen.getByText("只读查看 B-01 · 行程目标仍为 A-01 · 占用")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /A-01.*当前行程目标/ })).toBeInTheDocument();
    expect(fetchMock.mock.calls.some((call) => call[1]?.method === "POST")).toBe(false);
  });

  test("accepts a facility view only when the trip sandwich read is stable", async () => {
    const navigating = { ...snapshot, journey: { ...journey, state: "navigating" as const, version: 3, legal_operations: ["occupy"] }, started_at: "2026-08-13T09:00:00Z" } satisfies DriverTripSnapshot;
    let tripReads = 0;
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
      const url = urlOf(input);
      if (url.endsWith("current-trip")) {
        tripReads += 1;
        return Promise.resolve(response(tripReads === 1 ? snapshot : navigating));
      }
      return Promise.resolve(response(fixtureFor(url, tripReads <= 1 ? snapshot : navigating)));
    }));
    render(<MemoryRouter><JourneyPage /></MemoryRouter>);
    expect(await screen.findByRole("heading", { name: "正在前往车位" })).toBeInTheDocument();
    expect(tripReads).toBe(3);
  });

  test("aborts the complete sandwich read without committing after unmount", async () => {
    let tripReads = 0;
    let releaseSecondTrip: () => void = () => { throw new Error("second trip read was not initialized"); };
    const pendingSecondTrip = new Promise<Response>((resolve) => {
      releaseSecondTrip = () => { resolve(response(snapshot)); };
    });
    const signals: AbortSignal[] = [];
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = urlOf(input);
      if (init?.signal) signals.push(init.signal);
      if (url.endsWith("current-trip")) {
        tripReads += 1;
        return tripReads === 1 ? Promise.resolve(response(snapshot)) : pendingSecondTrip;
      }
      return Promise.resolve(response(fixtureFor(url)));
    }));
    const { unmount } = render(<MemoryRouter><JourneyPage /></MemoryRouter>);
    await waitFor(() => { expect(tripReads).toBe(2); });
    expect(signals.length).toBeGreaterThanOrEqual(5);
    expect(new Set(signals).size).toBe(1);
    const recoverySignal = signals[0];
    unmount();
    expect(recoverySignal?.aborted).toBe(true);
    releaseSecondTrip();
    await Promise.resolve();
  });

  test("starts a fresh recovery when StrictMode replays an aborted effect", async () => {
    const signals: AbortSignal[] = [];
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = urlOf(input);
      if (init?.signal) signals.push(init.signal);
      return Promise.resolve(response(url.endsWith("current-trip") ? snapshot : fixtureFor(url)));
    }));
    render(<StrictMode><MemoryRouter><JourneyPage /></MemoryRouter></StrictMode>);
    expect(await screen.findByRole("heading", { name: "车位已预留" })).toBeInTheDocument();
    const distinctSignals = [...new Set(signals)];
    expect(distinctSignals).toHaveLength(2);
    expect(distinctSignals[0]?.aborted).toBe(true);
    expect(distinctSignals[1]?.aborted).toBe(false);
    expect(screen.queryByRole("heading", { name: "暂时无法读取行程" })).not.toBeInTheDocument();
  });

  test("fails closed when two sandwich attempts both observe a changing trip", async () => {
    let tripReads = 0;
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
      const url = urlOf(input);
      if (url.endsWith("current-trip")) {
        tripReads += 1;
        return Promise.resolve(response({ ...snapshot, journey: { ...journey, version: tripReads + 1 } }));
      }
      return Promise.resolve(response(fixtureFor(url)));
    }));
    render(<MemoryRouter><JourneyPage /></MemoryRouter>);
    expect(await screen.findByRole("heading", { name: "暂时无法读取行程" })).toBeInTheDocument();
    expect(screen.getByText("行程已在其他页面发生变化，正在读取最新状态。")).toBeInTheDocument();
    expect(tripReads).toBe(3);
  });

  test("fails closed when the target claim does not match the journey state", async () => {
    const mismatched = { ...facilityStateFor(snapshot), spaces: facilityStateFor(snapshot).spaces.map((space) => space.space_id === "A-01" ? { ...space, claim_status: "none" as const } : space) };
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
      const url = urlOf(input);
      if (url.endsWith("current-trip")) return Promise.resolve(response(snapshot));
      if (url.endsWith("facility-state")) return Promise.resolve(response(mismatched));
      return Promise.resolve(response(fixtureFor(url)));
    }));
    render(<MemoryRouter><JourneyPage /></MemoryRouter>);
    expect(await screen.findByText("当前行程与目标车位声明状态不一致")).toBeInTheDocument();
  });

  test("keeps route and vehicle static when reduced motion is requested", async () => {
    const navigating = { ...snapshot, journey: { ...journey, state: "navigating" as const, version: 3, legal_operations: ["occupy"] }, started_at: "2026-08-13T09:00:00Z" } satisfies DriverTripSnapshot;
    vi.stubGlobal("matchMedia", vi.fn(() => ({ matches: true, media: "(prefers-reduced-motion: reduce)", onchange: null, addListener: vi.fn(), removeListener: vi.fn(), addEventListener: vi.fn(), removeEventListener: vi.fn(), dispatchEvent: vi.fn() })));
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => Promise.resolve(response(urlOf(input).endsWith("current-trip") ? navigating : fixtureFor(urlOf(input), navigating)))));
    const { container } = render(<MemoryRouter><JourneyPage /></MemoryRouter>);
    expect(await screen.findByRole("application", { name: "当前行程完整停车场布局" })).toBeInTheDocument();
    expect(container.querySelector(".facility-route-layer")).not.toHaveClass("motion");
    expect(container.querySelector(".facility-vehicle")).toBeInTheDocument();
    expect(screen.getByText("当前行程目标 A-01 · 行程使用中")).toBeInTheDocument();
  });

  test("stops route flow and vehicle ticks while the page is hidden", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const navigating = { ...snapshot, journey: { ...journey, state: "navigating" as const, version: 3, legal_operations: ["occupy"] }, started_at: "2026-08-13T09:00:00Z" } satisfies DriverTripSnapshot;
    vi.stubGlobal("matchMedia", vi.fn(() => ({ matches: false, media: "(prefers-reduced-motion: reduce)", onchange: null, addListener: vi.fn(), removeListener: vi.fn(), addEventListener: vi.fn(), removeEventListener: vi.fn(), dispatchEvent: vi.fn() })));
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => Promise.resolve(response(urlOf(input).endsWith("current-trip") ? navigating : fixtureFor(urlOf(input), navigating)))));
    const { container } = render(<MemoryRouter><JourneyPage /></MemoryRouter>);
    expect(await screen.findByRole("application", { name: "当前行程完整停车场布局" })).toBeInTheDocument();
    expect(container.querySelector(".facility-route-layer")).toHaveClass("motion");
    Object.defineProperty(document, "visibilityState", { configurable: true, value: "hidden" });
    document.dispatchEvent(new Event("visibilitychange"));
    await waitFor(() => { expect(container.querySelector(".facility-route-layer")).not.toHaveClass("motion"); });
    const transform = container.querySelector(".facility-vehicle")?.getAttribute("transform");
    await vi.advanceTimersByTimeAsync(1_000);
    expect(container.querySelector(".facility-vehicle")?.getAttribute("transform")).toBe(transform);
    Object.defineProperty(document, "visibilityState", { configurable: true, value: "visible" });
    document.dispatchEvent(new Event("visibilitychange"));
    await waitFor(() => { expect(container.querySelector(".facility-route-layer")).toHaveClass("motion"); });
    await vi.advanceTimersByTimeAsync(500);
    expect(container.querySelector(".facility-vehicle")?.getAttribute("transform")).not.toBe(transform);
  });

  test("fails closed when a route edge does not match the layout", async () => {
    const broken = { ...layout, edges: layout.edges.map((edge, index) => index === 0 ? { ...edge, edge_id: "another-edge" } : edge) };
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
      const url = urlOf(input);
      return Promise.resolve(response(url.endsWith("current-trip") ? snapshot : fixtureFor(url, snapshot, broken)));
    }));
    render(<MemoryRouter><JourneyPage /></MemoryRouter>);
    expect(await screen.findByRole("heading", { name: "暂时无法读取行程" })).toBeInTheDocument();
    expect(screen.getByText("路线边或目标车位与布局不一致")).toBeInTheDocument();
  });

  test("fails closed on an orphaned empty-trip projection", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(response({
      schema_version: "1.0.0", observed_at: "2026-08-13T09:00:00Z", journey: null, driver: null,
      current_route: null, current_node_id: null, last_replan: null, started_at: "2026-08-13T09:00:00Z",
      parked_at: null, ended_at: null, recent_events: [], recent_trips: [],
      tandem_arrival_replay_enabled: false, tandem_arrival_replay: null,
      tandem_departure_replay_enabled: false, tandem_departure_replay: null,
    }))));
    render(<MemoryRouter><JourneyPage /></MemoryRouter>);
    expect(await screen.findByRole("heading", { name: "暂时无法读取行程" })).toBeInTheDocument();
    expect(screen.getByText("空行程快照包含了不应存在的路线")).toBeInTheDocument();
  });

  test("fails closed when a lifecycle timestamp is invalid", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(response({ ...snapshot, started_at: "not-a-time" }))));
    render(<MemoryRouter><JourneyPage /></MemoryRouter>);
    expect(await screen.findByRole("heading", { name: "暂时无法读取行程" })).toBeInTheDocument();
    expect(screen.getByText("当前行程、会话与路线不一致")).toBeInTheDocument();
  });

  test("fails closed when a warning replan omits its reason codes", async () => {
    const malformed = {
      ...snapshot,
      journey: { ...journey, state: "navigating", version: 3 },
      started_at: "2026-08-13T09:00:00Z",
      last_replan: {
        schema_version: "2.0.0", status: "warning", trigger: "cost_update", previous_route: route, route,
        remaining_reservation_s: 50, eta_with_safety_margin_s: 80,
        cost_snapshot: { schema_version: "2.0.0", parking_lot_id: "lot-school", layout_version: "layout-1", cost_version: "cost-1", observed_at: "2026-08-13T09:00:05Z", edge_travel_time_s: { "edge-1": 10, "edge-2": 30 }, unavailable_edge_ids: [] },
      },
    };
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(response(malformed))));
    render(<MemoryRouter><JourneyPage /></MemoryRouter>);
    expect(await screen.findByRole("heading", { name: "暂时无法读取行程" })).toBeInTheDocument();
    expect(screen.getByText("当前行程、会话与路线不一致")).toBeInTheDocument();
  });

  test("fails closed when a warning route crosses layout versions", async () => {
    const changedRoute = { ...route, layout_version: "layout-2" };
    const malformed = {
      ...snapshot,
      current_route: changedRoute,
      journey: { ...journey, state: "navigating", version: 3 },
      started_at: "2026-08-13T09:00:00Z",
      last_replan: {
        schema_version: "2.0.0", status: "warning", trigger: "cost_update", previous_route: route, route: changedRoute,
        reason_codes: ["ETA_EXCEEDS_RESERVATION"], remaining_reservation_s: 50, eta_with_safety_margin_s: 80,
        cost_snapshot: { schema_version: "2.0.0", parking_lot_id: "lot-school", layout_version: "layout-1", cost_version: "cost-1", observed_at: "2026-08-13T09:00:05Z", edge_travel_time_s: { "edge-1": 10, "edge-2": 30 }, unavailable_edge_ids: [] },
      },
    };
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(response(malformed))));
    render(<MemoryRouter><JourneyPage /></MemoryRouter>);
    expect(await screen.findByRole("heading", { name: "暂时无法读取行程" })).toBeInTheDocument();
    expect(screen.getByText("当前行程、会话与路线不一致")).toBeInTheDocument();
  });

  test("fails closed when a replan reuses the cost version with different route timing", async () => {
    const changedRoute = { ...route, dynamic_eta_s: 41, instructions: route.instructions.map((instruction, index) => index === 0 ? { ...instruction, travel_time_s: 11 } : instruction) };
    const malformed = {
      ...snapshot,
      journey: { ...journey, state: "navigating", version: 3 },
      started_at: "2026-08-13T09:00:00Z",
      last_replan: {
        schema_version: "2.0.0", status: "success", trigger: "cost_update", previous_route: route, route: changedRoute,
        reason_codes: ["ROUTE_CHANGED"], remaining_reservation_s: 50, eta_with_safety_margin_s: 45,
        cost_snapshot: { schema_version: "2.0.0", parking_lot_id: "lot-school", layout_version: "layout-1", cost_version: "cost-1", observed_at: "2026-08-13T09:00:05Z", edge_travel_time_s: { "edge-1": 11, "edge-2": 30 }, unavailable_edge_ids: [] },
      },
    };
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(response(malformed))));
    render(<MemoryRouter><JourneyPage /></MemoryRouter>);
    expect(await screen.findByRole("heading", { name: "暂时无法读取行程" })).toBeInTheDocument();
    expect(screen.getByText("当前行程、会话与路线不一致")).toBeInTheDocument();
  });

  test("hides reservation time after parking is authoritative", async () => {
    const occupied = { ...snapshot, journey: { ...journey, state: "occupied", expires_at: null, legal_operations: ["depart", "reset_demo"] }, current_route: null, current_node_id: null, started_at: "2026-08-13T09:00:01Z", parked_at: "2026-08-13T09:00:20Z" };
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => Promise.resolve(response(urlOf(input).endsWith("current-trip") ? occupied : fixtureFor(urlOf(input), occupied)))));
    render(<MemoryRouter><JourneyPage /></MemoryRouter>);
    expect((await screen.findAllByRole("heading", { name: "已确认停入" })).length).toBeGreaterThan(0);
    expect(screen.queryByText("服务端预留剩余")).not.toBeInTheDocument();
  });

  test("recovers the authoritative expired state when the server deadline reaches zero", async () => {
    let tripReads = 0;
    const due = { ...snapshot, observed_at: "2026-08-13T09:30:00Z", journey: { ...journey, expires_at: "2026-08-13T09:30:00Z" } };
    const expired = { ...snapshot, observed_at: "2026-08-13T09:30:01Z", journey: { ...journey, state: "expired", expires_at: null, terminal_reason: "SOFT_HELD_EXPIRED", legal_operations: [] }, current_route: null, current_node_id: null };
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
      const url = urlOf(input);
      if (url.endsWith("current-trip")) { tripReads += 1; return Promise.resolve(response(tripReads === 1 ? due : expired)); }
      return Promise.resolve(response(fixtureFor(url, tripReads === 1 ? due : expired)));
    }));
    render(<MemoryRouter><JourneyPage /></MemoryRouter>);
    expect((await screen.findAllByRole("heading", { name: "预留已到期" })).length).toBeGreaterThan(0);
    expect(tripReads).toBeGreaterThanOrEqual(2);
  });

  test("uses the matching replan cost observation as the new animation anchor", async () => {
    vi.spyOn(performance, "now").mockReturnValue(1000);
    const navigating = {
      ...snapshot,
      observed_at: "2026-08-13T09:00:05Z",
      journey: { ...journey, state: "navigating", version: 3, legal_operations: ["replan", "occupy"] },
      started_at: "2026-08-13T08:00:00Z",
      last_replan: {
        schema_version: "2.0.0", status: "success", trigger: "deviation", previous_route: route, route,
        reason_codes: ["ROUTE_CHANGED"], remaining_reservation_s: 100, eta_with_safety_margin_s: 40,
        cost_snapshot: { schema_version: "2.0.0", parking_lot_id: "lot-school", layout_version: "layout-1", cost_version: "cost-1", observed_at: "2026-08-13T09:00:05Z", edge_travel_time_s: { "edge-1": 10, "edge-2": 30 }, unavailable_edge_ids: [] },
      },
    };
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => Promise.resolve(response(urlOf(input).endsWith("current-trip") ? navigating : fixtureFor(urlOf(input), navigating)))));
    render(<MemoryRouter><JourneyPage /></MemoryRouter>);
    expect(await screen.findByText("已行进 0%")).toBeInTheDocument();
    expect(screen.getByText("正在前往车位")).toBeInTheDocument();
  });

  test("submits only the safe demo action and refreshes the authoritative trip", async () => {
    const navigating = {
      ...snapshot,
      journey: { ...journey, state: "navigating", version: 3, legal_operations: ["driver_demo_replan", "occupy"] },
      started_at: "2026-08-13T09:00:00Z",
    } satisfies DriverTripSnapshot;
    const postBodies: unknown[] = [];
    let tripReads = 0;
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = urlOf(input);
      if (init?.method === "POST") {
        if (typeof init.body !== "string") throw new Error("expected JSON body");
        postBodies.push(JSON.parse(init.body) as unknown);
        return Promise.resolve(response({
          schema_version: "2.0.0",
          journey: { ...navigating.journey, version: 4 },
          decision: {
            schema_version: "2.0.0", status: "success", trigger: "deviation", previous_route: route, route,
            reason_codes: ["ROUTE_CHANGED"], remaining_reservation_s: 120, eta_with_safety_margin_s: 80,
            cost_snapshot: { schema_version: "2.0.0", parking_lot_id: "lot-school", layout_version: "layout-1", cost_version: "cost-1", observed_at: "2026-08-13T09:00:10Z", edge_travel_time_s: { "edge-1": 10, "edge-2": 30 }, unavailable_edge_ids: [] },
          },
        }));
      }
      if (url.endsWith("current-trip")) { tripReads += 1; return Promise.resolve(response(navigating)); }
      return Promise.resolve(response(fixtureFor(url, navigating)));
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<MemoryRouter><JourneyPage /></MemoryRouter>);
    await userEvent.click(await screen.findByRole("button", { name: "模拟偏航" }));
    await waitFor(() => { expect(postBodies).toHaveLength(1); });
    expect(postBodies[0]).toMatchObject({ schema_version: "2.0.0", expected_version: 3, action: "simulate_deviation" });
    expect(postBodies[0]).not.toHaveProperty("current_node_id");
    expect(postBodies[0]).not.toHaveProperty("channel_load");
    expect(tripReads).toBeGreaterThanOrEqual(2);
  });

  test("stops the old route after an unreachable replan and obeys capability guards", async () => {
    const failed = {
      ...snapshot,
      journey: { ...journey, state: "navigating", version: 4, legal_operations: ["reassign"] },
      current_node_id: "off-route",
      started_at: "2026-08-13T09:00:00Z",
      last_replan: {
        schema_version: "2.0.0", status: "failed", trigger: "deviation", previous_route: route, route: null,
        reason_codes: ["DYNAMIC_ROUTE_UNREACHABLE"], remaining_reservation_s: 100, eta_with_safety_margin_s: null,
        cost_snapshot: { schema_version: "2.0.0", parking_lot_id: "lot-school", layout_version: "layout-1", cost_version: "cost-2", observed_at: "2026-08-13T09:00:05Z", edge_travel_time_s: { "edge-1": 10, "edge-2": 30 }, unavailable_edge_ids: ["edge-1"] },
      },
    } satisfies DriverTripSnapshot;
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => Promise.resolve(response(urlOf(input).endsWith("current-trip") ? failed : fixtureFor(urlOf(input), failed)))));
    render(<MemoryRouter><JourneyPage /></MemoryRouter>);
    expect(await screen.findByText("路线暂不可达 · 动画已停止")).toBeInTheDocument();
    expect(screen.queryByLabelText("当前行程完整停车场布局")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "再次检查路线" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "重新推荐" })).toBeEnabled();
  });

  test("offers both ETA-window choices and keeps continue as a local acknowledgement", async () => {
    const warning = {
      ...snapshot,
      journey: { ...journey, state: "navigating", version: 4, legal_operations: ["reassign", "occupy"] },
      started_at: "2026-08-13T09:00:00Z",
      last_replan: {
        schema_version: "2.0.0", status: "warning", trigger: "cost_update", previous_route: route, route,
        reason_codes: ["ETA_EXCEEDS_RESERVATION"], remaining_reservation_s: 50, eta_with_safety_margin_s: 80,
        cost_snapshot: { schema_version: "2.0.0", parking_lot_id: "lot-school", layout_version: "layout-1", cost_version: "cost-1", observed_at: "2026-08-13T09:00:05Z", edge_travel_time_s: { "edge-1": 10, "edge-2": 30 }, unavailable_edge_ids: [] },
      },
    } satisfies DriverTripSnapshot;
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === "POST") throw new Error("continue must not POST");
      return Promise.resolve(response(urlOf(input).endsWith("current-trip") ? warning : fixtureFor(urlOf(input), warning)));
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<MemoryRouter><JourneyPage /></MemoryRouter>);
    expect(await screen.findByText("预计到达时间可能超过当前预留窗口")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "继续当前路线" }));
    expect(screen.queryByText("预计到达时间可能超过当前预留窗口")).not.toBeInTheDocument();
    expect(fetchMock.mock.calls.some((call) => call[1]?.method === "POST")).toBe(false);
  });

  test("moves a recovered replacement journey back to the recommendation page", async () => {
    function LocationProbe() { return <output>{useLocation().pathname}{useLocation().search}</output>; }
    const replacement = { ...snapshot, journey: { ...journey, state: "waiting", version: 1, space_id: null, expires_at: null, legal_operations: ["retry_recommendation", "cancel"] }, current_route: null, current_node_id: null } satisfies DriverTripSnapshot;
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => Promise.resolve(response(urlOf(input).endsWith("current-trip") ? replacement : fixtureFor(urlOf(input), replacement)))));
    render(<MemoryRouter initialEntries={["/journey"]}><JourneyPage /><LocationProbe /></MemoryRouter>);
    expect(await screen.findByText("/recommend?parkingLotId=lot-school")).toBeInTheDocument();
  });

  test("reassigns an ETA warning with the explicit reason and follows the recovered replacement", async () => {
    function LocationProbe() { const location = useLocation(); return <output>{location.pathname}{location.search}</output>; }
    const warning = {
      ...snapshot,
      journey: { ...journey, state: "navigating", version: 4, legal_operations: ["reassign"] },
      started_at: "2026-08-13T09:00:00Z",
      last_replan: {
        schema_version: "2.0.0", status: "warning", trigger: "cost_update", previous_route: route, route,
        reason_codes: ["ETA_EXCEEDS_RESERVATION"], remaining_reservation_s: 50, eta_with_safety_margin_s: 80,
        cost_snapshot: { schema_version: "2.0.0", parking_lot_id: "lot-school", layout_version: "layout-1", cost_version: "cost-1", observed_at: "2026-08-13T09:00:05Z", edge_travel_time_s: { "edge-1": 10, "edge-2": 30 }, unavailable_edge_ids: [] },
      },
    } satisfies DriverTripSnapshot;
    const waitingJourney = { ...journey, journey_id: "journey-new", attempt_id: "attempt-new", state: "waiting" as const, version: 1, space_id: null, recommendation_id: "recommendation-new", expires_at: null, legal_operations: ["retry_recommendation", "cancel"] };
    const waitingSnapshot = { ...snapshot, journey: waitingJourney, current_route: null, current_node_id: null, last_replan: null } satisfies DriverTripSnapshot;
    let replaced = false;
    let posted: Record<string, unknown> | null = null;
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = urlOf(input);
      if (init?.method === "POST") {
        if (typeof init.body !== "string") throw new Error("expected JSON body");
        posted = JSON.parse(init.body) as Record<string, unknown>;
        replaced = true;
        return Promise.resolve(response({
          schema_version: "1.0.0",
          ended_journey: { ...warning.journey, state: "failed", version: 5, expires_at: null, terminal_reason: "ETA_EXCEEDS_RESERVATION", legal_operations: [] },
          replacement: {
            journey: waitingJourney,
            recommendation: { schema_version: "2.0.0", recommendation_id: "recommendation-new", parking_lot_id: "lot-school", algorithm_id: "online-rule-v2", solver_status: "no_feasible_space", recommended_space_id: null, alternative_space_ids: [], route: null, explanation_codes: ["NO_FEASIBLE_SPACE"], assessments: [], claim_status: "not_created_m2", soft_lock_expires_at: null, data_source: lot.data_source },
          },
        }));
      }
      if (url.endsWith("current-trip")) return Promise.resolve(response(replaced ? waitingSnapshot : warning));
      return Promise.resolve(response(fixtureFor(url, replaced ? waitingSnapshot : warning)));
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<MemoryRouter initialEntries={["/journey"]}><JourneyPage /><LocationProbe /></MemoryRouter>);
    await userEvent.click(await screen.findByRole("button", { name: "重新推荐" }));
    expect(await screen.findByText("/recommend?parkingLotId=lot-school")).toBeInTheDocument();
    expect(posted).toMatchObject({ reason: "eta_exceeds_reservation", expected_version: 4 });
  });

  test("parks only after explicit confirmation and then offers guarded departure actions", async () => {
    const navigating = { ...snapshot, journey: { ...journey, state: "navigating", version: 3, legal_operations: ["occupy"] }, started_at: "2026-08-13T09:00:00Z" } satisfies DriverTripSnapshot;
    const occupiedJourney = { ...journey, state: "occupied" as const, version: 4, expires_at: null, terminal_reason: null, legal_operations: ["depart", "reset_demo"] };
    const occupied = { ...snapshot, journey: occupiedJourney, current_route: null, current_node_id: null, started_at: "2026-08-13T09:00:00Z", parked_at: "2026-08-13T09:00:20Z" } satisfies DriverTripSnapshot;
    let parked = false;
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = urlOf(input);
      if (init?.method === "POST" && url.endsWith("occupy")) { parked = true; return Promise.resolve(response(occupiedJourney)); }
      if (url.endsWith("current-trip")) return Promise.resolve(response(parked ? occupied : navigating));
      return Promise.resolve(response(fixtureFor(url, parked ? occupied : navigating)));
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<MemoryRouter><JourneyPage /></MemoryRouter>);
    await userEvent.click(await screen.findByRole("button", { name: "我已停入" }));
    expect(await screen.findByRole("button", { name: "正常离场" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "演示重置" })).toBeEnabled();
    expect(screen.queryByText("服务端预留剩余")).not.toBeInTheDocument();
  });

  test.each([
    ["推荐位被占", "report-external-occupancy", undefined, "EXTERNAL_SPACE_OCCUPIED", "2.0.0"],
    ["无法停入", "reassign", "unable_to_park", "USER_UNABLE_TO_PARK", "1.0.0"],
  ])("%s ends the old journey and follows the authoritative replacement", async (label, endpoint, reason, terminalReason, schemaVersion) => {
    function LocationProbe() { const location = useLocation(); return <output>{location.pathname}{location.search}</output>; }
    const navigating = { ...snapshot, journey: { ...journey, state: "navigating", version: 3, legal_operations: ["report_external_occupancy", "reassign"] }, started_at: "2026-08-13T09:00:00Z" } satisfies DriverTripSnapshot;
    const replacementJourney = { ...journey, journey_id: "journey-replacement", attempt_id: "attempt-replacement", state: "waiting" as const, version: 1, space_id: null, recommendation_id: "recommendation-replacement", expires_at: null, legal_operations: ["retry_recommendation", "cancel"] };
    const replacementSnapshot = { ...snapshot, journey: replacementJourney, current_route: null, current_node_id: null } satisfies DriverTripSnapshot;
    let replaced = false;
    let posted: Record<string, unknown> | null = null;
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = urlOf(input);
      if (init?.method === "POST") {
        expect(url).toContain(endpoint);
        if (typeof init.body !== "string") throw new Error("expected JSON body");
        posted = JSON.parse(init.body) as Record<string, unknown>;
        replaced = true;
        return Promise.resolve(response({
          schema_version: schemaVersion,
          [endpoint === "reassign" ? "ended_journey" : "failed_journey"]: { ...navigating.journey, state: "failed", version: 4, expires_at: null, terminal_reason: terminalReason, legal_operations: [] },
          replacement: { journey: replacementJourney, recommendation: { schema_version: "2.0.0", recommendation_id: "recommendation-replacement", parking_lot_id: "lot-school", algorithm_id: "online-rule-v2", solver_status: "no_feasible_space", recommended_space_id: null, alternative_space_ids: [], route: null, explanation_codes: ["NO_FEASIBLE_SPACE"], assessments: [], claim_status: "not_created_m2", soft_lock_expires_at: null, data_source: lot.data_source } },
        }));
      }
      if (url.endsWith("current-trip")) return Promise.resolve(response(replaced ? replacementSnapshot : navigating));
      return Promise.resolve(response(fixtureFor(url, replaced ? replacementSnapshot : navigating)));
    }));
    render(<MemoryRouter initialEntries={["/journey"]}><JourneyPage /><LocationProbe /></MemoryRouter>);
    await userEvent.click(await screen.findByRole("button", { name: label }));
    expect(await screen.findByText("/recommend?parkingLotId=lot-school")).toBeInTheDocument();
    if (reason !== undefined) expect(posted).toMatchObject({ reason });
  });

  test.each([
    ["正常离场", "depart", "NORMAL_DEPARTURE"],
    ["演示重置", "reset-demo", "DEMO_RESET"],
  ])("%s recovers the matching departed reason", async (label, endpoint, terminalReason) => {
    const occupiedJourney = { ...journey, state: "occupied" as const, version: 4, expires_at: null, terminal_reason: null, legal_operations: ["depart", "reset_demo"] };
    const occupied = { ...snapshot, journey: occupiedJourney, current_route: null, current_node_id: null, started_at: "2026-08-13T09:00:00Z", parked_at: "2026-08-13T09:00:20Z" } satisfies DriverTripSnapshot;
    const departedJourney = { ...occupiedJourney, state: "departed" as const, version: 5, terminal_reason: terminalReason, legal_operations: [] };
    const departed = { ...occupied, journey: departedJourney, ended_at: "2026-08-13T09:01:00Z" } satisfies DriverTripSnapshot;
    let done = false;
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = urlOf(input);
      if (init?.method === "POST") { expect(url).toContain(endpoint); done = true; return Promise.resolve(response(departedJourney)); }
      if (url.endsWith("current-trip")) return Promise.resolve(response(done ? departed : occupied));
      return Promise.resolve(response(fixtureFor(url, done ? departed : occupied)));
    }));
    render(<MemoryRouter><JourneyPage /></MemoryRouter>);
    await userEvent.click(await screen.findByRole("button", { name: label }));
    expect((await screen.findAllByRole("heading", { name: "本次行程已结束" })).length).toBeGreaterThan(0);
  });

  test("recovers a newer authoritative state after a multi-tab 409", async () => {
    const navigating = { ...snapshot, journey: { ...journey, state: "navigating", version: 3, legal_operations: ["occupy"] }, started_at: "2026-08-13T09:00:00Z" } satisfies DriverTripSnapshot;
    const occupied = { ...snapshot, journey: { ...journey, state: "occupied", version: 4, expires_at: null, legal_operations: ["depart", "reset_demo"] }, current_route: null, current_node_id: null, started_at: "2026-08-13T09:00:00Z", parked_at: "2026-08-13T09:00:20Z" } satisfies DriverTripSnapshot;
    let conflicted = false;
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = urlOf(input);
      if (init?.method === "POST") { conflicted = true; return Promise.resolve(new Response(JSON.stringify({ code: "VERSION_CONFLICT", message: "changed elsewhere", request_id: "req-409" }), { status: 409, headers: { "Content-Type": "application/json" } })); }
      if (url.endsWith("current-trip")) return Promise.resolve(response(conflicted ? occupied : navigating));
      return Promise.resolve(response(fixtureFor(url, conflicted ? occupied : navigating)));
    }));
    render(<MemoryRouter><JourneyPage /></MemoryRouter>);
    await userEvent.click(await screen.findByRole("button", { name: "我已停入" }));
    expect(await screen.findByRole("button", { name: "正常离场" })).toBeEnabled();
    expect(screen.queryByText("行程已在其他页面发生变化，正在读取最新状态。")).not.toBeInTheDocument();
  });

  test("keeps the last route visible with an offline warning when a command and recovery both fail", async () => {
    const navigating = { ...snapshot, journey: { ...journey, state: "navigating", version: 3, legal_operations: ["occupy"] }, started_at: "2026-08-13T09:00:00Z" } satisfies DriverTripSnapshot;
    let offline = false;
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = urlOf(input);
      if (init?.method === "POST") { offline = true; return Promise.reject(new Error("offline")); }
      if (offline && url.endsWith("current-trip")) return Promise.reject(new Error("offline"));
      return Promise.resolve(response(url.endsWith("current-trip") ? navigating : fixtureFor(url, navigating)));
    }));
    render(<MemoryRouter><JourneyPage /></MemoryRouter>);
    await userEvent.click(await screen.findByRole("button", { name: "我已停入" }));
    expect(await screen.findByText("当前处于离线状态。已保留上次同步画面，重新连接后可恢复行程。")).toBeInTheDocument();
    expect(screen.getByLabelText("当前行程完整停车场布局")).toBeInTheDocument();
  });
});
