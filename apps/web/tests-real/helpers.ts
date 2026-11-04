import { expect, type APIRequestContext, type Page } from "@playwright/test";

/** Direct calls to the real core, as automation (used only to arrange and to check state). */
export const CORE = process.env.E2E_CORE_URL as string;
export const AUTO = { "X-Automation-Key": process.env.E2E_AUTOMATION_KEY as string };
export const PASSWORD = process.env.E2E_PASSWORD as string;
export const USERS = { operator: "operator@e2e.test", approver: "approver@e2e.test" } as const;

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
  await page.getByLabel("Password", { exact: true }).fill(PASSWORD);
  await page.getByRole("button", { name: "Log in", exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`${next.replace(/[/?]/g, (c) => `\\${c}`)}$`));
}
