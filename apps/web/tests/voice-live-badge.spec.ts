import { expect, test } from "@playwright/test";
import { previewInvestigation } from "../src/lib/preview/fixtures";
import { encodeJoin } from "../src/lib/join";

test("live voice shows the selected models, language, and detected language", async ({ page }) => {
  const question = {
    ...previewInvestigation.pending_question!, id: "q_live_badge", status: "pending" as const,
    action: { ...previewInvestigation.pending_question!.action, participant_id: "p_mahesh", requires_move: false },
    language: "hi-en",
  };
  const state = {
    ...previewInvestigation, id: "inv_live_badge", pending_question: question, pending_questions: [question],
  };
  await page.addInitScript(() => {
    Object.defineProperty(navigator, "mediaDevices", { value: { getUserMedia: async () => ({ getTracks: () => [{ stop() {} }] }) } });
    class FakeAudioContext {
      audioWorklet = { addModule: async () => {} };
      createMediaStreamSource() { return { connect() {} }; }
      close() { return Promise.resolve(); }
    }
    class FakeWorklet { port = { postMessage() {} }; disconnect() {} }
    Object.assign(window, { AudioContext: FakeAudioContext, AudioWorkletNode: FakeWorklet });
  });
  await page.route("**/api/core/v1/investigations/inv_live_badge", (route) => route.fulfill({ json: state }));
  await page.route("**/api/sim/**", (route) => route.fulfill({ json: { location_label: "desk", items: [], reachable_locations: [] } }));
  await page.routeWebSocket(/\/questions\/q_live_badge\/media$/, (ws) => {
    ws.onMessage((message) => {
      if (typeof message !== "string") return;
      const control = JSON.parse(message);
      if (control.type === "start") ws.send(JSON.stringify({
        type: "ready", question_id: question.id, participant_id: "p_mahesh", text: question.text,
        language: "hi-en", outcomes: question.outcomes, model_confirmed: true, provider: "gnani",
        protocol_emulator: false, stt_model: "prisma-v3.0", tts_model: "timbre-v2.5",
      }));
      if (control.type === "commit") ws.send(JSON.stringify({
        type: "transcript", text: "haan", detected_language: "hi-IN", provider_latency_ms: 15,
      }));
    });
  });
  await page.goto(`/join/${encodeJoin({ i: "inv_live_badge", p: "p_mahesh", s: "sc_1", t: "tok" })}`);
  await page.getByRole("button", { name: "Not now" }).click();
  await page.getByRole("button", { name: "Answer by voice" }).click();
  await expect(page.getByText("Prisma v3.0 / Timbre v2.5 · hi-en")).toBeVisible();
  await page.getByRole("button", { name: "Stop and send" }).click();
  await expect(page.getByText("Detected: hi-IN")).toBeVisible();
});
