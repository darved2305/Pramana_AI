/**
 * The electrician's repair survives what phones do: a reload after collecting permission, and
 * a report lost on the network after the breaker was already reset. Real core, simulator and
 * PostgreSQL; only one request is made to fail, on purpose.
 */
import { expect, test, type APIRequestContext } from "@playwright/test";
import { encodeJoin } from "../src/lib/join";
import type { InvestigationState } from "../src/lib/api/types";
import { CORE, PEOPLE, PHRASES, api, openParticipant } from "./helpers";

const SIM = process.env.E2E_SIM_URL as string;

async function decided(request: APIRequestContext) {
  let state = await api<InvestigationState>(request, "POST", "/v1/investigations", {
    pack_id: "campus_block_c",
    participants: PEOPLE,
    report: { text: "Floor 3 pe WiFi nahi chal raha", reporter_id: "p_riya" },
    scenario: { seed: 23, fault: { faults: [{ component_id: "CB_C2_7", mode: "tripped" }] } },
  });
  const tokens: Record<string, { token: string; scenario_id: string }> = {};
  for (const p of PEOPLE) tokens[p.id] = await api(request, "POST", `/v1/investigations/${state.id}/participants/${p.id}/token`);
  for (let step = 0; state.pending_question && step < 20; step++) {
    const q = state.pending_question;
    const { participant_id, probe_id, location_id, requires_move } = q.action;
    const headers = { Authorization: `Bearer ${tokens[participant_id].token}` };
    const sim = `${SIM}/sim/v1/scenarios/${tokens[participant_id].scenario_id}`;
    if (requires_move) expect((await request.post(`${sim}/move`, { headers, data: { to: location_id } })).ok()).toBeTruthy();
    const seen = await request.post(`${sim}/observe`, { headers, data: { probe_id } });
    expect(seen.ok()).toBeTruthy();
    const answered = await request.post(`${CORE}/v1/investigations/${state.id}/answers`, {
      headers, data: { question_id: q.id, participant_id, text: PHRASES[(await seen.json()).value] },
    });
    expect(answered.ok()).toBeTruthy();
    state = await api(request, "GET", `/v1/investigations/${state.id}`);
  }
  expect(state.status).toBe("decided");
  expect(state.plan.decision_class).toBe("DISPATCH_ELECTRICIAN_DB_C2");
  state = await api(request, "POST", `/v1/investigations/${state.id}/approvals`, {
    action: "reset_breaker", target: "CB_C2_7", participant_id: "p_imran",
  });
  const aid = (state.approvals ?? [])[0].id;
  state = await api(request, "POST", `/v1/investigations/${state.id}/approvals/${aid}/decision`, { decision: "approve", approver_id: "u_e2e" });
  expect(state.status).toBe("acting");
  return { state, imran: tokens.p_imran };
}

test("a reloaded page and a lost report do not strand the repair", async ({ browser, request }) => {
  const { state, imran } = await decided(request);
  const link = `/join/${encodeJoin({ i: state.id, p: "p_imran", s: imran.scenario_id, t: imran.token })}`;
  const page = await openParticipant(browser, link);
  try {
    await expect(page.getByRole("heading", { name: "You are cleared to act" })).toBeVisible({ timeout: 20_000 });
    await page.getByRole("button", { name: "Collect permission" }).click();
    await expect(page.getByRole("button", { name: "I am at the panel" })).toBeVisible();

    // The phone reloads: permission is collected again and is the same single-use one.
    await page.reload();
    await expect(page.getByRole("heading", { name: "You are cleared to act" })).toBeVisible({ timeout: 20_000 });
    await page.getByRole("button", { name: "Collect permission" }).click();
    await expect(page.locator("p[role=alert]")).toHaveCount(0);
    await page.getByRole("button", { name: "I am at the panel" }).click();

    // The breaker is reset, then the report to the core is lost on the network.
    let dropped = 0;
    await page.route("**/interventions", async (route) => {
      if (route.request().method() === "POST" && dropped === 0) {
        dropped++;
        await route.abort("connectionreset");
      } else {
        await route.continue();
      }
    });
    await page.getByRole("button", { name: "I have done it" }).click();
    await expect(page.locator("p[role=alert]")).toBeVisible();
    expect(dropped).toBe(1);
    expect((await api<InvestigationState>(request, "GET", `/v1/investigations/${state.id}`)).status).toBe("acting");

    // Trying again reports the reset that already happened instead of failing for ever.
    await page.getByRole("button", { name: "I have done it" }).click();
    await expect.poll(async () => (await api<InvestigationState>(request, "GET", `/v1/investigations/${state.id}`)).status).toBe("verifying");
    const events = await api<{ type: string }[]>(request, "GET", `/v1/investigations/${state.id}/events`);
    expect(events.filter((e) => e.type === "CapabilityIssued")).toHaveLength(1);
    expect(events.filter((e) => e.type === "InterventionReported")).toHaveLength(1);
  } finally {
    await page.context().close();
  }
});
