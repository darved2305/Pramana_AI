import { expect, test, type Page } from "@playwright/test";

async function googleSignIn(page: Page, subject: string, email: string, hd: string) {
  await page.goto("/api/core/v1/auth/google/start?next=%2Fapp");
  await page.getByRole("textbox", { name: "Subject", exact: true }).fill(subject);
  await page.getByRole("textbox", { name: "Email", exact: true }).fill(email);
  await page.getByRole("textbox", { name: "Workspace domain", exact: true }).fill(hd);
  await page.getByRole("button", { name: "Continue with mock account" }).click();
}

async function signOut(page: Page) {
  await page.request.post("/api/core/v1/auth/logout", { headers: { "X-Pramana-CSRF": "1" } });
}

test("ID-03 and ID-04: request and automatic domain joins work in a real browser", async ({ page }) => {
  test.setTimeout(180_000);
  const stamp = Date.now();
  const owner = `domain-owner-${stamp}`;
  const requester = `domain-requester-${stamp}`;
  const automatic = `domain-auto-${stamp}`;
  const ownerEmail = `${owner}@college.edu`;
  const requesterEmail = `${requester}@college.edu`;
  const autoEmail = `${automatic}@college.edu`;

  await googleSignIn(page, owner, ownerEmail, "college.edu");
  const created = await page.request.post("/api/core/v1/orgs", {
    headers: { "X-Pramana-CSRF": "1", "Idempotency-Key": `${owner}-domain-org-001` },
    data: { name: "Nava College", kind: "campus" },
  });
  expect(created.status(), await created.text()).toBe(201);
  const workspace = (await created.json()) as { organization: { slug: string; id: string } };
  const base = `/app/${workspace.organization.slug}`;

  await page.goto(`${base}/settings`);
  await page.getByLabel("Email domain").fill("college.edu");
  await page.getByRole("button", { name: "Add domain" }).click();
  await page.getByRole("button", { name: "Verify domain" }).click();
  await expect(page.getByText("Verified", { exact: true })).toBeVisible();

  await signOut(page);
  await googleSignIn(page, requester, requesterEmail, "college.edu");
  await expect(page).toHaveURL(/\/onboarding\/welcome$/);
  await page.getByRole("button", { name: "Request to join Nava College" }).click();
  await expect(page.getByText("Request sent. You can create a separate organization to use a sandbox.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Create a separate organization" })).toBeVisible();

  await signOut(page);
  await googleSignIn(page, owner, ownerEmail, "college.edu");
  await page.goto(`${base}/settings#join-requests`);
  const pending = page.getByRole("list", { name: "Workspace join requests" });
  await expect(pending.getByText(requesterEmail)).toBeVisible();
  await pending.getByRole("button", { name: "Approve" }).click();
  await expect(pending.getByText("Approved", { exact: true })).toBeVisible();

  await signOut(page);
  await googleSignIn(page, requester, requesterEmail, "college.edu");
  await expect(page).toHaveURL(new RegExp(`${base}$`));
  const requesterAccount = await (await page.request.get("/api/core/v1/me")).json();
  expect(requesterAccount.memberships).toEqual(
    expect.arrayContaining([expect.objectContaining({ id: workspace.organization.id, roles: ["viewer"] })]),
  );

  await signOut(page);
  await googleSignIn(page, owner, ownerEmail, "college.edu");
  await page.goto(`${base}/settings`);
  await page.getByLabel("Who can join from college.edu").selectOption("auto");
  await expect(page.getByLabel("Who can join from college.edu")).toHaveValue("auto");

  await signOut(page);
  await googleSignIn(page, automatic, autoEmail, "college.edu");
  await expect(page).toHaveURL(new RegExp(`${base}$`));
  const automaticAccount = await (await page.request.get("/api/core/v1/me")).json();
  expect(automaticAccount.memberships).toEqual(
    expect.arrayContaining([expect.objectContaining({ id: workspace.organization.id, roles: ["viewer"] })]),
  );

  await signOut(page);
  await googleSignIn(page, owner, ownerEmail, "college.edu");
  await page.goto(base);
  await expect(page.getByText("Joined as viewer", { exact: true })).toBeVisible();
});
