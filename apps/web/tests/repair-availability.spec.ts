import { expect, test } from "@playwright/test";
import { previewInvestigation, previewPack } from "../src/lib/preview/fixtures";
import type { InvestigationState } from "../src/lib/api/types";

for (const scenario of [
  { decision: "IT_REPLACE_AP_2A", electrician: true, available: false, message: "breaker resets only" },
  { decision: "DISPATCH_ELECTRICIAN_DB_C2", electrician: false, available: false, message: "No electrician" },
  { decision: "DISPATCH_ELECTRICIAN_MAIN", electrician: true, available: true, message: "send it for approval" },
]) {
  test(`repair availability: ${scenario.decision}, electrician ${scenario.electrician}`, async ({ page }) => {
    const state: InvestigationState = {
      ...previewInvestigation, id: "inv_repair1", status: "decided", approvals: [],
      pending_question: null, pending_questions: [],
      participants: previewInvestigation.participants.filter((p) => scenario.electrician || !p.roles.includes("electrician")),
      plan: { ...previewInvestigation.plan, kind: "decide", decision_class: scenario.decision },
    };
    await page.route("**/api/core/v1/auth/session", (r) => r.fulfill({ json: {
      user_id: "u_1", display_name: "Operator", email: "op@x.test", roles: ["operator"],
      expires_at: "2099-01-01T00:00:00Z", method: "session",
    } }));
    await page.route("**/api/core/v1/packs/**", (r) => r.fulfill({ json: previewPack }));
    await page.route("**/api/core/v1/investigations/inv_repair1", (r) => r.fulfill({ json: state }));
    await page.route("**/api/core/v1/investigations/inv_repair1/events**", (r) => r.fulfill({ json: [] }));
    await page.route("**/api/core/v1/investigations/inv_repair1/stream**", (r) => r.abort());
    await page.goto("/app/investigations/inv_repair1");
    const panel = page.locator("[aria-labelledby=appr-title]");
    await expect(panel).toContainText(scenario.message);
    const button = panel.getByRole("button", { name: "Propose repair", exact: true });
    if (scenario.available) {
      await button.click();
      await expect(page.getByRole("dialog", { name: "Propose a repair" })).toBeVisible();
      await expect(page.getByRole("dialog").getByLabel("Breaker")).toBeVisible();
    } else {
      await expect(button).toHaveCount(0);
    }
  });
}
