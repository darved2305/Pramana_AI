import { defineConfig, devices } from "@playwright/test";

const PORT = 3012;

export default defineConfig({
  testDir: "./tests",
  timeout: 45_000,
  expect: { timeout: 10_000 },
  fullyParallel: true,
  retries: 0,
  reporter: [["list"]],
  use: {
    baseURL: `http://localhost:${PORT}`,
    channel: "chrome",
    trace: "retain-on-failure",
  },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"], channel: "chrome", viewport: { width: 1440, height: 900 } }, testIgnore: /mobile\.spec\.ts/ },
    { name: "mobile", use: { ...devices["Pixel 7"], channel: "chrome", viewport: { width: 390, height: 844 } }, testMatch: /mobile\.spec\.ts/ },
  ],
  webServer: {
    command: `npx next build && npx next start -p ${PORT}`,
    url: `http://localhost:${PORT}`,
    timeout: 240_000,
    reuseExistingServer: true,
    // The tests mock the core where they need deterministic data; point the proxy at a
    // closed port so nothing ever reaches a real backend by accident.
    env: { PRAMANA_CORE_URL: "http://127.0.0.1:9", PRAMANA_SIM_URL: "http://127.0.0.1:9" },
  },
});
