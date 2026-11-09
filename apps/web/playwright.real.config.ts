import { generateKeyPairSync, randomBytes } from "node:crypto";
import { defineConfig, devices } from "@playwright/test";

/**
 * End-to-end tests against a REAL simulator, core and PostgreSQL test database. Nothing is
 * mocked. Every run gets fresh keys and a freshly migrated database (`E2E_DATABASE`), so it
 * never touches development data. Requires the local PostgreSQL (`make db-up`) and `uv`.
 */
const WEB_PORT = Number(process.env.E2E_WEB_PORT ?? 3022);
const CORE_PORT = Number(process.env.E2E_CORE_PORT ?? 8020);
const SIM_PORT = Number(process.env.E2E_SIM_PORT ?? 8120);
const OIDC_PORT = Number(process.env.E2E_OIDC_PORT ?? 8420);

// Workers re-evaluate this file; keys are generated once in the main process and inherited.
if (!process.env.E2E_SIGNING_KEY) {
  const { privateKey, publicKey } = generateKeyPairSync("ed25519");
  process.env.E2E_SIGNING_KEY = privateKey.export({ format: "jwk" }).d as string;
  process.env.E2E_PUBLIC_KEY = publicKey.export({ format: "jwk" }).x as string;
  process.env.E2E_OPERATOR_KEY = randomBytes(18).toString("base64url");
  process.env.E2E_AUTOMATION_KEY = randomBytes(18).toString("base64url");
  process.env.E2E_PASSWORD = randomBytes(12).toString("base64url");
}
const DATABASE = process.env.E2E_DATABASE ?? "pramana_web_e2e";
process.env.E2E_DATABASE = DATABASE;
process.env.E2E_CORE_URL = `http://127.0.0.1:${CORE_PORT}`;
process.env.E2E_SIM_URL = `http://127.0.0.1:${SIM_PORT}`;

const shared = { E2E_DATABASE: DATABASE, E2E_CORE_PORT: String(CORE_PORT), E2E_SIM_PORT: String(SIM_PORT) };

// Local runs use Playwright's own Chromium in a throwaway profile. The installed Google Chrome can
// pass the password fields these tests type (some deliberately wrong) to Windows sign-in, which
// locked the Windows account on a shared laptop. CI keeps the installed Chrome; set
// PW_CHANNEL=chrome to use it locally on purpose.
const CHANNEL = process.env.PW_CHANNEL ?? (process.env.CI ? "chrome" : undefined);

export default defineConfig({
  testDir: "./tests-real",
  timeout: 180_000,
  expect: { timeout: 20_000 },
  // One shared backend and database: tests run one at a time.
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [["list"]],
  use: {
    baseURL: `http://localhost:${WEB_PORT}`,
    channel: CHANNEL,
    trace: "retain-on-failure",
    ...devices["Desktop Chrome"],
    viewport: { width: 1440, height: 900 },
  },
  webServer: [
    {
      command: `uv run python ../../scripts/mock_oidc.py --port ${OIDC_PORT} --client-id pramana-e2e`,
      url: `http://127.0.0.1:${OIDC_PORT}/.well-known/openid-configuration`,
      timeout: 120_000,
      reuseExistingServer: false,
    },
    {
      command: "uv run python tests-real/backend.py sim",
      url: `http://127.0.0.1:${SIM_PORT}/health`,
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
      url: `http://127.0.0.1:${CORE_PORT}/health`,
      timeout: 180_000,
      reuseExistingServer: false,
      env: {
        ...shared,
        PRAMANA_MODE: "dev",
        AUTH_REQUIRED: "true",
        LOG_JSON: "false",
        LOG_LEVEL: "WARNING",
        SIM_URL: `http://127.0.0.1:${SIM_PORT}`,
        SIM_PUBLIC_URL: `http://127.0.0.1:${SIM_PORT}`,
        SIM_OPERATOR_KEY: process.env.E2E_OPERATOR_KEY as string,
        PARTICIPANT_SIGNING_KEY: process.env.E2E_SIGNING_KEY as string,
        CORE_AUTOMATION_KEY: process.env.E2E_AUTOMATION_KEY as string,
        E2E_PASSWORD: process.env.E2E_PASSWORD as string,
        GNANI_API_KEY: "",
        LLM_EXTRACTOR_PROVIDER: "none",
        EVAL_REPORTS_DIR: "apps/web/tests-real/fixtures/reports",
        OIDC_ISSUER: `http://localhost:${OIDC_PORT}`,
        OIDC_DISCOVERY_URL: `http://localhost:${OIDC_PORT}/.well-known/openid-configuration`,
        GOOGLE_OAUTH_CLIENT_ID: "pramana-e2e",
        GOOGLE_OAUTH_CLIENT_SECRET: "local-only",
        OIDC_REDIRECT_URL: `http://localhost:${WEB_PORT}/api/core/v1/auth/google/callback`,
        // Tests always keep email in the local outbox, even if the parent shell has Gmail set.
        GMAIL_ADDRESS: "",
        GMAIL_APP_PASSWORD: "",
      },
    },
    {
      command: `npx next build && npx next start -p ${WEB_PORT}`,
      url: `http://localhost:${WEB_PORT}`,
      timeout: 300_000,
      reuseExistingServer: false,
      env: {
        PRAMANA_CORE_URL: `http://127.0.0.1:${CORE_PORT}`,
        PRAMANA_SIM_URL: `http://127.0.0.1:${SIM_PORT}`,
        // The product build: no sample-data mode, everything comes from the live core.
        NEXT_PUBLIC_ENABLE_PREVIEW: "0",
      },
    },
  ],
});
