import { expect, test, type Page } from "@playwright/test";
import { resolve } from "node:path";

const lots = ["lot-commercial", "lot-school", "lot-hospital", "lot-transport-hub"] as const;
const visualRoot = resolve(process.cwd(), "..", "..", "docs", "visual-qa", "web-v2", "m4-p4");
const r2VisualRoot = resolve(process.cwd(), "..", "..", "docs", "visual-qa", "web-v2", "m4-r2");
const r4VisualRoot = resolve(process.cwd(), "..", "..", "docs", "visual-qa", "web-v2", "m4-r4");
const r5VisualRoot = resolve(process.cwd(), "..", "..", "docs", "visual-qa", "web-v2", "m4-r5");
const r6VisualRoot = resolve(process.cwd(), "..", "..", "docs", "visual-qa", "web-v2", "m4-r6");

async function capture(page: Page, projectName: string, name: string) {
  if (process.env.P4_CAPTURE_VISUALS !== "1") return;
  const viewport = projectName === "real-mobile" ? "mobile" : projectName === "real-desktop" ? "desktop" : null;
  if (viewport !== null) await page.screenshot({ path: resolve(visualRoot, `${name}-${viewport}.png`), fullPage: true });
}

async function captureR2(page: Page, projectName: string, name: string) {
  if (process.env.R2_CAPTURE_VISUALS !== "1") return;
  const viewport = projectName === "real-mobile" ? "mobile" : projectName === "real-desktop" ? "desktop" : null;
  if (viewport !== null) await page.screenshot({ path: resolve(r2VisualRoot, `${name}-${viewport}.png`), fullPage: true });
}

async function captureR4(page: Page, projectName: string, name: string) {
  if (process.env.R4_CAPTURE_VISUALS !== "1") return;
  const viewport = projectName === "real-mobile" ? "mobile" : projectName === "real-desktop" ? "desktop" : null;
  if (viewport !== null) await page.screenshot({ path: resolve(r4VisualRoot, `${name}-${viewport}.png`), fullPage: true });
}

async function captureR5(page: Page, projectName: string, name: string) {
  if (process.env.R5_CAPTURE_VISUALS !== "1") return;
  const viewport = projectName === "real-mobile" ? "mobile" : projectName === "real-desktop" ? "desktop" : null;
  if (viewport !== null) await page.screenshot({ path: resolve(r5VisualRoot, `${name}-${viewport}.png`), fullPage: true });
}

async function captureR6(page: Page, projectName: string, name: string) {
  if (process.env.R6_CAPTURE_VISUALS !== "1") return;
  const viewport = projectName === "real-mobile" ? "mobile" : projectName === "real-desktop" ? "desktop" : null;
  if (viewport !== null) await page.screenshot({ path: resolve(r6VisualRoot, `${name}-${viewport}.png`), fullPage: true });
}

test.beforeEach(async ({ page }, testInfo) => {
  await page.addInitScript((identity) => {
    localStorage.setItem("parksim.driver-session-id.v1", identity);
  }, `real-${testInfo.project.name.slice(0, 12)}-${crypto.randomUUID()}`);
});

function auditBrowser(page: Page) {
  const failures: string[] = [];
  page.on("pageerror", (error) => { failures.push(`pageerror:${error.message}`); });
  page.on("console", (message) => { if (message.type() === "error") failures.push(`console:${message.text()}`); });
  page.on("requestfailed", (request) => {
    const reason = request.failure()?.errorText ?? "failed";
    // AbortController intentionally cancels superseded initial reads.
    if (!reason.includes("ERR_ABORTED")) failures.push(`request:${request.url()}:${reason}`);
  });
  return failures;
}

for (const lotId of lots) {
  test(`${lotId} completes recommendation route anomaly parking and departure`, async ({ page }, testInfo) => {
    const failures = auditBrowser(page);
    const apiResponses: number[] = [];
    page.on("response", (response) => {
      if (response.url().includes("/api/v2/")) apiResponses.push(response.status());
    });

    await page.goto(`/recommend?parkingLotId=${lotId}`);
    await expect(page.getByRole("heading", { name: "告诉我们你从哪里进入" })).toBeVisible();
    await expect(page.locator(".request-card label").first().locator("strong")).toHaveText(/.+停车场$/);
    const entrance = page.getByLabel("进入入口");
    if (await entrance.inputValue() === "") await entrance.selectOption({ index: 1 });
    await page.getByRole("button", { name: "获取智能推荐" }).click();
    await expect(page.getByText("已为你锁定主推荐")).toBeVisible();

    const acceptTandem = page.getByRole("button", { name: "接受协同停车并确认" });
    if (await acceptTandem.isVisible()) await acceptTandem.click();
    else await page.getByRole("button", { name: "确认使用此车位" }).click();

    await expect(page).toHaveURL(/\/journey$/);
    await expect(page.getByRole("application", { name: "当前行程完整停车场布局" })).toBeVisible();
    await expect(page.getByRole("button", { name: /当前行程目标/ })).toBeVisible();
    await expect(page.locator(".facility-route-layer")).toBeVisible();
    await expect(page.locator(".guidance-panel ol")).toContainText("到达目标区域");
    await expect(page.locator(".guidance-panel ol")).not.toContainText(/entry-west|lane-north|access-north/);
    await page.getByRole("button", { name: "开始场内指引" }).click();
    await expect(page.getByRole("heading", { name: "正在前往车位" })).toBeVisible();
    await expect(page.locator(".facility-vehicle")).toBeVisible();
    await captureR4(page, testInfo.project.name, `journey-${lotId}`);
    if (lotId === "lot-hospital") await capture(page, testInfo.project.name, "navigation");
    await page.getByRole("button", { name: "模拟偏航" }).click();
    await expect(page.getByText("状态版本 v4")).toBeVisible();
    if (lotId === "lot-commercial") await capture(page, testInfo.project.name, "anomaly-recovery");
    await page.getByRole("button", { name: "我已停入" }).click();
    await expect(page.getByRole("button", { name: "正常离场" })).toBeEnabled();
    await page.getByRole("button", { name: "正常离场" }).click();
    await expect(page.getByRole("heading", { name: "本次行程已结束" }).first()).toBeVisible();
    if (lotId === "lot-transport-hub") await captureR4(page, testInfo.project.name, "terminal");
    if (lotId === "lot-transport-hub") await capture(page, testInfo.project.name, "terminal");

    expect(apiResponses.length).toBeGreaterThanOrEqual(12);
    expect(apiResponses.every((status) => status >= 200 && status < 300)).toBe(true);
    expect(failures).toEqual([]);
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    expect(overflow).toBeLessThanOrEqual(1);
  });
}

test("synthetic driver profiles expose peak charging wait and tandem outcomes", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name === "real-chrome-desktop", "Edge desktop and mobile provide the full profile matrix");
  const failures = auditBrowser(page);
  const apiResponses: number[] = [];
  page.on("response", (response) => {
    if (response.url().includes("/api/v2/")) apiResponses.push(response.status());
  });

  await page.goto("/recommend?parkingLotId=lot-school");
  await expect(page.getByText("平峰通行", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "换一组模拟状态" }).click();
  await expect(page.getByText("高峰远端", { exact: true })).toBeVisible();
  await captureR5(page, testInfo.project.name, "profile-switcher");
  await page.getByRole("button", { name: "换一组模拟状态" }).click();
  await expect(page.getByText("充电紧张", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "需要充电车位" }).click();
  await page.getByRole("button", { name: "获取智能推荐" }).click();
  await expect(page.getByRole("heading", { name: "正在等待合规车位" })).toBeVisible();
  await captureR5(page, testInfo.project.name, "charging-wait");
  await page.getByRole("button", { name: "取消等待" }).click();
  await expect(page.getByRole("heading", { name: "告诉我们你从哪里进入" })).toBeVisible();
  await page.getByRole("button", { name: "换一组模拟状态" }).click();
  await expect(page.getByText("纵深协同", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "需要充电车位" }).click();
  await page.getByRole("button", { name: "获取智能推荐" }).click();
  await expect(page.getByText("协同停车位").first()).toBeVisible();
  await expect(page.getByRole("button", { name: "接受协同停车并确认" })).toBeVisible();
  await captureR5(page, testInfo.project.name, "tandem-profile");

  expect(apiResponses.length).toBeGreaterThanOrEqual(12);
  expect(apiResponses.every((status) => status >= 200 && status < 300)).toBe(true);
  expect(failures).toEqual([]);
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(1);
});

test("real tandem flow reaches informed confirmation through authoritative replacements", async ({ page }, testInfo) => {
  test.setTimeout(90_000);
  test.skip(testInfo.project.name === "real-chrome-desktop", "desktop and mobile full-flow projects provide evidence");
  const failures = auditBrowser(page);
  await page.goto("/recommend?parkingLotId=lot-school");
  await page.getByRole("button", { name: "获取智能推荐" }).click();

  for (let replacement = 0; replacement < 28; replacement += 1) {
    const accept = page.getByRole("button", { name: "接受协同停车并确认" });
    const confirm = page.getByRole("button", { name: "确认使用此车位" });
    const request = page.getByRole("button", { name: "获取智能推荐" });
    await expect(accept.or(confirm).or(request)).toBeVisible();
    if (await accept.isVisible()) {
      await capture(page, testInfo.project.name, "tandem-confirmation");
      await captureR4(page, testInfo.project.name, "tandem-confirmation");
      await expect(page.getByText(/协同停车位/).first()).toBeVisible();
      expect(failures).toEqual([]);
      return;
    }
    if (await request.isVisible()) {
      await request.click();
      continue;
    }
    await confirm.click();
    await page.getByRole("button", { name: "开始场内指引" }).click();
    await page.getByRole("button", { name: "推荐位被占" }).click();
    await expect(page).toHaveURL(/\/recommend\?parkingLotId=lot-school/);
  }

  throw new Error("authoritative replacement chain did not reach a tandem space");
});

test("real tandem arrival and departure replay one authoritative coordination", async ({ page }, testInfo) => {
  test.setTimeout(90_000);
  const failures = auditBrowser(page);
  const apiResponses: number[] = [];
  page.on("response", (response) => {
    if (response.url().includes("/api/v2/")) apiResponses.push(response.status());
  });

  await page.goto("/recommend?parkingLotId=lot-school");
  for (const profile of ["高峰远端", "充电紧张", "纵深协同"]) {
    await page.getByRole("button", { name: "换一组模拟状态" }).click();
    await expect(page.getByText(profile, { exact: true })).toBeVisible();
  }
  await page.getByRole("button", { name: "获取智能推荐" }).click();
  await expect(page.getByText("协同停车位").first()).toBeVisible();
  await page.getByRole("button", { name: "接受协同停车并确认" }).click();
  await expect(page).toHaveURL(/\/journey$/);
  await page.getByRole("button", { name: "开始场内指引" }).click();
  await expect(page.getByRole("heading", { name: "正在前往车位" })).toBeVisible();
  const arrivalResponsePromise = page.waitForResponse((response) =>
    response.url().includes("/tandem-arrival-replay") && response.request().method() === "POST",
  );
  await page.getByRole("button", { name: "我已到达，开始协同入位" }).click();
  const arrivalResponse = await arrivalResponsePromise;
  const arrivalPayload = await arrivalResponse.json() as {
    blocker_vehicle_ids: string[];
    buffer_ids: string[];
    before_state_version: string;
    after_state_version: string;
    before_facility_state: { state_version: string };
    after_facility_state: { state_version: string };
  };
  expect(arrivalPayload.before_facility_state.state_version).toBe(arrivalPayload.before_state_version);
  expect(arrivalPayload.after_facility_state.state_version).toBe(arrivalPayload.after_state_version);
  const arrivalCanvas = page.getByRole("application", { name: "纵深协同入位完整停车场布局" });
  await expect(arrivalCanvas).toBeVisible();
  await expect(page.locator('[data-action="relocate_to_buffer"]')).toBeVisible();
  await expect(page.locator('[data-action="direct_entry"]')).toBeVisible();
  await expect(page.locator('[data-action="restore_original"]')).toBeVisible();
  await expect(page.locator(".facility-vehicle.driver")).toHaveCount(1);
  await expect(page.locator(".facility-vehicle.blocker")).toHaveCount(1);
  await page.waitForTimeout(1_000);
  await captureR6(page, testInfo.project.name, "tandem-arrival-blocker-to-buffer");
  await expect(page.locator('[data-action="direct_entry"][aria-current="step"]')).toBeVisible({ timeout: 12_000 });
  await captureR6(page, testInfo.project.name, "tandem-arrival-current-vehicle-entry");
  await expect(page.getByRole("heading", { name: "协同入位已完成" }).first()).toBeVisible({ timeout: 25_000 });
  await captureR6(page, testInfo.project.name, "tandem-arrival-complete");
  await page.getByRole("button", { name: "查看停车状态" }).click();
  await expect(page.getByRole("button", { name: "演示协同移位后离场" })).toBeEnabled();
  const replayResponsePromise = page.waitForResponse((response) =>
    response.url().includes("/tandem-departure-replay") && response.request().method() === "POST",
  );
  await page.getByRole("button", { name: "演示协同移位后离场" }).click();
  const replayResponse = await replayResponsePromise;
  const replayPayload = await replayResponse.json() as { blocker_vehicle_ids: string[]; buffer_ids: string[]; state_version: string; profile_id: string; facility_state: { state_version: string; demo_profile: { profile_id: string } | null } };
  expect(replayPayload.facility_state.state_version).toBe(replayPayload.state_version);
  expect(replayPayload.facility_state.demo_profile?.profile_id).toBe(replayPayload.profile_id);
  expect(replayPayload.blocker_vehicle_ids).toEqual(arrivalPayload.blocker_vehicle_ids);
  expect(replayPayload.buffer_ids).toEqual(arrivalPayload.buffer_ids);

  const replayCanvas = page.getByRole("application", { name: "纵深协同离场完整停车场布局" });
  await expect(replayCanvas).toBeVisible();
  await expect(page.locator(".facility-vehicle.driver")).toHaveCount(1);
  await expect(page.locator(".facility-vehicle.blocker")).toHaveCount(1);
  await expect(page.locator('[data-action="relocate_to_buffer"]')).toBeVisible();
  await expect(page.locator('[data-action="direct_exit"]')).toBeVisible();
  await expect(page.locator('[data-action="restore_original"]')).toBeVisible();
  await page.waitForTimeout(1_000);
  await captureR6(page, testInfo.project.name, "tandem-departure-blocker-to-buffer");
  await expect(page.locator('[data-action="direct_exit"][aria-current="step"]')).toBeVisible({ timeout: 12_000 });
  await captureR6(page, testInfo.project.name, "tandem-departure-current-vehicle-exit");
  await expect(page.getByRole("heading", { name: "协同移位已完成" }).first()).toBeVisible({ timeout: 25_000 });
  await captureR6(page, testInfo.project.name, "tandem-departure-complete");

  expect(apiResponses.length).toBeGreaterThanOrEqual(10);
  expect(apiResponses.every((status) => status >= 200 && status < 300)).toBe(true);
  expect(failures).toEqual([]);
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(1);
});

test("real discovery exposes all four synthetic parking lots", async ({ page }, testInfo) => {
  const failures = auditBrowser(page);
  await page.goto("/parking");
  await expect(page.getByRole("heading", { name: "更快找到合适的车位" })).toBeVisible();
  await expect(page.getByLabel("停车场列表").getByRole("button")).toHaveCount(4);
  await capture(page, testInfo.project.name, "discovery");
  expect(failures).toEqual([]);
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(1);
});

for (const lotId of lots) {
  test(`real facility layout ${lotId} renders and previews an authoritative route`, async ({ page }, testInfo) => {
    test.skip(testInfo.project.name === "real-chrome-desktop", "desktop and mobile full-flow projects provide evidence");
    const failures = auditBrowser(page);
    const apiResponses: number[] = [];
    page.on("response", (response) => {
      if (response.url().includes(`/api/v2/parking-lots/${lotId}/`)) apiResponses.push(response.status());
    });

    await page.goto(`/parking/${lotId}/layout`);
    await expect(page.getByRole("application", { name: "完整停车场布局" })).toBeVisible();
    await expect(page.getByLabel("布局图例")).toBeVisible();
    await captureR4(page, testInfo.project.name, `layout-${lotId}-panorama`);
    const availableSpace = page.locator(".facility-space.status-available").first();
    await expect(availableSpace).toBeVisible();
    await availableSpace.click();
    await page.getByRole("button", { name: "查看场内路线" }).click();
    await expect(page.locator(".facility-route-layer")).toBeVisible();
    await captureR2(page, testInfo.project.name, lotId);
    await captureR4(page, testInfo.project.name, `layout-${lotId}-preview`);

    if (testInfo.project.name === "real-mobile" && lotId === "lot-school") {
      await page.getByRole("button", { name: "全屏查看" }).click();
      await expect.poll(() => page.evaluate(() => document.fullscreenElement !== null)).toBe(true);
      await captureR4(page, testInfo.project.name, "facility-fullscreen");
      await page.evaluate(() => document.exitFullscreen());
      await expect.poll(() => page.evaluate(() => document.fullscreenElement === null)).toBe(true);
    }

    expect(apiResponses.length).toBeGreaterThanOrEqual(3);
    expect(apiResponses.every((status) => status >= 200 && status < 300)).toBe(true);
    expect(failures).toEqual([]);
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    expect(overflow).toBeLessThanOrEqual(1);
  });
}
