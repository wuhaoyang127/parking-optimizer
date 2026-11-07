import { expect, test, type Page } from "@playwright/test";
import { gzipSync } from "node:zlib";
import { readdirSync, readFileSync } from "node:fs";
import { resolve } from "node:path";

function p95(samples: number[]): number {
  const ordered = [...samples].sort((left, right) => left - right);
  return ordered[Math.ceil(ordered.length * 0.95) - 1] ?? Number.POSITIVE_INFINITY;
}

const diagnosticsEnabled = process.env.PARKSIM_PERF_DIAGNOSTICS === "1";

async function installDiagnostics(page: Page): Promise<void> {
  await page.addInitScript(() => {
    const events: Record<string, unknown>[] = [
      { kind: "init", at: performance.now(), visibility: document.visibilityState },
    ];
    Object.defineProperty(window, "__parksimPerfDiagnostics", { value: events });
    document.addEventListener("visibilitychange", () => {
      events.push({ kind: "visibility", at: performance.now(), visibility: document.visibilityState });
    });
    try {
      new PerformanceObserver((list) => {
        for (const entry of list.getEntries()) {
          events.push({ kind: "longtask", at: entry.startTime, duration: entry.duration });
        }
      }).observe({ type: "longtask", buffered: true });
    } catch {
      events.push({ kind: "longtask-api-unavailable" });
    }
    const observer = new MutationObserver(() => {
      const result = Array.from(document.querySelectorAll("main span")).find(
        (element) => element.textContent.startsWith("已为你锁定主推荐"),
      );
      if (result !== undefined && result.getBoundingClientRect().width > 0) {
        events.push({ kind: "recommendation-dom-present", at: performance.now() });
        observer.disconnect();
      }
    });
    observer.observe(document, { childList: true, subtree: true });
  });
}

async function browserDiagnostics(page: Page): Promise<unknown> {
  return page.evaluate(() => ({
    at: performance.now(),
    visibility: document.visibilityState,
    events: (window as unknown as { __parksimPerfDiagnostics?: unknown[] }).__parksimPerfDiagnostics ?? [],
    resources: performance.getEntriesByType("resource")
      .filter((entry) => new URL(entry.name).pathname.startsWith("/api/v2/"))
      .map((entry) => {
        const resource = entry as PerformanceResourceTiming;
        return { path: new URL(entry.name).pathname, start: resource.startTime,
          responseStart: resource.responseStart, responseEnd: resource.responseEnd };
      }),
  }));
}

test("production performance meets the frozen P4 budget", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "real-desktop", "one controlled desktop sample set is authoritative");
  const diagnostics: unknown[] = [];
  if (diagnosticsEnabled) await installDiagnostics(page);
  try {

  const assets = resolve(process.cwd(), "dist", "assets");
  const gzipBytes = readdirSync(assets)
    .filter((name) => name.endsWith(".js") || name.endsWith(".css"))
    .reduce((sum, name) => sum + gzipSync(readFileSync(resolve(assets, name))).byteLength, 0);
  expect(gzipBytes).toBeLessThanOrEqual(400 * 1024);

  const startupMs: number[] = [];
  for (let index = 0; index < 5; index += 1) {
    const started = performance.now();
    await page.goto(`/parking?warm=${String(index)}`);
    await expect(page.getByRole("heading", { name: "更快找到合适的车位" })).toBeVisible();
    startupMs.push(performance.now() - started);
  }
  expect(p95(startupMs)).toBeLessThanOrEqual(2_000);

  const mutationMs: number[] = [];
  for (let index = 0; index < 10; index += 1) {
    await page.evaluate((identity) => {
      localStorage.setItem("parksim.driver-session-id.v1", identity);
    }, `perf-${String(index)}-${crypto.randomUUID()}`);
    await page.goto("/recommend?parkingLotId=lot-school");
    await expect(page.getByRole("heading", { name: "告诉我们你从哪里进入" })).toBeVisible();
    const started = performance.now();
    await page.getByRole("button", { name: "获取智能推荐" }).click();
    await expect(page.getByText("已为你锁定主推荐")).toBeVisible();
    mutationMs.push(performance.now() - started);
    if (diagnosticsEnabled) diagnostics.push({ phase: "recommendation", index,
      measuredMs: mutationMs.at(-1), browser: await browserDiagnostics(page) });
  }
  expect(p95(mutationMs)).toBeLessThanOrEqual(1_000);

  const arrivalReplayMutationMs: number[] = [];
  const replayMutationMs: number[] = [];
  for (let index = 0; index < 5; index += 1) {
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.evaluate((identity) => {
      localStorage.setItem("parksim.driver-session-id.v1", identity);
    }, `perf-replay-${String(index)}-${crypto.randomUUID()}`);
    await page.goto("/recommend?parkingLotId=lot-school");
    for (const profile of ["高峰远端", "充电紧张", "纵深协同"]) {
      await page.getByRole("button", { name: "换一组模拟状态" }).click();
      await expect(page.getByText(profile, { exact: true })).toBeVisible();
    }
    await page.getByRole("button", { name: "获取智能推荐" }).click();
    await page.getByRole("button", { name: "接受协同停车并确认" }).click();
    await page.getByRole("button", { name: "开始场内指引" }).click();
    const arrivalStarted = performance.now();
    await page.getByRole("button", { name: "我已到达，开始协同入位" }).click();
    await expect(page.getByRole("application", { name: "纵深协同入位完整停车场布局" })).toBeVisible();
    arrivalReplayMutationMs.push(performance.now() - arrivalStarted);
    for (let step = 0; step < 3; step += 1) {
      await page.getByRole("button", { name: "查看下一阶段" }).click();
    }
    await page.getByRole("button", { name: "查看停车状态" }).click();
    await page.emulateMedia({ reducedMotion: "no-preference" });
    const started = performance.now();
    await page.getByRole("button", { name: "演示协同移位后离场" }).click();
    await expect(page.getByRole("application", { name: "纵深协同离场完整停车场布局" })).toBeVisible();
    replayMutationMs.push(performance.now() - started);
  }
  expect(p95(arrivalReplayMutationMs)).toBeLessThanOrEqual(1_000);
  expect(p95(replayMutationMs)).toBeLessThanOrEqual(1_000);
  await expect(page.locator(".facility-vehicle.driver")).toHaveCount(1);
  await expect(page.locator(".facility-vehicle.blocker")).toHaveCount(1);
  const frameIntervals = await page.evaluate(async () => {
    const values: number[] = [];
    let previous = performance.now();
    const deadline = previous + 5_000;
    await new Promise<void>((resolveFrames) => {
      const sample = (now: number) => {
        values.push(now - previous);
        previous = now;
        if (now >= deadline) resolveFrames(); else requestAnimationFrame(sample);
      };
      requestAnimationFrame(sample);
    });
    return values;
  });
  expect(p95(frameIntervals)).toBeLessThanOrEqual(50);
  expect(frameIntervals.filter((value) => value > 100)).toHaveLength(0);

  console.log(`P4_PERFORMANCE ${JSON.stringify({
    gzipBytes,
    startupMs: startupMs.map((value) => Math.round(value * 100) / 100),
    startupP95Ms: Math.round(p95(startupMs) * 100) / 100,
    mutationMs: mutationMs.map((value) => Math.round(value * 100) / 100),
    mutationP95Ms: Math.round(p95(mutationMs) * 100) / 100,
    arrivalReplayMutationMs: arrivalReplayMutationMs.map((value) => Math.round(value * 100) / 100),
    arrivalReplayMutationP95Ms: Math.round(p95(arrivalReplayMutationMs) * 100) / 100,
    replayMutationMs: replayMutationMs.map((value) => Math.round(value * 100) / 100),
    replayMutationP95Ms: Math.round(p95(replayMutationMs) * 100) / 100,
    animationFrames: frameIntervals.length,
    animationP95Ms: Math.round(p95(frameIntervals) * 100) / 100,
    longFramesOver100Ms: frameIntervals.filter((value) => value > 100).length,
  })}`);
  } finally {
    if (diagnosticsEnabled) {
      diagnostics.push({ phase: "final", browser: await browserDiagnostics(page) });
      await testInfo.attach("performance-diagnostics", {
        body: JSON.stringify({ instrumentation: "diagnosis only; frozen assertions unchanged", diagnostics }, null, 2),
        contentType: "application/json",
      });
      console.log(`P4_DIAGNOSTICS ${JSON.stringify(diagnostics)}`);
    }
  }
});
