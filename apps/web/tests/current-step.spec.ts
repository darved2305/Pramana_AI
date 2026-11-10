import { expect, test } from "@playwright/test";
import { previewInvestigation, previewPack } from "../src/lib/preview/fixtures";
import { encodeJoin } from "../src/lib/join";
import { reasonSummary } from "../src/lib/data/derive";

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
      await expect(step).toContainText(reasonSummary(state.plan.reason));
      const box = await step.boundingBox();
      expect(box).not.toBeNull();
      expect(box!.y + box!.height).toBeLessThanOrEqual(viewport.height);
    });
  }
}

test("operator gets a clear explanation when the active plan has no recorded reason", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const state = { ...previewInvestigation, plan: { ...previewInvestigation.plan, reason: "" } };
  await page.route("**/api/core/v1/auth/session", (r) => r.fulfill({ json: session }));
  await page.route("**/api/core/v1/packs/**", (r) => r.fulfill({ json: previewPack }));
  await page.route("**/api/core/v1/investigations/step-empty-reason", (r) => r.fulfill({ json: state }));
  await page.route("**/api/core/v1/investigations/step-empty-reason/events**", (r) => r.fulfill({ json: [] }));
  await page.route("**/api/core/v1/investigations/step-empty-reason/stream**", () => new Promise<void>(() => {}));
  await page.goto("/app/investigations/step-empty-reason");
  const step = page.getByRole("region", { name: "Current step" });
  await expect(step).toContainText("This check is expected to help narrow the reported problem.");
  const box = await step.boundingBox();
  expect(box).not.toBeNull();
  expect(box!.y + box!.height).toBeLessThanOrEqual(844);
});

test("participant sees who the question is for, the question, and its recorded reason", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/join/preview?p=p_mahesh");
  const step = page.getByTestId("participant-current-step");
  await expect(step).toContainText("Question for Mahesh");
  await expect(step).toContainText(previewInvestigation.pending_question!.text);
  await expect(step).toContainText("more than any other available question");
  const box = await step.boundingBox();
  expect(box).not.toBeNull();
  expect(box!.y + box!.height).toBeLessThanOrEqual(844);
});

test("participant gets a clear explanation when the plan has no recorded reason", async ({ page }) => {
  const state = { ...previewInvestigation, plan: { ...previewInvestigation.plan, reason: "" } };
  const token = encodeJoin({ i: "participant-reason", p: "p_mahesh", s: "scenario", t: "token" });
  await page.route("**/api/core/v1/investigations/participant-reason", (r) => r.fulfill({ json: state }));
  await page.route("**/api/sim/**", (r) => r.abort());
  await page.goto(`/join/${token}`);
  const reason = page.getByTestId("participant-current-step").locator("p").last();
  await expect(reason).toContainText("Why this check:");
  await expect(reason).toContainText("Your answer adds an observation that helps narrow the reported problem.");
});

test("participant sees the recorded recommendation and confidence without hidden truth", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const decided = {
    ...previewInvestigation,
    status: "decided" as const,
    pending_question: null,
    pending_questions: [],
    ground_truth: null,
    plan: {
      ...previewInvestigation.plan,
      kind: "decide" as const,
      decision_class: "DISPATCH_ELECTRICIAN_DB_C2",
      decision_probability: 0.95,
      reason: "The recorded evidence meets the decision threshold.",
    },
  };
  const token = encodeJoin({ i: "participant-decision", p: "p_mahesh", s: "scenario", t: "token" });
  await page.route("**/api/core/v1/investigations/participant-decision", (r) => r.fulfill({ json: decided }));
  await page.route("**/api/sim/**", (r) => r.abort());
  await page.goto(`/join/${token}`);
  const step = page.getByTestId("participant-current-step");
  await expect(step).toContainText("Send the electrician to panel DB-C2");
  await expect(step).toContainText("95% confidence");
  await expect(step).toContainText("hidden fault stays sealed");
  await expect(step).not.toContainText("ground_truth");
});
