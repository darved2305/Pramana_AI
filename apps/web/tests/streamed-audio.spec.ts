import { expect, test } from "@playwright/test";
import { previewInvestigation } from "../src/lib/preview/fixtures";

/**
 * "Listen to the question" plays the core's streamed WAV (an open-ended header, then PCM16)
 * through Web Audio while it downloads. Web Audio is instrumented to record what was scheduled.
 */
test.use({ launchOptions: { args: ["--autoplay-policy=no-user-gesture-required"] } });

function streamedWav(seconds: number, rate = 24000): Buffer {
  const header = Buffer.alloc(44);
  header.write("RIFF", 0);
  header.writeUInt32LE(0xffffffff, 4); // length unknown while streaming
  header.write("WAVEfmt ", 8);
  header.writeUInt32LE(16, 16);
  header.writeUInt16LE(1, 20);
  header.writeUInt16LE(1, 22);
  header.writeUInt32LE(rate, 24);
  header.writeUInt32LE(rate * 2, 28);
  header.writeUInt16LE(2, 32);
  header.writeUInt16LE(16, 34);
  header.write("data", 36);
  header.writeUInt32LE(0xffffffff, 40);
  const pcm = Buffer.alloc(Math.round(seconds * rate) * 2 + 1); // odd: a split sample at the end
  for (let i = 0; i + 1 < pcm.length; i += 2) pcm.writeInt16LE(Math.round(8000 * Math.sin(i / 20)), i);
  return Buffer.concat([header, pcm]);
}

test("a streamed question is decoded and scheduled as one gapless run", async ({ page }) => {
  await page.addInitScript(() => {
    const log: { at: number; duration: number; rate: number }[] = [];
    (window as unknown as { __scheduled: typeof log }).__scheduled = log;
    const start = AudioBufferSourceNode.prototype.start;
    AudioBufferSourceNode.prototype.start = function (when?: number, ...rest: number[]) {
      const b = this.buffer;
      if (b) log.push({ at: when ?? 0, duration: b.duration, rate: b.sampleRate });
      return start.call(this, when, ...rest);
    };
  });
  const inv = { ...previewInvestigation, id: "inv_stream1", pending_questions: [previewInvestigation.pending_question!] };
  await page.route("**/api/core/v1/investigations/inv_stream1", (r) => r.fulfill({ json: inv }));
  await page.route("**/api/sim/**", (r) => r.fulfill({ json: { location_label: "the guard desk", items: [], reachable_locations: [] } }));
  let served = 0;
  await page.route("**/api/core/v1/investigations/inv_stream1/questions/*/audio", (r) => {
    served++;
    return r.fulfill({ status: 200, body: streamedWav(1.5), headers: { "content-type": "audio/wav", "x-audio-streamed": "true" } });
  });
  const seg = Buffer.from(JSON.stringify({ i: "inv_stream1", p: "p_mahesh", s: "sc_1", t: "tok" })).toString("base64url");
  await page.goto(`/join/${seg}`);
  await page.getByRole("button", { name: "Listen to the question" }).click();
  await expect.poll(() => served).toBe(1);
  await expect
    .poll(async () => page.evaluate(() => (window as unknown as { __scheduled: { duration: number }[] }).__scheduled.reduce((s, x) => s + x.duration, 0)), { timeout: 10_000 })
    .toBeGreaterThan(1.49);
  const runs = await page.evaluate(() => (window as unknown as { __scheduled: { at: number; duration: number; rate: number }[] }).__scheduled);
  expect(runs.every((r) => r.rate === 24000)).toBe(true);
  for (let i = 1; i < runs.length; i++) expect(runs[i].at).toBeCloseTo(runs[i - 1].at + runs[i - 1].duration, 3); // no gaps
  await expect(page.getByText(/could not|not reachable|failed/i)).toHaveCount(0);
});
