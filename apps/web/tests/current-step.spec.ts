import { expect, test } from "@playwright/test";
import { previewInvestigation, previewPack } from "../src/lib/preview/fixtures";

const session = { user_id: "u_1", display_name: "Operator", email: "op@x.test", roles: ["operator"], expires_at: "2099-01-01T00:00:00Z", method: "session" };

for (const viewport of [{ width: 390, height: 844 }, { width: 1440, height: 900 }]) {
  for (const decided of [false, true]) {
    test(`current ${decided ? "decision" : "question"} is in the first viewport at ${viewport.width}px`, async ({ page }) => {
      await page.setViewportSize(viewport);
      const state = decided ? {
        ...previewInvestigation, status: "decided", pending_question: null, pending_questions: [],
        plan: { ...previewInvestigation.plan, kind: "decide", decision_class: previewInvestigation.belief.decisions[0].id, decision_probability: 0.96, reason: "The evidence supports this decision." },
      } : previewInvestigation;
      await page.route("**/api/core/v1/auth/session", (r) => r.fulfill({ json: session }));
      await page.route("**/api/core/v1/packs/**", (r) => r.fulfill({ json: previewPack }));
      await page.route("**/api/core/v1/investigations/step-test", (r) => r.fulfill({ json: state }));
      await page.route("**/api/core/v1/investigations/step-test/events**", (r) => r.fulfill({ json: [] }));
      await page.route("**/api/core/v1/investigations/step-test/stream**", () => new Promise<void>(() => {}));
      await page.goto("/app/investigations/step-test");
      await expect(page.getByText("The building and its fault are simulated.")).toBeVisible();
      const step = page.getByRole("region", { name: "Current step" });
      await expect(step).toContainText(decided ? "96% confidence" : previewInvestigation.pending_question!.text);
      await expect(step).toContainText(state.plan.reason);
      const box = await step.boundingBox();
      expect(box).not.toBeNull();
      expect(box!.y + box!.height).toBeLessThanOrEqual(viewport.height);
    });
  }
}
