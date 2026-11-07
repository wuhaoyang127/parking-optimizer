import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import type { DiscoveryArea, ParkingLot } from "../api/client";
import { ParkingDiscoveryPage } from "./ParkingDiscoveryPage";

const lots: ParkingLot[] = ([
  { parking_lot_id: "lot-school", name: "大学创新园停车场", region_label: "学校", venue_type: "school" },
  { parking_lot_id: "lot-hospital", name: "市立医院停车场", region_label: "医院", venue_type: "hospital" },
] as const).map((item) => ({
  schema_version: "2.0.0", ...item,
  synthetic: true, opening_status: "open", total_spaces: 8, available_spaces: 6, charging_spaces: 2,
  pricing: { currency: "CNY", first_hour_yuan: 2, additional_hour_yuan: 3, daily_cap_yuan: 30, note: "测试价格" },
  updated_at: "2026-08-13T09:00:00Z",
  data_source: { schema_version: "2.0.0", parking_lot_id: item.parking_lot_id, mode: "synthetic", health: "healthy", source_name: "test", missing_fields: [], updated_at: "2026-08-13T09:00:00Z", fail_reason: null },
}));
const area = {
  schema_version: "1.0.0", area_id: "area", display_version: "v1", coordinate_system: "percentage_top_left", synthetic: true, source_mode: "synthetic", source_health: "healthy", default_reference_id: "south",
  references: [{ reference_id: "south", label: "南侧参考点", position: { x_pct: 46, y_pct: 84 } }, { reference_id: "west", label: "西侧参考点", position: { x_pct: 12, y_pct: 48 } }],
  lots: lots.map((lot, index) => ({ parking_lot_id: lot.parking_lot_id, opening_hours_label: "每日开放", position: { x_pct: index === 0 ? 53 : 20, y_pct: index === 0 ? 39 : 66 }, offsite_estimates: [{ reference_id: "south", distance_m: index === 0 ? 680 : 920, eta_s: 150 }, { reference_id: "west", distance_m: index === 0 ? 620 : 310, eta_s: 90 }] })),
  updated_at: "2026-08-13T09:00:00Z",
} satisfies DiscoveryArea;

let fetchMock: ReturnType<typeof vi.fn>;
beforeEach(() => {
  fetchMock = vi.fn((input: RequestInfo | URL) => {
    const url = input instanceof Request ? input.url : input instanceof URL ? input.href : input;
    return Promise.resolve(new Response(JSON.stringify(url.endsWith("discovery-area") ? area : lots), { status: 200 }));
  });
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => { vi.unstubAllGlobals(); });

function renderPage(path = "/parking") {
  render(<MemoryRouter initialEntries={[path]}><Routes><Route path="/parking" element={<ParkingDiscoveryPage />} /><Route path="/parking/:parkingLotId" element={<ParkingDiscoveryPage />} /><Route path="/recommend" element={<h1>推荐页</h1>} /></Routes></MemoryRouter>);
}

test("searches and switches reference without refetching", async () => {
  const user = userEvent.setup();
  renderPage();
  expect(await screen.findByRole("heading", { name: "更快找到合适的车位" })).toBeInTheDocument();
  expect(fetchMock).toHaveBeenCalledTimes(2);
  await user.type(screen.getByRole("searchbox"), "医院");
  expect(screen.queryByText("大学创新园停车场")).not.toBeInTheDocument();
  expect(screen.getAllByText("市立医院停车场")).not.toHaveLength(0);
  await user.click(screen.getByRole("button", { name: "西侧参考点" }));
  expect(within(screen.getByRole("complementary")).getByText("310 米 · 约 2 分钟")).toBeInTheDocument();
  expect(fetchMock).toHaveBeenCalledTimes(2);
});

test("direct URL, selection and unknown ID stay explicit", async () => {
  const user = userEvent.setup();
  renderPage("/parking/lot-school");
  expect(await screen.findByRole("heading", { name: "大学创新园停车场" })).toBeInTheDocument();
  await user.click(within(screen.getByLabelText("停车场列表")).getByRole("button", { name: /市立医院停车场/ }));
  expect(await screen.findByRole("heading", { name: "市立医院停车场" })).toBeInTheDocument();
  expect(fetchMock).toHaveBeenCalledTimes(2);
});

test("shows a dedicated unknown parking lot state", async () => {
  renderPage("/parking/not-present");
  expect(await screen.findByRole("heading", { name: "未找到该停车场" })).toBeInTheDocument();
});

test("shows a dedicated empty-source state", async () => {
  const emptyArea = { ...area, lots: [] };
  fetchMock.mockImplementation((input: RequestInfo | URL) => {
    const url = input instanceof Request ? input.url : input instanceof URL ? input.href : input;
    return new Response(JSON.stringify(url.endsWith("discovery-area") ? emptyArea : []), { status: 200 });
  });
  renderPage();
  await waitFor(() => { expect(screen.getByRole("heading", { name: "当前没有可展示的停车场" })).toBeInTheDocument(); });
});

test("shows an explicit loading state while discovery requests are pending", () => {
  const pendingResponse = new Promise<Response>(() => {
    // Intentionally pending so the component remains in its loading state.
  });
  fetchMock.mockReturnValue(pendingResponse);
  renderPage();
  const heading = screen.getByRole("heading", { name: "正在读取停车场" });
  expect(heading.closest("section")).toHaveAttribute("aria-busy", "true");
});

test("shows an offline state when the network rejects discovery requests", async () => {
  fetchMock.mockRejectedValue(new TypeError("network unavailable"));
  renderPage();
  expect(await screen.findByRole("heading", { name: "当前处于离线状态" })).toBeInTheDocument();
  expect(screen.getByText("无法连接停车场服务，请检查本地后端或网络连接")).toBeInTheDocument();
});

test("shows a fail-closed 503 state", async () => {
  fetchMock.mockImplementation(() => new Response(JSON.stringify({ code: "DATA_SOURCE_UNAVAILABLE", message: "not configured", request_id: "req-test", details: [] }), { status: 503 }));
  renderPage();
  expect(await screen.findByRole("heading", { name: "停车场数据源暂时不可用" })).toBeInTheDocument();
});

test("makes degraded discovery visible and blocks unknown opening status", async () => {
  const degradedArea = { ...area, source_health: "degraded" as const };
  const unknownLots = [{ ...lots[0], opening_status: "unknown" as const }, lots[1]];
  fetchMock.mockImplementation((input: RequestInfo | URL) => {
    const url = input instanceof Request ? input.url : input instanceof URL ? input.href : input;
    return new Response(JSON.stringify(url.endsWith("discovery-area") ? degradedArea : unknownLots), { status: 200 });
  });
  renderPage("/parking/lot-school");
  expect(await screen.findByText("Synthetic 区域摘要已降级")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "营业状态未知，暂不可选择" })).toBeDisabled();
});
