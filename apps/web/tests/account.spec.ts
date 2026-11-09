import { expect, test } from "@playwright/test";

test("account explains when sign-in is not required", async ({ page }) => {
  await page.route("**/api/core/v1/auth/session", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      json: {
        display_name: "Local user",
        email: "local@example.test",
        email_verified: true,
        expires_at: "2026-11-10T00:00:00Z",
        method: "open",
        roles: ["operator"],
        user_id: "user_open_mode",
      },
    }),
  );
  await page.goto("/app/account");
  await expect(page.getByRole("main").getByText("Sign-in is not required here.")).toBeVisible();
});
