import { mkdirSync } from "node:fs";
import { join } from "node:path";
import { expect, test, type Browser, type Page, type APIRequestContext } from "@playwright/test";
import { answerTruthfully, api, openParticipant, PHRASES, signIn, visiblePresenceCode } from "./helpers";

const SIM = process.env.E2E_SIM_URL as string;
const SCREENSHOTS = process.env.P2B_SCREENSHOT_DIR;

interface Question {
  id: string;
  text: string;
  language: "en" | "hi" | "mr" | "hi-en";
  kind: "probe" | "confirm" | "challenge";
  presence_token_id?: string | null;
  action: { participant_id: string; probe_id: string; location_id: string; requires_move: boolean };
}

interface State {
  id: string;
  status: string;
  questions_asked: number;
  participants: { id: string; display_name: string }[];
  pending_question: Question | null;
  plan: { decision_class?: string | null };
}

interface Preset {
  id: "S2" | "S7";
  title: string;
  adversarial_participant_id?: string | null;
  request: Record<string, unknown>;
}

async function createPreset(request: APIRequestContext, presetId: Preset["id"]) {
  const presets = await api<Preset[]>(request, "GET", "/v1/investigations/presets");
  const preset = presets.find((item) => item.id === presetId);
  expect(preset, `${presetId} preset is available`).toBeTruthy();
  return { preset: preset!, state: await api<State>(request, "POST", "/v1/investigations", preset!.request) };
}

async function participantPages(page: Page, browser: Browser, state: State) {
  await page.getByRole("button", { name: "Participant links" }).first().click();
  const dialog = page.getByRole("dialog", { name: "Participant links" });
  const people: Record<string, Page> = {};
  for (const person of state.participants) {
    const row = dialog.getByRole("listitem").filter({ hasText: person.display_name });
    await row.getByRole("button", { name: "Create link" }).click();
    people[person.id] = await openParticipant(browser, (await row.getByRole("link").getAttribute("href")) as string);
  }
  await page.keyboard.press("Escape");
  return people;
}

async function answerFromSimulator(
  request: APIRequestContext,
  invId: string,
  question: Question,
  override?: string,
) {
  const token = await api<{ token: string; scenario_id: string }>(
    request,
    "POST",
    `/v1/investigations/${invId}/participants/${question.action.participant_id}/token`,
  );
  const headers = { Authorization: `Bearer ${token.token}` };
  if (question.action.requires_move) {
    const moved = await request.post(`${SIM}/sim/v1/scenarios/${token.scenario_id}/move`, {
      headers,
      data: { to: question.action.location_id },
    });
    expect(moved.ok(), await moved.text()).toBeTruthy();
  }

  let text: string;
  if (question.kind === "challenge") {
    const view = await request.get(`${SIM}/sim/v1/scenarios/${token.scenario_id}/view`, { headers });
    expect(view.ok(), await view.text()).toBeTruthy();
    const presence = (await view.json()).presence_tokens.find((item: { token_id: string }) => item.token_id === question.presence_token_id);
    expect(presence, "the simulator shows a label only at its location").toBeTruthy();
    const rendered = presence.display_texts[question.language] as string;
    const match = rendered.match(/([A-Z2-9]{3})[^A-Z0-9]*$/i);
    expect(match, `a three-character label is visible in ${question.language}`).toBeTruthy();
    text = (match?.[1] as string).split("").join(" ");
  } else if (override) {
    text = PHRASES[override];
  } else {
    const observed = await request.post(`${SIM}/sim/v1/scenarios/${token.scenario_id}/observe`, {
      headers,
      data: { probe_id: question.action.probe_id },
    });
    expect(observed.ok(), await observed.text()).toBeTruthy();
    const value = (await observed.json()).value as string;
    text = PHRASES[value];
    expect(text, `a natural answer exists for ${value}`).toBeTruthy();
  }

  const result = await api<{ state: State; passed?: boolean; extraction?: { outcome: string } }>(
    request,
    "POST",
    `/v1/investigations/${invId}/answers`,
    { question_id: question.id, participant_id: question.action.participant_id, text },
  );
  if (override && result.extraction) expect(result.extraction.outcome).toBe(override);
  return result;
}

function capture(page: Page, name: string) {
  if (!SCREENSHOTS) return Promise.resolve();
  mkdirSync(SCREENSHOTS, { recursive: true });
  return page.screenshot({ path: join(SCREENSHOTS, name), fullPage: true });
}

test("S7: a false presence claim fails neutrally, and other evidence reaches the right decision", async ({ page, browser, request }) => {
  test.setTimeout(360_000);
  const { preset, state: created } = await createPreset(request, "S7");
  const adversaryId = preset.adversarial_participant_id as string;
  await signIn(page, "operator", `/app/investigations/${created.id}`);
  const people = await participantPages(page, browser, created);
  let state = await api<State>(request, "GET", `/v1/investigations/${created.id}`);
  let failedChallenge = false;
  let failureScreenshot = false;
  let visibleLabelCode = "";
  const falseReports: Record<string, string> = { switch_leds: "green", nvr_screen: "on", closet_light: "on" };
  const labels = await api<{ probes: { id: string; label: string }[] }>(request, "GET", "/v1/packs/campus_block_c");
  const label = (probeId: string) => labels.probes.find((probe) => probe.id === probeId)?.label ?? probeId;

  for (let step = 0; state.pending_question && step < 36; step++) {
    const question = state.pending_question;
    const { participant_id: participantId, location_id: locationId, probe_id: probeId } = question.action;
    if (question.kind === "challenge" && participantId === adversaryId) {
      const participant = people[adversaryId];
      await expect(participant.getByRole("heading", { level: 1 })).toHaveText(question.text, { timeout: 20_000 });
      await expect(participant.getByRole("button", { name: "I am there now" })).toBeVisible();
      await expect(participant.locator("dt", { hasText: "Location label" })).toHaveCount(0);
      visibleLabelCode = await visiblePresenceCode(participant, question.text);
      const answer = (visibleLabelCode[0] === "A" ? "B" : "A") + visibleLabelCode.slice(1);
      const input = participant.getByLabel("Type your answer");
      await expect(input).toHaveAttribute("inputmode", "text");
      await expect(input).toHaveAttribute("autocapitalize", "characters");
      await expect(input).toHaveClass(/font-mono/);
      await capture(participant, "p2b-s7-participant-challenge-phone.png");

      await input.fill(answer.split("").join(" "));
      await participant.getByRole("button", { name: "Send" }).click();
      await expect(participant.getByRole("status")).toHaveText("मी जागेची खात्री करू शकलो नाही; मी दुसऱ्या व्यक्तीला विचारेन.");
      state = await api<State>(request, "GET", `/v1/investigations/${created.id}`);
      failedChallenge = true;
      await expect(page.getByText("Location not confirmed for Mahesh; asking someone else.", { exact: true })).toBeVisible({ timeout: 30_000 });
      await expect(page.getByText(/Presence not confirmed · reduced weight/)).toBeVisible();
      await capture(page, "p2b-s7-console-failed-desktop.png");
      failureScreenshot = true;
      continue;
    }

    const falseOutcome = participantId === adversaryId && locationId === "IDF2" ? falseReports[probeId] : undefined;
    if (falseOutcome) {
      const response = await api<{ state: State; extraction: { outcome: string } }>(request, "POST", `/v1/investigations/${created.id}/answers`, {
        question_id: question.id,
        participant_id: participantId,
        text: PHRASES[falseOutcome],
      });
      expect(response.extraction.outcome).toBe(falseOutcome);
      state = response.state;
    } else if (question.kind === "challenge") {
      state = (await answerFromSimulator(request, created.id, question)).state;
    } else {
      await answerTruthfully(people[participantId], question.text, label(probeId), false);
      state = await api<State>(request, "GET", `/v1/investigations/${created.id}`);
    }
    if (failedChallenge) {
      await expect(page.getByTestId("pending-question").first()).toBeVisible({ timeout: 20_000 });
    }
  }

  expect(failedChallenge).toBe(true);
  expect(failureScreenshot).toBe(true);
  expect(state.status).toBe("decided");
  expect(state.plan.decision_class).toBe("DISPATCH_ELECTRICIAN_DB_C2");
  await expect(page.getByText("Decided").first()).toBeVisible({ timeout: 30_000 });
  const events = await api<{ type: string; payload: Record<string, unknown> }[]>(request, "GET", `/v1/investigations/${created.id}/events?after_seq=0`);
  expect(events.some((event) => event.type === "ChallengeResult" && event.payload.participant_id === adversaryId && event.payload.result === "failed")).toBe(true);
  expect(JSON.stringify(events)).not.toContain("K 7 Q");
  expect(JSON.stringify(events)).not.toContain("K7Q");
  expect(JSON.stringify(events)).not.toContain(visibleLabelCode);
  expect(JSON.stringify(events)).not.toContain(visibleLabelCode.split("").join(" "));
  expect((await api<{ identical: boolean }>(request, "GET", `/v1/investigations/${created.id}/replay`)).identical).toBe(true);
  for (const participant of Object.values(people)) await participant.context().close();
});

test("S2: the console explains different access points and records the tie-break answer", async ({ page, browser, request }) => {
  test.setTimeout(360_000);
  const { state: created } = await createPreset(request, "S2");
  await signIn(page, "operator", `/app/investigations/${created.id}`);
  const people = await participantPages(page, browser, created);
  let state = await api<State>(request, "GET", `/v1/investigations/${created.id}`);
  let sawExplanation = false;
  let sawTieBreak = false;
  const pack = await api<{ probes: { id: string; label: string }[] }>(request, "GET", "/v1/packs/campus_block_c");
  const label = (probeId: string) => pack.probes.find((probe) => probe.id === probeId)?.label ?? probeId;

  for (let step = 0; state.pending_question && step < 28; step++) {
    const question = state.pending_question;
    if (question.kind === "challenge") {
      state = (await answerFromSimulator(request, created.id, question)).state;
      continue;
    }
    if (question.action.probe_id === "wifi_access_point") {
      sawTieBreak = true;
      await expect(page.getByText("Both can be right", { exact: false })).toBeVisible({ timeout: 30_000 });
      await expect(page.getByTestId("reconciliation-explanation").getByText(question.text, { exact: true })).toBeVisible();
    }
    await answerTruthfully(people[question.action.participant_id], question.text, label(question.action.probe_id), false);
    state = await api<State>(request, "GET", `/v1/investigations/${created.id}`);
    if (!sawExplanation && question.action.probe_id !== "wifi_access_point") {
      const events = await api<{ type: string }[]>(request, "GET", `/v1/investigations/${created.id}/events?after_seq=0`);
      sawExplanation = events.some((event) => event.type === "ContradictionExplained");
      if (sawExplanation) await expect(page.getByText("Both can be right", { exact: false })).toBeVisible({ timeout: 30_000 });
    }
  }

  expect(sawExplanation).toBe(true);
  expect(sawTieBreak).toBe(true);
  expect(state.status).toBe("decided");
  expect(state.plan.decision_class).toBe("IT_REPLACE_AP_2A");
  await expect(page.getByText("Answered: access point 2B", { exact: true })).toBeVisible({ timeout: 30_000 });
  const accessPointExplanations = page.getByTestId("reconciliation-explanation").getByText(/room 205.*access point 2B.*room 210.*access point 2A/i);
  expect(await accessPointExplanations.count()).toBeGreaterThan(0);
  await expect(accessPointExplanations.first()).toBeVisible();
  await capture(page, "p2b-s2-console-resolved-desktop.png");
  const events = await api<{ type: string; payload: Record<string, unknown> }[]>(request, "GET", `/v1/investigations/${created.id}/events?after_seq=0`);
  expect(events.some((event) => event.type === "ContradictionResolved" && event.payload.outcome === "AP_2B")).toBe(true);
  expect((await api<{ identical: boolean }>(request, "GET", `/v1/investigations/${created.id}/replay`)).identical).toBe(true);
  await page.goto(`/app/investigations/${created.id}/replay`);
  await page.getByRole("button", { name: /Reconciliation explained/ }).first().click();
  await expect(page.getByTestId("reconciliation-explanation")).toBeVisible();
  await page.getByRole("button", { name: /Tie-break answered/ }).first().click();
  await expect(page.getByText("Tie-break answered: access point 2B.", { exact: true })).toBeVisible();
  await capture(page, "p2b-s2-replay-desktop.png");
  for (const participant of Object.values(people)) await participant.context().close();
});
