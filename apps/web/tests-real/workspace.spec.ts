import { expect, test, type Page } from "@playwright/test";
import { answerTruthfully, openParticipant, PEOPLE } from "./helpers";

/** A brand-new person: mock Google sign-in, then a workspace of their own. */
async function newWorkspace(page: Page, who: string) {
  await page.goto("/api/core/v1/auth/google/start?next=/app/account");
  await page.getByRole("textbox", { name: "Subject", exact: true }).fill(who);
  await page.getByRole("textbox", { name: "Email", exact: true }).fill(`${who}@gmail.com`);
  await page.getByRole("button", { name: "Continue with mock account" }).click();
  await expect(page).toHaveURL(/\/app\/account$/);
  const created = await page.request.post("/api/core/v1/orgs", {
    headers: { "X-Pramana-CSRF": "1", "Idempotency-Key": `${who}-workspace-0001` },
    data: { name: "Riverside Offices", kind: "office" },
  });
  expect(created.status(), await created.text()).toBe(201);
  return (await created.json()) as {
    organization: { slug: string; id: string; name: string };
    live_site: { id: string };
    sandbox_site: { id: string };
  };
}

test("a new workspace describes its own site, checks it and publishes it", async ({ page, browser }) => {
  test.setTimeout(120_000);
  const ws = await newWorkspace(page, `builder-${Date.now()}`);
  const base = `/app/${ws.organization.slug}`;

  // Home: why each module is there, and what to do next.
  await page.goto(base);
  await expect(page.getByRole("heading", { name: /^Good (morning|afternoon|evening)/ })).toBeVisible();
  const setup = page.getByRole("region", { name: "Set up Pramana" });
  await expect(setup.getByText("1 of 5 steps done. Next: run a practice investigation.")).toBeVisible();
  await expect(page.getByRole("button", { name: /Workspace: |Riverside Offices/ }).first()).toBeVisible();

  // Sites: start from a template, check the generated model, publish it.
  await page.getByRole("link", { name: /Your first building/ }).first().click();
  await expect(page).toHaveURL(new RegExp(`${base}/sites/site_`));
  await page.getByRole("button", { name: /Office water supply/ }).click();
  await expect(page.getByRole("heading", { name: "Draft, version 1" })).toBeVisible();
  await expect(page.getByText(/7 pieces of equipment/)).toBeVisible();
  await page.getByRole("button", { name: "Check this model" }).click();
  await expect(page.getByText("Ready to publish")).toBeVisible({ timeout: 60_000 });
  await expect(page.getByRole("table").filter({ hasText: "Simulated investigations per fault" })).toBeVisible();
  await page.getByRole("button", { name: "Publish version 1" }).click();
  await expect(page.getByText("Version 1 is published")).toBeVisible();
  await expect(page.getByRole("listitem").filter({ hasText: "Version 1" }).getByText("In use")).toBeVisible();

  // Editing after publishing opens a new draft from the same description.
  await page.getByRole("button", { name: "Edit as a new version" }).click();
  await expect(page.getByRole("heading", { name: "Draft, version 2" })).toBeVisible();
  await page.getByRole("tab", { name: /Equipment/ }).click();
  const name = page.getByRole("textbox", { name: "Equipment name" }).first();
  await name.fill("main power");
  await expect(page.getByText("Unsaved changes")).toBeVisible();
  const upload = (body: string) =>
    page.getByLabel("Import equipment from CSV").setInputFiles({ name: "assets.csv", mimeType: "text/csv", buffer: Buffer.from(body) });
  await upload("name,type,location\nBooster,not_a_type,Plant room\n");
  await expect(page.getByText('Row 2: unknown equipment type "not_a_type".')).toBeVisible();
  await upload("name,type,location,floor,depends_on\nBooster unit,pump,Plant room,1,main power\n");
  await expect(page.getByText("Imported: 1 added, 0 updated, 1 new places.", { exact: false })).toBeVisible();
  await page.getByRole("button", { name: "Save draft" }).click();
  await expect(page.getByText("Saved", { exact: true })).toBeVisible();

  // People: placed in this site's own places, with this site's own roles.
  await page.goto(`${base}/people?site=${ws.live_site.id}`);
  await expect(page.getByText("Nobody listed yet")).toBeVisible();
  const added = await page.request.post(`/api/core/v1/orgs/${ws.organization.slug}/sites/${ws.live_site.id}/people`, {
    headers: { "X-Pramana-CSRF": "1", "Idempotency-Key": `${ws.organization.id}-person-0001` },
    data: {
      id: "p_ravi",
      display_name: "Ravi",
      roles: ["plumber"],
      skill: "technician",
      location_id: "LOBBY",
      languages: { stt_candidates: ["hi-IN"] },
    },
  });
  expect(added.status(), await added.text()).toBe(201);
  await page.reload();
  await expect(page.getByText("Ravi", { exact: true })).toBeVisible();
  await expect(page.getByText("Plumber")).toBeVisible();
  await expect(page.getByText(/Can make \d+ checks? at this site\./)).toBeVisible();

  // Home now reflects the published site, the added person and the open draft.
  await page.goto(base);
  await expect(setup.getByText("3 of 5 steps done. Next: run a practice investigation.")).toBeVisible();
  await expect(page.getByText("Draft to check")).toBeVisible();

  // A practice investigation on the person's own published site, from the workspace.
  await page.goto(`${base}/investigations/new?site=${ws.live_site.id}`);
  await expect(page.getByText("This is a practice run on your own model")).toBeVisible();
  await page.getByLabel("What is wrong, in the reporter's words").fill("No water on the second floor since morning");
  await expect(page.getByRole("checkbox", { name: "Include Ravi" })).toBeChecked();
  await page.getByRole("button", { name: "Start investigation" }).click();
  await expect(page).toHaveURL(new RegExp(`${base}/investigations/inv_[0-9A-HJKMNP-TV-Z]{26}$`));
  await expect(page.getByRole("heading", { name: "No water on the second floor since morning" })).toBeVisible();
  // Estimates are on request and labelled as estimates.
  await page.getByRole("button", { name: "Estimate the rest of this investigation" }).click();
  await expect(page.getByText(/simulated runs/)).toBeVisible({ timeout: 60_000 });
  await page.getByRole("button", { name: "Check whether the site's map fits" }).click();
  await expect(page.getByText(/Not enough answers yet to judge|possible map mistakes|Worth checking the documentation/)).toBeVisible({ timeout: 60_000 });

  // A participant link from the workspace works on its own, with no staff session.
  const invId = page.url().split("/").pop() as string;
  const state = await (await page.request.get(`/api/core/v1/orgs/${ws.organization.slug}/investigations/${invId}`)).json();
  const q = state.pending_question;
  const model = await (await page.request.get(`/api/core/v1/orgs/${ws.organization.slug}/sites/${ws.live_site.id}/models/${state.site_model_id}`)).json();
  const probeLabel = model.spec.probes.find((p: { id: string }) => p.id === q.action.probe_id).label as string;
  const who = state.participants.find((p: { id: string }) => p.id === q.action.participant_id).display_name as string;
  await page.getByRole("button", { name: "Participant links" }).first().click();
  const row = page.getByRole("dialog", { name: "Participant links" }).getByRole("listitem").filter({ hasText: who });
  await row.getByRole("button", { name: "Create link" }).click();
  const joinUrl = (await row.getByRole("link").getAttribute("href")) as string;
  await page.keyboard.press("Escape");
  const phone = await openParticipant(browser, joinUrl);
  await answerTruthfully(phone, q.text, probeLabel, false);
  await expect.poll(async () => (await (await page.request.get(`/api/core/v1/orgs/${ws.organization.slug}/investigations/${invId}`)).json()).questions_asked).toBeGreaterThan(state.questions_asked);
  await phone.context().close();

  await page.goto(`${base}/investigations`);
  await expect(page.getByText("No water on the second floor since morning")).toBeVisible();
  // The board shows the same investigation in the column for its stage.
  await page.getByRole("button", { name: "Board" }).click();
  await expect(page).toHaveURL(/view=board$/);
  await expect(page.getByLabel("Investigations by stage").getByText("No water on the second floor since morning")).toBeVisible();

  // Hiding a module is remembered by the core.
  await page.goto(base);
  await page.getByRole("button", { name: "Hide Set up Pramana" }).click();
  await expect(page.getByRole("region", { name: "Set up Pramana" })).toHaveCount(0);
  await page.reload();
  await expect(page.getByRole("region", { name: "Set up Pramana" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Show setup" })).toBeVisible();
});

test("someone else's workspace shows no data", async ({ page }) => {
  await newWorkspace(page, `outsider-${Date.now()}`);
  await page.goto("/app/somebody-elses-campus");
  await expect(page.getByText("You do not have access to this workspace")).toBeVisible();
});

test("investigation history requests bounded cursor pages only when asked", async ({ page }) => {
  const ws = await newWorkspace(page, `cursor-${Date.now()}`);
  const collection = `/api/core/v1/orgs/${ws.organization.slug}/investigations`;
  for (let i = 0; i < 26; i += 1) {
    const response = await page.request.post(collection, {
      headers: { "X-Pramana-CSRF": "1", "Idempotency-Key": `${ws.organization.id}-inv-${i}` },
      data: {
        participants: PEOPLE,
        report: { text: `Pagination cursor check ${i}`, reporter_id: "p_riya" },
        scenario: { seed: i + 1, fault: "random" },
        site_id: ws.sandbox_site.id,
      },
    });
    expect(response.status(), await response.text()).toBe(201);
  }

  const listRequests: URL[] = [];
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (request.method() === "GET" && url.pathname === collection) listRequests.push(url);
  });
  // Site investigations seal report text, so search must use IDs. All generated IDs share this prefix.
  const path = `/app/${ws.organization.slug}/investigations?filter=active&q=inv_`;
  await page.goto(path);
  const list = page.getByRole("list", { name: "Investigations" });
  await expect(list.getByRole("listitem")).toHaveCount(24);
  const loadMore = page.getByRole("button", { name: "Load more investigations" });
  await expect(loadMore).toBeVisible();
  expect(listRequests).toHaveLength(1);
  expect(listRequests[0].searchParams.get("limit")).toBe("24");
  expect(listRequests[0].searchParams.get("offset")).toBeNull();
  expect(listRequests[0].searchParams.get("q")).toBe("inv_");

  await loadMore.focus();
  await page.keyboard.press("Enter");
  await expect(list.getByRole("listitem")).toHaveCount(26);
  expect(listRequests).toHaveLength(2);
  expect(listRequests[1].searchParams.get("limit")).toBe("24");
  expect(listRequests[1].searchParams.get("cursor")).toBeTruthy();
  expect(listRequests[1].searchParams.get("offset")).toBeNull();

  await page.goto(`/app/${ws.organization.slug}/investigations?view=board&filter=active&q=inv_`);
  await expect(page.getByRole("heading", { name: "Asking people" })).toBeVisible();
  expect(listRequests).toHaveLength(3);
  expect(listRequests[2].searchParams.get("q")).toBe("inv_");
  expect(listRequests[2].searchParams.getAll("status")).toContain("investigating");
});

async function mockSignIn(page: Page, who: string, next: string) {
  await page.goto(`/api/core/v1/auth/google/start?next=${encodeURIComponent(next)}`);
  await page.getByRole("textbox", { name: "Subject", exact: true }).fill(who);
  await page.getByRole("textbox", { name: "Email", exact: true }).fill(`${who}@gmail.com`);
  await page.getByRole("button", { name: "Continue with mock account" }).click();
}

async function signOut(page: Page) {
  const out = await page.request.post("/api/core/v1/auth/logout", { headers: { "X-Pramana-CSRF": "1" } });
  expect(out.ok(), await out.text()).toBe(true);
}

test("workspace owner exports, deletes, members see the notice, and the owner restores", async ({ page }) => {
  test.setTimeout(180_000);
  const stamp = Date.now();
  const owner = `delete-${stamp}`;
  const mate = `mate-${stamp}`;
  const ws = await newWorkspace(page, owner);
  const base = `/app/${ws.organization.slug}`;
  const invited = await page.request.post(`/api/core/v1/orgs/${ws.organization.slug}/invitations`, {
    headers: { "X-Pramana-CSRF": "1", "Idempotency-Key": `${owner}-invite-0001` },
    data: { email: `${mate}@gmail.com`, roles: ["operator"] },
  });
  expect(invited.status(), await invited.text()).toBe(201);
  const token = ((await invited.json()) as { accept_path: string }).accept_path.split("/").pop() as string;

  // The teammate joins first, so they still belong to the workspace when it is deleted.
  await signOut(page);
  await mockSignIn(page, mate, "/app/account");
  await expect(page).toHaveURL(/\/app\/account$/);
  const accepted = await page.request.post("/api/core/v1/invitations/accept", {
    headers: { "X-Pramana-CSRF": "1", "Idempotency-Key": `${mate}-accept-0001` },
    data: { token },
  });
  expect(accepted.status(), await accepted.text()).toBeLessThan(300);
  await page.goto(`${base}/settings`);
  await expect(page.getByRole("heading", { name: "Delete workspace" })).toHaveCount(0); // owners only

  await signOut(page);
  await mockSignIn(page, owner, `${base}/settings`);
  await expect(page).toHaveURL(new RegExp(`${base}/settings$`));
  const exportLink = page.getByRole("link", { name: "Download workspace export" });
  await expect(exportLink).toBeVisible();
  const downloadReady = page.waitForEvent("download");
  await exportLink.click();
  const download = await downloadReady;
  expect(download.suggestedFilename()).toMatch(/export-.*\.zip$/);

  const remove = page.getByRole("button", { name: "Delete workspace" });
  await expect(remove).toBeDisabled();
  await page.getByRole("checkbox", { name: "I downloaded the export or have decided I do not need a copy." }).check();
  const confirm = page.getByRole("textbox", { name: `Type ${ws.organization.name} to confirm` });
  await confirm.fill(ws.organization.name.toLowerCase());
  await expect(remove).toBeDisabled(); // the name must match exactly
  await confirm.fill(ws.organization.name);
  await remove.click();
  // Their only workspace is gone, so they land on the first step of setting one up.
  await expect(page).toHaveURL(/\/onboarding\/welcome$/);

  // The teammate sees a notice, not an error, and cannot restore.
  await signOut(page);
  await mockSignIn(page, mate, base);
  await expect(page.getByRole("heading", { name: `${ws.organization.name} was deleted` })).toBeVisible();
  await expect(page.getByText("Ask a workspace owner to restore this workspace")).toBeVisible();
  await expect(page.getByRole("button", { name: "Restore workspace" })).toHaveCount(0);
  await expect(page.getByRole("link", { name: "Download workspace export" })).toHaveCount(0);
  const blocked = await page.request.get(`/api/core/v1/orgs/${ws.organization.slug}/sites`);
  expect(blocked.status()).toBe(410);

  await signOut(page);
  await mockSignIn(page, owner, base);
  await expect(page.getByRole("heading", { name: `${ws.organization.name} was deleted` })).toBeVisible();
  await expect(page.getByRole("link", { name: "Download workspace export" })).toBeVisible();
  await page.getByRole("button", { name: "Restore workspace" }).click();
  await expect(page.getByRole("heading", { name: `${ws.organization.name} was deleted` })).toHaveCount(0);
  await expect(page).toHaveURL(new RegExp(`${base}$`));
  const sites = await page.request.get(`/api/core/v1/orgs/${ws.organization.slug}/sites`);
  expect(sites.status(), await sites.text()).toBe(200);
});
