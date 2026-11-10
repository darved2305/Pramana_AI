import { expect, test, type WebSocketRoute } from "@playwright/test";
import { previewInvestigation } from "../src/lib/preview/fixtures";
import { encodeJoin } from "../src/lib/join";

for (const drop of ["capture", "submission"] as const) {
  test(`a voice drop during ${drop} checks the question before retry`, async ({ page }, testInfo) => {
    const question = {
      ...previewInvestigation.pending_question!, id: "q_recover", status: "pending" as const,
      action: { ...previewInvestigation.pending_question!.action, participant_id: "p_mahesh", requires_move: false },
    };
    const open = { ...previewInvestigation, id: "inv_recover", pending_question: question, pending_questions: [question] };
    const answered = { ...open, pending_question: null, pending_questions: [] };
    let state = open as typeof open | typeof answered;
    let answers = 0;
    let socket: WebSocketRoute | undefined;
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
    await page.route("**/api/core/v1/investigations/inv_recover", (route) => route.fulfill({ json: state }));
    await page.route("**/api/sim/**", (route) => route.fulfill({ json: { location_label: "desk", items: [], reachable_locations: [] } }));
    await page.route("**/api/core/v1/investigations/inv_recover/answers", (route) => {
      answers++;
      state = answered;
      return route.fulfill({ json: { extraction: { outcome: "yes", evidence: [] }, state } });
    });
    await page.routeWebSocket(/\/questions\/q_recover\/media$/, (ws) => {
      socket = ws;
      ws.onMessage((message) => {
        if (typeof message !== "string") return;
        const control = JSON.parse(message);
        if (control.type === "start") ws.send(JSON.stringify({
          type: "ready", question_id: question.id, participant_id: "p_mahesh", text: question.text,
          language: "mr", outcomes: question.outcomes, model_confirmed: true,
          provider: "other", protocol_emulator: true, stt_model: "prisma-v3.0", tts_model: "timbre-v3.0",
        }));
        if (control.type === "commit" && drop === "submission") {
          answers++;
          state = answered;
          void ws.close({ code: 1011 });
        }
      });
    });
    await page.goto(`/join/${encodeJoin({ i: "inv_recover", p: "p_mahesh", s: "sc_1", t: "tok" })}`);
    await page.getByRole("button", { name: "Not now" }).click();
    await page.getByRole("button", { name: "Answer by voice" }).click();
    await expect(page.getByRole("button", { name: "Stop and send" })).toBeVisible();
    await expect(page.getByText("Gnani protocol emulator - synthetic audio", { exact: true })).toBeVisible();
    await page.screenshot({ path: testInfo.outputPath(`voice-participant-${drop}-1440.png`), fullPage: true });
    await page.setViewportSize({ width: 390, height: 844 });
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await page.screenshot({ path: testInfo.outputPath(`voice-participant-${drop}-390.png`), fullPage: true });
    await page.setViewportSize({ width: 1440, height: 900 });
    if (drop === "capture") await socket!.close({ code: 1011 });
    else await page.getByRole("button", { name: "Stop and send" }).click();
    await expect(page.getByRole("alert").filter({ hasText: "voice connection closed" })).toBeVisible();
    if (drop === "capture") {
      await expect(page.getByRole("button", { name: "Answer by voice" })).toBeEnabled();
      await page.getByRole("group", { name: "Answers" }).getByRole("button").first().click();
    } else {
      await expect(page.getByRole("heading", { name: "Nothing to answer right now" })).toBeVisible();
    }
    await expect.poll(() => answers).toBe(1);
  });
}

test("a failed check after a voice drop does not stick on Checking and recovers on retry", async ({ page }, testInfo) => {
  const question = {
    ...previewInvestigation.pending_question!, id: "q_recover", status: "pending" as const,
    action: { ...previewInvestigation.pending_question!.action, participant_id: "p_mahesh", requires_move: false },
  };
  const open = { ...previewInvestigation, id: "inv_recover", pending_question: question, pending_questions: [question] };
  let checksFail = false;
  let answers = 0;
  let socket: WebSocketRoute | undefined;
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
  await page.route("**/api/core/v1/investigations/inv_recover", (route) =>
    checksFail
      ? route.fulfill({ status: 503, json: { code: "UNAVAILABLE", message: "temporarily unavailable" } })
      : route.fulfill({ json: open }),
  );
  await page.route("**/api/sim/**", (route) => route.fulfill({ json: { location_label: "desk", items: [], reachable_locations: [] } }));
  await page.route("**/api/core/v1/investigations/inv_recover/answers", (route) => {
    answers++;
    return route.fulfill({ json: { extraction: { outcome: "yes", evidence: [] }, state: open } });
  });
  await page.routeWebSocket(/\/questions\/q_recover\/media$/, (ws) => {
    socket = ws;
    ws.onMessage((message) => {
      if (typeof message !== "string") return;
      const control = JSON.parse(message);
      if (control.type === "start") ws.send(JSON.stringify({
        type: "ready", question_id: question.id, participant_id: "p_mahesh", text: question.text,
        language: "mr", outcomes: question.outcomes, model_confirmed: true,
        provider: "other", protocol_emulator: true, stt_model: "prisma-v3.0", tts_model: "timbre-v3.0",
      }));
    });
  });
  await page.goto(`/join/${encodeJoin({ i: "inv_recover", p: "p_mahesh", s: "sc_1", t: "tok" })}`);
  await page.getByRole("button", { name: "Not now" }).click();
  await page.getByRole("button", { name: "Answer by voice" }).click();
  await expect(page.getByRole("button", { name: "Stop and send" })).toBeVisible();
  checksFail = true;
  await socket!.close({ code: 1011 });
  await expect(page.getByText("We could not check whether your answer was received.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Checking..." })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Answer by voice" })).toBeDisabled();
  await page.screenshot({ path: testInfo.outputPath("voice-check-failed-1440.png"), fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath("voice-check-failed-390.png"), fullPage: true });
  await page.setViewportSize({ width: 1440, height: 900 });
  checksFail = false;
  await page.getByRole("button", { name: "Check connection" }).click();
  await expect(page.getByRole("button", { name: "Answer by voice" })).toBeEnabled();
  await page.getByRole("group", { name: "Answers" }).getByRole("button").first().click();
  await expect.poll(() => answers).toBe(1);
});
