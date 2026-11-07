import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { facilityLayout, facilityState, routePreview } from "../test/facilityFixture";
import { FacilityLayoutPage } from "./FacilityLayoutPage";

let fetchMock = vi.fn<typeof fetch>();

function LocationProbe() { return <output aria-label="location">{useLocation().search}</output>; }

beforeEach(() => {
  fetchMock = vi.fn<typeof fetch>((input) => {
    const url = input instanceof Request ? input.url : input instanceof URL ? input.href : input;
    const payload = url.endsWith("facility-layout") ? facilityLayout : url.endsWith("route-previews") ? routePreview : facilityState;
    return Promise.resolve(new Response(JSON.stringify(payload), { status: 200, headers: { "Content-Type": "application/json" } }));
  });
  vi.stubGlobal("fetch", fetchMock);
  Object.defineProperty(document, "visibilityState", { configurable: true, value: "visible" });
});

afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers(); });

function renderPage(path = "/parking/lot-school/layout") {
  render(<MemoryRouter initialEntries={[path]}><Routes><Route path="/parking/:parkingLotId/layout" element={<><FacilityLayoutPage /><LocationProbe /></>} /><Route path="/parking/:parkingLotId" element={<h1>停车场详情</h1>} /><Route path="/parking" element={<h1>停车场列表</h1>} /></Routes></MemoryRouter>);
}

test("selects a space, syncs URL, previews route and controls zoom", async () => {
  const user = userEvent.setup();
  renderPage();
  expect(await screen.findByRole("heading", { name: "停车场全景" })).toBeInTheDocument();
  expect(screen.getByLabelText("停车场状态统计")).toHaveTextContent("空闲1");
  expect(screen.getByRole("application", { name: "完整停车场布局" })).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: /P-01/ }));
  expect(screen.getByRole("button", { name: "P-01，available" })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /P-01.*当前行程目标/ })).not.toBeInTheDocument();
  expect(screen.getByLabelText("location")).toHaveTextContent("space=P-01");
  await user.click(screen.getByRole("button", { name: "查看场内路线" }));
  expect(await screen.findByText("18 米 · 约 5 秒")).toBeInTheDocument();
  expect(fetchMock.mock.calls.some(([, init]) => init?.method === "POST")).toBe(true);
  expect(screen.getByText("1.0×")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "放大" }));
  expect(screen.getByText("1.4×")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "重置视图" }));
  expect(screen.getByText("1.0×")).toBeInTheDocument();
});

test("rejects unknown URL references instead of guessing", async () => {
  const user = userEvent.setup();
  renderPage("/parking/lot-school/layout?space=missing&entrance=south");
  expect(await screen.findByRole("heading", { name: "布局链接已失效" })).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "打开默认布局" }));
  expect(await screen.findByRole("heading", { name: "停车场全景" })).toBeInTheDocument();
  expect(screen.getByLabelText("location")).not.toHaveTextContent("space=missing");
});

test("clears a preview when polling reports target unavailable", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
  let stateCalls = 0;
  fetchMock.mockImplementation((input) => {
    const url = input instanceof Request ? input.url : input instanceof URL ? input.href : input;
    if (url.endsWith("facility-layout")) return Promise.resolve(new Response(JSON.stringify(facilityLayout), { status: 200 }));
    if (url.endsWith("route-previews")) return Promise.resolve(new Response(JSON.stringify(routePreview), { status: 200 }));
    stateCalls += 1;
    const state = stateCalls < 2 ? facilityState : { ...facilityState, state_version: "state-2", spaces: [{ ...facilityState.spaces[0], assignable: false, effective_status: "unavailable", reason_codes: ["SESSION_CLAIMED"] }, facilityState.spaces[1]] };
    return Promise.resolve(new Response(JSON.stringify(state), { status: 200 }));
  });
  renderPage("/parking/lot-school/layout?space=P-01&entrance=south");
  expect(await screen.findByRole("heading", { name: "停车场全景" })).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "查看场内路线" }));
  expect(await screen.findByText("18 米 · 约 5 秒")).toBeInTheDocument();
  await vi.advanceTimersByTimeAsync(3100);
  await waitFor(() => { expect(screen.queryByText("18 米 · 约 5 秒")).not.toBeInTheDocument(); });
  expect(screen.getByRole("button", { name: "查看场内路线" })).toBeDisabled();
});

test("does not commit a delayed route after the URL target changes", async () => {
  const user = userEvent.setup();
  let resolveRoute: ((response: Response) => void) | undefined;
  fetchMock.mockImplementation((input) => {
    const url = input instanceof Request ? input.url : input instanceof URL ? input.href : input;
    if (url.endsWith("facility-layout")) return Promise.resolve(new Response(JSON.stringify(facilityLayout), { status: 200 }));
    if (url.endsWith("route-previews")) return new Promise<Response>((resolve) => { resolveRoute = resolve; });
    return Promise.resolve(new Response(JSON.stringify(facilityState), { status: 200 }));
  });
  renderPage("/parking/lot-school/layout?space=P-01&entrance=south");
  expect(await screen.findByRole("heading", { name: "停车场全景" })).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "查看场内路线" }));
  await user.click(screen.getByRole("button", { name: /P-02/ }));
  resolveRoute?.(new Response(JSON.stringify(routePreview), { status: 200 }));
  await waitFor(() => { expect(screen.getByLabelText("location")).toHaveTextContent("space=P-02"); });
  expect(screen.queryByText("18 米 · 约 5 秒")).not.toBeInTheDocument();
});

test("pauses polling while hidden and refreshes once visible", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  let stateCalls = 0;
  fetchMock.mockImplementation((input) => {
    const url = input instanceof Request ? input.url : input instanceof URL ? input.href : input;
    if (url.endsWith("facility-layout")) return Promise.resolve(new Response(JSON.stringify(facilityLayout), { status: 200 }));
    stateCalls += 1;
    return Promise.resolve(new Response(JSON.stringify(facilityState), { status: 200 }));
  });
  Object.defineProperty(document, "visibilityState", { configurable: true, value: "hidden" });
  renderPage();
  expect(await screen.findByRole("heading", { name: "停车场全景" })).toBeInTheDocument();
  await vi.advanceTimersByTimeAsync(6100);
  expect(stateCalls).toBe(1);
  Object.defineProperty(document, "visibilityState", { configurable: true, value: "visible" });
  document.dispatchEvent(new Event("visibilitychange"));
  await waitFor(() => { expect(stateCalls).toBe(2); });
});

test("keeps state polling single-flight while a refresh is pending", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  let stateCalls = 0;
  let resolveRefresh: ((response: Response) => void) | undefined;
  fetchMock.mockImplementation((input) => {
    const url = input instanceof Request ? input.url : input instanceof URL ? input.href : input;
    if (url.endsWith("facility-layout")) return Promise.resolve(new Response(JSON.stringify(facilityLayout), { status: 200 }));
    stateCalls += 1;
    if (stateCalls === 1) return Promise.resolve(new Response(JSON.stringify(facilityState), { status: 200 }));
    return new Promise<Response>((resolve) => { resolveRefresh = resolve; });
  });
  renderPage();
  expect(await screen.findByRole("heading", { name: "停车场全景" })).toBeInTheDocument();
  await vi.advanceTimersByTimeAsync(6500);
  expect(stateCalls).toBe(2);
  resolveRefresh?.(new Response(JSON.stringify(facilityState), { status: 200 }));
  await vi.advanceTimersByTimeAsync(0);
});

test("allows a global entrance while viewing another floor", async () => {
  const multiFloor = structuredClone(facilityLayout) as unknown as Record<string, unknown>;
  (multiFloor.floors as Record<string, unknown>[]).push({ floor_id: "floor-2", label: "地下层", elevation_m: -4, bounds: { min_x_m: 0, min_y_m: 0, max_x_m: 40, max_y_m: 30 } });
  fetchMock.mockImplementation((input) => {
    const url = input instanceof Request ? input.url : input instanceof URL ? input.href : input;
    const payload = url.endsWith("facility-layout") ? multiFloor : facilityState;
    return Promise.resolve(new Response(JSON.stringify(payload), { status: 200 }));
  });
  renderPage("/parking/lot-school/layout?floor=floor-2&entrance=south");
  expect(await screen.findByRole("heading", { name: "停车场全景" })).toBeInTheDocument();
  expect(screen.queryByRole("heading", { name: "布局链接已失效" })).not.toBeInTheDocument();
  expect(screen.getByLabelText("楼层")).toHaveValue("floor-2");
  expect(screen.getByLabelText("路线入口")).toHaveValue("south");
});
