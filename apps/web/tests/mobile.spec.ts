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
