import { expect, test, type Page } from "@playwright/test";

async function googleSignIn(page: Page, who: string, next: string) {
  await page.goto(`/api/core/v1/auth/google/start?next=${encodeURIComponent(next)}`);
  await page.getByRole("textbox", { name: "Subject", exact: true }).fill(who);
  await page.getByRole("textbox", { name: "Email", exact: true }).fill(`${who}@gmail.com`);
  await page.getByRole("button", { name: "Continue with mock account" }).click();
}

const csrf = (key: string) => ({ "X-Pramana-CSRF": "1", "Idempotency-Key": key });

test("staff record and withdraw consent, and only owners or admins can erase, with a warning first", async ({ page, browser }) => {
  test.setTimeout(180_000);
  const stamp = Date.now();
  const owner = `privacy-owner-${stamp}`;
  const operator = `privacy-operator-${stamp}`;

  await googleSignIn(page, owner, "/app/account");
  await expect(page).toHaveURL(/\/app\/account$/);
  const created = await page.request.post("/api/core/v1/orgs", {
    headers: csrf(`${owner}-workspace`),
    data: { name: "Privacy Clinic", kind: "hospital" },
  });
  expect(created.status(), await created.text()).toBe(201);
  const ws = (await created.json()) as { organization: { slug: string }; live_site: { id: string } };
  const base = `/app/${ws.organization.slug}`;
  const sitePath = `${base}/people?site=${ws.live_site.id}`;

  // A site with a model, using the template the workspace journey uses.
  await page.goto(`${base}/sites/${ws.live_site.id}`);
  await page.getByRole("button", { name: /Office water supply/ }).click();
  await expect(page.getByRole("heading", { name: "Draft, version 1" })).toBeVisible();
  await page.getByRole("button", { name: "Check this model" }).click();
  await expect(page.getByText("Ready to publish")).toBeVisible({ timeout: 60_000 });
  await page.getByRole("button", { name: "Publish version 1" }).click();
  await expect(page.getByText("Version 1 is published")).toBeVisible();

  const people = `/api/core/v1/orgs/${ws.organization.slug}/sites/${ws.live_site.id}/people`;
  for (const [id, name] of [["p_ravi", "Ravi"], ["p_meena", "Meena"]]) {
    const added = await page.request.post(people, {
      headers: csrf(`${owner}-${id}-person`),
      data: { id, display_name: name, roles: ["plumber"], skill: "technician", location_id: "LOBBY", languages: { stt_candidates: ["hi-IN"] } },
    });
    expect(added.status(), await added.text()).toBe(201);
  }

  await page.goto(sitePath);
  const ravi = page.getByRole("listitem").filter({ hasText: "Ravi" }).filter({ has: page.getByRole("button", { name: "Edit" }) });
  await expect(ravi.getByText("Contact: not recorded")).toBeVisible();
  await expect(ravi.getByText("Voice: not recorded")).toBeVisible();

  // Record consent for contact: shows on the card and in the dialog.
  await ravi.getByRole("button", { name: "Consent" }).click();
  const dialog = page.getByRole("dialog", { name: "Consent for Ravi" });
  const contact = dialog.getByRole("listitem", { name: "Contact" });
  await expect(contact.getByText("Not recorded yet.")).toBeVisible();
  await contact.getByRole("button", { name: "Record consent" }).click();
  await contact.getByLabel("How they agreed").selectOption("pstn");
  await contact.getByRole("button", { name: "Save consent" }).click();
  await expect(contact.getByText(/^Given .*notice version 1/)).toBeVisible();
  await expect(ravi.getByText("Contact: given")).toBeVisible();

  // Withdraw it.
  await contact.getByRole("button", { name: "Withdraw consent: Contact" }).click();
  await expect(contact.getByText(/^Withdrawn /)).toBeVisible();
  await expect(ravi.getByText("Contact: withdrawn")).toBeVisible();
  await dialog.getByRole("button", { name: "Close", exact: true }).click();

  // The person page saves a local quiet-hours window and can issue a one-use link.
  await ravi.getByRole("link", { name: "Person page" }).click();
  await expect(page.getByRole("heading", { name: "Ravi", exact: true })).toBeVisible();
  await expect(page.getByLabel("Quiet hours start")).toHaveValue("22:00");
  await expect(page.getByLabel("Quiet hours end")).toHaveValue("08:00");
  await expect(page.getByLabel("Timezone")).toHaveValue("Asia/Kolkata");
  await page.getByLabel("Quiet hours start").fill("21:30");
  await page.getByLabel("Quiet hours end").fill("07:30");
  const saved = page.waitForResponse((r) => r.url().endsWith("/people/p_ravi") && r.request().method() === "PATCH");
  await page.getByRole("button", { name: "Save settings" }).click();
  expect((await saved).status()).toBe(200);
  await expect(page.getByLabel("Quiet hours start")).toHaveValue("21:30");
  await expect(page.getByText("Web questions: not allowed")).toBeVisible();
  await page.getByRole("button", { name: "Manage consent" }).click();
  const detailDialog = page.getByRole("dialog", { name: "Consent for Ravi" });
  await detailDialog.getByRole("button", { name: "Send consent request" }).click();
  await expect(detailDialog.getByText("No email is saved for this person. Copy and share the link.")).toBeVisible();
  await expect(detailDialog.getByRole("button", { name: "Copy link" })).toBeVisible();
  const consentUrl = (await detailDialog.locator("code").innerText()).trim();
  const phoneContext = await browser.newContext({ viewport: { width: 390, height: 844 } });
  const phone = await phoneContext.newPage();
  await phone.goto(consentUrl);
  await expect(phone.getByRole("heading", { name: "May Pramana ask you questions?" })).toBeVisible();
  await phone.getByRole("button", { name: "Yes, I agree" }).click();
  await expect(phone.getByText(/Your choice is recorded/)).toBeVisible();
  await phone.reload();
  await expect(phone.getByText(/This link has expired or has already been used/)).toBeVisible();
  await phoneContext.close();
  await page.reload();
  await expect(page.getByText("Web questions: allowed")).toBeVisible();
  await page.goto(sitePath);
  await expect(ravi.getByText("Web questions: allowed")).toBeVisible();

  // The server's refusal reaches the person in plain words.
  await page.route(`**${people}/p_meena/erase`, (route) =>
    route.fulfill({ status: 403, contentType: "application/problem+json", body: JSON.stringify({ code: "ROLE_FORBIDDEN", title: "x", status: 403 }) }),
  );
  const meena = page.getByRole("listitem").filter({ hasText: "Meena" }).filter({ has: page.getByRole("button", { name: "Edit" }) });
  await meena.getByRole("button", { name: "Erase" }).click();
  const refused = page.getByRole("dialog", { name: "Permanently erase Meena?" });
  await refused.getByRole("checkbox").check();
  await refused.getByRole("button", { name: "Erase permanently" }).click();
  await expect(refused.getByText("Your account does not have permission to do this.")).toBeVisible();
  await page.unroute(`**${people}/p_meena/erase`);
  await refused.getByRole("button", { name: "Cancel" }).click();

  // Erasure needs a deliberate in-page confirmation that says it cannot be undone.
  await meena.getByRole("button", { name: "Erase" }).click();
  const confirm = page.getByRole("dialog", { name: "Permanently erase Meena?" });
  await expect(confirm.getByText(/This cannot be undone/)).toBeVisible();
  const erase = confirm.getByRole("button", { name: "Erase permanently" });
  await expect(erase).toBeDisabled();
  await confirm.getByRole("checkbox").check();
  await erase.click();
  await expect(page.getByText("Meena was erased")).toBeVisible();
  await expect(page.getByRole("button", { name: "Edit" })).toHaveCount(1);
  const listed = await (await page.request.get(people)).json();
  expect(listed.map((x: { person: { id: string } }) => x.person.id)).toEqual(["p_ravi"]);

  // An operator can manage consent, but is never offered erasure and the server refuses it too.
  const invited = await page.request.post(`/api/core/v1/orgs/${ws.organization.slug}/invitations`, {
    headers: csrf(`${owner}-invite`),
    data: { email: `${operator}@gmail.com`, roles: ["operator"] },
  });
  expect(invited.status(), await invited.text()).toBe(201);
  const { accept_path } = (await invited.json()) as { accept_path: string };
  await page.request.post("/api/core/v1/auth/logout", { headers: { "X-Pramana-CSRF": "1" } });
  await googleSignIn(page, operator, accept_path);
  await page.getByRole("button", { name: "Accept invitation" }).click();
  await expect(page).toHaveURL(new RegExp(`${base}$`));
  await page.goto(sitePath);
  const asOperator = page.getByRole("listitem").filter({ hasText: "Ravi" }).filter({ has: page.getByRole("button", { name: "Edit" }) });
  await expect(asOperator.getByRole("button", { name: "Consent" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Erase", exact: true })).toHaveCount(0);
  const denied = await page.request.post(`${people}/p_ravi/erase`, { headers: csrf(`${operator}-erase-key`) });
  expect(denied.status()).toBe(403);
});
