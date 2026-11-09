/**
 * Parallel questions in the browser (docs/adr/0011), against the real core, simulator and
 * database: the operator asks for up to 3 people at once, the console shows every question in
 * flight, each participant sees only their own question on their own link, they answer at the
 * same time, and the engine still reaches the right decision for S1 (breaker CB_C2_7 tripped).
 */
import { expect, test, type Page } from "@playwright/test";
import { answerTruthfully, api, openParticipant, seedDirectory, signIn } from "./helpers";

interface Q {
  id: string;
  text: string;
  action: { participant_id: string; probe_id: string };
}
interface State {
  status: string;
  questions_asked: number;
  max_parallel_calls: number;
  pending_questions: Q[];
  plan: { decision_class?: string | null };
}

// A question withdrawn while its person is answering removes its buttons: fail that click fast.
test.use({ actionTimeout: 15_000 });

test("parallel: three people asked at once reach the S1 decision", async ({ page, browser, request }) => {
  test.setTimeout(360_000);
  await seedDirectory(request);
  const pack = await api<{ probes: { id: string; label: string }[] }>(request, "GET", "/v1/packs/campus_block_c");
  const label = (probe: string) => pack.probes.find((x) => x.id === probe)?.label ?? probe;

  await signIn(page, "operator", "/app/investigations/new");
  const next = () => page.getByRole("button", { name: "Continue" }).click();
  await expect(page.getByText(/floors, \d+ places/)).toBeVisible();
  await next();
  await page.getByLabel("What is wrong?").fill("Floor 3 pe WiFi nahi chal raha, kuch khul nahi raha");
  await next();
  for (const name of ["Riya", "Mahesh", "Imran"]) await page.getByRole("checkbox", { name: new RegExp(`^${name}`) }).check({ force: true });
  await page.getByRole("listitem").filter({ hasText: "Riya" }).getByLabel("Reported it").check();
  await next();
  await next();
  await next();
  await page.getByRole("textbox", { name: "Simulation seed" }).fill("19");
  await page.getByLabel("People asked at once").selectOption("3");
  await page.getByLabel("Specified").check({ force: true });
  await page.getByRole("textbox", { name: "Component ID" }).fill("CB_C2_7");
  await page.getByRole("textbox", { name: "Failure mode" }).fill("tripped");
  await next();
  await expect(page.getByText("up to 3 people at once")).toBeVisible();
  // Click the visible label, as a person would: a forced click on the hidden input can land
  // while the page is still scrolling to this step.
  await page.getByText("These people have agreed to be contacted").click();
  await expect(page.getByRole("checkbox", { name: /agreed to be contacted/ })).toBeChecked();
  await page.getByRole("button", { name: "Start investigation" }).click();
  await expect(page).toHaveURL(/\/app\/investigations\/inv_[0-9A-HJKMNP-TV-Z]{26}$/);
  const invId = page.url().split("/").pop() as string;

  let state = await api<State>(request, "GET", `/v1/investigations/${invId}`);
  expect(state.max_parallel_calls).toBe(3);
  expect(state.pending_questions.length).toBeGreaterThanOrEqual(2);
  // The console shows every question in flight.
  await expect(page.getByTestId("pending-question")).toHaveCount(state.pending_questions.length);
  await expect(page.getByText(/Asking \d people at once/)).toBeVisible();

  await page.getByRole("button", { name: "Participant links" }).first().click();
  const dialog = page.getByRole("dialog", { name: "Participant links" });
  const people: Record<string, Page> = {};
  for (const [pid, name] of [["p_riya", "Riya"], ["p_mahesh", "Mahesh"], ["p_imran", "Imran"]]) {
    const row = dialog.getByRole("listitem").filter({ hasText: name });
    await row.getByRole("button", { name: "Create link" }).click();
    people[pid] = await openParticipant(browser, (await row.getByRole("link").getAttribute("href")) as string);
  }
  await page.keyboard.press("Escape");

  // Each person sees their own question at the same time, never someone else's.
  for (const q of state.pending_questions) {
    await expect(people[q.action.participant_id].getByRole("heading", { level: 1 })).toHaveText(q.text, { timeout: 20_000 });
  }

  // Everyone with a question answers at once, round after round, until the engine concludes.
  let rounds = 0;
  let mostAtOnce = state.pending_questions.length;
  while (state.pending_questions.length && rounds < 8) {
    const before = state.questions_asked;
    const asked = new Set(state.pending_questions.map((q) => q.id));
    const results = await Promise.allSettled(
      state.pending_questions.map((q) => answerTruthfully(people[q.action.participant_id], q.text, label(q.action.probe_id), false)),
    );
    // A question can be withdrawn while its person is answering; the others must succeed.
    expect(results.some((r) => r.status === "fulfilled")).toBe(true);
    const failed = state.pending_questions.flatMap((q, i) => {
      const result = results[i];
      if (result.status !== "rejected") return [];
      const reason = result.reason;
      return [
        {
          id: q.id,
          participant_id: q.action.participant_id,
          probe_id: q.action.probe_id,
          error: reason instanceof Error ? `${reason.name}: ${reason.message}` : String(reason),
        },
      ];
    });
    if (failed.length) {
      type EventRow = {
        type: string;
        payload: {
          question_id?: string;
          participant_id?: string;
          probe_id?: string;
          evidence?: { participant_id?: string; probe_id?: string };
        };
      };
      // A withdrawal can land a moment after the rejected answer. Wait until every rejected
      // question is either withdrawn or no longer pending, then judge the outcome strictly.
      let log: EventRow[] = [];
      await expect
        .poll(
          async () => {
            const [events, current] = await Promise.all([
              api<EventRow[]>(request, "GET", `/v1/investigations/${invId}/events`),
              api<State>(request, "GET", `/v1/investigations/${invId}`),
            ]);
            log = events;
            state = current;
            const withdrawn = new Set(events.filter((e) => e.type === "QuestionWithdrawn").map((e) => e.payload.question_id));
            const pending = new Set(current.pending_questions.map((q) => q.id));
            return failed.filter(({ id }) => !withdrawn.has(id) && pending.has(id)).map(({ id }) => id);
          },
          { timeout: 10_000, intervals: [100, 250, 500, 1000] },
        )
        .toEqual([]);
      const gone = new Set(log.filter((e) => e.type === "QuestionWithdrawn").map((e) => e.payload.question_id));
      const unaccounted = failed.filter(({ id }) => !gone.has(id));
      const answerAndWithdrawalEvents = log
        .filter((e) => e.type === "ObservationRecorded" || e.type === "QuestionWithdrawn")
        .map((e) => ({
          type: e.type,
          question_id: e.payload.question_id,
          participant_id: e.payload.participant_id ?? e.payload.evidence?.participant_id,
          probe_id: e.payload.probe_id ?? e.payload.evidence?.probe_id,
        }));
      expect(
        unaccounted,
        `only withdrawn questions may go unanswered; rejected answers: ${JSON.stringify(failed)}; ` +
          `answer and withdrawal events: ${JSON.stringify(answerAndWithdrawalEvents)}`,
      ).toEqual([]);
    }
    rounds++;
    await expect
      .poll(async () => {
        state = await api<State>(request, "GET", `/v1/investigations/${invId}`);
        return state.questions_asked > before || !state.pending_questions.some((q) => asked.has(q.id)) || !state.pending_questions.length;
      })
      .toBe(true);
    mostAtOnce = Math.max(mostAtOnce, state.pending_questions.length);
  }
  expect(state.status).toBe("decided");
  expect(state.plan.decision_class).toBe("DISPATCH_ELECTRICIAN_DB_C2");
  expect(mostAtOnce).toBeGreaterThanOrEqual(2);
  await expect(page.getByText("Decided").first()).toBeVisible();

  const events = await api<{ type: string; payload: { question_id?: string } }[]>(request, "GET", `/v1/investigations/${invId}/events`);
  const asked = events.filter((e) => e.type === "QuestionAsked").length;
  const withdrawn = events.filter((e) => e.type === "QuestionWithdrawn").length;
  const answered = events.filter((e) => e.type === "ObservationRecorded").length - 1; // minus the report
  expect(answered + withdrawn).toBe(asked);
  const replay = await api<{ identical: boolean }>(request, "GET", `/v1/investigations/${invId}/replay`);
  expect(replay.identical).toBe(true);

  for (const p of Object.values(people)) await p.context().close();
});
