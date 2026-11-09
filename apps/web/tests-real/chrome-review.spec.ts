import { expect, test, type Page } from "@playwright/test";
import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";
import { answerTruthfully, openParticipant } from "./helpers";

const output = path.resolve(process.cwd(), "../../.cache/review-shots");
let runId = "";
let steps: { label: string; path: string; width: number; documentWidth: number; screenshot: string }[] = [];
let signals: { kind: string; page: string; detail: string }[] = [];
const nonGenericPracticeCopy = /hostel|guard desk|student|nava[- ]?wifi|\bwifi\b|wi[- ]?fi|वाई.?फ़ाई|वाय-?फाय|ip test page|bookmark|\bont\b|\bpon\b|\bidf\b|db[- ]?c2|\bisp\b|\bdhcp\b|\bdns\b|\bcctv\b|\bnvr\b|\bpoe\b|\bhvac\b|access point|\brack\b|main-1|c2-[57]|\bgateway\b/i;

function safeUrl(value: string) {
  try {
    const url = new URL(value);
    url.pathname = url.pathname.replace(/\/(invite|j|join)\/[^/]+/g, "/$1/[token]");
    return `${url.origin}${url.pathname}`;
  } catch {
    return value;
  }
}

function watch(page: Page) {
  page.on("console", (message) => {
    if (message.type() === "error") signals.push({ kind: "console", page: safeUrl(page.url()), detail: message.text() });
  });
  page.on("pageerror", (error) => signals.push({ kind: "pageerror", page: safeUrl(page.url()), detail: error.message }));
  page.on("requestfailed", (request) =>
    signals.push({ kind: "requestfailed", page: safeUrl(page.url()), detail: `${request.method()} ${safeUrl(request.url())}: ${request.failure()?.errorText ?? "failed"}` }),
  );
  page.on("response", (response) => {
    if (response.status() >= 400) {
      signals.push({ kind: "http", page: safeUrl(page.url()), detail: `${response.status()} ${safeUrl(response.url())}` });
    }
  });
}

async function capture(page: Page, label: string) {
  await page.evaluate(() => document.fonts.ready.then(() => true));
  await page.evaluate(async () => {
    await new Promise<void>((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve())));
    const active = document.documentElement
      .getAnimations({ subtree: true })
      .filter((animation) => animation.playState === "running" && animation.effect?.getTiming().iterations !== Infinity);
    await Promise.all(active.map((animation) => animation.finished.catch(() => undefined)));
  });
  const original = page.viewportSize() ?? { width: 1440, height: 900 };
  const file = (width: number) => path.join(output, `${runId}-${label}-${width}.png`);

  await page.screenshot({ path: file(original.width) });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.waitForTimeout(80);
  const layout = await page.evaluate(() => {
    // On setup pages the brand and the skip button share one header; they must not touch at phone width.
    const header = document.querySelector("header");
    const skip = header ? [...header.querySelectorAll("button")].find((b) => /skip setup/i.test(b.textContent ?? "")) : undefined;
    const brand = header?.querySelector("svg")?.parentElement?.getBoundingClientRect();
    return {
    width: innerWidth,
    headerGap: skip && brand ? Math.round(skip.getBoundingClientRect().left - brand.right) : null,
    documentWidth: document.documentElement.scrollWidth,
    offenders: [...document.body.querySelectorAll("*")]
      .filter((element) => {
        // Content inside a scroll box does not widen the page, except absolutely positioned
        // content, which escapes a scroll box that is not itself positioned.
        if (["absolute", "fixed"].includes(getComputedStyle(element).position)) return true;
        let parent = element.parentElement;
        while (parent && parent !== document.body) {
          const css = getComputedStyle(parent);
          if (["auto", "scroll", "hidden", "clip"].includes(css.overflowX)) return false;
          parent = parent.parentElement;
        }
        return true;
      })
      .map((element) => {
        const rect = element.getBoundingClientRect();
        return {
          tag: element.tagName,
          className: typeof element.className === "string" ? element.className : "",
          text: element.textContent?.trim().slice(0, 60),
          left: Math.round(rect.left),
          right: Math.round(rect.right),
          width: Math.round(rect.width),
        };
      })
      .filter((element) => element.width > 0 && element.right > innerWidth + 1)
      .sort((a, b) => b.right - a.right)
      .slice(0, 8),
    };
  });
  const phoneShot = file(390);
  const desktopScrollY = await page.evaluate(() => window.scrollY);
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.evaluate(() => new Promise<void>((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));
  await page.screenshot({ path: phoneShot });
  steps.push({ label, path: safeUrl(page.url()), width: layout.width, documentWidth: layout.documentWidth, screenshot: path.relative(path.resolve(process.cwd(), "../.."), phoneShot) });
  if (layout.headerGap !== null) expect(layout.headerGap, `${label} header items touch at 390 px`).toBeGreaterThanOrEqual(8);
  expect(layout.documentWidth, `${label} overflows at 390 px: ${JSON.stringify(layout.offenders)}`).toBeLessThanOrEqual(390);
  await page.setViewportSize(original);
  await page.evaluate((y) => window.scrollTo(0, y), desktopScrollY);
}

test.beforeEach(async ({ page }, info) => {
  runId = `${Date.now()}-${info.workerIndex}`;
  steps = [];
  signals = [];
  mkdirSync(output, { recursive: true });
  watch(page);
});

test.afterEach(async ({}, info) => {
  mkdirSync(output, { recursive: true });
  writeFileSync(path.join(output, `${runId}-network.json`), JSON.stringify({ title: info.title, steps, signals }, null, 2), "utf8");
});

test("real Chrome review: first-time owner can finish setup on a phone", async ({ page, browser }) => {
  test.setTimeout(240_000);
  await page.goto("/");
  await capture(page, "landing");

  await page.getByRole("link", { name: /Open the console/ }).first().click();
  await expect(page.getByRole("link", { name: "Continue with Google" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Log in", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Log in", exact: true })).toHaveCSS("background-color", "rgb(255, 252, 247)");
  await capture(page, "sign-in");
  await page.keyboard.press("Tab");
  expect(await page.evaluate(() => document.activeElement !== document.body)).toBeTruthy();

  await page.getByRole("link", { name: "Continue with Google" }).click();
  await expect(page.getByRole("heading", { name: "Pramana local mock sign-in" })).toBeVisible();
  await capture(page, "mock-google");
  const state = new URL(page.url()).searchParams.get("state");
  expect(state).toBeTruthy();
  await page.goto(`/api/core/v1/auth/google/callback?error=access_denied&state=${encodeURIComponent(state as string)}`);
  await expect(page).toHaveURL(/\/login\?error=cancelled$/);
  await expect(page.getByText("Google sign-in was cancelled. You can try again.")).toBeVisible();
  await capture(page, "sign-in-cancelled");

  const stamp = Date.now();
  await page.goto("/login");
  await page.getByRole("link", { name: "Continue with Google" }).click();
  await page.getByRole("textbox", { name: "Subject", exact: true }).fill(`chrome-owner-${stamp}`);
  await page.getByRole("textbox", { name: "Email", exact: true }).fill(`chrome-owner-${stamp}@gmail.com`);
  await page.getByRole("textbox", { name: "Name", exact: true }).fill("मयूरी कुलकर्णी");
  await page.getByRole("button", { name: "Continue with mock account" }).click();
  await expect(page).toHaveURL(/\/onboarding\/welcome$/);
  await expect(page.getByRole("heading", { name: "Find out what is wrong by asking the people who are there" })).toBeVisible();
  await capture(page, "onboarding-welcome");

  await page.getByRole("button", { name: "Get started" }).click();
  await expect(page).toHaveURL(/\/onboarding\/survey$/);
  await capture(page, "onboarding-survey-empty");
  await expect(page.getByRole("button", { name: "Continue", exact: true })).toBeEnabled();

  await page.getByRole("button", { name: "I run facilities or maintenance" }).click();
  await page.getByRole("button", { name: "Hospital or clinic" }).click();
  await page.getByRole("button", { name: "One", exact: true }).click();
  await page.getByRole("button", { name: "Water supply" }).click();
  await page.getByRole("button", { name: "Hindi" }).click();
  await page.getByRole("button", { name: "Marathi" }).click();
  await expect(page.getByRole("button", { name: "Continue", exact: true })).toBeEnabled();
  await capture(page, "onboarding-survey-selected");
  await page.goBack();
  await expect(page).toHaveURL(/\/onboarding\/welcome$/);
  await capture(page, "onboarding-browser-back");
  await page.goForward();
  await expect(page).toHaveURL(/\/onboarding\/survey$/);
  await page.reload();
  await expect(page.getByRole("button", { name: "Water supply" })).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByRole("button", { name: "Marathi" })).toHaveAttribute("aria-pressed", "true");
  await capture(page, "onboarding-survey-restored");

  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await expect(page).toHaveURL(/\/onboarding\/org$/);
  await expect(page.locator("main")).toContainText("guided example and a blank site to describe");
  await expect(page.locator("main")).not.toContainText(/hospital or clinic|hostel/i);
  await capture(page, "onboarding-workspace-empty");
  const name = page.getByLabel("Workspace name");
  await name.fill("प्रशासन कार्यालय ".repeat(24));
  expect((await name.inputValue()).length).toBeLessThanOrEqual(120);
  await capture(page, "onboarding-workspace-long-marathi");
  const longHindiName = "कार्यालय ".repeat(40);
  await name.fill(longHindiName);
  expect((await name.inputValue()).length).toBeLessThanOrEqual(120);
  await capture(page, "onboarding-workspace-long-hindi");
  await page.getByRole("button", { name: "Create workspace" }).dblclick();
  await expect(page).toHaveURL(/\/onboarding\/sandbox$/);
  const account = await page.request.get("/api/core/v1/me");
  expect((await account.json()).memberships).toHaveLength(1);
  await expect(page.locator("main")).toContainText("A simulated site has a hidden fault.");
  await expect(page.locator("main")).not.toContainText(/hostel/i);
  await capture(page, "onboarding-sandbox");

  await page.getByRole("link", { name: "Start a practice investigation" }).click();
  await expect(page).toHaveURL(/\/app\/.+\/investigations\/new\?practice=1$/);
  await expect(page.getByRole("checkbox", { name: /Include .*\(simulated\)/ }).first()).toBeVisible();
  await expect(page.getByText("Site colleague (simulated)", { exact: true })).toBeVisible();
  await expect(page.locator("main")).not.toContainText(/\b(student|guard|electrician|it_tech|housekeeping)\b/i);
  await expect(page.getByRole("combobox", { name: "Hidden fault" })).toBeVisible();
  await expect(page.locator("main")).not.toContainText(/hostel/i);
  await capture(page, "practice-investigation-new");
  await page.getByLabel("What is wrong, in the reporter's words").fill("Internet access is not working");
  await page.getByRole("button", { name: "Start investigation" }).click();
  await expect(page).toHaveURL(/\/app\/.+\/investigations\/inv_[0-9A-HJKMNP-TV-Z]{26}$/);
  await expect(page.getByRole("heading", { name: "Internet access is not working" })).toBeVisible();
  await expect(page.getByText("Live updates", { exact: true })).toBeVisible();
  await capture(page, "practice-investigation-started");

  const workspaceSlug = new URL(page.url()).pathname.split("/")[2];
  const investigationId = new URL(page.url()).pathname.split("/").at(-1) as string;
  const readState = async () =>
    (await (await page.request.get(`/api/core/v1/orgs/${workspaceSlug}/investigations/${investigationId}`)).json()) as {
      status: string;
      questions_asked: number;
      pending_question: { text: string; action: { participant_id: string; probe_id: string } } | null;
      participants: { id: string; display_name: string }[];
      site_id: string;
      site_model_id: string;
      ground_truth: { correct: boolean | null; reveal: { commitment_verified: boolean } } | null;
    };
  let practiceState = await readState();
  const model = await (
    await page.request.get(
      `/api/core/v1/orgs/${workspaceSlug}/sites/${practiceState.site_id}/models/${practiceState.site_model_id}`,
    )
  ).json();
  const practiceCopy = [
    model.spec.title,
    ...model.spec.roles.map((role: { label: string }) => role.label),
    ...model.spec.locations.map((location: { label: { en: string } }) => location.label.en),
    ...model.spec.components.map((component: { label: string }) => component.label),
    ...model.spec.components.flatMap((component: { failure_modes: { label: string }[] }) => component.failure_modes.map((failure) => failure.label)),
    ...model.spec.probes.flatMap((probe: { label: string; templates: Record<string, string> }) => [probe.label, ...Object.values(probe.templates)]),
    ...model.spec.decision_classes.map((decision: { label: string }) => decision.label),
    ...model.spec.presence_tokens.flatMap((token: { label: string; templates: Record<string, string> }) => [token.label, ...Object.values(token.templates)]),
  ].join(" ");
  expect(practiceCopy).not.toMatch(nonGenericPracticeCopy);
  await expect(page.locator("main")).not.toContainText(/\(simulated\) (student|guard|electrician|it_tech|housekeeping)\b/i);
  const phones = new Map<string, Page>();
  async function phoneFor(participantId: string) {
    const found = phones.get(participantId);
    if (found) return found;
    await page.getByRole("button", { name: "Participant links" }).first().click();
    const person = practiceState.participants.find((item) => item.id === participantId);
    expect(person).toBeTruthy();
    const row = page
      .getByRole("dialog", { name: "Participant links" })
      .getByRole("listitem")
      .filter({ hasText: person!.display_name });
    await row.getByRole("button", { name: "Create link" }).click();
    const url = (await row.getByRole("link").getAttribute("href")) as string;
    await page.keyboard.press("Escape");
    const phone = await openParticipant(browser, url);
    watch(phone);
    phones.set(participantId, phone);
    return phone;
  }

  let answered = 0;
  while (practiceState.pending_question && answered < 40) {
    const question = practiceState.pending_question;
    const phone = await phoneFor(question.action.participant_id);
    const probeLabel = model.spec.probes.find((probe: { id: string }) => probe.id === question.action.probe_id)?.label;
    expect(probeLabel).toBeTruthy();
    await expect(phone.getByRole("heading", { level: 1 })).toHaveText(question.text);
    await expect(phone.getByRole("button", { name: "Accept", exact: true })).toHaveCSS("background-color", "rgb(255, 252, 247)");
    await expect(phone.locator("main")).not.toContainText(nonGenericPracticeCopy);
    await phone.screenshot({ path: path.join(output, `${runId}-practice-participant-pending-${answered}-390.png`) });
    await expect(phone.locator("main")).not.toContainText(/hostel/i);
    const before = practiceState.questions_asked;
    await answerTruthfully(phone, question.text, probeLabel, false);
    answered++;
    await expect.poll(async () => {
      practiceState = await readState();
      return practiceState.questions_asked > before || !practiceState.pending_question;
    }).toBe(true);
  }
  expect(["decided", "abstained"]).toContain(practiceState.status);
  expect(answered).toBeGreaterThan(0);
  await capture(page, "practice-investigation-decided");
  await Promise.all(Array.from(phones.values(), (phone) => phone.context().close()));
  await page.getByRole("button", { name: "Reveal ground truth" }).first().click();
  await page.getByRole("dialog").getByRole("button", { name: /Reveal/ }).click();
  await expect.poll(async () => (practiceState = await readState()).status).toBe("closed");
  expect(practiceState.ground_truth?.reveal.commitment_verified).toBe(true);
  expect([true, false, null]).toContain(practiceState.ground_truth?.correct);
  await expect(page.getByText("Updates stopped: investigation closed")).toBeVisible();
  await capture(page, "practice-investigation-revealed");
  await page.goto("/onboarding/sandbox");
  await expect(page).toHaveURL(/\/onboarding\/sandbox$/);

  await page.getByRole("button", { name: "Skip, I will try it later" }).click();
  await expect(page).toHaveURL(/\/onboarding\/site$/);
  await expect(page.locator("main")).toContainText("Pramana checks your site description before you publish it.");
  await capture(page, "onboarding-site");
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page).toHaveURL(/\/onboarding\/people$/);
  await expect(page.locator("main")).toContainText("Add facilities staff, technicians and the people who are there each day.");
  await expect(page.locator("main")).not.toContainText(/guards|judges your model/i);
  await capture(page, "onboarding-people");
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page).toHaveURL(/\/onboarding\/test_call$/);
  await capture(page, "onboarding-test-call");
  await page.getByRole("button", { name: "Finish setup" }).click();
  await expect(page).toHaveURL(/\/app\/.+$/);
  await expect(page.locator('[aria-label="Loading your home"]')).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Your sites" })).toBeVisible();
  await expect(page.getByText("2 of 5 steps done. Next: describe your own site and publish it.")).toBeVisible();
  await expect(page.getByText(/2 sites in this workspace\./)).toBeVisible();
  await expect(page.getByText("Still narrowing down the cause")).toHaveCount(0);
  await capture(page, "workspace-home");

  const base = new URL(page.url()).pathname;
  await page.goto(`${base}/sites`);
  await expect(page.getByRole("heading", { name: "Sites" })).toBeVisible();
  const practice = page.getByRole("list").getByRole("listitem").filter({ hasText: "Practice" });
  await expect(practice).toContainText("A simulated site for guided practice runs.");
  await expect(practice).toContainText("Practice site (simulated)");
  await expect(practice).not.toContainText(/hostel/i);
  await capture(page, "workspace-sites");
  await practice.getByRole("link").click();
  await expect(page.getByRole("heading", { name: "Practice site (simulated)" })).toBeVisible();
  await expect(page.getByText("A simulated site. Use it to see an investigation end to end before modelling your own site.")).toBeVisible();
  await expect(page.locator("main")).not.toContainText(/hostel/i);
  await capture(page, "workspace-practice-site");

  await page.goto("/review-page-that-does-not-exist");
  await expect(page.getByRole("heading", { name: "Nothing was observed here" })).toBeVisible();
  await capture(page, "page-not-found");

  expect(signals.filter((x) => x.kind === "pageerror")).toEqual([]);
});

test("real Chrome review: drafts warn about changes in another tab", async ({ page, context }) => {
  test.setTimeout(120_000);
  const who = `draft-review-${Date.now()}`;
  await page.goto("/api/core/v1/auth/google/start?next=/app/account");
  await page.getByRole("textbox", { name: "Subject", exact: true }).fill(who);
  await page.getByRole("textbox", { name: "Email", exact: true }).fill(`${who}@gmail.com`);
  await page.getByRole("button", { name: "Continue with mock account" }).click();
  await expect(page).toHaveURL(/\/app\/account$/);
  const made = await page.request.post("/api/core/v1/orgs", {
    headers: { "X-Pramana-CSRF": "1", "Idempotency-Key": `${who}-workspace` },
    data: { name: "Draft review", kind: "office" },
  });
  expect(made.status()).toBe(201);
  const ws = await made.json();
  const path = `/app/${ws.organization.slug}/sites/${ws.live_site.id}`;
  await page.goto(path);
  await page.getByRole("button", { name: /Office water supply/ }).click();
  await expect(page.getByRole("heading", { name: "Draft, version 1" })).toBeVisible();
  // On a laptop screen the whole equipment table fits without scrolling sideways.
  const table = page.getByRole("table").first();
  expect(await table.evaluate((t) => t.parentElement!.scrollWidth - t.parentElement!.clientWidth)).toBeLessThanOrEqual(0);
  await capture(page, "draft-template");
  const second = await context.newPage();
  watch(second);
  await second.goto(path);
  await expect(second.getByRole("heading", { name: "Draft, version 1" })).toBeVisible();
  await page.getByRole("tab", { name: /Equipment/ }).click();
  await second.getByRole("tab", { name: /Equipment/ }).click();
  await second.getByRole("textbox", { name: "Equipment name" }).first().fill("Second tab change");
  await page.getByRole("textbox", { name: "Equipment name" }).first().fill("First tab change");
  await page.getByRole("button", { name: "Save draft" }).click();
  await expect(page.getByText("Saved", { exact: true })).toBeVisible();
  await second.getByRole("button", { name: "Save draft" }).click();
  await expect(second.getByText("Someone else changed this draft. Reload it to see their version.")).toBeVisible();
  await capture(second, "draft-conflict");
  const draftPath = `/api/core/v1/orgs/${ws.organization.slug}/sites/${ws.live_site.id}/draft`;
  const current = await (await page.request.get(draftPath)).json();
  const missing = await page.request.post(draftPath, {
    headers: { "X-Pramana-CSRF": "1", "Idempotency-Key": `${who}-missing-match` },
    data: { description: current.description },
  });
  expect(missing.status()).toBe(428);
  await second.close();
  await page.getByRole("button", { name: "Discard draft" }).click();
  await expect(page.getByRole("button", { name: "Start from scratch" })).toBeVisible();
  await capture(page, "draft-discarded");
  await page.getByRole("button", { name: "Start from scratch" }).click();
  await expect(page.getByRole("heading", { name: "Draft, version 1" })).toBeVisible();
  await capture(page, "draft-from-scratch");
});

test("real Chrome review: an owner describes, checks and publishes a site", async ({ page }) => {
  test.setTimeout(180_000);
  const who = `builder-review-${Date.now()}`;
  await page.goto("/api/core/v1/auth/google/start?next=/app/account");
  await page.getByRole("textbox", { name: "Subject", exact: true }).fill(who);
  await page.getByRole("textbox", { name: "Email", exact: true }).fill(`${who}@gmail.com`);
  await page.getByRole("button", { name: "Continue with mock account" }).click();
  const made = await page.request.post("/api/core/v1/orgs", {
    headers: { "X-Pramana-CSRF": "1", "Idempotency-Key": `${who}-workspace` },
    data: { name: "Builder review", kind: "office" },
  });
  expect(made.status()).toBe(201);
  const ws = await made.json();
  const sitePath = `/app/${ws.organization.slug}/sites/${ws.live_site.id}`;
  await page.goto(sitePath);
  await expect(page.getByRole("heading", { name: "Describe this site" })).toBeVisible();
  await capture(page, "builder-start-options");

  await page.getByRole("button", { name: /Office water supply/ }).click();
  await expect(page.getByRole("heading", { name: "Draft, version 1" })).toBeVisible();
  await capture(page, "builder-template-draft");
  await page.getByRole("button", { name: "Check this model" }).click();
  await expect(page.getByText("Ready to publish")).toBeVisible({ timeout: 60_000 });
  await capture(page, "builder-health-ready");
  await page.getByRole("button", { name: "Publish version 1" }).click();
  await expect(page.getByText("Version 1 is published")).toBeVisible();
  await capture(page, "builder-published");

  await page.getByRole("button", { name: "Edit as a new version" }).click();
  await expect(page.getByRole("heading", { name: "Draft, version 2" })).toBeVisible();
  await page.getByRole("tab", { name: /Equipment/ }).click();
  await capture(page, "builder-equipment");
  const upload = (name: string, body: string) =>
    page.getByLabel("Import equipment from CSV").setInputFiles({ name, mimeType: "text/csv", buffer: Buffer.from(body) });
  await upload("review-bad.csv", "name,type,location\nBooster,not_a_type,Plant room\n");
  await expect(page.getByText('Row 2: unknown equipment type "not_a_type".')).toBeVisible();
  await capture(page, "builder-csv-error");
  await upload("review-good.csv", "name,type,location,floor,depends_on\nBooster unit,pump,Plant room,1,mains power\n");
  await expect(page.getByText(/Imported: 1 added/)).toBeVisible();
  await capture(page, "builder-csv-imported");
  await page.getByRole("button", { name: "Save draft" }).click();
  await expect(page.getByText("Saved", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Discard draft" }).click();
  await expect(page.getByRole("button", { name: "Start from scratch" })).toBeVisible();
  await capture(page, "builder-draft-discarded");

  await page.getByRole("button", { name: "Start from scratch" }).click();
  await expect(page.getByRole("heading", { name: "Draft, version 2" })).toBeVisible();
  const siteName = page.getByRole("textbox", { name: "Site name" });
  await expect(siteName).toHaveValue("Your first building");
  await capture(page, "builder-start-from-scratch");
  await siteName.fill("Reception lights");
  await page.getByRole("button", { name: "Save draft" }).click();
  await expect(page.getByText("Saved", { exact: true })).toBeVisible();
  await capture(page, "builder-scratch-description-saved");
  await page.getByRole("button", { name: "Check this model" }).click();
  await expect(page.getByText("Ready to publish")).toBeVisible({ timeout: 60_000 });
  await capture(page, "builder-scratch-health-ready");
  await page.getByRole("button", { name: "Publish version 2" }).click();
  await expect(page.getByText("Version 2 is published")).toBeVisible();
  await capture(page, "builder-scratch-published");
});

test("real Chrome review: invitations can be withdrawn or joined from welcome", async ({ page }) => {
  test.setTimeout(120_000);
  const stamp = Date.now();
  const owner = `review-owner-${stamp}`;
  const invitee = `review-invitee-${stamp}`;
  const withdrawn = `review-withdrawn-${stamp}`;
  async function signIn(who: string, next: string) {
    await page.goto(`/api/core/v1/auth/google/start?next=${encodeURIComponent(next)}`);
    await page.getByRole("textbox", { name: "Subject", exact: true }).fill(who);
    await page.getByRole("textbox", { name: "Email", exact: true }).fill(`${who}@gmail.com`);
    await page.getByRole("button", { name: "Continue with mock account" }).click();
  }
  async function logout() {
    const response = await page.request.post("/api/core/v1/auth/logout", { headers: { "X-Pramana-CSRF": "1" } });
    expect(response.ok()).toBeTruthy();
  }
  await signIn(owner, "/app/account");
  const made = await page.request.post("/api/core/v1/orgs", {
    headers: { "X-Pramana-CSRF": "1", "Idempotency-Key": `${owner}-workspace` },
    data: { name: "Invitation review", kind: "hospital" },
  });
  expect(made.status()).toBe(201);
  const ws = await made.json();
  const base = `/app/${ws.organization.slug}`;
  await page.goto(`${base}/settings`);
  await page.getByLabel("Their email address").fill(`${withdrawn}@gmail.com`);
  await page.getByRole("button", { name: "Create invitation link" }).click();
  const link = await page.locator("code").filter({ hasText: "/invite/org_" }).innerText();
  const pending = page.getByRole("list", { name: "Invitations" }).getByRole("listitem").filter({ hasText: `${withdrawn}@gmail.com` });
  await pending.getByRole("button", { name: "Withdraw" }).click();
  await expect(pending.getByText("revoked")).toBeVisible();
  await expect(page.locator("code").filter({ hasText: "/invite/org_" })).toHaveCount(0);
  await capture(page, "invitation-withdrawn");
  await page.getByLabel("Their email address").fill(`${invitee}@gmail.com`);
  await page.getByRole("button", { name: "Create invitation link" }).click();
  await expect(page.getByRole("list", { name: "Invitations" }).getByText("pending")).toBeVisible();
  const activeLink = await page.locator("code").filter({ hasText: "/invite/org_" }).innerText();
  await logout();
  await signIn(`review-wrong-${stamp}`, new URL(activeLink).pathname);
  await page.getByRole("button", { name: "Accept invitation" }).click();
  await expect(page.locator("main").getByRole("alert")).toContainText("this invitation is for");
  await expect(page.getByRole("button", { name: "Use another account" })).toBeVisible();
  await capture(page, "invitation-wrong-account");
  await logout();
  await signIn(withdrawn, new URL(link).pathname);
  await page.getByRole("button", { name: "Accept invitation" }).click();
  await expect(page.locator("main").getByRole("alert")).toContainText("withdrawn");
  await expect(page.getByRole("button", { name: "Invitation unavailable" })).toBeDisabled();
  await capture(page, "invitation-withdrawn-error");
  await logout();
  await signIn(invitee, "/onboarding/welcome");
  await expect(page.getByRole("heading", { name: "You have been invited" })).toBeVisible();
  await capture(page, "invitation-welcome");
  await page.getByRole("region", { name: "Invitations" }).getByRole("button", { name: "Join" }).click();
  await expect(page).toHaveURL(new RegExp(`${base}$`));
  await expect(page.locator('[aria-label="Loading your home"]')).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Your sites" })).toBeVisible();
  await capture(page, "invitation-joined");
  await logout();
  await signIn(owner, `${base}/settings`);
  const row = page.getByRole("list", { name: "Members" }).getByRole("listitem").filter({ hasText: `${invitee}@gmail.com` });
  await row.getByRole("button", { name: "Remove" }).click();
  await expect(row).toHaveCount(0);
  await logout();
  await signIn(invitee, base);
  await expect(page.getByText("You do not have access to this workspace")).toBeVisible();
  await capture(page, "removed-user");
  await page.goto("/app/account");
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page).toHaveURL(/\/(login|$)/);
  await capture(page, "signed-out");
});

test("real Chrome review: terminal invitations cannot be accepted", async ({ page }) => {
  const stamp = Date.now();
  const who = `review-expired-${stamp}`;
  await page.goto("/api/core/v1/auth/google/start?next=/app/account");
  await page.getByRole("textbox", { name: "Subject", exact: true }).fill(who);
  await page.getByRole("textbox", { name: "Email", exact: true }).fill(`${who}@gmail.com`);
  await page.getByRole("button", { name: "Continue with mock account" }).click();
  const errors = [
    { token: "expired", code: "INVITATION_EXPIRED", status: 410, message: "this invitation has expired" },
    { token: "missing", code: "INVITATION_NOT_FOUND", status: 404, message: "this invitation could not be found" },
    { token: "revoked", code: "INVITATION_REVOKED", status: 410, message: "this invitation was withdrawn" },
    { token: "used", code: "INVITATION_USED", status: 410, message: "this invitation has already been used" },
  ];
  let activeError = errors[0];
  await page.route("**/api/core/v1/invitations/accept", (route) =>
    route.fulfill({
      status: activeError.status,
      contentType: "application/problem+json",
      json: { error: { code: activeError.code, message: activeError.message } },
    }),
  );
  for (const error of errors) {
    activeError = error;
    await page.goto(`/invite/org_${error.token}-review-token`);
    await page.getByRole("button", { name: "Accept invitation" }).click();
    await expect(page.locator("main").getByRole("alert")).toHaveText(error.message);
    await expect(page.getByRole("button", { name: "Invitation unavailable" })).toBeDisabled();
    await capture(page, `invitation-${error.token}`);
  }
});

test("real Chrome review: a returning owner finds their workspace and an expired session is refused", async ({ page, context }) => {
  const stamp = Date.now();
  const who = `review-returning-${stamp}`;
  const signIn = async (next: string) => {
    await page.goto(`/api/core/v1/auth/google/start?next=${encodeURIComponent(next)}`);
    await page.getByRole("textbox", { name: "Subject", exact: true }).fill(who);
    await page.getByRole("textbox", { name: "Email", exact: true }).fill(`${who}@gmail.com`);
    await page.getByRole("button", { name: "Continue with mock account" }).click();
  };
  await signIn("/app/account");
  const made = await page.request.post("/api/core/v1/orgs", {
    headers: { "X-Pramana-CSRF": "1", "Idempotency-Key": `${who}-workspace` },
    data: { name: "Returning owner", kind: "office" },
  });
  expect(made.status()).toBe(201);
  const ws = await made.json();
  const base = `/app/${ws.organization.slug}`;
  await page.goto(base);
  await expect(page.getByRole("heading", { name: "Your sites" })).toBeVisible();
  await capture(page, "returning-workspace");

  await page.request.post("/api/core/v1/auth/logout", { headers: { "X-Pramana-CSRF": "1" } });
  await signIn(base);
  await expect(page).toHaveURL(new RegExp(`${base}$`));
  await expect(page.getByRole("heading", { name: "Your sites" })).toBeVisible();
  await capture(page, "returning-workspace-restored");

  const session = (await context.cookies()).find((cookie) => cookie.name === "pramana_session");
  expect(session).toBeTruthy();
  await context.addCookies([{ ...session!, expires: Math.floor(Date.now() / 1000) - 1 }]);
  await page.goto(base);
  await expect(page).toHaveURL(/\/login\?next=/);
  await capture(page, "returning-session-expired");
});

test("real Chrome review: offline messages do not expose internal setup details", async ({ page }) => {
  test.setTimeout(90_000);
  const who = `review-offline-${Date.now()}`;
  await page.route("**/api/core/health", (route) => route.abort());
  await page.goto("/api/core/v1/auth/google/start?next=/app/account");
  await page.getByRole("textbox", { name: "Subject", exact: true }).fill(who);
  await page.getByRole("textbox", { name: "Email", exact: true }).fill(`${who}@gmail.com`);
  await page.getByRole("button", { name: "Continue with mock account" }).click();
  const made = await page.request.post("/api/core/v1/orgs", {
    headers: { "X-Pramana-CSRF": "1", "Idempotency-Key": `${who}-workspace` },
    data: { name: "Offline review", kind: "office" },
  });
  expect(made.status()).toBe(201);
  const ws = await made.json();
  await page.route(`**/api/core/v1/orgs/${ws.organization.slug}/home`, (route) => route.abort());
  await page.goto(`/app/${ws.organization.slug}`);
  await expect(page.getByRole("complementary").getByText("Offline", { exact: true })).toBeVisible();
  await expect(page.getByText("Pramana cannot be reached").first()).toBeVisible();
  await expect(page.locator("body")).not.toContainText(/uv run|scripts\/dev\.py|127\.0\.0\.1:\d+/i);
  await capture(page, "offline-help");
});

test("real Chrome review: a URL for another account's workspace shows no data", async ({ page }) => {
  const stamp = Date.now();
  const targetOwner = `review-target-${stamp}`;
  const currentOwner = `review-current-${stamp}`;
  async function signIn(who: string) {
    await page.goto("/api/core/v1/auth/google/start?next=/app/account");
    await page.getByRole("textbox", { name: "Subject", exact: true }).fill(who);
    await page.getByRole("textbox", { name: "Email", exact: true }).fill(`${who}@gmail.com`);
    await page.getByRole("button", { name: "Continue with mock account" }).click();
  }
  async function createWorkspace(who: string) {
    const response = await page.request.post("/api/core/v1/orgs", {
      headers: { "X-Pramana-CSRF": "1", "Idempotency-Key": `${who}-workspace` },
      data: { name: `${who} workspace`, kind: "office" },
    });
    expect(response.status()).toBe(201);
    return response.json();
  }
  await signIn(targetOwner);
  const target = await createWorkspace(targetOwner);
  await page.request.post("/api/core/v1/auth/logout", { headers: { "X-Pramana-CSRF": "1" } });
  await signIn(currentOwner);
  const own = await createWorkspace(currentOwner);
  expect(target.organization.slug).not.toBe(own.organization.slug);
  await page.goto(`/app/${target.organization.slug}`);
  await expect(page.getByText("You do not have access to this workspace")).toBeVisible();
  await expect(page.locator("main")).not.toContainText(target.organization.name);
  await capture(page, "other-organization-url");
});
