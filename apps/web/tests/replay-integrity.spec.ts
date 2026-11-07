import { expect, test } from "@playwright/test";
import { previewEvents } from "../src/lib/preview/fixtures";

const session = {
  user_id: "u_1", display_name: "Operator", email: "op@x.test", roles: ["operator"],
  expires_at: "2099-01-01T00:00:00Z", method: "session",
};

for (const c of [
  { name: "intact after the reveal", sealed: true, intact: true, text: "Log unchanged since the reveal" },
  { name: "edited after the reveal", sealed: true, intact: false, text: "Log changed after the reveal" },
  { name: "not revealed yet", sealed: false, intact: null, text: "Log not sealed yet" },
]) {
  test(`replay shows the core's integrity check: ${c.name}`, async ({ page }) => {
    await page.route("**/api/core/v1/auth/session", (r) => r.fulfill({ json: session }));
    await page.route("**/api/core/v1/investigations/inv_seal1/events**", (r) =>
      r.fulfill({ json: r.request().url().includes("after_seq=0") ? previewEvents : [] }),
    );
    await page.route("**/api/core/v1/investigations/inv_seal1/replay", (r) => r.fulfill({ json: {
      investigation_id: "inv_seal1", status: "closed", events_replayed: 12, identical: true,
      replayed_sha256: "a".repeat(64), recorded_sha256: "a".repeat(64), final_belief: {}, recorded_belief: {},
      recorded_model_version: "2", current_model_version: "2", engine_changed: false,
      log_sealed: c.sealed, log_intact: c.intact,
    } }));
    await page.goto("/app/investigations/inv_seal1/replay");
    const integrity = page.getByRole("status", { name: "Integrity" });
    await expect(integrity).toContainText("Replay identical (12 events)");
    await expect(integrity).toContainText(c.text);
  });
}
