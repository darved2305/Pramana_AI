import { test, expect } from "@playwright/test";

test("mobile menu opens, navigates and closes", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Open menu" }).click();
  const menu = page.getByRole("dialog", { name: "Menu" });
  await expect(menu).toBeVisible();
  await menu.getByRole("link", { name: "Evidence" }).click();
  await expect(page).toHaveURL(/#evidence$/);
  await expect(menu).toBeHidden();
});

test("menu closes with Escape", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Open menu" }).click();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog", { name: "Menu" })).toBeHidden();
});

test("console drawer works on a phone", async ({ page }) => {
  await page.goto("/preview/app");
  await page.getByRole("button", { name: "Open navigation" }).click();
  await page.getByRole("dialog", { name: "Navigation" }).getByRole("link", { name: "Sites" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Sites" })).toBeVisible();
  await expect(page.getByRole("dialog", { name: "Navigation" })).toBeHidden();
});

test("no horizontal overflow on key screens", async ({ page }) => {
  for (const path of ["/", "/login", "/join/preview"]) {
    await page.goto(path);
    await page.waitForLoadState("networkidle");
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    expect(overflow, path).toBeLessThanOrEqual(1);
  }
});

test("a consent link can be refused in Hindi on a phone", async ({ page }) => {
  await page.route("**/api/core/v1/consent-links/**", async (route) => {
    if (route.request().method() === "GET") {
      await route.fulfill({ json: { purpose: "contact_for_investigations", language: "hi", notice_version: "1", expires_at: "2099-01-01T00:00:00Z" } });
    } else {
      expect(route.request().postDataJSON()).toEqual({ decision: "refused" });
      await route.fulfill({ json: { decision: "refused", recorded_at: "2026-11-09T00:00:00Z" } });
    }
  });
  await page.goto("/consent/org_example.secret");
  await expect(page.getByRole("heading", { name: "क्या Pramana आपसे सवाल पूछ सकता है?" })).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(1);
  await page.getByRole("button", { name: "नहीं, मैं सहमत नहीं हूँ" }).click();
  await expect(page.getByText(/आपका फैसला दर्ज हो गया है/)).toBeVisible();
});

test("a consent page reports a connection failure without calling the link expired", async ({ page }) => {
  await page.route("**/api/core/v1/consent-links/**", (route) => route.abort());
  await page.goto("/consent/org_example.secret");
  await expect(page.getByText("Pramana could not be reached. Check your connection and try again.")).toBeVisible();
  await expect(page.getByText(/This link has expired/)).toHaveCount(0);
});
