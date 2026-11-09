import { expect, test } from "@playwright/test";

type PracticeState = {
  id: string;
  status: string;
  questions_asked: number;
  pending_question: { id: string; text: string } | null;
  pending_questions?: { id: string; text: string }[];
};

function finished(status: string) {
  return ["decided", "abstained", "verified", "not_verified", "closed"].includes(status);
}

test("a first-time workspace owner can complete and reveal a practice investigation", async ({ page }) => {
  test.setTimeout(180_000);
  const subject = "first-time-practice-" + Date.now();
  await page.goto("/login");
  await page.getByRole("link", { name: "Continue with Google" }).click();
  await page.getByRole("textbox", { name: "Subject", exact: true }).fill(subject);
  await page.getByRole("textbox", { name: "Email", exact: true }).fill(subject + "@gmail.com");
  await page.getByRole("button", { name: "Continue with mock account" }).click();
  await expect(page).toHaveURL(/\/onboarding\/welcome$/);

  await page.getByRole("button", { name: "Get started" }).click();
  await page.getByRole("button", { name: "I run facilities or maintenance" }).click();
  await page.getByRole("button", { name: "Office", exact: true }).click();
  await page.getByRole("button", { name: "Water supply" }).click();
  await page.getByRole("button", { name: "Hindi" }).click();
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page).toHaveURL(/\/onboarding\/org$/);
  await page.getByLabel("Workspace name").fill("Practice workspace " + Date.now());
  await page.getByRole("button", { name: "Create workspace" }).click();
  await expect(page).toHaveURL(/\/onboarding\/sandbox$/);
  await page.getByRole("link", { name: "Start a practice investigation" }).click();
  await page.getByLabel("What is wrong, in the reporter's words").fill("The water tank is not filling on the hostel's second floor.");
  await page.getByRole("button", { name: "Start investigation" }).click();
  await expect(page).toHaveURL(/\/investigations\/inv_[0-9A-HJKMNP-TV-Z]{26}$/);

  const parts = new URL(page.url()).pathname.split("/");
  const org = parts[2];
  const investigation = parts[parts.length - 1];
  const readState = async (): Promise<PracticeState> => {
    const response = await page.request.get("/api/core/v1/orgs/" + org + "/investigations/" + investigation);
    expect(response.status()).toBe(200);
    return response.json() as Promise<PracticeState>;
  };

  let state = await readState();
  for (let i = 0; i < 20 && !finished(state.status); i++) {
    const pending = (state.pending_questions ?? [])[0] ?? state.pending_question;
    if (!pending) {
      await expect.poll(async () => {
        state = await readState();
        return finished(state.status) || Boolean(state.pending_question) || Boolean(state.pending_questions?.length);
      }, { timeout: 30_000 }).toBe(true);
      continue;
    }
    const before = state.questions_asked;
    const card = page.getByTestId("pending-question").filter({ hasText: pending.text }).first();
    await card.locator("summary").click();
    await card.getByRole("button", { name: "Submit answer" }).click();
    await expect.poll(async () => {
      state = await readState();
      return state.questions_asked > before || finished(state.status);
    }, { timeout: 30_000 }).toBe(true);
  }
  state = await readState();
  expect(finished(state.status), "practice investigation should reach a finished state").toBe(true);
  if (state.status !== "closed") {
    await expect(page.getByRole("button", { name: "Reveal ground truth" })).toBeVisible();
    await page.getByRole("button", { name: "Reveal ground truth" }).click();
    const dialog = page.getByRole("dialog", { name: "Reveal the ground truth?" });
    await dialog.getByRole("button", { name: "Reveal", exact: true }).click();
  }
  await expect.poll(async () => (await readState()).status).toBe("closed");
  await page.setViewportSize({ width: 390, height: 844 });
  const dimensions = await page.evaluate(() => ({ width: window.innerWidth, scroll: document.documentElement.scrollWidth }));
  expect(dimensions.scroll).toBeLessThanOrEqual(dimensions.width + 1);
  await page.getByRole("link", { name: "Replay" }).click();
  await expect(page.getByRole("status", { name: "Integrity" })).toContainText("Replay identical");
  await expect(page.getByRole("status", { name: "Integrity" })).toContainText("Log unchanged since the reveal");
});
