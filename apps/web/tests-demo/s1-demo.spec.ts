import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { expect, test, type BrowserContext, type Locator, type Page } from "@playwright/test";
import { answerTruthfully } from "../tests-real/helpers";

const FAST = process.env.DEMO_FAST === "1";
const RECORD_VIDEO = process.env.DEMO_VIDEO === "1";
const DISCLOSURE = "Simulated building. Gnani protocol emulator - synthetic audio";
const DESKTOP_SIZE = { width: 1920, height: 1080 };
const PHONE_SIZE = { width: 390, height: 844 };
const INVESTIGATION_EVENT_TYPES = new Set([
  "QuestionAsked",
  "ObservationRecorded",
  "DecisionReached",
  "ApprovalRequested",
  "ApprovalDecided",
  "InterventionReported",
  "VerificationResult",
  "GroundTruthRevealed",
]);

type Question = {
  id: string;
  text: string;
  action: { participant_id: string; probe_id: string; requires_move?: boolean };
};

type Participant = { id: string; display_name: string };

type RepairOption = {
  action: string;
  action_label: string;
  target: string;
  target_label: string;
  place?: string | null;
  participant_ids: string[];
  risk: string;
  reversible: boolean;
};

type Investigation = {
  id: string;
  status: string;
  questions_asked: number;
  site_id: string;
  site_model_id: string;
  sealed_commitment: string;
  participants: Participant[];
  pending_question: Question | null;
  pending_questions?: Question[];
  repair_options?: RepairOption[];
  approvals: { id: string; action: string; target: string; participant_id: string; status: string }[];
  plan: { decision_class?: string | null };
  ground_truth?: {
    correct?: boolean | null;
    reveal?: { commitment_verified?: boolean; fault_spec?: { faults?: { component_id: string; mode: string }[] } };
  } | null;
};

type Probe = { id: string; label: string };
type SiteModel = { spec: { probes: Probe[] } };
type EventEnvelope = { seq: number; type: string; payload: Record<string, unknown>; ts?: string };
type Milestone = {
  name: string;
  elapsed_ms: number;
  event_type: string;
  caption: string;
  event_match?: Record<string, unknown>;
};

async function labelDisclosure(context: BrowserContext): Promise<void> {
  await context.addInitScript((text) => {
    const id = "b7-simulation-disclosure";
    const install = () => {
      if (!document.body || document.getElementById(id)) return;
      const badge = document.createElement("div");
      badge.id = id;
      badge.setAttribute("role", "note");
      badge.textContent = text;
      badge.style.cssText = [
        "position:fixed",
        "z-index:2147483647",
        "left:0",
        "right:0",
        "bottom:0",
        "min-height:24px",
        "box-sizing:border-box",
        "display:flex",
        "align-items:center",
        "justify-content:center",
        "padding:3px 8px",
        "background:#171717",
        "color:#fff",
        "font:600 11px/1.3 system-ui,sans-serif",
        "letter-spacing:.01em",
        "text-align:center",
        "pointer-events:none",
      ].join(";");
      document.body.appendChild(badge);
      document.body.style.paddingBottom = "26px";
    };
    const observe = () => {
      const root = document.documentElement;
      if (!root) {
        document.addEventListener("DOMContentLoaded", observe, { once: true });
        return;
      }
      install();
      new MutationObserver(install).observe(root, { childList: true, subtree: true });
    };
    observe();
  }, DISCLOSURE);
}

async function showCursor(context: BrowserContext): Promise<void> {
  await context.addInitScript(() => {
    const id = "b7-recording-cursor";
    const install = () => {
      if (!document.body || document.getElementById(id)) return;
      const cursor = document.createElement("div");
      cursor.id = id;
      cursor.style.cssText =
        "position:fixed;z-index:2147483646;width:13px;height:13px;border:2px solid #fff;" +
        "border-radius:50%;background:#e5484d;box-shadow:0 1px 5px #0008;pointer-events:none;" +
        "transform:translate(-50%,-50%);left:-30px;top:-30px";
      document.body.appendChild(cursor);
      document.addEventListener("mousemove", (event) => {
        cursor.style.left = event.clientX + "px";
        cursor.style.top = event.clientY + "px";
      });
    };
    const observe = () => {
      const root = document.documentElement;
      if (!root) {
        document.addEventListener("DOMContentLoaded", observe, { once: true });
        return;
      }
      install();
      new MutationObserver(install).observe(root, { childList: true, subtree: true });
    };
    observe();
  });
}

async function allowLocalOnly(context: BrowserContext): Promise<void> {
  await context.route("**/*", async (route) => {
    const host = new URL(route.request().url()).hostname;
    if (host === "localhost" || host === "127.0.0.1" || host === "::1") {
      await route.continue();
    } else {
      await route.abort("blockedbyclient");
    }
  });
}

async function pause(ms: number): Promise<void> {
  if (!FAST) await new Promise((resolve) => setTimeout(resolve, ms));
}

// Playwright burns its own action callouts (for example "Mouse move") into recorded video.
// The recording cursor and the captions explain each step instead.
async function hideActionTitles(page: Page): Promise<void> {
  if (RECORD_VIDEO) await page.screencast.showActions({ cursor: "none", style: { title: "display: none" } });
}

async function moveTo(page: Page, locator: Locator): Promise<void> {
  if (FAST) return;
  const box = await locator.boundingBox();
  if (box) await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2, { steps: 12 });
  await pause(250);
}

async function click(page: Page, locator: Locator, settleMs = 500): Promise<void> {
  await moveTo(page, locator);
  await locator.click();
  await pause(settleMs);
}

async function mockGoogleSignIn(page: Page, subject: string, email: string, next: string): Promise<void> {
  await page.goto("/api/core/v1/auth/google/start?next=" + encodeURIComponent(next));
  await expect(page.getByRole("heading", { name: "Pramana local mock sign-in" })).toBeVisible();
  await page.getByRole("textbox", { name: "Subject" }).fill(subject);
  await page.getByRole("textbox", { name: "Email" }).fill(email);
  await page.getByRole("textbox", { name: "Workspace domain" }).fill(email.split("@")[1]);
  await click(page, page.getByRole("button", { name: "Continue with mock account" }));
}

async function readInvestigation(page: Page, org: string, id: string): Promise<Investigation> {
  const response = await page.request.get("/api/core/v1/orgs/" + org + "/investigations/" + id);
  expect(response.status(), await response.text()).toBe(200);
  return response.json() as Promise<Investigation>;
}

function pendingQuestions(state: Investigation): Question[] {
  return state.pending_questions?.length
    ? state.pending_questions
    : state.pending_question
      ? [state.pending_question]
      : [];
}

function normalizeText(value: string): string {
  return value.normalize("NFC").replace(/\s+/g, " ").trim();
}

async function nextCoreQuestion(
  page: Page,
  org: string,
  investigationId: string,
  activeStatus: string,
): Promise<{ state: Investigation; question: Question } | null> {
  let state: Investigation | null = null;
  let question: Question | null = null;
  let outcome = "waiting";
  await expect
    .poll(
      async () => {
        state = await readInvestigation(page, org, investigationId);
        question = pendingQuestions(state)[0] ?? null;
        if (state.status !== activeStatus) {
          question = null;
          outcome = "done";
          return outcome;
        }
        outcome = question ? "ready" : "waiting";
        return outcome;
      },
      { timeout: 30_000, message: "wait for the next active core question" },
    )
    .not.toBe("waiting");
  if (outcome === "done" || !question || !state) return null;
  return { state, question };
}

function eventFor(milestone: Milestone, events: EventEnvelope[]): EventEnvelope | undefined {
  return events.find((event) => {
    if (event.type !== milestone.event_type) return false;
    return Object.entries(milestone.event_match ?? {}).every(([key, value]) => {
      let actual: unknown = event.payload;
      for (const part of key.split(".")) {
        if (typeof actual !== "object" || actual === null) return false;
        actual = (actual as Record<string, unknown>)[part];
      }
      return actual === value;
    });
  });
}

test("B7: a first-time operator completes S1 with a separate approver and exact replay", async ({
  browser,
  context,
  page,
}, testInfo) => {
  test.setTimeout(360_000);
  const started = Date.now();
  const stamp = Date.now().toString() + "-" + Math.floor(Math.random() * 1_000_000);
  const operatorSubject = "b7-operator-" + stamp;
  const operatorEmail = operatorSubject + "@example.test";
  const approverSubject = "b7-approver-" + stamp;
  const approverEmail = approverSubject + "@example.test";
  const moments: Milestone[] = [];
  const pageErrors: string[] = [];
  let questionAudioCacheHit = false;
  const emulatorUrl = process.env.B7_GNANI_EMULATOR_URL;
  expect(emulatorUrl, "the local Gnani protocol emulator should be configured").toBeTruthy();
  page.on("pageerror", (error) => pageErrors.push(error.stack ?? error.message));
  await hideActionTitles(page);
  const mark = (
    name: string,
    eventType: string,
    caption: string,
    eventMatch?: Record<string, unknown>,
  ) => {
    moments.push({
      name,
      event_type: eventType,
      elapsed_ms: Date.now() - started,
      caption,
      ...(eventMatch ? { event_match: eventMatch } : {}),
    });
  };

  await labelDisclosure(context);
  await showCursor(context);
  await allowLocalOnly(context);

  const phoneContext = await browser.newContext({
    baseURL: process.env.B7_BASE_URL ?? "http://localhost:3235",
    viewport: PHONE_SIZE,
    screen: PHONE_SIZE,
    deviceScaleFactor: 1,
    isMobile: true,
    hasTouch: true,
    ...(RECORD_VIDEO ? { recordVideo: { dir: testInfo.outputDir, size: PHONE_SIZE } } : {}),
  });
  await labelDisclosure(phoneContext);
  await allowLocalOnly(phoneContext);
  const phone = await phoneContext.newPage();
  phone.on("pageerror", (error) => pageErrors.push(error.stack ?? error.message));
  await hideActionTitles(phone);
  await phone.goto("/login");

  await page.goto("/login");
  await expect(page.getByRole("link", { name: "Continue with Google" })).toBeVisible();
  await click(page, page.getByRole("link", { name: "Continue with Google" }));
  await expect(page.getByRole("heading", { name: "Pramana local mock sign-in" })).toBeVisible();
  await page.getByRole("textbox", { name: "Subject" }).fill(operatorSubject);
  await page.getByRole("textbox", { name: "Email" }).fill(operatorEmail);
  await page.getByRole("textbox", { name: "Workspace domain" }).fill(operatorEmail.split("@")[1]);
  await click(page, page.getByRole("button", { name: "Continue with mock account" }));
  const operatorSession = await page.request.get("/api/core/v1/auth/session");
  expect(await operatorSession.json()).toMatchObject({ email: operatorEmail, email_verified: true });
  await expect(page).toHaveURL(/\/onboarding\/welcome$/);
  await phoneContext.addCookies(await context.cookies());
  await phone.goto("/onboarding/welcome");
  mark("first_time_operator", "LocalMockSignIn", "A new operator signs in through the local mock.");
  await pause(1_000);

  await click(page, page.getByRole("button", { name: "Get started" }));
  await expect(page).toHaveURL(/\/onboarding\/survey$/);
  await phone.goto("/onboarding/survey");
  await click(page, page.getByRole("button", { name: "I run facilities or maintenance" }));
  await click(page, page.getByRole("button", { name: "Office", exact: true }));
  await click(page, page.getByRole("button", { name: "Water supply" }));
  await click(page, page.getByRole("button", { name: "Hindi" }));
  await pause(1_000);
  await click(page, page.getByRole("button", { name: "Continue" }));
  await expect(page).toHaveURL(/\/onboarding\/org$/);
  await phone.goto("/onboarding/org");
  const workspaceName = "B7 practice " + stamp;
  await page.getByLabel("Workspace name").fill(workspaceName);
  await pause(500);
  const workspaceCreated = page.waitForResponse(
    (response) =>
      response.request().method() === "POST" &&
      new URL(response.url()).pathname === "/api/core/v1/orgs",
  );
  await click(page, page.getByRole("button", { name: "Create workspace" }));
  const createResponse = await workspaceCreated;
  expect(
    createResponse.ok(),
    "workspace creation returned " + createResponse.status() + ": " + (await createResponse.text()),
  ).toBe(true);
  await expect(page).toHaveURL(/\/onboarding\/sandbox$/);
  const practiceHref = await page.getByRole("link", { name: "Start a practice investigation" }).getAttribute("href");
  expect(practiceHref).toBeTruthy();
  const org = new URL(practiceHref as string, page.url()).pathname.split("/")[2];
  const base = "/app/" + org;
  await phone.goto("/onboarding/sandbox");
  await pause(1_000);
  await click(page, page.getByRole("button", { name: "Skip, I will try it later" }));
  await expect(page).toHaveURL(/\/onboarding\/site$/);
  await click(page, page.getByRole("button", { name: "Skip setup for now" }));
  await expect(page).toHaveURL(new RegExp(base + "$"));
  await phone.goto(base);
  mark("workspace_ready", "WorkspaceCreated", "The operator's simulated practice site is ready.");
  await pause(1_000);

  // The email service is disabled. Only the local invitation link is used.
  await page.goto(base + "/settings");
  await expect(page.getByLabel("Their email address")).toBeVisible();
  await page.getByLabel("Their email address").fill(approverEmail);
  const operatorRole = page.getByRole("checkbox", { name: /Operator/ });
  if (await operatorRole.isChecked()) await operatorRole.uncheck();
  const approverRole = page.getByRole("checkbox", { name: /Approver/ });
  if (!(await approverRole.isChecked())) await approverRole.check();
  await pause(750);
  await click(page, page.getByRole("button", { name: "Create invitation link" }));
  const inviteCode = page.locator("code").filter({ hasText: "/invite/org_" });
  await expect(inviteCode).toBeVisible();
  const invitePath = new URL(await inviteCode.innerText(), page.url()).pathname;
  await pause(1_000);

  const approverContext = await browser.newContext({
    baseURL: process.env.B7_BASE_URL ?? "http://localhost:3235",
    viewport: DESKTOP_SIZE,
    deviceScaleFactor: 1,
  });
  await labelDisclosure(approverContext);
  await allowLocalOnly(approverContext);
  const approverPage = await approverContext.newPage();
  approverPage.on("pageerror", (error) => pageErrors.push(error.stack ?? error.message));
  await mockGoogleSignIn(approverPage, approverSubject, approverEmail, "/app/account");
  await expect(approverPage).toHaveURL(/\/app\/account$/);
  await approverPage.goto(invitePath);
  await expect(approverPage.getByRole("button", { name: "Accept invitation" })).toBeVisible();
  await click(approverPage, approverPage.getByRole("button", { name: "Accept invitation" }));
  await expect(approverPage).toHaveURL(new RegExp(base + "$"));
  mark("approver_session_ready", "InvitationAccepted", "A separate account joins with the approver role.");
  await pause(1_000);

  // Start S1 on the workspace's real simulated practice site and fixed hidden fault.
  await page.goto(base + "/investigations/new?practice=1");
  await expect(page.getByLabel("What is wrong, in the reporter's words")).toBeVisible();
  await page.getByLabel("What is wrong, in the reporter's words").fill("Floor 3 pe WiFi nahi chal raha, kuch khul nahi raha");
  await page.getByLabel("Hidden fault").selectOption("CB_C2_7|tripped");
  await page.getByLabel("People asked at the same time").fill("3");
  await pause(750);
  await click(page, page.getByRole("button", { name: "Start investigation" }));
  await expect(page).toHaveURL(new RegExp(base + "/investigations/inv_[0-9A-HJKMNP-TV-Z]{26}$"));
  const investigationId = page.url().split("/").pop() as string;
  let state = await readInvestigation(page, org, investigationId);
  expect(state.sealed_commitment).toMatch(/^[0-9a-f]{64}$/i);
  const modelResponse = await page.request.get(
    "/api/core/v1/orgs/" + org + "/sites/" + state.site_id + "/models/" + state.site_model_id,
  );
  expect(modelResponse.status(), await modelResponse.text()).toBe(200);
  const model = (await modelResponse.json()) as SiteModel;
  const probeLabel = (probeId: string) => model.spec.probes.find((probe) => probe.id === probeId)?.label;
  expect(probeLabel("wifi_status")).toBeTruthy();

  const links: Record<string, string> = {};
  await click(page, page.getByRole("button", { name: "Participant links" }).first());
  const linksDialog = page.getByRole("dialog", { name: "Participant links" });
  for (const participant of state.participants) {
    const row = linksDialog.getByRole("listitem").filter({ hasText: participant.display_name });
    await row.getByRole("button", { name: "Create link" }).click();
    links[participant.id] = (await row.getByRole("link").getAttribute("href")) as string;
  }
  await page.keyboard.press("Escape");
  state = await readInvestigation(page, org, investigationId);
  await page.reload();
  await expect(page.getByTestId("pending-question").first()).toBeVisible({ timeout: 30_000 });
  const initialCards = page.getByTestId("pending-question");
  const initialCardTexts = await initialCards.allTextContents();
  let initialPendingQuestion: Question | undefined;
  let initialPendingIndex = -1;
  for (const candidate of pendingQuestions(state)) {
    initialPendingIndex = initialCardTexts.findIndex((text) =>
      normalizeText(text).includes(normalizeText(candidate.text)),
    );
    if (initialPendingIndex >= 0) {
      initialPendingQuestion = candidate;
      break;
    }
  }
  expect(initialPendingQuestion, "the first visible question should match the current core state").toBeTruthy();
  const initialPending = {
    state,
    question: initialPendingQuestion as Question,
    card: initialCards.nth(initialPendingIndex),
  };

  const participants = new Map(state.participants.map((participant) => [participant.id, participant.display_name]));
  const answers: { participant: string; question: string; observed: string }[] = [];
  let questionCount = 0;
  for (let answered = 0; answered < 16; answered += 1) {
    const pending = answered === 0 ? initialPending : await nextCoreQuestion(page, org, investigationId, "investigating");
    if (!pending) break;
    state = pending.state;
    const question = pending.question;
    const before = state.questions_asked;
    questionCount += 1;
    const name = participants.get(question.action.participant_id);
    const probe = probeLabel(question.action.probe_id);
    expect(name).toBeTruthy();
    expect(probe).toBeTruthy();
    mark("question_choice", "QuestionAsked", "Question " + questionCount + ": " + question.text, {
      text: question.text,
      "action.participant_id": question.action.participant_id,
      "action.probe_id": question.action.probe_id,
    });
    await pause(1_000);
    await phone.goto(new URL(links[question.action.participant_id], page.url()).href);
    await expect(phone.getByRole("heading", { level: 1 })).toHaveText(question.text, { timeout: 20_000 });
    if (questionCount === 1) {
      const audioResponse = phone.waitForResponse((response) =>
        response.request().method() === "GET" &&
        new URL(response.url()).pathname.endsWith("/questions/" + encodeURIComponent(question.id) + "/audio"),
      );
      await click(phone, phone.getByRole("button", { name: "Listen to the question" }), 1_250);
      const response = await audioResponse;
      expect(response.ok(), "question audio should be served by the local core").toBe(true);
      questionAudioCacheHit = response.headers()["x-audio-cached"] === "true";
      if (!questionAudioCacheHit) {
        await expect
          .poll(async () => {
            const statsResponse = await page.request.get((emulatorUrl as string) + "/stats");
            if (!statsResponse.ok()) return 0;
            const stats = (await statsResponse.json()) as { tts_sse?: number; tts_rest?: number };
            return (stats.tts_sse ?? 0) + (stats.tts_rest ?? 0);
          }, { timeout: 15_000, message: "the question audio should reach the local Gnani emulator" })
          .toBeGreaterThan(0);
      }
    }
    await pause(750);
    const observed = await answerTruthfully(phone, question.text, probe as string, false);
    answers.push({ participant: name as string, question: question.text, observed });
    await pause(750);
    await expect.poll(async () => {
      state = await readInvestigation(page, org, investigationId);
      const stillPending =
        state.pending_questions?.some((candidate) => candidate.id === question.id) ??
        state.pending_question?.id === question.id;
      return state.questions_asked > before || !stillPending || ["decided", "abstained"].includes(state.status);
    }, { timeout: 30_000 }).toBe(true);
    mark(
      "participant_answer",
      "ObservationRecorded",
      name + " answered from the simulated site card: " + observed.replace(/_/g, " ") + ".",
      {
        "evidence.participant_id": question.action.participant_id,
        "evidence.probe_id": question.action.probe_id,
        "evidence.outcome": observed,
      },
    );
    await pause(750);
  }
  state = await readInvestigation(page, org, investigationId);
  expect(state.status).toBe("decided");
  expect(state.plan.decision_class).toBe("DISPATCH_ELECTRICIAN_DB_C2");
  mark("decision", "DecisionReached", "The investigation reached " + state.plan.decision_class + ".", {
    decision_class: state.plan.decision_class,
  });
  await pause(1_500);
  await page.reload();
  // Regression check for the belief change panel: its answers must name a person, probe and outcome.
  const beliefChange = page.locator('[aria-labelledby="change-title"]');
  await expect(beliefChange).toBeVisible();
  expect(await beliefChange.innerText()).not.toContain("undefined");
  const proposeRepairButton = page.getByRole("button", { name: "Propose repair", exact: true });
  try {
    await expect(proposeRepairButton).toBeVisible();
  } catch (cause) {
    const body = await page.locator("body").innerText().catch(() => "<unavailable>");
    throw new Error(
      "The decided view did not load. Browser errors: " + JSON.stringify(pageErrors) +
        "; page text: " + JSON.stringify(body.slice(-1_000)),
      { cause },
    );
  }

  // The operator requests the action; a different approver-only account approves it.
  const repairOption = (state.repair_options ?? []).find(
    (option) => option.action === "reset_breaker" && option.target === "CB_C2_7",
  );
  expect(repairOption, "the practice model should offer the S1 breaker repair").toBeTruthy();
  expect(
    repairOption?.participant_ids.length,
    "the practice model should name an eligible person: " + JSON.stringify(state.repair_options),
  ).toBeGreaterThan(0);
  const proposeBox = await proposeRepairButton.boundingBox();
  expect(proposeBox).toBeTruthy();
  if (proposeBox) {
    await page.mouse.move(proposeBox.x + proposeBox.width / 2, proposeBox.y + proposeBox.height / 2, { steps: 1 });
  }
  await proposeRepairButton.click({ timeout: 2_000 });
  const repairDialog = page.getByRole("dialog", { name: "Propose a repair" });
  const repairLabel =
    repairOption?.action_label +
    ": " +
    repairOption?.target_label +
    (repairOption?.place ? " at " + repairOption.place : "");
  await repairDialog.getByLabel("Repair").selectOption({ label: repairLabel });
  await repairDialog.getByLabel("Carried out by").selectOption(repairOption?.participant_ids[0] as string);
  await pause(750);
  await click(page, repairDialog.getByRole("button", { name: "Send for approval" }));
  await expect(page.getByText("Awaiting approval").first()).toBeVisible();
  state = await readInvestigation(page, org, investigationId);
  expect(state.status).toBe("awaiting_approval");
  expect(state.approvals.find((approval) => approval.status === "pending")).toBeTruthy();
  mark(
    "approval_requested",
    "ApprovalRequested",
    "Approval requested for " + repairOption?.action_label + " on " + repairOption?.target + ".",
    {
      action: repairOption?.action,
      target: repairOption?.target,
      participant_id: repairOption?.participant_ids[0],
    },
  );
  await pause(1_250);

  await approverPage.goto(base + "/investigations/" + investigationId);
  await expect(approverPage.getByRole("button", { name: "Approve", exact: true })).toBeVisible();
  await expect(approverPage.getByRole("button", { name: "Reveal ground truth" })).toHaveCount(0);
  await click(approverPage, approverPage.getByRole("button", { name: "Approve", exact: true }));
  const approveDialog = approverPage.getByRole("dialog", { name: "Approve this repair?" });
  await click(approverPage, approveDialog.getByRole("button", { name: "Approve", exact: true }));
  await expect(approverPage.getByText(/Approved by .+\(you\)/)).toBeVisible();
  state = await readInvestigation(page, org, investigationId);
  expect(state.status).toBe("acting");
  mark("approval_decided", "ApprovalDecided", "The separate approver approved the repair.", {
    decision: "approve",
  });
  await pause(1_250);

  const approval = state.approvals.find((candidate) => candidate.status === "approved");
  expect(approval).toBeTruthy();
  const repairPersonId = approval?.participant_id as string;
  await phone.goto(new URL(links[repairPersonId], page.url()).href);
  await expect(phone.getByRole("heading", { name: "You are cleared to act" })).toBeVisible({ timeout: 20_000 });
  await pause(750);
  await click(phone, phone.getByRole("button", { name: "Collect permission" }));
  await click(phone, phone.getByRole("button", { name: "I am at the panel" }));
  await pause(750);
  await click(phone, phone.getByRole("button", { name: "I have done it" }));
  await expect.poll(async () => (state = await readInvestigation(page, org, investigationId)).status).toBe("verifying");
  mark("repair_reported", "InterventionReported", "The approved participant reported the simulated repair.", {
    participant_id: repairPersonId,
  });
  await pause(1_250);

  let checks = 0;
  while (checks < 12) {
    const pending = await nextCoreQuestion(page, org, investigationId, "verifying");
    if (!pending) break;
    state = pending.state;
    const question = pending.question;
    const name = participants.get(question.action.participant_id);
    const probe = probeLabel(question.action.probe_id);
    expect(name).toBeTruthy();
    expect(probe).toBeTruthy();
    mark("verification_question", "QuestionAsked", "Verification question: " + question.text, {
      text: question.text,
      "action.participant_id": question.action.participant_id,
      "action.probe_id": question.action.probe_id,
    });
    await pause(750);
    await phone.goto(new URL(links[question.action.participant_id], page.url()).href);
    const observed = await answerTruthfully(phone, question.text, probe as string, false);
    answers.push({ participant: name as string, question: question.text, observed });
    checks += 1;
    state = await readInvestigation(page, org, investigationId);
    await pause(750);
  }
  state = await readInvestigation(page, org, investigationId);
  expect(checks).toBeGreaterThan(0);
  expect(state.status).toBe("verified");
  mark("verification_complete", "VerificationResult", "The investigation status is " + state.status + ".", {
    kind: "verified",
  });
  await pause(1_500);

  await page.reload();
  await expect(page.getByRole("button", { name: "Reveal ground truth" }).first()).toBeVisible();
  await click(page, page.getByRole("button", { name: "Reveal ground truth" }).first());
  const revealDialog = page.getByRole("dialog", { name: "Reveal the ground truth?" });
  await pause(750);
  await click(page, revealDialog.getByRole("button", { name: "Reveal", exact: true }));
  await expect.poll(async () => (state = await readInvestigation(page, org, investigationId)).status).toBe("closed");
  expect(state.ground_truth?.correct).toBe(true);
  expect(state.ground_truth?.reveal?.commitment_verified).toBe(true);
  const revealedFault = state.ground_truth?.reveal?.fault_spec?.faults?.[0];
  expect(revealedFault).toMatchObject({ component_id: "CB_C2_7", mode: "tripped" });
  mark(
    "reveal",
    "GroundTruthRevealed",
    "Reveal: " +
      revealedFault?.component_id +
      " " +
      revealedFault?.mode +
      "; commitment verified: " +
      state.ground_truth?.reveal?.commitment_verified +
      ".",
    {
      "reveal.commitment_verified": true,
      correct: true,
    },
  );
  await pause(1_500);

  await page.goto(base + "/investigations/" + investigationId + "/replay");
  const integrity = page.getByRole("status", { name: "Integrity" });
  await expect(integrity).toContainText("Replay identical");
  await expect(integrity).toContainText("Log unchanged since the reveal");
  const replayResponse = await page.request.get(
    "/api/core/v1/orgs/" + org + "/investigations/" + investigationId + "/replay",
  );
  expect(replayResponse.status(), await replayResponse.text()).toBe(200);
  const replay = (await replayResponse.json()) as { identical: boolean; events_replayed: number };
  expect(replay.identical).toBe(true);
  expect(pageErrors, pageErrors.join("\n")).toEqual([]);
  mark("replay", "ReplayChecked", "Replay identical across " + replay.events_replayed + " events.");
  await pause(2_000);

  const emulatorStatsResponse = await page.request.get((emulatorUrl as string) + "/stats");
  expect(emulatorStatsResponse.status()).toBe(200);
  const emulatorStats = (await emulatorStatsResponse.json()) as { tts_sse?: number; tts_rest?: number };
  const emulatorTtsRequests = (emulatorStats.tts_sse ?? 0) + (emulatorStats.tts_rest ?? 0);
  if (!questionAudioCacheHit) expect(emulatorTtsRequests).toBeGreaterThan(0);

  const eventsResponse = await page.request.get(
    "/api/core/v1/orgs/" + org + "/investigations/" + investigationId + "/events?after_seq=0",
  );
  expect(eventsResponse.status(), await eventsResponse.text()).toBe(200);
  const events = (await eventsResponse.json()) as EventEnvelope[];
  const safeEvents = events.map((event) => {
    const payload = event.payload;
    const safe: Record<string, unknown> = {};
    if (event.type === "QuestionAsked") {
      safe.text = payload.text;
      safe.language = payload.language;
      const action = payload.action;
      if (typeof action === "object" && action !== null) {
        const record = action as Record<string, unknown>;
        safe.participant_id = record.participant_id;
        safe.probe_id = record.probe_id;
      }
    } else if (event.type === "DecisionReached") {
      safe.decision_class = payload.decision_class;
      safe.decision_probability = payload.decision_probability;
    } else if (event.type === "ApprovalRequested") {
      safe.action = payload.action;
      safe.target = payload.target;
      safe.participant_id = payload.participant_id;
    } else if (event.type === "ApprovalDecided") {
      safe.decision = payload.decision;
      safe.approver_id = payload.approver_id;
    } else if (event.type === "ObservationRecorded") {
      const evidence = payload.evidence;
      if (typeof evidence === "object" && evidence !== null) {
        const record = evidence as Record<string, unknown>;
        safe.participant_id = record.participant_id;
        safe.probe_id = record.probe_id;
        safe.outcome = record.outcome;
      }
      safe.used_as_evidence = payload.used_as_evidence;
    } else if (event.type === "InterventionReported") {
      safe.participant_id = payload.participant_id;
      safe.approval_id = payload.approval_id;
    } else if (event.type === "VerificationResult") {
      safe.kind = payload.kind;
      safe.rule = payload.rule;
      safe.fixed_probability = payload.fixed_probability;
    } else if (event.type === "GroundTruthRevealed") {
      const reveal = payload.reveal;
      if (typeof reveal === "object" && reveal !== null) {
        const record = reveal as Record<string, unknown>;
        safe.commitment_verified = record.commitment_verified;
        const faultSpec = record.fault_spec;
        if (typeof faultSpec === "object" && faultSpec !== null) {
          safe.fault_spec = (faultSpec as Record<string, unknown>).faults;
        }
      }
      safe.correct = payload.correct;
    }
    return { seq: event.seq, type: event.type, ...(event.ts ? { ts: event.ts } : {}), payload: safe };
  });
  const selectedEventTypes = new Set([
    "InvestigationCreated",
    "ReportReceived",
    "QuestionAsked",
    "ObservationRecorded",
    "DecisionReached",
    "ApprovalRequested",
    "ApprovalDecided",
    "CapabilityIssued",
    "InterventionReported",
    "VerificationResult",
    "GroundTruthRevealed",
  ]);
  const selectedEvents = safeEvents.filter((event) => selectedEventTypes.has(event.type));
  const captions = moments.map((moment) => {
    const matching = eventFor(moment, events);
    if (INVESTIGATION_EVENT_TYPES.has(moment.event_type)) {
      expect(matching, "milestone should match its exact event: " + moment.name).toBeTruthy();
    }
    return { ...moment, ...(matching ? { event_seq: matching.seq } : {}) };
  });
  const matchedSequences = captions.flatMap((moment) =>
    typeof moment.event_seq === "number" ? [moment.event_seq] : [],
  );
  expect(new Set(matchedSequences).size).toBe(matchedSequences.length);
  const timeline = {
    schema_version: 1,
    scenario: "S1",
    source: "real local core, simulator and database; local mock OIDC; local Gnani protocol emulator",
    simulated_building: true,
    gnani_protocol_emulator: true,
    synthetic_audio: true,
    disclosure: DISCLOSURE,
    resolution: { desktop: DESKTOP_SIZE, phone: PHONE_SIZE },
    started_at: new Date(started).toISOString(),
    duration_ms: Date.now() - started,
    investigation_id: investigationId,
    question_count: questionCount,
    answer_count: answers.length,
    answers,
    decision_class: state.plan.decision_class,
    verification_status: state.status,
    revealed_fault: revealedFault,
    commitment_verified: state.ground_truth?.reveal?.commitment_verified,
    correct: state.ground_truth?.correct,
    replay_identical: replay.identical,
    replay_events: replay.events_replayed,
    emulator_tts_sse_requests: emulatorStats.tts_sse ?? 0,
    emulator_tts_rest_requests: emulatorStats.tts_rest ?? 0,
    emulator_tts_requests: emulatorTtsRequests,
    question_audio_cache_hit: questionAudioCacheHit,
    events: selectedEvents,
    milestones: captions,
  };
  const timelinePath = process.env.DEMO_TIMELINE_PATH ?? testInfo.outputPath("timeline.json");
  await mkdir(path.dirname(timelinePath), { recursive: true });
  await writeFile(timelinePath, JSON.stringify(timeline, null, 2) + "\n", "utf8");

  await approverContext.close();
  if (RECORD_VIDEO) {
    const videoDir = process.env.DEMO_VIDEO_DIR;
    expect(videoDir, "DEMO_VIDEO_DIR is required when recording").toBeTruthy();
    await mkdir(videoDir as string, { recursive: true });
    const desktopVideo = page.video();
    const phoneVideo = phone.video();
    await phoneContext.close();
    await phoneVideo?.saveAs(path.join(videoDir as string, "demo-s1-phone-paced-source.webm"));
    await context.close();
    await desktopVideo?.saveAs(path.join(videoDir as string, "demo-s1-desktop-paced-source.webm"));
  } else {
    await phoneContext.close();
  }
});
