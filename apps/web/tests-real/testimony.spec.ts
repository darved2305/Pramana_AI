import { expect, test, type APIRequestContext } from "@playwright/test";
import type { InvestigationState } from "../src/lib/api/types";
import { CORE, PEOPLE, PHRASES, api, signIn } from "./helpers";

const SIM = process.env.E2E_SIM_URL as string;

async function rehearse(request: APIRequestContext, scenario: "S2" | "S7", honest: boolean) {
  const people = scenario === "S2" ? [
    { ...PEOPLE[0], id: "p_neha", display_name: "Neha", location_id: "F2_R210" },
    { ...PEOPLE[0], id: "p_aarav", display_name: "Aarav", location_id: "F2_R205" },
  ] : PEOPLE.slice(0, 2);
  let state = await api<InvestigationState>(request, "POST", "/v1/investigations", {
    pack_id: "campus_block_c", participants: people,
    report: { text: scenario === "S2" ? "Wi-Fi is not working in room 210" : "Floor 3 pe WiFi nahi chal raha", reporter_id: people[0].id },
    scenario: { seed: 19, fault: { faults: [{ component_id: scenario === "S2" ? "AP_2A" : "SW_C2", mode: "dead" }] } },
    presence_checks: scenario === "S7",
  });
  const tokens: Record<string, { token: string; scenario_id: string }> = {};
  for (const person of people) tokens[person.id] = await api(request, "POST", `/v1/investigations/${state.id}/participants/${person.id}/token`);
  for (let step = 0; state.pending_question && step < 20; step++) {
    const q = state.pending_question;
    const action = q.action;
    const token = tokens[action.participant_id];
    const headers = { Authorization: `Bearer ${token.token}` };
    const sim = `${SIM}/sim/v1/scenarios/${token.scenario_id}`;
    const lying = !honest && action.participant_id === "p_mahesh" && action.location_id === "IDF2";
    let text: string;
    if (q.kind === "challenge") {
      const response = await request.get(`${sim}/view`, { headers });
      expect(response.ok()).toBeTruthy();
      const view = await response.json();
      text = view.labels.length ? view.labels[0].value.split("").join(" ") : "I cannot see the label from here";
    } else if (lying) {
      text = PHRASES[action.probe_id === "switch_leds" ? "green" : "off"];
    } else {
      if (action.requires_move) {
        const moved = await request.post(`${sim}/move`, { headers, data: { to: action.location_id } });
        expect(moved.ok()).toBeTruthy();
      }
      const response = await request.post(`${sim}/observe`, { headers, data: { probe_id: action.probe_id } });
      expect(response.ok()).toBeTruthy();
      text = PHRASES[(await response.json()).value];
    }
    const answered = await request.post(`${CORE}/v1/investigations/${state.id}/answers`, {
      headers, data: { question_id: q.id, participant_id: action.participant_id, text },
    });
    expect(answered.ok()).toBeTruthy();
    state = await api(request, "GET", `/v1/investigations/${state.id}`);
  }
  expect(state.pending_question).toBeNull();
  for (const person of people) {
    const response = await request.get(`${CORE}/v1/investigations/${state.id}`, {
      headers: { Authorization: `Bearer ${tokens[person.id].token}` },
    });
    expect(response.ok()).toBeTruthy();
    const personal = await response.json();
    expect(personal.disagreements).toEqual([]);
    expect(personal.presence_checks.every((c: { participant_id: string }) => c.participant_id === person.id)).toBe(true);
  }
  return state;
}

test("S2: the real console explains why both students can be right", async ({ page, request }, info) => {
  const state = await rehearse(request, "S2", true);
  expect(state.plan.decision_class).toBe("IT_REPLACE_AP_2A");
  await signIn(page, "operator", `/app/investigations/${state.id}`);
  const panel = page.locator("[aria-labelledby=testimony-title]");
  await expect(panel.getByTestId("disagreement").last()).toContainText("Both can be right");
  await expect(panel).toContainText("room 205 is also covered by Access point 2B");
  await expect(page.getByRole("button", { name: "Propose repair", exact: true })).toHaveCount(0);
  // The campus model has no on-site repair for a dead access point: nothing is offered.
  await expect(page.locator("[aria-labelledby=appr-title]")).toContainText("no on-site repair for this decision");
  await page.screenshot({ path: info.outputPath("S2-console.png"), fullPage: true });
  const replay = await api<{ identical: boolean }>(request, "GET", `/v1/investigations/${state.id}/replay`);
  expect(replay.identical).toBe(true);
});

for (const honest of [true, false]) {
  test(`S7: the real console shows a ${honest ? "confirmed" : "unconfirmed"} location`, async ({ page, request }, info) => {
    const state = await rehearse(request, "S7", honest);
    expect(state.status).toBe("abstained");
    expect(state.presence_checks?.[0].status).toBe(honest ? "passed" : "failed");
    await signIn(page, "operator", `/app/investigations/${state.id}`);
    const check = page.getByTestId("presence-check");
    await expect(check).toContainText(honest ? "Confirmed on site" : "Could not confirm");
    await expect(page.locator("[aria-labelledby=why-title]")).toContainText("Why Pramana stopped");
    await page.screenshot({ path: info.outputPath(`S7-${honest ? "honest" : "adversary"}-console.png`), fullPage: true });
    const replay = await api<{ identical: boolean }>(request, "GET", `/v1/investigations/${state.id}/replay`);
    expect(replay.identical).toBe(true);
  });
}
