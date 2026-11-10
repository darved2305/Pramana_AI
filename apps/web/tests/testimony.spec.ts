import { expect, test } from "@playwright/test";
import { previewInvestigation } from "../src/lib/preview/fixtures";
import type { InvestigationState } from "../src/lib/api/types";

/** Presence checks (S7) and disagreement explanations (S2), as people and operators see them. */

const seg = (id: string, p: string) => Buffer.from(JSON.stringify({ i: id, p, s: "sc_1", t: "tok" })).toString("base64url");

test("a location check asks for a reading, not a choice, and the card shows the label on site", async ({ page }) => {
  const check = {
    ...previewInvestigation.pending_question!,
    id: "q_check",
    action: { ...previewInvestigation.pending_question!.action, requires_move: false },
    kind: "challenge" as const,
    outcomes: [],
    text: "One quick check, since you are in network closet IDF-2: please read the last three characters on the white label of the network switch.",
  };
  const inv: InvestigationState = { ...previewInvestigation, id: "inv_check1", pending_question: check, pending_questions: [check] };
  await page.route("**/api/core/v1/investigations/inv_check1", (r) => r.fulfill({ json: inv }));
  await page.route("**/api/sim/**", (r) =>
    r.fulfill({
      json: {
        location_label: "network closet IDF-2",
        items: [],
        reachable_locations: [],
        labels: [{ token_id: "idf2_switch_label", label: "Label on the network switch (last three characters)", value: "K7Q" }],
      },
    }),
  );
  let sent: unknown = null;
  await page.route("**/api/core/v1/investigations/inv_check1/answers", async (r) => {
    sent = r.request().postDataJSON();
    const done = { ...inv, pending_question: null, pending_questions: [] };
    await r.fulfill({
      json: {
        observation: previewInvestigation.observations[0],
        extraction: { outcome: "unknown", hedge: "certain", directness: "direct", method: "rules", evidence: ["reading:K7Q"] },
        state: done,
      },
    });
  });
  await page.goto(`/join/${seg("inv_check1", "p_mahesh")}`);
  await page.getByRole("button", { name: "Accept" }).click().catch(() => undefined);
  await expect(page.getByText("Quick location check")).toBeVisible();
  await expect(page.getByRole("group", { name: "Answers" }).getByRole("button")).toHaveCount(0);
  await page.getByText("What you can see here (simulation)").click();
  await expect(page.getByText("K7Q")).toBeVisible();
  await page.getByPlaceholder("Type what the label says").fill("K 7 Q");
  await page.getByRole("button", { name: "Send" }).click();
  await expect(page.getByRole("status")).toContainText("the label reads K7Q");
  expect(sent).toMatchObject({ question_id: "q_check", participant_id: "p_mahesh", text: "K 7 Q" });
  await expect(page.getByText(/accus|liar|lying|fail/i)).toHaveCount(0); // nobody is accused
});

test.describe("preview console", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/preview/app");
    await expect(page).toHaveURL(/\/app$/);
  });

  test("the testimony panel shows presence checks and how disagreements are read", async ({ page }) => {
    await page.goto("/app/investigations/preview-0001");
    const panel = page.getByRole("region", { name: "Testimony" }).or(page.locator("[aria-labelledby=testimony-title]"));
    await expect(panel.getByTestId("presence-check")).toHaveCount(1);
    await expect(panel.getByTestId("presence-check")).toContainText("Confirmed on site");
    await expect(panel.getByTestId("disagreement")).toContainText("One is likely mistaken");
    await expect(panel.getByTestId("disagreement")).toContainText("mistaken 31%");
  });

  test("the change card compares recorded beliefs around an answer", async ({ page }) => {
    await page.goto("/app/investigations/preview-0001");
    const card = page.getByRole("region", { name: "What changed" });
    await expect(card).toContainText("Before");
    await expect(card).toContainText("After");
    await expect(card).toContainText("Breaker C2-7 tripped");
    await expect(card).toContainText("36%");
    await expect(card).toContainText("43%");
  });
});
