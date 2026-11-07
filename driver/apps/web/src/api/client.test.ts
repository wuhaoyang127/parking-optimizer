import { afterEach, expect, test, vi } from "vitest";

import { ApiError, loadParkingDiscovery, type DiscoveryArea, type ParkingLot } from "./client";

const lot = {
  schema_version: "2.0.0", parking_lot_id: "lot-1", name: "测试停车场", region_label: "学校", venue_type: "school",
  synthetic: true, opening_status: "open", total_spaces: 8, available_spaces: 6, charging_spaces: 2,
  pricing: { currency: "CNY", first_hour_yuan: 2, additional_hour_yuan: 3, daily_cap_yuan: 30, note: "测试" },
  updated_at: "2026-08-13T09:00:00Z",
  data_source: { schema_version: "2.0.0", parking_lot_id: "lot-1", mode: "synthetic", health: "healthy", source_name: "test", missing_fields: [], updated_at: "2026-08-13T09:00:00Z", fail_reason: null },
} as const satisfies ParkingLot;
const area = {
  schema_version: "1.0.0", area_id: "area", display_version: "v1", coordinate_system: "percentage_top_left",
  synthetic: true, source_mode: "synthetic", source_health: "healthy", default_reference_id: "south",
  references: [{ reference_id: "south", label: "南侧", position: { x_pct: 46, y_pct: 84 } }],
  lots: [{ parking_lot_id: "lot-1", opening_hours_label: "每日开放", position: { x_pct: 50, y_pct: 50 }, offsite_estimates: [{ reference_id: "south", distance_m: 100, eta_s: 60 }] }],
  updated_at: "2026-08-13T09:00:00Z",
} as const satisfies DiscoveryArea;

function requestUrl(input: RequestInfo | URL): string {
  return input instanceof Request ? input.url : input instanceof URL ? input.href : input;
}

afterEach(() => { vi.unstubAllGlobals(); });

function mockPayloads(lotsPayload: unknown, areaPayload: unknown) {
  vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
    const url = input instanceof Request ? input.url : input instanceof URL ? input.href : input;
    return Promise.resolve(new Response(JSON.stringify(url.endsWith("discovery-area") ? areaPayload : lotsPayload), { status: 200 }));
  }));
}

test("loads parking and discovery contracts together", async () => {
  mockPayloads([lot], area);
  await expect(loadParkingDiscovery()).resolves.toMatchObject({ lots: [{ parking_lot_id: "lot-1" }], area: { schema_version: "1.0.0" } });
  const parkingCall = vi.mocked(fetch).mock.calls.find(([input]) => requestUrl(input).endsWith("parking-lots"));
  expect(new Headers(parkingCall?.[1]?.headers).get("X-Session-ID")).toMatch(/^driver-/);
  const discoveryCall = vi.mocked(fetch).mock.calls.find(([input]) => requestUrl(input).endsWith("discovery-area"));
  expect(new Headers(discoveryCall?.[1]?.headers).has("X-Session-ID")).toBe(false);
});

test("accepts a consistent real data pair", async () => {
  mockPayloads([{ ...lot, synthetic: false, data_source: { ...lot.data_source, mode: "real" } }], { ...area, synthetic: false, source_mode: "real" });
  await expect(loadParkingDiscovery()).resolves.toMatchObject({ area: { synthetic: false } });
});

test("fails closed when source modes are mixed", async () => {
  mockPayloads([lot], { ...area, synthetic: false, source_mode: "real" });
  await expect(loadParkingDiscovery()).rejects.toMatchObject({ code: "DISCOVERY_SCOPE_MISMATCH" });
});

test.each([
  [[{ ...lot, available_spaces: -1 }], area],
  [[lot], { ...area, lots: [{ ...area.lots[0], position: { x_pct: 101, y_pct: 50 } }] }],
  [[lot], { ...area, lots: [{ ...area.lots[0], offsite_estimates: [{ reference_id: "south", distance_m: Number.NaN, eta_s: 60 }] }] }],
])("rejects malformed nested payloads", async (lotsPayload, areaPayload) => {
  mockPayloads(lotsPayload, areaPayload);
  await expect(loadParkingDiscovery()).rejects.toMatchObject({ code: "CONTRACT_MISMATCH" });
});

test("preserves a structured 503 response", async () => {
  vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(new Response(JSON.stringify({ code: "DATA_SOURCE_UNAVAILABLE", message: "not configured", request_id: "req-test", details: [] }), { status: 503 }))));
  await expect(loadParkingDiscovery()).rejects.toEqual(new ApiError(503, "DATA_SOURCE_UNAVAILABLE", "not configured", "req-test"));
});

test("rejects an already aborted caller without issuing requests", async () => {
  const controller = new AbortController();
  controller.abort();
  const fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
  await expect(loadParkingDiscovery(controller.signal)).rejects.toMatchObject({ name: "AbortError" });
  expect(fetchMock).not.toHaveBeenCalled();
});

test("propagates an abort raised while both resources are loading", async () => {
  const controller = new AbortController();
  vi.stubGlobal("fetch", vi.fn((_input: RequestInfo | URL, init?: RequestInit) => new Promise((_resolve, reject) => {
    init?.signal?.addEventListener("abort", () => { reject(new DOMException("aborted", "AbortError")); }, { once: true });
  })));
  const pending = loadParkingDiscovery(controller.signal);
  controller.abort();
  await expect(pending).rejects.toMatchObject({ name: "AbortError" });
});

test("rejects an incomplete structured error as an unexpected API error", async () => {
  vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(new Response(JSON.stringify({ code: "BROKEN", message: "missing request id" }), { status: 503 }))));
  await expect(loadParkingDiscovery()).rejects.toMatchObject({ code: "UNEXPECTED_API_ERROR" });
});

test("rejects duplicate or incomplete discovery references", async () => {
  mockPayloads([lot], {
    ...area,
    references: [...area.references, area.references[0]],
  });
  await expect(loadParkingDiscovery()).rejects.toMatchObject({ code: "CONTRACT_MISMATCH" });
});

test("turns a ten-second request timeout into an explicit API error", async () => {
  vi.useFakeTimers();
  vi.stubGlobal("fetch", vi.fn((_input: RequestInfo | URL, init?: RequestInit) => new Promise((_resolve, reject) => {
    init?.signal?.addEventListener("abort", () => { reject(new DOMException("aborted", "AbortError")); }, { once: true });
  })));
  try {
    const pending = loadParkingDiscovery();
    const assertion = expect(pending).rejects.toMatchObject({ code: "REQUEST_TIMEOUT" });
    await vi.advanceTimersByTimeAsync(10_000);
    await assertion;
  } finally {
    vi.useRealTimers();
  }
});
