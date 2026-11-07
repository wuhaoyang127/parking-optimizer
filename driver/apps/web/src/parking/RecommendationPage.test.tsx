import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

import { RecommendationPage } from "./RecommendationPage";
import { conservativeServerClock } from "./serverClock";
import { facilityLayout, facilityState } from "../test/facilityFixture";
import type { ParkingLot } from "../api/recommendationClient";

const namedLot = {
  schema_version: "2.0.0", parking_lot_id: "lot-school", name: "大学创新园停车场",
  region_label: "学校", venue_type: "school", synthetic: true, opening_status: "open",
  total_spaces: 28, available_spaces: 14, charging_spaces: 4,
  pricing: { currency: "CNY", first_hour_yuan: 2, additional_hour_yuan: 2,
    daily_cap_yuan: null, note: "模拟价格" },
  updated_at: "2026-08-13T09:00:00Z",
  data_source: { schema_version: "2.0.0", parking_lot_id: "lot-school", mode: "synthetic",
    health: "healthy", source_name: "test", missing_fields: [],
    updated_at: "2026-08-13T09:00:00Z", fail_reason: null },
} satisfies ParkingLot;

const emptySnapshot = {
  schema_version: "1.0.0",
  observed_at: "2026-08-13T09:00:00Z",
  journey: null,
  recommendation: null,
  driver: null,
  waiting_since: null,
};

const context = {
  schema_version: "1.0.0",
  observed_at: "2026-08-13T09:00:00Z",
  scenario_id: "school-demo",
  parking_lot_id: "lot-school",
  layout_version: "layout-v1",
  entrances: [{ node_id: "entry", label: "南入口" }],
  spaces: [
    { parking_lot_id: "lot-school", space_id: "B-02", coordinate: { x_m: 37, y_m: 15 }, access_node_id: "access-b", status: "available", charging: false, stack_group_id: "stack-B1", depth: 2, assignable: true, assignability_reasons: [] },
    { parking_lot_id: "lot-school", space_id: "A-02", coordinate: { x_m: 41, y_m: -11 }, access_node_id: "access-a", status: "available", charging: false, stack_group_id: "independent-A-02", depth: 1, assignable: true, assignability_reasons: [] },
  ],
  tandem_groups: [{ stack_group_id: "stack-B1", space_ids_near_to_deep: ["B-01", "B-02"] }],
  data_source: { schema_version: "2.0.0", parking_lot_id: "lot-school", mode: "synthetic", health: "healthy", source_name: "test", missing_fields: [], updated_at: "2026-08-13T09:00:00Z", fail_reason: null },
};

function held(expiresAt = "2099-08-13T09:00:30Z") {
  return {
    schema_version: "2.0.0",
    journey: { schema_version: "2.0.0", journey_id: "journey-1", attempt_id: "attempt-1", session_id: "driver-test", namespace: "driver", scenario_id: "school-demo", parking_lot_id: "lot-school", state: "soft_held", version: 1, space_id: "B-02", recommendation_id: "recommendation-1", updated_at: "2026-08-13T09:00:00Z", expires_at: expiresAt, terminal_reason: null, legal_operations: ["select_alternative", "confirm", "cancel"] },
    recommendation: { schema_version: "2.0.0", recommendation_id: "recommendation-1", request_id: "request-1", parking_lot_id: "lot-school", algorithm_id: "online-rule-v2", algorithm_version: "2.0.0", data_source: context.data_source, solver_status: "success", failure_code: null, recommended_space_id: "B-02", alternative_space_ids: ["A-02"], assessments: [], route: { schema_version: "2.0.0", parking_lot_id: "lot-school", layout_version: "layout-v1", cost_version: "cost-v1", from_node_id: "entry", to_node_id: "access-b", node_ids: ["entry", "access-b"], edge_ids: ["edge-1"], distance_m: 38, dynamic_eta_s: 39, instructions: [] }, explanation_codes: ["V1_FEASIBILITY_REUSED"], degraded: false, degradation_reason: null, claim_status: "soft_held", soft_lock_expires_at: expiresAt },
  };
}

function response(payload: unknown): Response {
  return new Response(JSON.stringify(payload), { status: 200, headers: { "Content-Type": "application/json" } });
}

function requestUrl(input: RequestInfo | URL): string {
  return input instanceof Request ? input.url : input instanceof URL ? input.href : input;
}

function renderPage() {
  return render(<MemoryRouter initialEntries={["/recommend?parkingLotId=lot-school"]}><Routes><Route path="/recommend" element={<RecommendationPage />} /><Route path="/journey" element={<h1>当前行程页</h1>} /></Routes></MemoryRouter>);
}

beforeEach(() => {
  localStorage.setItem("parksim.driver-session-id.v1", "driver-test");
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  localStorage.clear();
});

describe("RecommendationPage", () => {
  test("loads the published parking lot name instead of exposing its internal ID", async () => {
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
      const url = requestUrl(input);
      return Promise.resolve(response(url.endsWith("/lot-school") ? namedLot
        : url.includes("current-journey") ? emptySnapshot : context));
    }));
    renderPage();
    expect(await screen.findByText("大学创新园停车场")).toBeInTheDocument();
    expect(screen.queryByText("lot-school", { exact: true })).not.toBeInTheDocument();
  });

  test.each(["wrong-scope", "unavailable"])("shows a visible name fallback for %s", async (failure) => {
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
      const url = requestUrl(input);
      if (url.endsWith("/lot-school")) return Promise.resolve(failure === "unavailable"
        ? new Response("{}", { status: 503 })
        : response({ ...namedLot, parking_lot_id: "lot-foreign",
          data_source: { ...namedLot.data_source, parking_lot_id: "lot-foreign" } }));
      return Promise.resolve(response(url.includes("current-journey") ? emptySnapshot : context));
    }));
    renderPage();
    expect(await screen.findByText("名称暂不可用，请返回停车场列表核对")).toBeInTheDocument();
    expect(screen.queryByText("大学创新园停车场")).not.toBeInTheDocument();
    expect(screen.queryByText("lot-school", { exact: true })).not.toBeInTheDocument();
  });

  test("cancels a pending name request when leaving the page", async () => {
    let nameSignal: AbortSignal | null | undefined;
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = requestUrl(input);
      if (url.endsWith("/lot-school")) {
        nameSignal = init?.signal;
        return new Promise<Response>(() => undefined);
      }
      return Promise.resolve(response(url.includes("current-journey") ? emptySnapshot : context));
    }));
    const { unmount } = renderPage();
    expect(await screen.findByText("正在读取停车场名称…")).toBeInTheDocument();
    unmount();
    expect(nameSignal?.aborted).toBe(true);
  });

  test("does not show a recommendation before server soft hold succeeds", async () => {
    let resolvePost: ((value: Response) => void) | undefined;
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = requestUrl(input);
      if (url.includes("current-journey")) return Promise.resolve(response(emptySnapshot));
      if (url.includes("driver-context")) return Promise.resolve(response(context));
      if (init?.method === "POST") return new Promise<Response>((resolve) => { resolvePost = resolve; });
      throw new Error("unexpected request");
    }));
    const user = userEvent.setup();
    renderPage();
    await user.click(await screen.findByRole("button", { name: "获取智能推荐" }));
    expect(screen.getByRole("button", { name: "正在校验并锁位…" })).toBeDisabled();
    expect(screen.queryByText("已为你锁定主推荐")).not.toBeInTheDocument();
    resolvePost?.(response(held()));
    expect(await screen.findByText("已为你锁定主推荐")).toBeInTheDocument();
  });

  test("sends the optional user stay estimate and visibly reports fallback", async () => {
    let body: { driver: { requested_at: string; expected_departure_at: string } } | undefined;
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = requestUrl(input);
      if (init?.method === "POST") {
        body = JSON.parse(String(init.body)) as typeof body;
        const result = held();
        return Promise.resolve(response({ ...result, recommendation: { ...result.recommendation,
          degraded: true, degradation_reason: "研究算法输入不足，已使用常规推荐" } }));
      }
      return Promise.resolve(response(url.endsWith("/lot-school") ? namedLot
        : url.includes("current-journey") ? emptySnapshot : context));
    }));
    const user = userEvent.setup();
    renderPage();
    await user.selectOptions(await screen.findByRole("combobox", { name: /预计停留/ }), "120");
    await user.click(screen.getByRole("button", { name: "获取智能推荐" }));
    expect((await screen.findAllByText("研究算法输入不足，已使用常规推荐")).length).toBeGreaterThan(0);
    expect(Date.parse(body!.driver.expected_departure_at) - Date.parse(body!.driver.requested_at)).toBe(7_200_000);
  });

  test("shows and advances a deterministic synthetic demo profile while idle", async () => {
    const normal = {
      schema_version: "1.0.0", profile_id: "normal-flow", label: "平峰通行",
      description: "空位分布较均衡。", ordinal: 1, total: 4,
    };
    const peak = {
      schema_version: "1.0.0", profile_id: "peak-remote", label: "高峰远端",
      description: "近端车位接近饱和。", ordinal: 2, total: 4,
    };
    let advanced = false;
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = requestUrl(input);
      if (url.includes("current-journey")) return Promise.resolve(response(emptySnapshot));
      if (url.includes("driver-context")) return Promise.resolve(response({ ...context, demo_profile: advanced ? peak : normal }));
      if (url.includes("facility-layout")) return Promise.resolve(response(facilityLayout));
      if (url.includes("facility-state")) return Promise.resolve(response({ ...facilityState, state_version: advanced ? "state-2" : "state-1", demo_profile: advanced ? peak : normal }));
      if (url.includes("driver-demo-profile/advance") && init?.method === "POST") {
        advanced = true;
        return Promise.resolve(response({
          schema_version: "1.0.0", demo_profile: peak,
          facility_state: { ...facilityState, state_version: "state-2", demo_profile: peak },
          parking_lot: { parking_lot_id: "lot-school" },
        }));
      }
      throw new Error(`unexpected request: ${url}`);
    }));
    const user = userEvent.setup();
    renderPage();
    expect(await screen.findByText("平峰通行")).toBeInTheDocument();
    expect(screen.getByText("模拟状态 1/4")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "换一组模拟状态" }));
    expect(await screen.findByText("高峰远端")).toBeInTheDocument();
    expect(screen.getByText(/下一次推荐将使用这组模拟状态/)).toBeInTheDocument();
  });

  test("renders tandem disclosure and one compliant alternative", async () => {
    const current = { ...emptySnapshot, journey: held().journey, recommendation: held().recommendation, driver: { schema_version: "2.0.0", request_id: "request-1", idempotency_key: "driver-1", session_id: "driver-test", parking_lot_id: "lot-school", entrance_node_id: "entry", requires_charging: false, requested_at: "2026-08-13T09:00:00Z", expected_departure_at: null } };
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => Promise.resolve(response(requestUrl(input).includes("current-journey") ? current : context))));
    renderPage();
    expect(await screen.findByText("需要你确认协同停车")).toBeInTheDocument();
    expect(screen.getByText("A-02")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "不接受，重新推荐" })).toBeInTheDocument();
    expect(screen.queryByText("online-rule-v2")).not.toBeInTheDocument();
  });

  test("keeps charging demand visible in waiting state", async () => {
    const waiting = { schema_version: "1.0.0", observed_at: "2026-08-13T09:00:10Z", waiting_since: "2026-08-13T09:00:00Z", journey: { ...held().journey, state: "waiting", space_id: null, expires_at: null, legal_operations: ["cancel", "retry_recommendation"] }, recommendation: { ...held().recommendation, solver_status: "no_feasible_space", recommended_space_id: null, alternative_space_ids: [], route: null, claim_status: "not_created_m2", soft_lock_expires_at: null }, driver: { schema_version: "2.0.0", request_id: "request-1", idempotency_key: "driver-1", session_id: "driver-test", parking_lot_id: "lot-school", entrance_node_id: "entry", requires_charging: true, requested_at: "2026-08-13T09:00:00Z", expected_departure_at: null } };
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => Promise.resolve(response(requestUrl(input).includes("current-journey") ? waiting : context))));
    renderPage();
    expect(await screen.findByText("充电需求已保留，不会自动降级为普通车位。")).toBeInTheDocument();
    expect(screen.queryByText(/队列位置/)).toBeInTheDocument();
  });

  test("calibrates the soft-hold countdown from server observed time", async () => {
    vi.spyOn(Date, "now").mockReturnValue(new Date("2040-01-01T00:00:00Z").getTime());
    vi.spyOn(performance, "now").mockReturnValue(1000);
    const calibratedHeld = held("2026-08-13T09:00:30Z");
    const current = { ...emptySnapshot, journey: calibratedHeld.journey, recommendation: calibratedHeld.recommendation, driver: { schema_version: "2.0.0", request_id: "request-1", idempotency_key: "driver-1", session_id: "driver-test", parking_lot_id: "lot-school", entrance_node_id: "entry", requires_charging: false, requested_at: "2026-08-13T09:00:00Z", expected_departure_at: null } };
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => Promise.resolve(response(requestUrl(input).includes("current-journey") ? current : context))));
    renderPage();
    expect(await screen.findByText("00:30")).toBeInTheDocument();
  });

  test("conservatively accounts for recovery request latency in the countdown", () => {
    expect(conservativeServerClock("2026-08-13T09:00:00Z", 1000, 11_000)).toEqual({
      observedAt: "2026-08-13T09:00:10.000Z",
      monotonicAt: 11_000,
    });
  });

  test("shows that an expired soft hold was released", async () => {
    const expired = { ...emptySnapshot, journey: { ...held().journey, state: "expired", expires_at: null, terminal_reason: "SOFT_HELD_EXPIRED", legal_operations: [] }, recommendation: held().recommendation, driver: { schema_version: "2.0.0", request_id: "request-1", idempotency_key: "driver-1", session_id: "driver-test", parking_lot_id: "lot-school", entrance_node_id: "entry", requires_charging: false, requested_at: "2026-08-13T09:00:00Z", expected_departure_at: null } };
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => Promise.resolve(response(requestUrl(input).includes("current-journey") ? expired : context))));
    renderPage();
    expect(await screen.findByText("车位软锁已到期并释放，请重新推荐。")).toBeInTheDocument();
  });
});
