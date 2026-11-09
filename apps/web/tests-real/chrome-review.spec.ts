import { expect, test, type Page } from "@playwright/test";
import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";
import { answerTruthfully, openParticipant } from "./helpers";

const output = path.resolve(process.cwd(), "../../.cache/review-shots");
let runId = "";
let steps: { label: string; path: string; width: number; documentWidth: number; screenshot: string }[] = [];
let signals: { kind: string; page: string; detail: string }[] = [];

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
  const layout = await page.evaluate(() => ({
    width: innerWidth,
    documentWidth: document.documentElement.scrollWidth,
    offenders: [...document.body.querySelectorAll("*")]
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
  }));
  const phoneShot = file(390);
  await page.screenshot({ path: phoneShot });
  steps.push({ label, path: safeUrl(page.url()), width: layout.width, documentWidth: layout.documentWidth, screenshot: path.relative(path.resolve(process.cwd(), "../.."), phoneShot) });
  expect(layout.documentWidth, `${label} overflows at 390 px: ${JSON.stringify(layout.offenders)}`).toBeLessThanOrEqual(390);
  await page.setViewportSize(original);
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
  await capture(page, "onboarding-workspace-empty");
  const name = page.getByLabel("Workspace name");
  const longHindiName = "कार्यालय ".repeat(40);
  await name.fill(longHindiName);
  expect((await name.inputValue()).length).toBeLessThanOrEqual(120);
  await capture(page, "onboarding-workspace-long-hindi");
  await page.getByRole("button", { name: "Create workspace" }).click();
  await expect(page).toHaveURL(/\/onboarding\/sandbox$/);
  await expect(page.locator("main")).toContainText("A simulated site has a hidden fault.");
  await expect(page.locator("main")).not.toContainText(/hostel/i);
  await capture(page, "onboarding-sandbox");

  await page.getByRole("link", { name: "Start a practice investigation" }).click();
  await expect(page).toHaveURL(/\/app\/.+\/investigations\/new\?practice=1$/);
  await expect(page.locator("main")).not.toContainText(/hostel/i);
  await capture(page, "practice-investigation-new");
  await page.getByLabel("What is wrong, in the reporter's words").fill("Internet access is not working");
  await page.getByRole("button", { name: "Start investigation" }).click();
  await expect(page).toHaveURL(/\/app\/.+\/investigations\/inv_[0-9A-HJKMNP-TV-Z]{26}$/);
  await expect(page.getByRole("heading", { name: "Internet access is not working" })).toBeVisible();
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
  await capture(page, "practice-investigation-revealed");
  await page.goto("/onboarding/sandbox");
  await expect(page).toHaveURL(/\/onboarding\/sandbox$/);

  await page.getByRole("button", { name: "Skip, I will try it later" }).click();
  await expect(page).toHaveURL(/\/onboarding\/site$/);
  await capture(page, "onboarding-site");
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page).toHaveURL(/\/onboarding\/people$/);
  await capture(page, "onboarding-people");
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page).toHaveURL(/\/onboarding\/test_call$/);
  await capture(page, "onboarding-test-call");
  await page.getByRole("button", { name: "Finish setup" }).click();
  await expect(page).toHaveURL(/\/app\/.+$/);
  await expect(page.locator('[aria-label="Loading your home"]')).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Your sites" })).toBeVisible();
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

  expect(signals.filter((x) => x.kind === "pageerror")).toEqual([]);
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
  await capture(page, "invitation-withdrawn");
  await page.getByLabel("Their email address").fill(`${invitee}@gmail.com`);
  await page.getByRole("button", { name: "Create invitation link" }).click();
  await expect(page.getByRole("list", { name: "Invitations" }).getByText("pending")).toBeVisible();
  await logout();
  await signIn(withdrawn, new URL(link).pathname);
  await page.getByRole("button", { name: "Accept invitation" }).click();
  await expect(page.locator("main").getByRole("alert")).toContainText("withdrawn");
  await capture(page, "invitation-withdrawn-error");
  await logout();
  await signIn(invitee, "/onboarding/welcome");
  await expect(page.getByRole("heading", { name: "You have been invited" })).toBeVisible();
  await capture(page, "invitation-welcome");
  await page.getByRole("region", { name: "Invitations" }).getByRole("button", { name: "Join" }).click();
  await expect(page).toHaveURL(new RegExp(`${base}$`));
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
