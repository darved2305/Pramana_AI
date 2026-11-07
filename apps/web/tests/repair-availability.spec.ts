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

for (const who of [
  { userId: "u_both", asked: true },
  { userId: "u_other", asked: false },
]) {
  test(`an approval ${who.asked ? "cannot" : "can"} be decided by ${who.asked ? "the account that asked" : "another approver"}`, async ({ page }) => {
    const state: InvestigationState = {
      ...previewInvestigation, id: "inv_self1", status: "awaiting_approval",
      pending_question: null, pending_questions: [],
      plan: { ...previewInvestigation.plan, kind: "decide", decision_class: "DISPATCH_ELECTRICIAN_DB_C2" },
      approvals: [{
        id: "apr_1", action: "reset_breaker", action_label: "Reset breaker", target: "CB_C2_7",
        participant_id: "p_imran", status: "pending", risk: "medium", reversible: true,
        rationale: "DISPATCH_ELECTRICIAN_DB_C2 at P = 0.970", requested_at: "2026-11-07T06:00:00Z",
        requested_by: "u_both",
      }],
    };
    await page.route("**/api/core/v1/auth/session", (r) => r.fulfill({ json: {
      user_id: who.userId, display_name: "Bo Both", email: "both@x.test", roles: ["operator", "approver"],
      expires_at: "2099-01-01T00:00:00Z", method: "session",
    } }));
    await page.route("**/api/core/v1/packs/**", (r) => r.fulfill({ json: previewPack }));
    await page.route("**/api/core/v1/investigations/inv_self1", (r) => r.fulfill({ json: state }));
    await page.route("**/api/core/v1/investigations/inv_self1/events**", (r) => r.fulfill({ json: [] }));
    await page.route("**/api/core/v1/investigations/inv_self1/stream**", (r) => r.abort());
    await page.goto("/app/investigations/inv_self1");
    const panel = page.locator("[aria-labelledby=appr-title]");
    const approve = panel.getByRole("button", { name: "Approve", exact: true });
    await expect(approve).toBeVisible();
    if (who.asked) {
      await expect(approve).toBeDisabled();
      await expect(panel).toContainText("another approver must decide it");
    } else {
      await expect(approve).toBeEnabled();
    }
  });
}
