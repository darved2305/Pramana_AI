import { expect, test } from "@playwright/test";

test("ID-01: the mock Google flow returns an authenticated browser session", async ({ page }) => {
  await page.goto("/api/core/v1/auth/google/start?next=/app");
  await expect(page.getByRole("heading", { name: "Pramana local mock sign-in" })).toBeVisible();
  await page.getByRole("textbox", { name: "Subject", exact: true }).fill("browser-google-new-user");
  await page.getByRole("textbox", { name: "Email", exact: true }).fill("browser-google-new-user@gmail.com");
  await page.getByRole("button", { name: "Continue with mock account" }).click();
  await expect(page).toHaveURL(/\/app$/);
  const response = await page.request.get("/api/core/v1/auth/session");
  expect(response.status()).toBe(200);
  expect(await response.json()).toMatchObject({
    email: "browser-google-new-user@gmail.com", email_verified: true, roles: [],
  });
  const cookies = await page.context().cookies();
  expect(cookies.find((cookie) => cookie.name === "pramana_session")?.httpOnly).toBe(true);
  expect(cookies.find((cookie) => cookie.name === "pramana_auth")).toBeUndefined();
});

test("ID-16: cancellation returns to sign-in and consumes the browser flow", async ({ page }) => {
  await page.goto("/api/core/v1/auth/google/start");
  const state = new URL(page.url()).searchParams.get("state");
  expect(state).toBeTruthy();
  const callback = `/api/core/v1/auth/google/callback?error=access_denied&state=${state}`;
  await page.goto(callback);
  await expect(page).toHaveURL(/\/login\?error=cancelled$/);
  await page.goto(callback);
  await expect(page).toHaveURL(/\/login\?error=sign_in_failed$/);
});
