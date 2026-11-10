import { expect, type APIRequestContext, type Browser, type Page } from "@playwright/test";

/** Direct calls to the real core, as automation (used only to arrange and to check state). */
export const CORE = process.env.E2E_CORE_URL as string;
export const AUTO = { "X-Automation-Key": process.env.E2E_AUTOMATION_KEY as string };
export const PASSWORD = process.env.E2E_PASSWORD as string;
export const DEMO_PASSWORDS = {
  operator: "local-demo-operator-2026",
  approver: "local-demo-approver-2026",
} as const;
export const USERS = {
  operator: "operator@e2e.test",
  approver: "approver@e2e.test",
  demoOperator: "demo-operator@local.test",
  demoApprover: "demo-approver@local.test",
} as const;

export const PEOPLE = [
  {
    id: "p_riya",
    display_name: "Riya",
    roles: ["student"],
    skill: "lay",
    location_id: "F3_R304",
    languages: { stt_candidates: ["hi-IN", "en-IN"], template_language: "hi-en", codemix: true },
  },
  {
    id: "p_mahesh",
    display_name: "Mahesh",
    roles: ["guard"],
    skill: "access",
    location_id: "GUARD_DESK",
    languages: { stt_candidates: ["mr-IN", "hi-IN"], template_language: "mr" },
  },
  {
    id: "p_imran",
    display_name: "Imran",
    roles: ["electrician"],
    skill: "technician",
    location_id: "MAINT_ROOM",
    languages: { stt_candidates: ["hi-IN"], template_language: "hi" },
  },
];

export async function api<T>(request: APIRequestContext, method: string, path: string, data?: unknown): Promise<T> {
  const r = await request.fetch(`${CORE}${path}`, { method, headers: AUTO, data });
  expect(r.ok(), `${method} ${path}: ${r.status()} ${await r.text()}`).toBeTruthy();
  return (r.status() === 204 ? undefined : await r.json()) as T;
}

export async function seedDirectory(request: APIRequestContext) {
  const existing = await api<{ participant: { id: string } }[]>(request, "GET", "/v1/participants?pack_id=campus_block_c");
  for (const e of existing) await api(request, "DELETE", `/v1/participants/${e.participant.id}?pack_id=campus_block_c`);
  for (const p of PEOPLE) await api(request, "POST", "/v1/participants?pack_id=campus_block_c", p);
}

export async function signIn(page: Page, who: keyof typeof USERS, next = "/app") {
  await page.goto(`/login?next=${encodeURIComponent(next)}`);
  await page.getByLabel("Email").fill(USERS[who]);
  const password = who === "demoOperator" ? DEMO_PASSWORDS.operator : who === "demoApprover" ? DEMO_PASSWORDS.approver : PASSWORD;
  await page.getByLabel("Password", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Log in", exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`${next.replace(/[/?]/g, (c) => `\\${c}`)}$`));
}

export async function openParticipant(browser: Browser, url: string): Promise<Page> {
  // A separate browser context: no staff cookie, only the link.
  const ctx = await browser.newContext({ viewport: { width: 390, height: 844 } });
  const page = await ctx.newPage();
  await page.goto(url);
  return page;
}

/** Answer the pending question on the participant's own page, from their surroundings card. */
export async function answerTruthfully(p: Page, questionText: string, probeLabel: string, typed: boolean) {
  const there = p.getByRole("button", { name: "I am there now" });
  // The page polls; wait until it shows this very question, not the previous screen.
  await expect(p.getByRole("heading", { level: 1 })).toHaveText(questionText, { timeout: 20_000 });
  if (await there.isVisible()) await there.click();
  const card = p.locator("details", { hasText: "What you can see here (simulation)" });
  await expect(card).toBeVisible();
  if (!(await card.evaluate((d) => (d as HTMLDetailsElement).open))) await card.locator("summary").click();
  const row = card.locator("div", { has: p.locator("dt", { hasText: probeLabel }) }).last();
  await expect(row).toBeVisible();
  const value = (await row.locator("dd").innerText()).trim();
  const answerButtons = p.getByRole("group", { name: "Answers" }).getByRole("button");
  const answerLines = await answerButtons.evaluateAll((buttons) => buttons.flatMap((button) => {
    const rect = button.getBoundingClientRect();
    const style = getComputedStyle(button);
    const available = rect.width - Number.parseFloat(style.paddingLeft) - Number.parseFloat(style.paddingRight);
    const range = document.createRange();
    range.selectNodeContents(button);
    return [...range.getClientRects()]
      .filter((line) => line.width > 0)
      .map((line) => ({ line: line.width, available, left: Number.parseFloat(style.paddingLeft), right: Number.parseFloat(style.paddingRight) }));
  }));
  expect(answerLines.length, "answer buttons have visible labels").toBeGreaterThan(0);
  expect(answerLines.every(({ line, available, left, right }) => left >= 16 && right >= 16 && line <= available + 1), "each answer label fits between its 16 px side paddings").toBe(true);
  if (typed) {
    await p.getByLabel("Type your answer").fill(PHRASES[value] ?? value);
    await p.getByRole("button", { name: "Send" }).click();
  } else {
    await p.getByRole("group", { name: "Answers" }).getByRole("button", { name: value.replace(/_/g, " "), exact: true }).click();
  }
  await expect(p.getByRole("status")).toContainText("I understood");
  return value;
}

// How someone might say each outcome (Hinglish and Marathi on purpose); the core must extract it.
export const PHRASES: Record<string, string> = {
  yes: "haan, khul rahi hai",
  no: "nahi, khul nahi rahi",
  on: "haan chalu hai",
  off: "band aahe",
  green: "lights green hain",
  amber: "orange dikh rahi hain",
  red: "laal hai",
  up: "breaker upar hai",
  tripped: "breaker neeche hai, trip hai",
  no_network: "NAVA-WiFi dikh hi nahi raha",
  stuck_connecting: "connecting pe atka hai",
  connected: "connected hai",
};
