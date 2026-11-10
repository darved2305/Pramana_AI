import { generateKeyPairSync, randomBytes } from "node:crypto";
import { defineConfig } from "@playwright/test";
import { selectE2EDatabase } from "./scripts/e2e-database-safety.mjs";

const WEB_PORT = Number(process.env.E2E_WEB_PORT ?? 3235);
const CORE_PORT = Number(process.env.E2E_CORE_PORT ?? 8235);
const SIM_PORT = Number(process.env.E2E_SIM_PORT ?? 8335);
const OIDC_PORT = Number(process.env.E2E_OIDC_PORT ?? 8635);
const EMULATOR_PORT = OIDC_PORT + 1;
const RECORD_VIDEO = process.env.DEMO_VIDEO === "1";
const RESULTS_DIR = process.env.DEMO_RESULTS_DIR ?? "./test-results-demo";

if (!process.env.E2E_SIGNING_KEY) {
  const { privateKey, publicKey } = generateKeyPairSync("ed25519");
  process.env.E2E_SIGNING_KEY = privateKey.export({ format: "jwk" }).d as string;
  process.env.E2E_PUBLIC_KEY = publicKey.export({ format: "jwk" }).x as string;
  process.env.E2E_OPERATOR_KEY = randomBytes(18).toString("base64url");
  process.env.E2E_AUTOMATION_KEY = randomBytes(18).toString("base64url");
  process.env.E2E_PASSWORD = randomBytes(12).toString("base64url");
}

const DATABASE = selectE2EDatabase(process.env);
process.env.E2E_DATABASE = DATABASE;
process.env.E2E_CORE_URL = "http://127.0.0.1:" + CORE_PORT;
process.env.E2E_SIM_URL = "http://127.0.0.1:" + SIM_PORT;
process.env.B7_GNANI_EMULATOR_URL = "http://127.0.0.1:" + EMULATOR_PORT;
process.env.B7_BASE_URL = "http://localhost:" + WEB_PORT;

const shared = {
  E2E_DATABASE: DATABASE,
  PRAMANA_DB_NAMES: process.env.PRAMANA_DB_NAMES as string,
  PRAMANA_DB_PORT: process.env.PRAMANA_DB_PORT ?? "5433",
  E2E_CORE_PORT: String(CORE_PORT),
  E2E_SIM_PORT: String(SIM_PORT),
};

export default defineConfig({
  testDir: "./tests-demo",
  outputDir: RESULTS_DIR,
  timeout: 360_000,
  expect: { timeout: 20_000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [["list"]],
  use: {
    baseURL: "http://localhost:" + WEB_PORT,
    browserName: "chromium",
    channel: undefined,
    launchOptions: { headless: true },
    actionTimeout: 20_000,
    navigationTimeout: 30_000,
    viewport: { width: 1920, height: 1080 },
    screen: { width: 1920, height: 1080 },
    deviceScaleFactor: 1,
    video: RECORD_VIDEO
      ? {
          mode: "on",
          size: { width: 1920, height: 1080 },
        }
      : "off",
    trace: "off",
  },
  projects: [{ name: "desktop", use: { viewport: { width: 1920, height: 1080 } } }],
  webServer: [
    {
      command: "uv run python ../../scripts/mock_oidc.py --port " + OIDC_PORT + " --client-id pramana-e2e",
      url: "http://127.0.0.1:" + OIDC_PORT + "/.well-known/openid-configuration",
      timeout: 120_000,
      reuseExistingServer: false,
    },
    {
      command: "uv run python ../../scripts/gnani_emulator.py --serve --port " + EMULATOR_PORT,
      url: "http://127.0.0.1:" + EMULATOR_PORT + "/stats",
      timeout: 120_000,
      reuseExistingServer: false,
    },
    {
      command: "uv run python tests-real/backend.py sim",
      url: "http://127.0.0.1:" + SIM_PORT + "/health",
      timeout: 120_000,
      reuseExistingServer: false,
      env: {
        ...shared,
        PRAMANA_MODE: "dev",
        SIM_OPERATOR_KEY: process.env.E2E_OPERATOR_KEY as string,
        SIM_PARTICIPANT_PUBLIC_KEY: process.env.E2E_PUBLIC_KEY as string,
      },
    },
    {
      command: "uv run python tests-real/backend.py core",
      url: "http://127.0.0.1:" + CORE_PORT + "/health",
      timeout: 180_000,
      reuseExistingServer: false,
      env: {
        ...shared,
        PRAMANA_MODE: "dev",
        AUTH_REQUIRED: "true",
        LOG_JSON: "false",
        LOG_LEVEL: "WARNING",
        SIM_URL: "http://127.0.0.1:" + SIM_PORT,
        SIM_PUBLIC_URL: "http://127.0.0.1:" + SIM_PORT,
        SIM_OPERATOR_KEY: process.env.E2E_OPERATOR_KEY as string,
        PARTICIPANT_SIGNING_KEY: process.env.E2E_SIGNING_KEY as string,
        CORE_AUTOMATION_KEY: process.env.E2E_AUTOMATION_KEY as string,
        E2E_PASSWORD: process.env.E2E_PASSWORD as string,
        GNANI_API_KEY: "local-emulator-only",
        GNANI_BASE_URL: "http://127.0.0.1:" + EMULATOR_PORT,
        GMAIL_ADDRESS: "",
        GMAIL_APP_PASSWORD: "",
        LLM_EXTRACTOR_PROVIDER: "none",
        EVAL_REPORTS_DIR: "apps/web/tests-real/fixtures/reports",
        OIDC_ISSUER: "http://localhost:" + OIDC_PORT,
        OIDC_DISCOVERY_URL: "http://localhost:" + OIDC_PORT + "/.well-known/openid-configuration",
        GOOGLE_OAUTH_CLIENT_ID: "pramana-e2e",
        GOOGLE_OAUTH_CLIENT_SECRET: "local-only",
        OIDC_REDIRECT_URL: "http://localhost:" + WEB_PORT + "/api/core/v1/auth/google/callback",
      },
    },
    {
      command: "npx next build && npx next start -p " + WEB_PORT,
      url: "http://localhost:" + WEB_PORT,
      timeout: 300_000,
      reuseExistingServer: false,
      env: {
        PRAMANA_CORE_URL: "http://127.0.0.1:" + CORE_PORT,
        PRAMANA_SIM_URL: "http://127.0.0.1:" + SIM_PORT,
        NEXT_PUBLIC_ENABLE_PREVIEW: "0",
      },
    },
  ],
});
