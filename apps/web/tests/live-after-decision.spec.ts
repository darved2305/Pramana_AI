import { expect, test } from "@playwright/test";
import { previewInvestigation, previewPack } from "../src/lib/preview/fixtures";
import type { InvestigationState } from "../src/lib/api/types";

/**
 * A decision is not the end: an approver in another browser approves, the electrician repairs,
 * verification questions follow, and the operator reveals. The console must keep following the
 * investigation after "decided" (found watching a live voice-bot run), and stop only once closed.
 */
const session = { user_id: "u_1", display_name: "Olu Operator", email: "op@x.test", roles: ["operator"], expires_at: "2099-01-01T00:00:00Z", method: "session" };

test("the console keeps following an investigation after it is decided", async ({ page }) => {
  let current: InvestigationState = { ...previewInvestigation, id: "inv_after1", status: "decided", pending_question: null, pending_questions: [] };
  let seq = 10;
  await page.route("**/api/core/v1/auth/session", (r) => r.fulfill({ json: session }));
  await page.route("**/api/core/v1/packs/**", (r) => r.fulfill({ json: previewPack }));
  await page.route("**/api/core/v1/investigations/inv_after1", (r) => r.fulfill({ json: current }));
  await page.route("**/api/core/v1/investigations/inv_after1/stream**", () => new Promise<void>(() => {}));
  await page.route("**/api/core/v1/investigations/inv_after1/events**", (r) =>
    r.fulfill({ json: [{ seq, investigation_id: "inv_after1", type: "BeliefUpdated", payload: {}, ts: new Date().toISOString() }] }),
  );
  await page.goto("/app/investigations/inv_after1");
  await expect(page.getByText("Decided", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("Live", { exact: true })).toBeVisible();
  // Someone else approves and the repair is verified: the page must show it without a reload.
  current = { ...current, status: "verified" };
  seq = 11;
  await expect(page.getByText("Verified", { exact: true }).first()).toBeVisible({ timeout: 20_000 });
  // Only a closed investigation stops changing.
  current = { ...current, status: "closed" };
  seq = 12;
  await expect(page.getByText("Closed", { exact: true }).first()).toBeVisible({ timeout: 20_000 });
  await expect(page.getByText("Not polling: investigation closed")).toBeVisible();
});
