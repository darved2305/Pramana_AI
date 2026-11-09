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
  await expect(page.getByText("We could not send the email, so please send this link yourself")).toBeVisible(); // no Gmail set up here
  await expect(page.getByRole("list", { name: "Invitations" }).getByText("pending")).toBeVisible();

  // Someone else with the link cannot use it.
  await page.request.post("/api/core/v1/auth/logout", { headers: { "X-Pramana-CSRF": "1" } });
  await googleSignIn(page, `stranger-${stamp}`, "/app/account");
  await page.goto(new URL(link).pathname);
  await page.getByRole("button", { name: "Accept invitation" }).click();
  await expect(page.getByText(/This invitation is for/)).toBeVisible();
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
  await page.setViewportSize({ width: 390, height: 844 });
  await row.scrollIntoViewIfNeeded();
  const memberAddress = row.locator(".break-all");
  const memberRole = row.getByText("approver", { exact: true });
  const memberAddressBox = await memberAddress.boundingBox();
  const memberRoleBox = await memberRole.boundingBox();
  if (!memberAddressBox || !memberRoleBox) throw new Error("member address or role is not visible");
  const memberOverlap =
    memberAddressBox.x < memberRoleBox.x + memberRoleBox.width &&
    memberAddressBox.x + memberAddressBox.width > memberRoleBox.x &&
    memberAddressBox.y < memberRoleBox.y + memberRoleBox.height &&
    memberAddressBox.y + memberAddressBox.height > memberRoleBox.y;
  expect(memberOverlap).toBe(false);
  expect(await memberAddress.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true);
  await page.setViewportSize({ width: 1440, height: 900 });
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
  await expect(me.getByText(/A workspace needs an owner/)).toBeVisible();
  await me.getByRole("button", { name: "Cancel" }).click();
  await row.getByRole("button", { name: "Remove" }).click();
  await expect(memberList.getByRole("listitem").filter({ hasText: `${mate}@gmail.com` })).toHaveCount(0);

  // The screen says truthfully whether the link was emailed. The core's answer is rewritten here,
  // because this stack has no Gmail account and never sends a real message.
  for (const [delivery, words] of [
    ["sent", "We emailed this link to"],
    ["queued", "The email is queued. Copy the link now if you want to send it yourself"],
    ["failed", "We could not send the email, so please send this link yourself"],
  ] as const) {
    let keepQueuedList = delivery === "queued";
    await page.route("**/invitations", async (route) => {
      if (route.request().method() !== "POST") {
        if (delivery !== "queued" || !keepQueuedList) return route.continue();
        const response = await route.fetch();
        const rows = await response.json() as Array<Record<string, unknown>>;
        await route.fulfill({ response, json: rows.map((row) => ({ ...row, email_delivery: "queued" })) });
        return;
      }
      const response = await route.fetch();
      await route.fulfill({ response, json: { ...(await response.json()), email_delivery: delivery } });
    });
    const address = `${delivery}-${stamp}@example.com`;
    await page.getByLabel("Their email address").fill(address);
    const createdLink = page.waitForResponse((response) =>
      response.request().method() === "POST" && response.url().endsWith("/invitations"),
    );
    await page.getByRole("button", { name: "Create invitation link" }).click();
    await createdLink;
    const deliveryNotice = page.getByText(`Invitation link for ${address}`, { exact: true }).locator("..");
    await expect(deliveryNotice.getByText(words)).toBeVisible();
    if (delivery === "queued") {
      keepQueuedList = false;
      await expect(deliveryNotice.getByText("We could not send the email, so please send this link yourself")).toBeVisible();
    }
    await page.unroute("**/invitations");
  }

  await page.route("**/invitations", async (route) => {
    if (route.request().method() !== "GET") return route.continue();
    const response = await route.fetch();
    const rows = await response.json() as Array<Record<string, unknown>>;
    await route.fulfill({ response, json: rows.map((row) => ({ ...row, email_delivery: "unknown" })) });
  });
  await page.reload();
  await expect(page.getByText("Email status unavailable").first()).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  const latestInvitation = page.getByRole("list", { name: "Invitations" }).getByRole("listitem").first();
  await latestInvitation.scrollIntoViewIfNeeded();
  const invitationEmail = latestInvitation.locator(":scope > span").first();
  const invitationRoles = latestInvitation.locator(":scope > span").nth(1);
  const invitationEmailBox = await invitationEmail.boundingBox();
  const invitationRolesBox = await invitationRoles.boundingBox();
  if (!invitationEmailBox || !invitationRolesBox) {
    throw new Error("invitation address or roles are not visible");
  }
  expect(invitationRolesBox.y).toBeGreaterThanOrEqual(
    invitationEmailBox.y + invitationEmailBox.height - 1,
  );
  expect(await invitationEmail.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true);
  await page.unroute("**/invitations");
});
