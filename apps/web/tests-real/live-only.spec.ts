/**
 * The product has no sample-data mode: every page reads the live core, simulator and database.
 * (Sample data exists only in the UI test build, `NEXT_PUBLIC_ENABLE_PREVIEW=1`.)
 */
import { expect, test } from "@playwright/test";

test("the old preview entry leads to sign-in, not to sample data", async ({ page }) => {
  await page.goto("/preview/app");
  await expect(page).toHaveURL(/\/login/);
  await expect(page.getByText("Development preview.")).toHaveCount(0);
  await expect(page.getByText(/Open the (development )?preview/)).toHaveCount(0);
});

test("a preview join link is not a participant link", async ({ page }) => {
  await page.goto("/join/preview?p=p_mahesh");
  await expect(page.getByText("Preview data")).toHaveCount(0);
});

test("the landing page opens the live console", async ({ page }) => {
  await page.goto("/");
  await expect(page.locator('a[href="/preview/app"]')).toHaveCount(0);
  await page.getByRole("link", { name: /Open the console/ }).first().click();
  await expect(page).toHaveURL(/\/login\?next=%2Fapp|\/app/);
});
