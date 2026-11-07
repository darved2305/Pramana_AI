import { expect, test } from "@playwright/test";
import { encodeJoin } from "../src/lib/join";
import { previewInvestigation } from "../src/lib/preview/fixtures";
import type { InvestigationState } from "../src/lib/api/types";

/**
 * The electrician collected permission but it expired before the reset (the server clock
 * cannot be moved in the real-stack tests, so the core and simulator answers are stubbed with
 * the exact shapes they return). The page must offer to collect it again, not dead-end.
 */
test("an expired repair permission is collected again and the repair completes", async ({ page }) => {
  const approval = {
    id: "apr_1", action: "reset_breaker", action_label: "Reset breaker", target: "CB_C2_7",
    participant_id: "p_imran", status: "approved" as const, risk: "medium" as const, reversible: true,
    rationale: "DISPATCH_ELECTRICIAN_DB_C2 at P = 0.970", requested_at: "2026-11-07T06:00:00Z",
    approver_id: "u_ap",
  };
  const acting: InvestigationState = {
    ...previewInvestigation, id: "inv_exp1", status: "acting", pending_question: null, pending_questions: [],
    approvals: [approval],
  };
  let collected = 0;
  let acted = 0;
  let reported = false;
  await page.route("**/api/core/v1/investigations/inv_exp1", (r) =>
    r.fulfill({ json: reported ? { ...acting, status: "verifying", approvals: [{ ...approval, status: "executed" }] } : acting }),
  );
  await page.route("**/api/core/v1/investigations/inv_exp1/approvals/apr_1/capability**", (r) => {
    collected++;
    return r.fulfill({ json: {
      capability: `cap-${collected}`, expires_at: "2026-11-07T06:05:00Z", action: "reset_breaker", target: "CB_C2_7",
      scenario_id: "scn_1", sim_url: "http://sim.test", instructions: "Reset breaker CB_C2_7 at the DB-C2 panel.",
      location_id: "DB_C2_PANEL",
    } });
  });
  await page.route("**/api/core/v1/investigations/inv_exp1/interventions", (r) => {
    reported = true;
    return r.fulfill({ json: { ...acting, status: "verifying", approvals: [{ ...approval, status: "executed" }] } });
  });
  await page.route("**/api/sim/sim/v1/scenarios/scn_1/view", (r) =>
    r.fulfill({ json: { location_label: "the maintenance room", items: [], reachable_locations: [] } }),
  );
  await page.route("**/api/sim/sim/v1/scenarios/scn_1/move", (r) => r.fulfill({ json: { location_id: "DB_C2_PANEL" } }));
  await page.route("**/api/sim/sim/v1/scenarios/scn_1/act", (r) => {
    acted++;
    const body = r.request().postDataJSON() as { capability: string };
    // The simulator's own response to an expired capability (pramana_sim.app: TokenError -> 403).
    if (body.capability === "cap-1") return r.fulfill({ status: 403, json: { detail: "capability expired" } });
    return r.fulfill({ json: { action: "reset_breaker", target: "CB_C2_7", performed: true } });
  });

  await page.goto(`/join/${encodeJoin({ i: "inv_exp1", p: "p_imran", s: "scn_1", t: "tok" })}`);
  await expect(page.getByRole("heading", { name: "You are cleared to act" })).toBeVisible();
  await page.getByRole("button", { name: "Collect permission" }).click();
  await page.getByRole("button", { name: "I am at the panel" }).click();
  await page.getByRole("button", { name: "I have done it" }).click();
  await expect(page.locator("p[role=alert]")).toHaveText("Your permission expired before it was used. Collect it again.");
  expect(reported).toBe(false);

  await page.getByRole("button", { name: "Collect permission" }).click();
  await page.getByRole("button", { name: "I am at the panel" }).click();
  await page.getByRole("button", { name: "I have done it" }).click();
  await expect.poll(() => reported).toBe(true);
  expect(collected).toBe(2);
  expect(acted).toBe(2);
});
