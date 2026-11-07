import { expect, test } from "@playwright/test";

const session = {
  user_id: "u_1", display_name: "Operator", email: "op@x.test", roles: ["operator"],
  expires_at: "2099-01-01T00:00:00Z", method: "session",
};
const usage = {
  spent_today_inr: 112.5,
  by_service: { stt_stream: { requests: 41, units: 900, cost_inr: 5.0 }, tts: { requests: 30, units: 6000, cost_inr: 10.8 } },
  limits: { stt_rest_per_min: 50, tts_per_min: 50, max_streams: 16, rest_max_inflight: 8, daily_budget_inr: 150 },
  window_used: { stt_rest: 3, tts: 7 },
  open_streams: 2,
};

for (const c of [
  { provider: "gnani", host: "api.vachana.ai", badge: "Live Gnani", warning: false },
  { provider: "other", host: "127.0.0.1", badge: "Not Gnani (emulator?)", warning: true },
]) {
  test(`voice meter: ${c.badge}`, async ({ page }) => {
    await page.route("**/api/core/v1/auth/session", (r) => r.fulfill({ json: session }));
    await page.route("**/api/core/v1/voice/status", (r) => r.fulfill({ json: {
      configured: true, provider: c.provider, provider_host: c.host, stt_model: "prisma-v3.0", tts_models: ["timbre-v3.0"],
    } }));
    await page.route("**/api/core/v1/voice/usage", (r) => r.fulfill({ json: usage }));
    await page.goto("/app/voice");
    const provider = page.getByRole("region", { name: "Provider" });
    await expect(provider).toContainText(c.badge);
    await expect(provider).toContainText(c.host);
    await expect(provider.getByText("Label runs as emulated")).toHaveCount(c.warning ? 1 : 0);
    const spend = page.getByRole("region", { name: "Spend today" });
    await expect(spend).toContainText("Rs 112.50");
    await expect(spend).toContainText("75% of today's budget");
    await expect(spend).toContainText("Live speech to text (Prisma)");
    await expect(page.getByRole("region", { name: "Limits now" })).toContainText("2 of 16");
  });
}
