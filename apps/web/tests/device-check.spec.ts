import { expect, test, type Page } from "@playwright/test";
import { encodeJoin } from "../src/lib/join";
import { previewInvestigation } from "../src/lib/preview/fixtures";
import type { InvestigationState } from "../src/lib/api/types";

/** A participant waiting for a call checks their microphone and sound first. */
async function waiting(page: Page) {
  const state: InvestigationState = {
    ...previewInvestigation, id: "inv_dev1", status: "investigating", pending_question: null, pending_questions: [], approvals: [],
  };
  await page.route("**/api/core/v1/investigations/inv_dev1", (r) => r.fulfill({ json: state }));
  await page.route("**/api/sim/sim/v1/scenarios/scn_1/view", (r) =>
    r.fulfill({ json: { location_label: "the guard desk", items: [], reachable_locations: [] } }),
  );
  await page.goto(`/join/${encodeJoin({ i: "inv_dev1", p: "p_mahesh", s: "scn_1", t: "tok" })}`);
  await expect(page.getByRole("heading", { name: "Nothing to answer right now" })).toBeVisible();
}

/** Replace the microphone: "speech" is a tone, "silence" is a muted source, "blocked" refuses. */
async function microphone(page: Page, kind: "speech" | "silence" | "blocked") {
  await page.addInitScript((k) => {
    navigator.mediaDevices.getUserMedia = async () => {
      if (k === "blocked") throw new DOMException("denied", "NotAllowedError");
      const ctx = new AudioContext();
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      gain.gain.value = k === "speech" ? 0.5 : 0;
      const out = ctx.createMediaStreamDestination();
      osc.connect(gain).connect(out);
      osc.start();
      return out.stream;
    };
  }, kind);
}

for (const c of [
  { kind: "speech" as const, says: "Your microphone works and the sound is on." },
  { kind: "silence" as const, says: "nothing was heard" },
  { kind: "blocked" as const, says: "Microphone access is blocked." },
]) {
  test(`device check: ${c.kind}`, async ({ page }) => {
    await microphone(page, c.kind);
    await waiting(page);
    const box = page.getByLabel("Device check");
    await box.getByRole("button", { name: "Check microphone and sound" }).click();
    await expect(box.getByRole("status")).toContainText(c.says, { timeout: 10_000 });
    await expect(box.getByRole("button", { name: "Check again" })).toBeVisible();
  });
}
