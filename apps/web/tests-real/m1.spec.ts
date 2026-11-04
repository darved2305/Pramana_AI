/**
 * M1 acceptance in the browser, against the real core, simulator and database:
 * the operator creates scenario S1 (breaker CB_C2_7 tripped) from the console, each participant
 * answers from their own /join link (no sign-in; only their link), the console updates live, the
 * engine decides DISPATCH_ELECTRICIAN_DB_C2 within six questions, an approver approves, the
 * electrician collects the capability, resets the breaker in the simulator and reports it, the
 * verification questions are answered, and the investigation ends verified.
 *
 * Participants answer truthfully from what their simulated surroundings card shows.
 */
import { expect, test, type Browser, type Page } from "@playwright/test";
import { api, seedDirectory, signIn } from "./helpers";

interface State {
  id: string;
  status: string;
  questions_asked: number;
  pending_question: { id: string; text: string; action: { participant_id: string; probe_id: string; requires_move: boolean } } | null;
  plan: { decision_class?: string | null };
  belief: { repair?: { fixed_probability: number } | null };
  approvals: { id: string; status: string; approver_id?: string | null }[];
  ground_truth?: { correct?: boolean | null; reveal?: { commitment_verified?: boolean } } | null;
}

async function openParticipant(browser: Browser, url: string): Promise<Page> {
  // A separate browser context: no staff cookie, only the link.
  const ctx = await browser.newContext({ viewport: { width: 390, height: 844 } });
  const page = await ctx.newPage();
  await page.goto(url);
  return page;
}

/** Answer the pending question on the participant's own page, from their surroundings card. */
async function answerTruthfully(p: Page, questionText: string, probeLabel: string, typed: boolean) {
  const there = p.getByRole("button", { name: "I am there now" });
  // The page polls; wait until it shows this very question, not the previous screen.
  await expect(p.getByRole("heading", { level: 1 })).toHaveText(questionText, { timeout: 20_000 });
  if (await there.isVisible()) await there.click();
  const card = p.locator("details", { hasText: "What you can see here (simulation)" });
  await expect(card).toBeVisible();
  if (!(await card.evaluate((d) => (d as HTMLDetailsElement).open))) await card.locator("summary").click();
  const row = card.locator("div", { has: p.locator("dt", { hasText: probeLabel }) }).last();
  await expect(row).toBeVisible();
  const value = (await row.locator("dd").innerText()).trim();
  if (typed) {
    await p.getByLabel("Type your answer").fill(PHRASES[value] ?? value);
    await p.getByRole("button", { name: "Send" }).click();
  } else {
    await p.getByRole("group", { name: "Answers" }).getByRole("button", { name: value.replace(/_/g, " "), exact: true }).click();
  }
  await expect(p.getByRole("status")).toContainText("I understood");
  return value;
}

// How someone might say each outcome (Hinglish and Marathi on purpose); the core must extract it.
const PHRASES: Record<string, string> = {
  yes: "haan, khul rahi hai",
  no: "nahi, khul nahi rahi",
  on: "haan chalu hai",
  off: "band aahe",
  green: "lights green hain",
  amber: "orange dikh rahi hain",
  red: "laal hai",
  up: "breaker upar hai",
  tripped: "breaker neeche hai, trip hai",
  no_network: "NAVA-WiFi dikh hi nahi raha",
  stuck_connecting: "connecting pe atka hai",
  connected: "connected hai",
};

test("M1: S1 from the console to a verified repair", async ({ page, browser, request }) => {
  await seedDirectory(request);
  const pack = await api<{ probes: { id: string; label: string }[] }>(request, "GET", "/v1/packs/campus_block_c");
  const label = (probe: string) => pack.probes.find((x) => x.id === probe)?.label ?? probe;

  // The console follows events over server-sent events (polling is only the fallback).
  const streams: string[] = [];
  page.on("request", (r) => {
    if (/\/v1\/investigations\/[^/]+\/stream\?after_seq=/.test(r.url())) streams.push(r.url());
  });

  // 1. The operator creates S1 in the console.
  await signIn(page, "operator", "/app/investigations/new");
  const next = () => page.getByRole("button", { name: "Continue" }).click();
  await expect(page.getByText(/floors, \d+ places/)).toBeVisible();
  await next();
  await page.getByLabel("What is wrong?").fill("Floor 3 pe WiFi nahi chal raha, kuch khul nahi raha");
  await next();
  for (const name of ["Riya", "Mahesh", "Imran"]) await page.getByRole("checkbox", { name: new RegExp(`^${name}`) }).check({ force: true }); // styled, visually hidden input
  await page.getByRole("listitem").filter({ hasText: "Riya" }).getByLabel("Reported it").check();
  await next(); // participants
  await next(); // languages
  await next(); // permissions
  await page.getByRole("textbox", { name: "Simulation seed" }).fill("19");
  await page.getByLabel("Specified").check({ force: true });
  await page.getByRole("textbox", { name: "Component ID" }).fill("CB_C2_7");
  await page.getByRole("textbox", { name: "Failure mode" }).fill("tripped");
  await next();
  await page.getByRole("checkbox", { name: /agreed to be contacted/ }).check({ force: true });
  await page.getByRole("button", { name: "Start investigation" }).click();
  await expect(page).toHaveURL(/\/app\/investigations\/inv_[0-9a-f]+$/);
  const invId = page.url().split("/").pop() as string;

  // 2. Personal links from the console.
  await page.getByRole("button", { name: "Participant links" }).first().click();
  const links: Record<string, string> = {};
  const dialog = page.getByRole("dialog", { name: "Participant links" });
  for (const [pid, name] of [["p_riya", "Riya"], ["p_mahesh", "Mahesh"], ["p_imran", "Imran"]]) {
    const row = dialog.getByRole("listitem").filter({ hasText: name });
    await row.getByRole("button", { name: "Create link" }).click();
    links[pid] = (await row.getByRole("link").getAttribute("href")) as string;
  }
  await page.keyboard.press("Escape");
  const people: Record<string, Page> = {};
  for (const [pid, url] of Object.entries(links)) people[pid] = await openParticipant(browser, url);

  // A participant link is not a staff session: it cannot open the console.
  const peek = people.p_riya;
  const peekCtx = await peek.context().newPage();
  await peekCtx.goto("/app/investigations");
  await expect(peekCtx).toHaveURL(/\/login\?next=/);
  await peekCtx.close();

  // 3. Diagnosis: answer whoever is asked, truthfully, until the engine concludes.
  let state = await api<State>(request, "GET", `/v1/investigations/${invId}`);
  let answered = 0;
  while (state.pending_question && answered < 8) {
    const { participant_id, probe_id } = state.pending_question.action;
    const before = state.questions_asked;
    await answerTruthfully(people[participant_id], state.pending_question.text, label(probe_id), answered === 0);
    answered++;
    await expect.poll(async () => (state = await api<State>(request, "GET", `/v1/investigations/${invId}`)).questions_asked > before || !state.pending_question).toBe(true);
  }
  expect(state.status).toBe("decided");
  expect(state.plan.decision_class).toBe("DISPATCH_ELECTRICIAN_DB_C2");
  expect(state.questions_asked).toBeLessThanOrEqual(6);

  // The console followed along without a reload, over the event stream.
  expect(streams.length).toBeGreaterThan(0);
  await expect(page.getByText("Decided").first()).toBeVisible();
  await expect.poll(() => page.getByRole("table").first().getByRole("row").count()).toBeGreaterThan(answered);

  // 4. The operator proposes the repair.
  await page.getByRole("button", { name: "Propose repair", exact: true }).click();
  const propose = page.getByRole("dialog", { name: "Propose a repair" });
  await propose.getByLabel("Breaker").fill("CB_C2_7");
  await propose.getByRole("button", { name: "Send for approval" }).click();
  await expect(page.getByText("Awaiting approval").first()).toBeVisible();
  // The operator cannot approve their own request.
  await expect(page.getByRole("button", { name: "Approve", exact: true })).toBeDisabled();

  // 5. An approver approves in their own session; the approval records their account.
  const approverCtx = await browser.newContext();
  const approver = await approverCtx.newPage();
  await signIn(approver, "approver", `/app/investigations/${invId}`);
  await approver.getByRole("button", { name: "Approve", exact: true }).click();
  await approver.getByRole("dialog").getByRole("button", { name: "Approve", exact: true }).click();
  await expect(approver.getByText(/Approved by Asha Approver \(you\)/)).toBeVisible();
  state = await api<State>(request, "GET", `/v1/investigations/${invId}`);
  expect(state.status).toBe("acting");
  const me = await approver.request.get("/api/core/v1/auth/session");
  expect(state.approvals[0].approver_id).toBe((await me.json()).user_id);

  // 6. The electrician collects the capability, goes to the panel, resets and reports.
  const imran = people.p_imran;
  await expect(imran.getByRole("heading", { name: "You are cleared to act" })).toBeVisible({ timeout: 20_000 });
  await imran.getByRole("button", { name: "Collect permission" }).click();
  await imran.getByRole("button", { name: "I am at the panel" }).click();
  await imran.getByRole("button", { name: "I have done it" }).click();
  await expect.poll(async () => (state = await api<State>(request, "GET", `/v1/investigations/${invId}`)).status).toBe("verifying");

  // 7. Verification questions, answered from what people now see.
  let checks = 0;
  while (state.pending_question && checks < 8) {
    const { participant_id, probe_id } = state.pending_question.action;
    const before = state.questions_asked;
    await answerTruthfully(people[participant_id], state.pending_question.text, label(probe_id), false);
    checks++;
    await expect.poll(async () => (state = await api<State>(request, "GET", `/v1/investigations/${invId}`)).questions_asked > before || !state.pending_question).toBe(true);
  }
  expect(checks).toBeGreaterThan(0); // a confident diagnosis alone never verifies a repair
  expect(state.status).toBe("verified");
  expect(state.belief.repair?.fixed_probability ?? 0).toBeGreaterThanOrEqual(0.97);
  await expect(page.getByText("Verified").first()).toBeVisible();

  // 8. Reveal: the sealed fault matches the commitment and the decision was right.
  await page.getByRole("button", { name: "Reveal ground truth" }).first().click();
  await page.getByRole("dialog").getByRole("button", { name: /Reveal/ }).click();
  await expect.poll(async () => (state = await api<State>(request, "GET", `/v1/investigations/${invId}`)).status).toBe("closed");
  expect(state.ground_truth?.correct).toBe(true);
  expect(state.ground_truth?.reveal?.commitment_verified).toBe(true);

  await approverCtx.close();
  for (const p of Object.values(people)) await p.context().close();
});
