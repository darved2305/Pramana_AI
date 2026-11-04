import { expect, test } from "@playwright/test";
import { PEOPLE, api } from "./helpers";

/**
 * The participant page opens the live voice socket same-origin, at /api/core/..., and relies on
 * the Next rewrite to forward the WebSocket upgrade to the core. These tests open that socket
 * from the real browser and check for close codes only the core sends, so they fail if the
 * rewrite does not proxy WebSockets. Gnani is not configured here: no credits are spent.
 */

type Closed = { code: number; frames: { type: string; code?: string }[] };

async function openMedia(page: import("@playwright/test").Page, path: string, token: string): Promise<Closed> {
  await page.goto("/");
  return page.evaluate(
    ({ path, token }) =>
      new Promise<Closed>((resolve) => {
        const url = `${location.origin.replace(/^http/, "ws")}${path}`;
        const ws = new WebSocket(url);
        const frames: { type: string; code?: string }[] = [];
        const timer = setTimeout(() => resolve({ code: -1, frames }), 15_000);
        ws.onopen = () => ws.send(JSON.stringify({ type: "start", token, play_question: false }));
        ws.onmessage = (e) => {
          if (typeof e.data === "string") frames.push(JSON.parse(e.data));
        };
        ws.onclose = (e) => {
          clearTimeout(timer);
          resolve({ code: e.code, frames });
        };
      }),
    { path, token },
  );
}

test.describe("live voice socket through the Next rewrite", () => {
  test("reaches the core: a forged token is refused by the core", async ({ page, request }) => {
    const inv = await api<{ id: string; pending_question: { id: string } }>(request, "POST", "/v1/investigations", {
      pack_id: "campus_block_c",
      participants: PEOPLE,
      report: { text: "Floor 3 pe WiFi nahi chal raha", reporter_id: "p_riya" },
      scenario: { seed: 7, fault: { faults: [{ component_id: "CB_C2_7", mode: "tripped" }] } },
    });
    const path = `/api/core/v1/investigations/${inv.id}/questions/${inv.pending_question.id}/media`;
    const closed = await openMedia(page, path, "abc.def");
    expect(closed.code).toBe(4401); // the core's "bad token" close code, not a proxy failure (1006)
  });

  test("a valid join token gets through to the voice checks", async ({ page, request }) => {
    const inv = await api<{ id: string; pending_question: { id: string; action: { participant_id: string } } }>(
      request,
      "POST",
      "/v1/investigations",
      {
        pack_id: "campus_block_c",
        participants: PEOPLE,
        report: { text: "Floor 3 pe WiFi nahi chal raha", reporter_id: "p_riya" },
        scenario: { seed: 7, fault: { faults: [{ component_id: "CB_C2_7", mode: "tripped" }] } },
      },
    );
    const q = inv.pending_question;
    const tok = await api<{ token: string }>(request, "POST", `/v1/investigations/${inv.id}/participants/${q.action.participant_id}/token`);
    const closed = await openMedia(page, `/api/core/v1/investigations/${inv.id}/questions/${q.id}/media`, tok.token);
    // Token and question were accepted; the core then refuses because Gnani is not configured.
    expect(closed.frames.at(-1)).toMatchObject({ type: "error", code: "VOICE_NOT_CONFIGURED" });
    expect(closed.code).toBe(4503);
  });
});
