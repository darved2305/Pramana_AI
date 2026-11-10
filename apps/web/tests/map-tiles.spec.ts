import { expect, test } from "@playwright/test";

test.beforeEach(async ({ page }) => {
  await page.goto("/preview/app");
  await expect(page).toHaveURL(/\/app$/);
  await expect(page.getByText("Development preview.")).toBeVisible();
});

// Map tiles show restricted places, occupancy and observations by icon, initial and colour.
// Their accessible text must say the same thing, so a screen reader user gets every fact.
test.describe("preview console map tiles", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/preview/app");
    await expect(page).toHaveURL(/\/app$/);
  });

  test("a restricted map tile says it is restricted to screen readers", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/app/investigations/preview-0001");
    const label = page.getByText("network closet IDF-1", { exact: true }).first();
    await expect(label).toBeVisible();
    const tile = label.locator("xpath=../..");
    await expect(tile).toContainText("restricted");
  });

  test("a tile with a person in it names the person count to screen readers", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto("/app/investigations/preview-0001");
    const tile = page.getByText("room 304", { exact: true }).first().locator("xpath=../..");
    await expect(tile).toContainText("1 person");
  });
});
