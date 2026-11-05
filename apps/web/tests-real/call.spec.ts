import { expect, test } from "@playwright/test";
import { encodeJoin } from "../src/lib/join";
import { PEOPLE, api } from "./helpers";

/**
 * The participant's call over one socket, in the real browser against the real core. Gnani is
 * not configured here, so these cover the ring and the consent step (no credits).
 */

type Inv = { id: string; pending_question: { id: string; action: { participant_id: string } } | null };

async function s1(request: import("@playwright/test").APIRequestContext) {
  const inv = await api<Inv>(request, "POST", "/v1/investigations", {
    pack_id: "campus_block_c",
    participants: PEOPLE,
    report: { text: "Floor 3 pe WiFi nahi chal raha", reporter_id: "p_riya" },
    scenario: { seed: 7, fault: { faults: [{ component_id: "CB_C2_7", mode: "tripped" }] } },
  });
  const pid = inv.pending_question!.action.participant_id;
  const tok = await api<{ token: string; scenario_id: string }>(request, "POST", `/v1/investigations/${inv.id}/participants/${pid}/token`);
  return { inv, pid, link: `/join/${encodeJoin({ i: inv.id, p: pid, s: tok.scenario_id, t: tok.token })}` };
}

test.describe("participant call", () => {
  test("rings, shows the consent line, and a No hands the question to someone else", async ({ page, request }) => {
    const { inv, pid, link } = await s1(request);
    await page.goto(link);
    await expect(page.getByRole("heading", { name: "Pramana is calling" })).toBeVisible();
    await page.getByRole("button", { name: "Accept" }).click();
    const consent = page.getByRole("group", { name: "Consent" });
    await expect(consent).toBeVisible();
    await expect(page.getByText("?", { exact: false }).first()).toBeVisible();
    await consent.getByRole("button", { name: "No" }).click();
    await expect.poll(async () => {
      const s = await api<Inv>(request, "GET", `/v1/investigations/${inv.id}`);
      return s.pending_question?.action.participant_id ?? "none";
    }).not.toBe(pid);
    const events = await api<{ type: string; payload: Record<string, unknown> }[]>(request, "GET", `/v1/investigations/${inv.id}/events`);
    const consentEvent = events.find((e) => e.type === "ConsentRecorded");
    expect(consentEvent?.payload).toMatchObject({ participant_id: pid, consented: false });
    expect(events.some((e) => e.type === "QuestionCancelled")).toBe(true);
    await expect(page.getByRole("heading", { name: "Nothing to answer right now" })).toBeVisible();
  });

  test("Not now only dismisses the call; the question can still be answered by tapping", async ({ page, request }) => {
    const { inv, pid, link } = await s1(request);
    await page.goto(link);
    await page.getByRole("button", { name: "Not now" }).click();
    await expect(page.getByRole("heading", { name: "Pramana is calling" })).toHaveCount(0);
    const answers = page.getByRole("group", { name: "Answers" });
    await expect(answers).toBeVisible();
    const s = await api<Inv>(request, "GET", `/v1/investigations/${inv.id}`);
    expect(s.pending_question?.action.participant_id).toBe(pid); // nobody was released
  });
});
