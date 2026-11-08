import { expect, test } from "@playwright/test";

test("a new person signs in with Google, sets up a workspace and resumes where they left off", async ({ page, browser }) => {
  test.setTimeout(120_000);
  const who = `onboard-${Date.now()}`;

  // The login page offers Google first; it hands over to the (mock) Google flow.
  await page.goto("/login");
  await expect(page.getByRole("link", { name: "Continue with Google" })).toHaveAttribute("href", /\/api\/core\/v1\/auth\/google\/start\?next=%2Fapp$/);
  await page.getByRole("link", { name: "Continue with Google" }).click();
  await page.getByRole("textbox", { name: "Subject", exact: true }).fill(who);
  await page.getByRole("textbox", { name: "Email", exact: true }).fill(`${who}@gmail.com`);
  await page.getByRole("button", { name: "Continue with mock account" }).click();
  await expect(page).toHaveURL(/\/onboarding\/welcome$/);

  await page.getByRole("button", { name: "Get started" }).click();
  await expect(page).toHaveURL(/\/onboarding\/survey$/);
  await page.getByRole("button", { name: "I run facilities or maintenance" }).click();
  await page.getByRole("button", { name: "Office", exact: true }).click();
  await page.getByRole("button", { name: "Water supply" }).click();
  await page.getByRole("button", { name: "Hindi" }).click();
  await expect(page.getByRole("button", { name: "Water supply" })).toHaveAttribute("aria-pressed", "true");

  // Answers are kept by the core: a fresh browser on the same account sees them.
  await page.reload();
  await expect(page.getByRole("button", { name: "Water supply" })).toHaveAttribute("aria-pressed", "true");
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page).toHaveURL(/\/onboarding\/org$/);

  await page.getByLabel("Workspace name").fill("Lakeside Offices");
  await page.getByRole("button", { name: "Create workspace" }).click();
  await expect(page).toHaveURL(/\/onboarding\/sandbox$/);
  await page.getByRole("button", { name: "Skip, I will try it later" }).click();
  await expect(page).toHaveURL(/\/onboarding\/site$/);

  // Coming back later: /app sends the person to the step they stopped at.
  await page.goto("/app");
  await expect(page).toHaveURL(/\/onboarding\/site$/);

  // The suggested template is the one their answers point to, on their own empty site.
  await page.getByRole("link", { name: "Describe my site" }).click();
  await expect(page).toHaveURL(/\/sites\/site_[0-9A-Z]+\?template=office_water$/);
  await expect(page.getByRole("button", { name: /Office water supply.*Suggested/ })).toBeVisible();

  // Skipping setup goes to the workspace home, and /app remembers it from then on.
  await page.goto("/onboarding/site");
  await page.getByRole("button", { name: "Skip setup for now" }).click();
  await expect(page).toHaveURL(/\/app\/lakeside-offices-[0-9a-f]{6}$/);
  await page.goto("/app");
  await expect(page).toHaveURL(/\/app\/lakeside-offices-[0-9a-f]{6}$/);
  void browser;
});

test("Google sign-in that was cancelled says so on the login page", async ({ page }) => {
  await page.goto("/login?error=cancelled");
  await expect(page.getByText("Google sign-in was cancelled. You can try again.")).toBeVisible();
});
