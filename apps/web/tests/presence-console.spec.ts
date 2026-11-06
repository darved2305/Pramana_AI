import { expect, test, type Page } from "@playwright/test";
import { previewInvestigation, previewPack, previewEvents } from "../src/lib/preview/fixtures";
import type { EventEnvelope, InvestigationState } from "../src/lib/api/types";

const challengedObservation = {
  id: "o_presence",
  participant_id: "p_mahesh",
  location_id: "IDF2",
  probe_id: "switch_leds",
  outcome: "green",
  committed_at: "2026-11-06T00:10:00Z",
  directness: "direct",
  hedge: "certain",
  modality: "text",
  extraction_method: "rules",
  question_id: "q_presence_observation",
  state: "committed",
  transcript: "The lights are green.",
};

const issued: EventEnvelope = {
  investigation_id: "inv_ui",
  seq: 401,
  ts: "2026-11-06T00:10:01Z",
  type: "ChallengeIssued",
  payload: {
    challenge_id: "q_presence",
    question_id: "q_presence",
    participant_id: "p_mahesh",
    probe_id: "switch_leds",
    location_id: "IDF2",
    token_id: "idf2_switch_label",
    cost_s: 12,
  },
};

const failed: EventEnvelope = {
  investigation_id: "inv_ui",
  seq: 402,
  ts: "2026-11-06T00:10:20Z",
  type: "ChallengeResult",
  payload: {
    challenge_id: "q_presence",
    participant_id: "p_mahesh",
    location_id: "IDF2",
    result: "failed",
    reason: "label_unavailable",
  },
};

const passed: EventEnvelope = {
  ...failed,
  seq: 402,
  payload: { ...failed.payload, result: "passed", reason: "label_matched" },
};

const withdrawn: EventEnvelope = {
  ...failed,
  seq: 402,
  payload: { ...failed.payload, result: "withdrawn", reason: "decision_reached" },
};

function stateFor(id: string, challengePending: boolean): InvestigationState {
  const q = {
    id: "q_presence",
    action: { participant_id: "p_mahesh", probe_id: "switch_leds", location_id: "IDF2", requires_move: false },
    language: "en",
    text: "Read the last three characters on the switch label.",
    outcomes: [],
    status: "pending",
    asked_at: "2026-11-06T00:10:01Z",
    kind: "challenge",
    presence_token_id: "idf2_switch_label",
  };
  return {
    ...previewInvestigation,
    id,
    pending_question: challengePending ? q : null,
    pending_questions: challengePending ? [q] : [],
    observations: [challengedObservation],
  } as unknown as InvestigationState;
}

function withEvents(id: string, events: EventEnvelope[]): EventEnvelope[] {
  return [
    ...previewEvents.map((event) => ({ ...event, investigation_id: id })),
    ...events.map((event) => ({ ...event, investigation_id: id })),
  ].sort((a, b) => a.seq - b.seq);
}

async function mockConsole(
  page: Page,
  states: Record<string, InvestigationState>,
  eventLogs: Record<string, EventEnvelope[]>,
) {
  await page.route("**/api/core/v1/auth/session", (route) =>
    route.fulfill({
      json: {
        user_id: "u_operator",
        display_name: "Console Operator",
        email: "operator@example.test",
        roles: ["operator"],
        expires_at: "2099-01-01T00:00:00Z",
        method: "session",
      },
    }),
  );
  await page.route("**/api/core/health", (route) => route.fulfill({ json: "ok" }));
  await page.route("**/api/core/v1/packs/campus_block_c", (route) => route.fulfill({ json: previewPack }));
  await page.route("**/api/core/v1/investigations/*/stream**", (route) => route.fulfill({ status: 404 }));
  await page.route("**/api/core/v1/investigations/*/events**", async (route) => {
    const id = new URL(route.request().url()).pathname.split("/").at(-2) as string;
    const after = Number(new URL(route.request().url()).searchParams.get("after_seq") ?? "0");
    await route.fulfill({ json: (eventLogs[id] ?? []).filter((event) => event.seq > after) });
  });
  await page.route("**/api/core/v1/investigations/*", async (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    const id = new URL(route.request().url()).pathname.split("/").at(-1) as string;
    const state = states[id];
    if (state) return route.fulfill({ json: state });
    return route.fallback();
  });
}

test("console shows asked, passed and failed presence checks with evidence weight", async ({ page }) => {
  const states = {
    inv_asked: stateFor("inv_asked", true),
    inv_passed: stateFor("inv_passed", false),
    inv_failed: stateFor("inv_failed", false),
  };
  const eventLogs = {
    inv_asked: withEvents("inv_asked", [issued]),
    inv_passed: withEvents("inv_passed", [issued, passed]),
    inv_failed: withEvents("inv_failed", [issued, failed]),
  };
  await mockConsole(page, states, eventLogs);

  await page.goto("/app/investigations/inv_asked");
  await expect(page.getByRole("heading", { name: "Presence checks" })).toBeVisible();
  await expect(page.getByText("Mahesh", { exact: true }).last()).toBeVisible();
  await expect(page.getByText("Asked", { exact: true })).toBeVisible();
  await expect(page.getByText(/Location check in progress for Mahesh at network closet IDF-2/)).toBeVisible();
  await expect(page.getByText(/reduced weight/i).first()).toBeVisible();
  await expect(page.getByText("K7Q", { exact: true })).toHaveCount(0);

  await page.goto("/app/investigations/inv_passed");
  await expect(page.getByText("Passed", { exact: true })).toBeVisible();
  await expect(page.getByText("Presence verified", { exact: true })).toBeVisible();

  await page.goto("/app/investigations/inv_failed");
  await expect(page.getByText("Not confirmed", { exact: true })).toBeVisible();
  await expect(page.getByText(/Presence not confirmed · reduced weight/)).toBeVisible();
  await expect(page.getByText("Location not confirmed for Mahesh; asking someone else.", { exact: true })).toBeVisible();
  await expect(page.getByText(/reduced weight/i).first()).toBeVisible();
});

test("a presence check withdrawn at decision is not presented as a failed check", async ({ page }) => {
  const state = { ...stateFor("inv_withdrawn", false), status: "decided" } as InvestigationState;
  await mockConsole(page, { inv_withdrawn: state }, { inv_withdrawn: withEvents("inv_withdrawn", [issued, withdrawn]) });
  await page.goto("/app/investigations/inv_withdrawn");
  await expect(page.getByText("Not confirmed", { exact: true })).toBeVisible();
  await expect(page.getByText(/Location not confirmed for Mahesh/)).toHaveCount(0);
  await expect(page.getByText(/Location check in progress for Mahesh/)).toHaveCount(0);
});

test("console explains an S2 disagreement and shows its tie-break outcome", async ({ page }) => {
  const observations = [
    {
      ...challengedObservation,
      id: "o_s2_a",
      participant_id: "p_riya",
      location_id: "F2_R205",
      probe_id: "wifi_status",
      outcome: "connected",
      transcript: "My phone is connected to the hostel Wi-Fi.",
    },
    {
      ...challengedObservation,
      id: "o_s2_b",
      participant_id: "p_asha",
      location_id: "F2_R210",
      probe_id: "wifi_status",
      outcome: "no_network",
      transcript: "There is no hostel Wi-Fi network here.",
    },
  ];
  const explanation: EventEnvelope = {
    investigation_id: "inv_s2",
    seq: 410,
    ts: "2026-11-06T00:11:00Z",
    type: "ContradictionExplained",
    payload: {
      explanation_id: "o_s2_b",
      observation_ids: ["o_s2_a", "o_s2_b"],
      families: [
        { code: "different_access_points", posterior_mass: 0.72, supported: true },
        { code: "observer_mistake", posterior_mass: 0.28, supported: true },
        { code: "world_changed", posterior_mass: 0, supported: false },
      ],
      contexts: [
        { participant_ids: ["p_riya", "p_asha"], location_ids: ["F2_R205", "F2_R210"], access_points: ["AP_2B", "AP_2A"], posterior_mass: 0.72 },
      ],
      tie_break_action: { participant_id: "p_riya", probe_id: "wifi_access_point", location_id: "F2_R205", requires_move: false },
    },
  };
  const tieQuestion: EventEnvelope = {
    investigation_id: "inv_s2",
    seq: 411,
    ts: "2026-11-06T00:11:01Z",
    type: "QuestionAsked",
    payload: {
      question_id: "q_tie",
      action: { participant_id: "p_riya", probe_id: "wifi_access_point", location_id: "F2_R205", requires_move: false },
      language: "en",
      text: "Which access point is your phone connected to?",
      kind: "probe",
    },
  };
  const resolved: EventEnvelope = {
    investigation_id: "inv_s2",
    seq: 412,
    ts: "2026-11-06T00:11:10Z",
    type: "ContradictionResolved",
    payload: { explanation_id: "o_s2_b", question_id: "q_tie", outcome: "AP_2B" },
  };
  const state = {
    ...stateFor("inv_s2", true),
    participants: [
      ...previewInvestigation.participants.filter((person) => ["p_riya", "p_asha"].includes(person.id)),
    ],
    observations,
    pending_question: {
      id: "q_tie",
      action: { participant_id: "p_riya", probe_id: "wifi_access_point", location_id: "F2_R205", requires_move: false },
      language: "en",
      text: "Which access point is your phone connected to?",
      outcomes: ["AP_2A", "AP_2B"],
      status: "pending",
      asked_at: "2026-11-06T00:11:01Z",
      kind: "probe",
    },
    pending_questions: [],
  } as unknown as InvestigationState;
  const eventLogs = { inv_s2: withEvents("inv_s2", [explanation, tieQuestion]) };
  await mockConsole(page, { inv_s2: state }, eventLogs);

  await page.goto("/app/investigations/inv_s2");
  await expect(page.getByText("Both can be right", { exact: false })).toBeVisible();
  await expect(page.getByText(/room 205.*access point 2B.*room 210.*access point 2A/i)).toBeVisible();
  await expect(page.getByText(/If access point 2A is down, only room 210 loses Wi-Fi/i)).toBeVisible();
  await expect(page.getByText("72%", { exact: true })).toBeVisible();
  await expect(page.getByTestId("reconciliation-explanation").getByText("Which access point is your phone connected to?", { exact: true })).toBeVisible();
  await expect(page.getByText("Asked, waiting for an answer", { exact: true })).toBeVisible();

  eventLogs.inv_s2 = withEvents("inv_s2", [explanation, tieQuestion, resolved]);
  await page.reload();
  await expect(page.getByText("Answered: access point 2B", { exact: true })).toBeVisible();
  await page.goto("/app/investigations/inv_s2/replay");
  await page.getByRole("button", { name: /Reconciliation explained/ }).click();
  await expect(page.getByTestId("reconciliation-explanation")).toBeVisible();
  await page.getByRole("button", { name: /Tie-break answered/ }).click();
  await expect(page.getByText("Tie-break answered: access point 2B.", { exact: true })).toBeVisible();
});

test("replay turns presence and reconciliation events into readable explanations", async ({ page }) => {
  const events = withEvents("inv_replay", [issued, failed]);
  await mockConsole(page, { inv_replay: stateFor("inv_replay", false) }, { inv_replay: events });
  await page.goto("/app/investigations/inv_replay/replay");
  await page.getByRole("button", { name: /Presence check asked/ }).click();
  await expect(page.getByText(/Mahesh.*asked.*IDF-2/i)).toBeVisible();
  await page.getByRole("button", { name: /Presence check result/ }).click();
  await expect(page.getByText(/Location not confirmed for Mahesh/)).toBeVisible();
  await expect(page.getByText(/reduced weight/i)).toBeVisible();
});

test("create form labels S2 and S7 as simulated one-click scenarios", async ({ page }) => {
  const session = {
    user_id: "u_operator",
    display_name: "Console Operator",
    email: "operator@example.test",
    roles: ["operator"],
    expires_at: "2099-01-01T00:00:00Z",
    method: "session",
  };
  const requestBody = {
    pack_id: "campus_block_c",
    participants: previewInvestigation.participants.slice(0, 2),
    report: { text: "Wi-Fi is unavailable in room 205.", reporter_id: "p_riya", affected_location_id: "F2_R205" },
    scenario: { seed: 2002, fault: "random" },
  };
  await page.route("**/api/core/v1/auth/session", (route) => route.fulfill({ json: session }));
  await page.route("**/api/core/health", (route) => route.fulfill({ json: "ok" }));
  await page.route("**/api/core/v1/packs", (route) => route.fulfill({ json: [{ id: "campus_block_c", title: previewPack.title, locations: 12, probes: 14 }] }));
  await page.route("**/api/core/v1/packs/campus_block_c", (route) => route.fulfill({ json: previewPack }));
  await page.route("**/api/core/v1/participants?**", (route) => route.fulfill({ json: [] }));
  await page.route("**/api/core/v1/investigations/presets", (route) =>
    route.fulfill({
      json: [
        { id: "S2", title: "Different Wi-Fi access points", description: "Two rooms can use different APs.", request: requestBody },
        { id: "S7", title: "Guard presence check at IDF-2", description: "A restricted-location check.", request: requestBody },
      ],
    }),
  );
  await page.route("**/api/core/v1/investigations", async (route) => {
    if (route.request().method() === "POST") return route.fulfill({ status: 201, json: { ...previewInvestigation, id: "inv_preset" } });
    return route.fallback();
  });
  await page.route("**/api/core/v1/investigations/inv_preset", (route) => route.fulfill({ json: { ...previewInvestigation, id: "inv_preset" } }));
  await page.route("**/api/core/v1/investigations/inv_preset/events**", (route) => route.fulfill({ json: [] }));
  await page.route("**/api/core/v1/investigations/inv_preset/stream**", (route) => route.fulfill({ status: 404 }));

  await page.goto("/app/investigations/new");
  await expect(page.getByText(/Simulated scenarios: start S2/)).toBeVisible();
  await expect(page.getByRole("button", { name: "Start S2: Different Wi-Fi access points" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Start S7: Guard presence check at IDF-2" })).toBeVisible();
  await page.getByRole("button", { name: "Start S2: Different Wi-Fi access points" }).click();
  await expect(page).toHaveURL(/\/app\/investigations\/inv_preset$/);
});
