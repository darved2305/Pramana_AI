import { expect, test } from "@playwright/test";
import { previewInvestigation, previewPack } from "../src/lib/preview/fixtures";
import { encodeJoin } from "../src/lib/join";

const session = { user_id: "u_1", display_name: "Operator", email: "op@x.test", roles: ["operator"], expires_at: "2099-01-01T00:00:00Z", method: "session" };

// The engine's own explanation is written for engineers. The operator card must not show it.
const engineJargon = [/Next best/, /bits/, /P = /, /expected loss/];

async function openOperatorInvestigation(page: import("@playwright/test").Page, id: string, state: unknown) {
  await page.route("**/api/core/v1/auth/session", (r) => r.fulfill({ json: session }));
  await page.route("**/api/core/v1/packs/**", (r) => r.fulfill({ json: previewPack }));
  await page.route(`**/api/core/v1/investigations/${id}`, (r) => r.fulfill({ json: state }));
  await page.route(`**/api/core/v1/investigations/${id}/events**`, (r) => r.fulfill({ json: [] }));
  await page.route(`**/api/core/v1/investigations/${id}/stream**`, () => new Promise<void>(() => {}));
  await page.goto(`/app/investigations/${id}`);
}

const chosenMinutes = Math.max(1, Math.round(previewInvestigation.plan.candidates[0].cost_s / 60));

for (const viewport of [{ width: 390, height: 844 }, { width: 1440, height: 900 }]) {
  test(`operator sees the current question and its plain reason in the first viewport at ${viewport.width}px`, async ({ page }) => {
    await page.setViewportSize(viewport);
    await openOperatorInvestigation(page, "step-test", previewInvestigation);
    await expect(page.getByText("The building and its fault are simulated.")).toBeVisible();
    const step = page.getByRole("region", { name: "Current step" });
    await expect(step).toContainText(previewInvestigation.pending_question!.text);
    await expect(step).toContainText(`Pramana expects this check to help the investigation most among the checks available, for about ${chosenMinutes} min of Mahesh's time.`);
    for (const jargon of engineJargon) await expect(step).not.toContainText(jargon);
    const box = await step.boundingBox();
    expect(box).not.toBeNull();
    expect(box!.y + box!.height).toBeLessThanOrEqual(viewport.height);
  });

  test(`operator sees the decision and its confidence in the first viewport at ${viewport.width}px`, async ({ page }) => {
    await page.setViewportSize(viewport);
    const decided = {
      ...previewInvestigation,
      status: "decided",
      pending_question: null,
      pending_questions: [],
      plan: { ...previewInvestigation.plan, kind: "decide", action: null, decision_class: previewInvestigation.belief.decisions[0].id, decision_probability: 0.96, reason: "P = 0.960 >= 0.95." },
    };
    await openOperatorInvestigation(page, "step-decided", decided);
    const step = page.getByRole("region", { name: "Current step" });
    await expect(step).toContainText("96% confidence");
    await expect(step).toContainText("The recorded evidence supports this recommendation.");
    for (const jargon of engineJargon) await expect(step).not.toContainText(jargon);
    const box = await step.boundingBox();
    expect(box).not.toBeNull();
    expect(box!.y + box!.height).toBeLessThanOrEqual(viewport.height);
  });
}

test("operator sees moderate confidence when nobody available can check anything more", async ({ page }) => {
  const decided = {
    ...previewInvestigation,
    status: "decided",
    pending_question: null,
    pending_questions: [],
    plan: { ...previewInvestigation.plan, kind: "decide", action: null, decision_class: previewInvestigation.belief.decisions[0].id, decision_probability: 0.8, moderate_confidence: true },
  };
  await page.setViewportSize({ width: 390, height: 844 });
  await openOperatorInvestigation(page, "step-moderate", decided);
  const step = page.getByRole("region", { name: "Current step" });
  await expect(step).toContainText("80% confidence");
  await expect(step).toContainText("Confidence is moderate: nobody available can check anything more.");
});

test("operator sees which blocked check would help when the planner stops without a decision", async ({ page }) => {
  const abstained = {
    ...previewInvestigation,
    status: "abstained",
    pending_question: null,
    pending_questions: [],
    plan: {
      ...previewInvestigation.plan,
      kind: "abstain",
      action: null,
      decision_class: null,
      reason: "The answers fit no modelled cause well (P(unknown cause) = 0.41 >= 0.30). Escalate to a human expert. Would help: breaker_c2_7 at DB_C2_PANEL (currently blocked: needs role electrician).",
      infeasible: [{ participant_id: "p_riya", probe_id: "breaker_c2_7", location_id: "DB_C2_PANEL", reasons: ["needs role electrician"] }],
    },
  };
  await page.setViewportSize({ width: 390, height: 844 });
  await openOperatorInvestigation(page, "step-abstain", abstained);
  const step = page.getByRole("region", { name: "Current step" });
  await expect(step).toContainText("Stopped without a decision");
  await expect(step).toContainText("Pramana did not reach a confident answer");
  await expect(step).toContainText("A check that would help is blocked");
  await expect(step).toContainText("needs role electrician");
  await expect(step).not.toContainText("P(unknown cause)");
});

test("operator gets a clear explanation when the chosen check is missing from the candidate trace", async ({ page }) => {
  const state = { ...previewInvestigation, plan: { ...previewInvestigation.plan, candidates: [] } };
  await page.setViewportSize({ width: 390, height: 844 });
  await openOperatorInvestigation(page, "step-no-candidates", state);
  const step = page.getByRole("region", { name: "Current step" });
  await expect(step).toContainText(previewInvestigation.pending_question!.text);
  await expect(step).toContainText("Pramana expects this check to help the investigation most among the checks available.");
  for (const jargon of engineJargon) await expect(step).not.toContainText(jargon);
});

test("participant sees who the question is for, the question, and why it is asked in plain words", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/join/preview?p=p_mahesh");
  const step = page.getByTestId("participant-current-step");
  await expect(step).toContainText("Question for Mahesh");
  await expect(step).toContainText(previewInvestigation.pending_question!.text);
  await expect(step).toContainText("Your answer adds an observation that helps narrow the reported problem.");
  const box = await step.boundingBox();
  expect(box).not.toBeNull();
  expect(box!.y + box!.height).toBeLessThanOrEqual(844);
});

test("participant view never shows the investigation's recommendation before verification", async ({ page }) => {
  // The core's participant view blanks the plan and beliefs (pramana_core.visibility), so the
  // participant state carries no decision. This guards the UI against rendering one anyway.
  const decided = {
    ...previewInvestigation,
    status: "decided" as const,
    pending_question: null,
    pending_questions: [],
    ground_truth: null,
    plan: { ...previewInvestigation.plan, kind: "decide" as const, action: null, decision_class: "DISPATCH_ELECTRICIAN_DB_C2", decision_probability: 0.95, reason: "" },
  };
  const token = encodeJoin({ i: "participant-decision", p: "p_mahesh", s: "scenario", t: "token" });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.route("**/api/core/v1/investigations/participant-decision", (r) => r.fulfill({ json: decided }));
  await page.route("**/api/sim/**", (r) => r.abort());
  await page.goto(`/join/${token}`);
  await expect(page.getByTestId("participant-current-step")).toHaveCount(0);
  await expect(page.locator("main")).not.toContainText("95% confidence");
});
