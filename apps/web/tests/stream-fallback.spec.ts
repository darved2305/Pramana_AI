import { expect, test } from "@playwright/test";
import { previewInvestigation, previewPack } from "../src/lib/preview/fixtures";

/**
 * A proxy that buffers server-sent events (a Cloudflare quick tunnel) answers the stream and
 * then delivers nothing, without an error. The console must notice and poll the event log.
 */
test("the console polls when the event stream never delivers", async ({ page }) => {
  const session = { user_id: "u_1", display_name: "Olu Operator", email: "op@x.test", roles: ["operator"], expires_at: "2099-01-01T00:00:00Z", method: "session" };
  const inv = { ...previewInvestigation, id: "inv_live1" };
  let polls = 0;
  await page.route("**/api/core/v1/auth/session", (r) => r.fulfill({ json: session }));
  await page.route("**/api/core/v1/packs/**", (r) => r.fulfill({ json: previewPack }));
  await page.route("**/api/core/v1/investigations/inv_live1", (r) => r.fulfill({ json: inv }));
  // The stream is accepted but never answered: no `ready`, no error.
  await page.route("**/api/core/v1/investigations/inv_live1/stream**", () => new Promise<void>(() => {}));
  await page.route("**/api/core/v1/investigations/inv_live1/events**", (r) => {
    polls++;
    return r.fulfill({ json: [] });
  });
  await page.goto("/app/investigations/inv_live1");
  await expect.poll(() => polls, { timeout: 15_000 }).toBeGreaterThan(0);
});
