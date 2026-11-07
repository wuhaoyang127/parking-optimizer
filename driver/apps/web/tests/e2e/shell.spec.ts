import { expect, test, type Page } from "@playwright/test";

import { facilityLayout, facilityState, routePreview } from "../../src/test/facilityFixture";

const lots = [
  { schema_version: "2.0.0", parking_lot_id: "lot-school", name: "大学创新园停车场", region_label: "学校", venue_type: "school", synthetic: true, opening_status: "open", total_spaces: 8, available_spaces: 6, charging_spaces: 2, pricing: { currency: "CNY", first_hour_yuan: 2, additional_hour_yuan: 3, daily_cap_yuan: 30, note: "模拟价格" }, updated_at: "2026-08-13T09:00:00Z", data_source: { schema_version: "2.0.0", parking_lot_id: "lot-school", mode: "synthetic", health: "healthy", source_name: "test", missing_fields: [], updated_at: "2026-08-13T09:00:00Z", fail_reason: null } },
  { schema_version: "2.0.0", parking_lot_id: "lot-hospital", name: "市立医院停车场", region_label: "医院", venue_type: "hospital", synthetic: true, opening_status: "open", total_spaces: 8, available_spaces: 4, charging_spaces: 2, pricing: { currency: "CNY", first_hour_yuan: 5, additional_hour_yuan: 3, daily_cap_yuan: 30, note: "模拟价格" }, updated_at: "2026-08-13T09:00:00Z", data_source: { schema_version: "2.0.0", parking_lot_id: "lot-hospital", mode: "synthetic", health: "healthy", source_name: "test", missing_fields: [], updated_at: "2026-08-13T09:00:00Z", fail_reason: null } },
];
const area = { schema_version: "1.0.0", area_id: "area", display_version: "v1", coordinate_system: "percentage_top_left", synthetic: true, source_mode: "synthetic", source_health: "healthy", default_reference_id: "south", references: [{ reference_id: "south", label: "南侧参考点", position: { x_pct: 46, y_pct: 84 } }, { reference_id: "west", label: "西侧参考点", position: { x_pct: 12, y_pct: 48 } }], lots: [{ parking_lot_id: "lot-school", opening_hours_label: "每日开放", position: { x_pct: 53, y_pct: 39 }, offsite_estimates: [{ reference_id: "south", distance_m: 680, eta_s: 150 }, { reference_id: "west", distance_m: 620, eta_s: 140 }] }, { parking_lot_id: "lot-hospital", opening_hours_label: "24 小时开放", position: { x_pct: 20, y_pct: 66 }, offsite_estimates: [{ reference_id: "south", distance_m: 920, eta_s: 210 }, { reference_id: "west", distance_m: 310, eta_s: 80 }] }], updated_at: "2026-08-13T09:00:00Z" };
const driverContext = { schema_version: "1.0.0", observed_at: "2026-08-13T09:00:00Z", scenario_id: "school-demo", parking_lot_id: "lot-school", layout_version: "layout-v1", entrances: [{ node_id: "entry", label: "南入口" }], spaces: [{ parking_lot_id: "lot-school", space_id: "B-02", coordinate: { x_m: 37, y_m: 15 }, access_node_id: "access-b", status: "available", charging: false, stack_group_id: "stack-B1", depth: 2, assignable: true, assignability_reasons: [] }, { parking_lot_id: "lot-school", space_id: "A-02", coordinate: { x_m: 41, y_m: -11 }, access_node_id: "access-a", status: "available", charging: false, stack_group_id: "independent-A-02", depth: 1, assignable: true, assignability_reasons: [] }], tandem_groups: [{ stack_group_id: "stack-B1", space_ids_near_to_deep: ["B-01", "B-02"] }], data_source: lots[0].data_source };
const tripLayout = { schema_version: "2.0.0", parking_lot_id: "lot-school", layout_version: "layout-v1", coordinate_system: "local_meters", coordinate_origin_note: "E2E local coordinates", entrance_node_ids: ["entry"], exit_node_ids: [], channel_zones: [], buffers: [], tandem_groups: [], nodes: [{ node_id: "entry", label: "南入口", kind: "entrance", coordinate: { x_m: 0, y_m: 0 } }, { node_id: "turn", label: "中央转角", kind: "junction", coordinate: { x_m: 18, y_m: 0 } }, { node_id: "access-a", label: "A 区入口", kind: "space_access", coordinate: { x_m: 42, y_m: 14 } }], edges: [{ edge_id: "edge-1", from_node_id: "entry", to_node_id: "turn", distance_m: 18, base_travel_time_s: 12, directed: false, channel_zone_ids: [] }, { edge_id: "edge-2", from_node_id: "turn", to_node_id: "access-a", distance_m: 28, base_travel_time_s: 20, directed: false, channel_zone_ids: [] }], spaces: [{ parking_lot_id: "lot-school", space_id: "A-02", coordinate: { x_m: 43, y_m: 15 }, access_node_id: "access-a", status: "available", charging: false, stack_group_id: "A-02", depth: 1, assignable: true, assignability_reasons: [] }] };
function tripSnapshot() {
  const now = new Date();
  return { schema_version: "1.0.0", observed_at: now.toISOString(), journey: { schema_version: "2.0.0", journey_id: "journey-trip-e2e", attempt_id: "attempt-trip-e2e", session_id: "driver-e2e", namespace: "driver", scenario_id: facilityState.scenario_id, parking_lot_id: "lot-school", state: "navigating", version: 4, space_id: "P-02", recommendation_id: "recommendation-trip-e2e", updated_at: now.toISOString(), expires_at: new Date(now.getTime() + 120_000).toISOString(), terminal_reason: null, legal_operations: ["replan", "driver_demo_replan", "report_external_occupancy", "reassign", "occupy"] }, driver: { schema_version: "2.0.0", request_id: "request-trip-e2e", idempotency_key: "driver-trip-e2e", session_id: "driver-e2e", parking_lot_id: "lot-school", entrance_node_id: "entry", requires_charging: false, requested_at: now.toISOString(), expected_departure_at: null }, current_route: { ...routePreview.route, cost_version: "cost-trip-v1" }, current_node_id: "entry", last_replan: null, started_at: now.toISOString(), parked_at: null, ended_at: null, recent_events: [], recent_trips: [], tandem_arrival_replay_enabled: false, tandem_arrival_replay: null, tandem_departure_replay_enabled: false, tandem_departure_replay: null };
}
const tripFacilityState = { ...facilityState, spaces: facilityState.spaces.map((space) => space.space_id === "P-02" ? { ...space, observed_status: "available", claim_status: "navigating", effective_status: "unavailable", assignable: false, reason_codes: ["SESSION_CLAIMED"] } : space) };

function heldRecommendation() {
  const expiresAt = new Date(Date.now() + 30_000).toISOString();
  return { schema_version: "2.0.0", journey: { schema_version: "2.0.0", journey_id: "journey-e2e", attempt_id: "attempt-e2e", session_id: "driver-e2e", namespace: "driver", scenario_id: "school-demo", parking_lot_id: "lot-school", state: "soft_held", version: 1, space_id: "B-02", recommendation_id: "recommendation-e2e", updated_at: new Date().toISOString(), expires_at: expiresAt, terminal_reason: null, legal_operations: ["select_alternative", "confirm", "cancel"] }, recommendation: { schema_version: "2.0.0", recommendation_id: "recommendation-e2e", request_id: "request-e2e", parking_lot_id: "lot-school", algorithm_id: "online-rule-v2", algorithm_version: "2.0.0", data_source: lots[0].data_source, solver_status: "success", failure_code: null, recommended_space_id: "B-02", alternative_space_ids: ["A-02"], assessments: [], route: { schema_version: "2.0.0", parking_lot_id: "lot-school", layout_version: "layout-v1", cost_version: "cost-v1", from_node_id: "entry", to_node_id: "access-b", node_ids: ["entry", "access-b"], edge_ids: ["edge-1"], distance_m: 38, dynamic_eta_s: 39, instructions: [] }, explanation_codes: ["V1_FEASIBILITY_REUSED"], degraded: false, degradation_reason: null, claim_status: "soft_held", soft_lock_expires_at: expiresAt } };
}

async function mockApi(page: Page) {
  const currentTrip = tripSnapshot();
  await page.route("**/api/v2/parking-lots", async (route) => { await route.fulfill({ json: lots }); });
  await page.route("**/api/v2/discovery-area", async (route) => { await route.fulfill({ json: area }); });
  await page.route("**/api/v2/driver-session/current-journey", async (route) => { await route.fulfill({ json: { schema_version: "1.0.0", observed_at: new Date().toISOString(), journey: null, recommendation: null, driver: null, waiting_since: null } }); });
  await page.route("**/api/v2/driver-session/current-trip", async (route) => { await route.fulfill({ json: currentTrip }); });
  await page.route("**/api/v2/parking-lots/lot-school/layout", async (route) => { await route.fulfill({ json: tripLayout }); });
  await page.route("**/api/v2/parking-lots/lot-school/facility-layout", async (route) => { await route.fulfill({ json: facilityLayout }); });
  await page.route("**/api/v2/parking-lots/lot-school/facility-state", async (route) => { await route.fulfill({ json: tripFacilityState }); });
  await page.route("**/api/v2/parking-lots/lot-school/route-previews", async (route) => { await route.fulfill({ json: routePreview }); });
  await page.route("**/api/v2/parking-lots/lot-school", async (route) => { await route.fulfill({ json: lots[0] }); });
  await page.route("**/api/v2/parking-lots/lot-school/driver-context", async (route) => { await route.fulfill({ json: driverContext }); });
  await page.route("**/api/v2/journeys/recommendations", async (route) => { await route.fulfill({ json: heldRecommendation() }); });
}

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => { localStorage.setItem("parksim.driver-session-id.v1", "driver-e2e"); });
  await mockApi(page);
});

test("driver discovery works without horizontal overflow", async ({ page }, testInfo) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "更快找到合适的车位" })).toBeVisible();
  await expect(page.getByText("固定 synthetic 场景")).toBeVisible();
  await page.getByRole("searchbox").fill("医院");
  await expect(page.getByText("大学创新园停车场")).toBeHidden();
  await expect(page.getByText("市立医院停车场").first()).toBeVisible();
  await page.getByRole("button", { name: "西侧参考点" }).click();
  await expect(page.getByRole("complementary").getByText("310 米 · 约 2 分钟")).toBeVisible();
  if (testInfo.project.name === "mobile-chromium") {
    const detailTop = await page.getByRole("complementary").evaluate((element) => element.getBoundingClientRect().top);
    const listTop = await page.getByLabel("停车场列表").evaluate((element) => element.getBoundingClientRect().top);
    expect(detailTop).toBeLessThan(listTop);
  }
  if (process.env.CAPTURE_VISUAL_QA === "1") {
    await page.screenshot({
      path: `../../docs/visual-qa/web-v2/m4-p1/${testInfo.project.name}.png`,
      fullPage: true,
    });
  }
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(1);
});

test("all three driver pages remain reachable", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("link", { name: "智能停车", exact: true }).click();
  await expect(page.getByRole("heading", { name: "请先选择停车场" })).toBeVisible();
  await page.getByRole("link", { name: "当前行程", exact: true }).click();
  await expect(page.getByRole("heading", { name: "正在前往车位" })).toBeVisible();
});

test("current journey keeps route and instructions in sync without viewport overflow", async ({ page }, testInfo) => {
  await page.goto("/journey");
  await expect(page.getByRole("heading", { name: "正在前往车位" })).toBeVisible();
  await expect(page.getByText("南入口 → P-02")).toBeVisible();
  await expect(page.getByText("沿入口通道行驶")).toBeVisible();
  await expect(page.getByRole("application", { name: "当前行程完整停车场布局" })).toBeVisible();
  await expect(page.getByRole("button", { name: /P-02.*当前行程目标/ })).toBeVisible();
  await expect(page.locator("[data-route-cost-version='cost-trip-v1']")).toBeVisible();
  await expect(page.locator("[data-edge-id='entry-access']")).toBeVisible();
  await expect(page.getByRole("button", { name: "模拟偏航" })).toBeVisible();
  await expect(page.getByRole("button", { name: "模拟通道繁忙" })).toBeVisible();
  await expect(page.getByRole("button", { name: "推荐位被占" })).toBeVisible();
  await expect(page.getByRole("button", { name: "无法停入" })).toBeVisible();
  await expect(page.getByRole("button", { name: "我已停入" })).toBeVisible();
  if (process.env.CAPTURE_VISUAL_QA === "1") {
    await page.screenshot({ path: `../../docs/visual-qa/web-v2/m4-r3/${testInfo.project.name}.png`, fullPage: true });
  }
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(1);
});

test("driver receives a server-held tandem recommendation without viewport overflow", async ({ page }) => {
  await page.goto("/recommend?parkingLotId=lot-school");
  await expect(page.getByRole("heading", { name: "告诉我们你从哪里进入" })).toBeVisible();
  await page.getByRole("button", { name: "获取智能推荐" }).click();
  await expect(page.getByText("已为你锁定主推荐")).toBeVisible();
  await expect(page.getByText("需要你确认协同停车")).toBeVisible();
  await expect(page.getByText("A-02")).toBeVisible();
  await expect(page.getByRole("button", { name: "接受协同停车并确认" })).toBeEnabled();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(1);
});

test("complete facility layout supports selection route preview and both viewports", async ({ page }, testInfo) => {
  await page.goto("/parking/lot-school/layout");
  await expect(page.getByRole("heading", { name: "停车场全景" })).toBeVisible();
  await expect(page.getByRole("application", { name: "完整停车场布局" })).toBeVisible();
  await expect(page.getByLabel("布局图例")).toBeVisible();
  await page.getByRole("button", { name: /P-01/ }).click();
  await expect(page).toHaveURL(/space=P-01/);
  await page.getByRole("button", { name: "查看场内路线" }).click();
  await expect(page.getByText("18 米 · 约 5 秒")).toBeVisible();
  await page.getByRole("button", { name: "放大" }).click();
  await expect(page.getByText("1.4×")).toBeVisible();
  const space = page.getByRole("button", { name: /P-01/ });
  const box = await space.boundingBox();
  if (box !== null && testInfo.project.name === "desktop-chromium") {
    const cdp = await page.context().newCDPSession(page);
    const point = (x: number) => ({ x: box.x + x, y: box.y + 2 });
    await cdp.send("Input.dispatchTouchEvent", { type: "touchStart", touchPoints: [{ ...point(2), id: 11 }, { ...point(8), id: 12 }] });
    await page.waitForTimeout(60);
    await cdp.send("Input.dispatchTouchEvent", { type: "touchMove", touchPoints: [{ ...point(2), id: 11 }, { ...point(24), id: 12 }] });
    await page.waitForTimeout(60);
    await cdp.send("Input.dispatchTouchEvent", { type: "touchMove", touchPoints: [{ ...point(2), id: 11 }, { ...point(40), id: 12 }] });
    await cdp.send("Input.dispatchTouchEvent", { type: "touchEnd", touchPoints: [] });
    await expect(page.getByText(/^[2-5]\.[0-9]×$/)).toBeVisible();
  }
  if (testInfo.project.name === "mobile-chromium") {
    await page.getByRole("button", { name: "放大" }).tap();
    await expect(page.getByText("1.9×")).toBeVisible();
  }
  if (process.env.CAPTURE_VISUAL_QA === "1") {
    await page.screenshot({ path: `../../docs/visual-qa/web-v2/m4-r2/${testInfo.project.name}.png`, fullPage: true });
  }
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(1);
  if (testInfo.project.name === "mobile-chromium") {
    const canvas = await page.getByRole("application", { name: "完整停车场布局" }).boundingBox();
    expect(canvas?.width ?? 0).toBeGreaterThan(300);
    await expect(page.getByRole("button", { name: "查看场内路线" })).toBeVisible();
  }
});
