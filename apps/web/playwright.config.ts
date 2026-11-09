import { defineConfig, devices } from "@playwright/test";

const PORT = Number(process.env.PW_PORT ?? 3012);

// Local runs use Playwright's own Chromium in a throwaway profile. The installed Google Chrome can
// pass the password fields these tests type (some deliberately wrong) to Windows sign-in, which
// locked the Windows account on a shared laptop. CI keeps the installed Chrome; set
// PW_CHANNEL=chrome to use it locally on purpose.
const CHANNEL = process.env.PW_CHANNEL ?? (process.env.CI ? "chrome" : undefined);

export default defineConfig({
  testDir: "./tests",
  timeout: 45_000,
  expect: { timeout: 10_000 },
  fullyParallel: true,
  // Local laptops time out the first pages with one worker per core against a cold server.
  workers: process.env.CI ? undefined : 2,
  retries: 0,
  reporter: [["list"]],
  use: {
    baseURL: `http://localhost:${PORT}`,
    channel: CHANNEL,
    trace: "retain-on-failure",
  },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"], channel: CHANNEL, viewport: { width: 1440, height: 900 } }, testIgnore: /mobile\.spec\.ts/ },
    { name: "mobile", use: { ...devices["Pixel 7"], channel: CHANNEL, viewport: { width: 390, height: 844 } }, testMatch: /mobile\.spec\.ts/ },
  ],
  webServer: {
    command: `npx next build && npx next start -p ${PORT}`,
    url: `http://localhost:${PORT}`,
    timeout: 240_000,
    reuseExistingServer: true,
    // The tests mock the core where they need deterministic data; point the proxy at a
    // closed port so nothing ever reaches a real backend by accident.
    env: {
      PRAMANA_CORE_URL: "http://127.0.0.1:9",
      PRAMANA_SIM_URL: "http://127.0.0.1:9",
      NEXT_PUBLIC_ENABLE_PREVIEW: "1",
    },
  },
});
