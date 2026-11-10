import { mkdirSync } from "node:fs";
import path from "node:path";
import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

const output = path.resolve(process.cwd(), "../../../nov10-polish/.cache/nov10/out/B5/final");
const viewports = [
  { width: 1440, height: 900 },
  { width: 768, height: 1024 },
  { width: 390, height: 844 },
];
const screens = [
  { label: "landing", path: "/" },
  { label: "sign-in", path: "/login" },
  { label: "console-home", path: "/app" },
  { label: "investigations-list", path: "/app/investigations" },
  { label: "investigation-new", path: "/app/investigations/new" },
  { label: "investigation-active", path: "/app/investigations/preview-0001" },
  { label: "replay", path: "/app/investigations/preview-0001/replay" },
  { label: "participants", path: "/app/participants" },
  { label: "sites", path: "/app/sites" },
  { label: "evaluation", path: "/app/evaluation" },
  { label: "settings", path: "/app/settings" },
  { label: "account", path: "/app/account" },
  { label: "participant-phone", path: "/join/preview?p=p_mahesh" },
  { label: "invitation", path: "/invite/not-a-token" },
  { label: "consent-invalid", path: "/consent/not-a-token" },
  { label: "not-found", path: "/b5-route-that-does-not-exist" },
];

const session = {
  user_id: "b5-review-user",
  display_name: "Review operator",
  email: "review@example.test",
  email_verified: true,
  roles: ["operator", "approver"],
  expires_at: "2099-11-10T00:00:00Z",
  method: "open",
};
const account = {
  destination: "/app",
  identities: [],
  memberships: [],
  onboarding: { answers: {}, step: "done", updated_at: "2026-11-10T00:00:00Z", version: 1 },
  pending_invitations: [],
  preferences: {},
  user: session,
};

async function installAccountMocks(page: Page, preview: boolean) {
  await page.route("**/api/core/health", (route) => route.fulfill({ json: "ok" }));
  await page.route("**/api/core/v1/auth/session", (route) => route.fulfill({ json: session }));
  await page.route("**/api/core/v1/me", (route) => route.fulfill({ json: account }));
  await page.route("**/api/core/v1/voice/status", (route) => route.fulfill({ json: { configured: false } }));
  if (preview) {
    await page.addInitScript(() => {
      if (location.pathname.startsWith("/app")) sessionStorage.setItem("pramana.preview", "true");
    });
  }
}

function expectedHttpError(label: string, status: number, url: string) {
  if (label === "not-found") return status === 404 && new URL(url).pathname === "/b5-route-that-does-not-exist";
  if (label === "consent-invalid") return status === 404 && url.includes("/v1/consent-links/not-a-token");
  if (label === "investigation-list-error") return status === 422 && url.includes("/v1/investigations");
  return false;
}

async function checkPage(page: Page, label: string, width: number) {
  await page.evaluate(async () => {
    await new Promise<void>((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve())));
    const active = document.documentElement
      .getAnimations({ subtree: true })
      .filter((animation) => animation.playState === "running" && animation.effect?.getTiming().iterations !== Infinity);
    await Promise.all(active.map((animation) => animation.finished.catch(() => undefined)));
  });
  const documentWidth = await page.evaluate(() => document.documentElement.scrollWidth);
  expect(documentWidth, `${label} has horizontal overflow at ${width}px`).toBeLessThanOrEqual(width);
  const axe = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
  expect(
    axe.violations.map((violation) => ({ id: violation.id, targets: violation.nodes.map((node) => node.target) })),
    `${label} accessibility at ${width}px`,
  ).toEqual([]);
  mkdirSync(output, { recursive: true });
  await page.screenshot({ path: path.join(output, `b5-${label}-${width}.png`) });
}

for (const screen of screens) {
  for (const viewport of viewports) {
    test(`${screen.label} has no overflow or WCAG 2.1 AA violations at ${viewport.width}px`, async ({ page }) => {
      const errors: string[] = [];
      const failedRequests: string[] = [];
      const badResponses: { status: number; url: string }[] = [];
      page.on("pageerror", (error) => errors.push(error.message));
      page.on("console", (message) => {
        if (message.type() === "error" && !message.text().startsWith("Failed to load resource:")) errors.push(message.text());
      });
      page.on("requestfailed", (request) => {
        const failure = request.failure()?.errorText ?? "failed";
        if (!(failure === "net::ERR_ABORTED" && request.url().includes("_rsc="))) {
          failedRequests.push(`${request.method()} ${request.url()} ${failure}`);
        }
      });
      page.on("response", (response) => {
        if (response.status() >= 400) badResponses.push({ status: response.status(), url: response.url() });
      });
      await page.setViewportSize(viewport);
      await installAccountMocks(page, screen.path.startsWith("/app"));
      if (screen.label === "consent-invalid") {
        await page.route("**/api/core/v1/consent-links/not-a-token", (route) =>
          route.fulfill({
            status: 404,
            json: { error: { code: "CONSENT_LINK_INVALID", message: "This consent link is unavailable." } },
          }),
        );
      }
      const response = await page.goto(screen.path);
      if (screen.label === "not-found") expect(response?.status()).toBe(404);
      if (screen.label === "consent-invalid") await expect(page.getByRole("main")).toContainText("Consent link unavailable");
      else await expect(page.getByRole("heading").first()).toBeVisible();
      if (screen.label === "investigation-new") {
        const steps = page.getByRole("navigation", { name: "Steps" });
        for (const name of ["Site", "Problem", "Participants", "Languages", "Permissions", "Configuration", "Confirm"]) {
          await expect(steps.getByText(name, { exact: true })).toBeVisible();
        }
      }
      if (screen.label === "participants") {
        await expect(page.getByText("Hinglish (Hindi and English mixed)", { exact: true })).toBeVisible();
        await expect(page.getByText("Hinglish (Hindi and English mixed) (mixed)", { exact: true })).toHaveCount(0);
      }
      if (screen.label === "settings") {
        await expect(page.locator("main")).not.toContainText(/PRAMANA_(CORE|SIM)_URL|127\.0\.0\.1:\d+/);
      }
      await page.evaluate(() => document.fonts.ready.then(() => true));
      await checkPage(page, screen.label, viewport.width);
      expect(errors, `${screen.label} emitted browser errors`).toEqual([]);
      expect(failedRequests, `${screen.label} had failed requests`).toEqual([]);
      expect(
        badResponses.filter(({ status, url }) => !expectedHttpError(screen.label, status, url)),
        `${screen.label} returned unexpected HTTP errors`,
      ).toEqual([]);
    });
  }
}

for (const viewport of viewports) {
  for (const state of ["empty", "error", "loading"] as const) {
    const label = `investigation-list-${state}`;
    test(`${label} has no overflow or WCAG violations at ${viewport.width}px`, async ({ page }) => {
      const errors: string[] = [];
      const failedRequests: string[] = [];
      const badResponses: { status: number; url: string }[] = [];
      page.on("pageerror", (error) => errors.push(error.message));
      page.on("console", (message) => {
        if (message.type() === "error" && !message.text().startsWith("Failed to load resource:")) errors.push(message.text());
      });
      page.on("requestfailed", (request) => {
        const failure = request.failure()?.errorText ?? "failed";
        if (!(failure === "net::ERR_ABORTED" && request.url().includes("_rsc="))) {
          failedRequests.push(`${request.method()} ${request.url()} ${failure}`);
        }
      });
      page.on("response", (response) => {
        if (response.status() >= 400) badResponses.push({ status: response.status(), url: response.url() });
      });
      await page.setViewportSize(viewport);
      await installAccountMocks(page, false);
      if (state === "empty") {
        await page.route("**/api/core/v1/investigations*", (route) =>
          route.fulfill({ json: { items: [], next_cursor: null, limit: 25 } }),
        );
      } else if (state === "error") {
        await page.route("**/api/core/v1/investigations*", (route) =>
          route.fulfill({ status: 422, json: { error: { code: "INVALID_FILTER", message: "The investigation list could not be loaded.", request_id: "b5" } } }),
        );
      } else {
        await page.route("**/api/core/v1/investigations*", () => new Promise<void>(() => {}));
      }
      await page.goto("/app/investigations");
      if (state === "loading") await expect(page.locator('[aria-busy="true"]')).toBeVisible();
      else await expect(page.getByText(state === "empty" ? "No investigations yet" : "Could not load this")).toBeVisible();
      await checkPage(page, label, viewport.width);
      expect(errors, `${label} emitted browser errors`).toEqual([]);
      expect(failedRequests, `${label} had failed requests`).toEqual([]);
      expect(
        badResponses.filter(({ status, url }) => !expectedHttpError(label, status, url)),
        `${label} returned unexpected HTTP errors`,
      ).toEqual([]);
    });
  }
}
