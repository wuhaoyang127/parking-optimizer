import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./tests/integration",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: "list",
  use: {
    baseURL: "http://127.0.0.1:4173",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    { name: "real-desktop", use: { ...devices["Desktop Chrome"], channel: "msedge", viewport: { width: 1440, height: 1000 } } },
    { name: "real-mobile", use: { ...devices["Pixel 7"], channel: "msedge" } },
    { name: "real-chrome-desktop", testMatch: /real-driver-flow\.spec\.ts/, grep: /real discovery|real tandem arrival and departure/, use: { ...devices["Desktop Chrome"], channel: "chrome", viewport: { width: 1440, height: 1000 } } },
  ],
});
