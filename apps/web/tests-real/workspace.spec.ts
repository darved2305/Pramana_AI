import { expect, test, type Page } from "@playwright/test";
import { answerTruthfully, openParticipant } from "./helpers";

type WorkspaceInvestigation = {
  status: string;
  questions_asked: number;
  site_model_id: string;
  participants: { id: string; display_name: string }[];
  pending_question: { text: string; action: { participant_id: string; probe_id: string } } | null;
  pending_questions?: { text: string; action: { participant_id: string; probe_id: string } }[];
};

function finished(status: string) {
  return ["decided", "abstained", "verified", "not_verified", "closed"].includes(status);
}

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
  return (await created.json()) as { organization: { slug: string; id: string }; live_site: { id: string } };
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
  await page.getByLabel("Import equipment from CSV").setInputFiles({
    name: "huge-assets.csv",
    mimeType: "text/csv",
    buffer: Buffer.alloc(5 * 1024 * 1024 + 1, 0x61),
  });
  await expect(page.getByRole("alert", { name: "Import result" })).toContainText("Choose a CSV file no larger than 5 MB.");
  await expect(page.getByRole("textbox", { name: "Equipment name" }).first()).toHaveValue("main power");
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
  await expect(page.getByText(/No track record yet: it builds up from investigations whose cause was revealed or confirmed\./)).toBeVisible();

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
  const readState = async () => {
    const response = await page.request.get(`/api/core/v1/orgs/${ws.organization.slug}/investigations/${invId}`);
    expect(response.status()).toBe(200);
    return (await response.json()) as WorkspaceInvestigation;
  };
  const state = await readState();
  const q = state.pending_question;
  if (!q) throw new Error("The investigation should have a pending question.");
  const model = await (await page.request.get(`/api/core/v1/orgs/${ws.organization.slug}/sites/${ws.live_site.id}/models/${state.site_model_id}`)).json();
  const probeLabel = model.spec.probes.find((p: { id: string }) => p.id === q.action.probe_id)?.label as string | undefined;
  const participant = state.participants.find((p: { id: string }) => p.id === q.action.participant_id);
  if (!probeLabel || !participant) throw new Error("The pending question should match its model and person.");
  const who = participant.display_name;
  await page.getByRole("button", { name: "Participant links" }).first().click();
  const row = page.getByRole("dialog", { name: "Participant links" }).getByRole("listitem").filter({ hasText: who });
  await row.getByRole("button", { name: "Create link" }).click();
  const joinUrl = (await row.getByRole("link").getAttribute("href")) as string;
  await page.keyboard.press("Escape");
  const phone = await openParticipant(browser, joinUrl);
  await answerTruthfully(phone, q.text, probeLabel, false);

  let current = await readState();
  await expect.poll(async () => {
    current = await readState();
    return current.questions_asked > state.questions_asked || finished(current.status);
  }).toBe(true);
  for (let answered = 1; answered < 20 && !finished(current.status); answered++) {
    const question = current.pending_question ?? current.pending_questions?.[0] ?? null;
    if (!question) {
      await expect.poll(async () => {
        current = await readState();
        return finished(current.status) || Boolean(current.pending_question) || Boolean(current.pending_questions?.length);
      }).toBe(true);
      continue;
    }
    const label = model.spec.probes.find((p: { id: string }) => p.id === question.action.probe_id)?.label as string | undefined;
    if (!label) throw new Error("The model should include the pending question's check.");
    const before = current.questions_asked;
    await answerTruthfully(phone, question.text, label, false);
    await expect.poll(async () => {
      current = await readState();
      return current.questions_asked > before || finished(current.status);
    }).toBe(true);
  }
  expect(finished(current.status), "the practice investigation should reach a finished state").toBe(true);
  if (current.status !== "closed") {
    await expect(page.getByRole("button", { name: "Reveal ground truth" })).toBeVisible();
    await page.getByRole("button", { name: "Reveal ground truth" }).click();
    const reveal = page.getByRole("dialog", { name: "Reveal the ground truth?" });
    await reveal.getByRole("button", { name: "Reveal", exact: true }).click();
  }
  await expect.poll(async () => (current = await readState()).status).toBe("closed");
  await phone.context().close();

  // The revealed answer now appears on the same person's track record in the People page.
  await page.goto(`${base}/people?site=${ws.live_site.id}`);
  const ravi = page.getByRole("listitem").filter({ hasText: "Ravi" });
  await expect(ravi.getByText(/\d+% of \d+ answers? matched the cause found later/)).toBeVisible();

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
