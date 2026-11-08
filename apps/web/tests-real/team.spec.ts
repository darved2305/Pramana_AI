import { expect, test, type Page } from "@playwright/test";

async function googleSignIn(page: Page, who: string, next: string) {
  await page.goto(`/api/core/v1/auth/google/start?next=${encodeURIComponent(next)}`);
  await page.getByRole("textbox", { name: "Subject", exact: true }).fill(who);
  await page.getByRole("textbox", { name: "Email", exact: true }).fill(`${who}@gmail.com`);
  await page.getByRole("button", { name: "Continue with mock account" }).click();
}

test("an owner invites a teammate, who joins with the invited address only", async ({ page }) => {
  test.setTimeout(120_000);
  const stamp = Date.now();
  const owner = `owner-${stamp}`;
  const mate = `mate-${stamp}`;

  await googleSignIn(page, owner, "/app/account");
  await expect(page).toHaveURL(/\/app\/account$/);
  const created = await page.request.post("/api/core/v1/orgs", {
    headers: { "X-Pramana-CSRF": "1", "Idempotency-Key": `${owner}-workspace-0001` },
    data: { name: "Harbour Clinic", kind: "hospital" },
  });
  expect(created.status(), await created.text()).toBe(201);
  const ws = (await created.json()) as { organization: { slug: string; id: string }; live_site: { id: string } };
  const base = `/app/${ws.organization.slug}`;

  // Model health lists the practice site even before anything is published.
  await page.goto(`${base}/health`);
  await expect(page.getByRole("heading", { name: "Model health" })).toBeVisible();
  await expect(page.getByText("Not described yet.")).toBeVisible();

  // Settings: the owner invites a teammate as an approver and copies the one-time link.
  await page.goto(`${base}/settings`);
  await expect(page.getByText(`${owner}@gmail.com`)).toBeVisible();
  await page.getByLabel("Their email address").fill(`${mate}@gmail.com`);
  await page.getByRole("checkbox", { name: /Operator/ }).uncheck();
  await page.getByRole("checkbox", { name: /Approver/ }).check();
  await page.getByRole("button", { name: "Create invitation link" }).click();
  const link = await page.locator("code").filter({ hasText: "/invite/org_" }).innerText();
  await expect(page.getByRole("list", { name: "Invitations" }).getByText("pending")).toBeVisible();

  // Someone else with the link cannot use it.
  await page.request.post("/api/core/v1/auth/logout", { headers: { "X-Pramana-CSRF": "1" } });
  await googleSignIn(page, `stranger-${stamp}`, "/app/account");
  await page.goto(new URL(link).pathname);
  await page.getByRole("button", { name: "Accept invitation" }).click();
  await expect(page.getByText(/this invitation is for/)).toBeVisible();
  await expect(page.getByRole("button", { name: "Use another account" })).toBeVisible();

  // The invited person joins and lands in the workspace with the role they were given.
  await page.request.post("/api/core/v1/auth/logout", { headers: { "X-Pramana-CSRF": "1" } });
  await googleSignIn(page, mate, new URL(link).pathname);
  await expect(page.getByText(`${mate}@gmail.com`)).toBeVisible();
  await page.getByRole("button", { name: "Accept invitation" }).click();
  await expect(page).toHaveURL(new RegExp(`${base}$`));
  await page.goto(`${base}/settings`);
  await expect(page.getByRole("heading", { name: "Harbour Clinic" })).toBeVisible();
  const members = page.getByRole("list", { name: "Members" }).getByRole("listitem");
  await expect(members).toHaveCount(2);
  await expect(page.getByText(`${owner}@gmail.com`)).toHaveCount(0); // approvers do not see addresses
  await expect(page.getByRole("button", { name: "Create invitation link" })).toHaveCount(0);

  // Back as the owner: change the teammate's roles, then remove them.
  await page.request.post("/api/core/v1/auth/logout", { headers: { "X-Pramana-CSRF": "1" } });
  await googleSignIn(page, owner, `${base}/settings`);
  await expect(page).toHaveURL(new RegExp(`${base}/settings$`));
  const memberList = page.getByRole("list", { name: "Members" });
  const row = memberList.getByRole("listitem").filter({ hasText: `${mate}@gmail.com` });
  await row.getByRole("button", { name: "Change roles" }).click();
  await row.getByRole("checkbox", { name: "operator" }).check();
  await row.getByRole("button", { name: "Save roles" }).click();
  await expect(row.getByText("operator", { exact: true })).toBeVisible();
  // The last owner cannot step down.
  const me = memberList.getByRole("listitem").filter({ hasText: `${owner}@gmail.com` });
  await me.getByRole("button", { name: "Change roles" }).click();
  await me.getByRole("checkbox", { name: "owner" }).uncheck();
  await me.getByRole("checkbox", { name: "admin" }).check();
  await me.getByRole("button", { name: "Save roles" }).click();
  await expect(me.getByText(/a workspace needs an owner/)).toBeVisible();
  await me.getByRole("button", { name: "Cancel" }).click();
  await row.getByRole("button", { name: "Remove" }).click();
  await expect(memberList.getByRole("listitem").filter({ hasText: `${mate}@gmail.com` })).toHaveCount(0);
});
