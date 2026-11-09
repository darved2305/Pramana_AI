import { expect, test } from "@playwright/test";
import { previewInvestigation } from "../src/lib/preview/fixtures";
import type { InvestigationState, Question } from "../src/lib/api/types";

const link = (id: string, participant: string) =>
  Buffer.from(JSON.stringify({ i: id, p: participant, s: "sc_answer", t: "token" })).toString("base64url");

test("starting another answer clears the previous acknowledgment until it succeeds", async ({ page }) => {
  const firstQuestion: Question = {
    ...previewInvestigation.pending_question!,
    id: "q_ack_first",
    status: "pending",
    text: "Are the switch lights green?",
    action: { ...previewInvestigation.pending_question!.action, participant_id: "p_mahesh", requires_move: false },
  };
  const secondQuestion: Question = {
    ...firstQuestion,
    id: "q_ack_second",
    text: "Is the breaker switch on?",
  };
  const firstState: InvestigationState = {
    ...previewInvestigation,
    id: "inv_ack1",
    pending_question: firstQuestion,
    pending_questions: [firstQuestion],
  };
  const secondState: InvestigationState = {
    ...firstState,
    pending_question: secondQuestion,
    pending_questions: [secondQuestion],
  };
  const doneState: InvestigationState = {
    ...secondState,
    status: "decided",
    pending_question: null,
    pending_questions: [],
  };
  let current = firstState;
  let answerCount = 0;
  let startSecond!: () => void;
  let finishSecond!: () => void;
  const secondStarted = new Promise<void>((resolve) => {
    startSecond = resolve;
  });
  const secondResponse = new Promise<void>((resolve) => {
    finishSecond = resolve;
  });

  await page.route("**/api/core/v1/investigations/inv_ack1", (route) => route.fulfill({ json: current }));
  await page.route("**/api/sim/**", (route) =>
    route.fulfill({ json: { location_label: "the guard desk", items: [], reachable_locations: [] } }),
  );
  await page.route("**/api/core/v1/investigations/inv_ack1/answers", async (route) => {
    answerCount++;
    const nextState = answerCount === 1 ? secondState : doneState;
    if (answerCount === 2) {
      startSecond();
      await secondResponse;
    }
    current = nextState;
    await route.fulfill({
      json: {
        extraction: { outcome: "green", hedge: "certain", directness: "direct", method: "structured" },
        state: nextState,
      },
    });
  });

  await page.goto(`/join/${link("inv_ack1", "p_mahesh")}`);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(firstQuestion.text);
  const answers = page.getByRole("group", { name: "Answers" });
  await answers.getByRole("button").first().click();
  await expect(page.getByRole("status")).toContainText("I understood");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(secondQuestion.text);

  await page.getByRole("group", { name: "Answers" }).getByRole("button").first().click();
  await secondStarted;
  try {
    await expect(page.getByRole("status")).toHaveCount(0);
  } finally {
    finishSecond();
  }
  await expect(page.getByRole("status")).toContainText("I understood");
  expect(answerCount).toBe(2);
});
