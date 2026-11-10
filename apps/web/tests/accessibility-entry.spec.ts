import { expect, test } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

for (const viewport of [{ width: 390, height: 844 }, { width: 1440, height: 900 }]) {
  for (const path of ["/", "/login"]) {
    test(`entry accessibility at ${viewport.width}px: ${path}`, async ({ page }) => {
      await page.setViewportSize(viewport);
      await page.goto(path);
      const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
      expect(results.violations).toEqual([]);
    });
  }
}

test("keyboard users can focus the language strip", async ({ page }) => {
  await page.goto("/");
  const strip = page.getByRole("list", { name: "Languages and answer modes" });
  for (let i = 0; i < 30 && !(await strip.evaluate((el) => el === document.activeElement)); i++) {
    await page.keyboard.press("Tab");
  }
  await expect(strip).toBeFocused();
});
