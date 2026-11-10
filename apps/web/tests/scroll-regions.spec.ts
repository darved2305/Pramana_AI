import { expect, test } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

for (const item of [
  { path: "/app/investigations/preview-0001", label: "Observations table" },
  { path: "/app/investigations/preview-0001/replay", label: "Event details" },
  { path: "/app/evaluation", label: "Metrics by policy" },
]) {
  test(`${item.label} can be focused and scrolled by keyboard`, async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/preview/app");
    await page.goto(item.path);
    const region = page.getByRole("region", { name: item.label });
    await expect(region).toBeVisible();
    await region.focus();
    await expect(region).toBeFocused();
    await expect(region).toHaveCSS("outline-style", "solid");
    const result = await new AxeBuilder({ page })
      .include(`[role="region"][aria-label="${item.label}"]`)
      .withRules(["scrollable-region-focusable"])
      .analyze();
    expect(result.violations).toEqual([]);
  });
}
