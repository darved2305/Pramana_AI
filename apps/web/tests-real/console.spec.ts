import { expect, test } from "@playwright/test";
import { AUTO, CORE, PASSWORD, PEOPLE, USERS, api, seedDirectory, signIn } from "./helpers";

test.describe("sign-in against the real core", () => {
  test("refuses a wrong password and sends a signed-out visitor to sign-in", async ({ page }) => {
    await page.goto("/app/participants");
    await expect(page).toHaveURL(/\/login\?next=%2Fapp%2Fparticipants$/);
    await page.getByLabel("Email").fill(USERS.operator);
    await page.getByLabel("Password", { exact: true }).fill("not-the-password");
    await page.getByRole("button", { name: "Log in", exact: true }).click();
    await expect(page.locator("#form-error")).toContainText("That email and password do not match an account.");
    await page.getByLabel("Password", { exact: true }).fill(PASSWORD);
    await page.getByRole("button", { name: "Log in", exact: true }).click();
    await expect(page).toHaveURL(/\/app\/participants$/);
  });

  test("shows the account, and signing out ends the session on the server", async ({ page, context }) => {
    await signIn(page, "operator", "/app/account");
    await expect(page.getByRole("main").getByText("Olu Operator")).toBeVisible();
    await expect(page.getByRole("main").getByText("operator", { exact: true })).toBeVisible();
    const cookie = (await context.cookies()).find((c) => c.name === "pramana_session");
    expect(cookie?.httpOnly).toBe(true);
    expect(cookie?.sameSite).toBe("Lax");
    await page.getByRole("button", { name: "Sign out" }).click();
    await expect(page).toHaveURL(/\/login(\?|$)/);
    // Replaying the old cookie no longer works.
    const r = await page.request.get(`${CORE}/v1/auth/session`, { headers: { Cookie: `pramana_session=${cookie?.value}` } });
    expect(r.status()).toBe(401);
  });
});

test.describe("console data comes from the core", () => {
  test("participant directory: add, edit and remove", async ({ page, request }) => {
    await seedDirectory(request);
    await api(request, "DELETE", "/v1/participants/p_imran?pack_id=campus_block_c");
    await signIn(page, "operator", "/app/participants");
    await expect(page.getByText("Riya", { exact: true })).toBeVisible();
    await expect(page.getByText("Imran", { exact: true })).toHaveCount(0);

    await page.getByRole("button", { name: "Add participant" }).first().click();
    const dialog = page.getByRole("dialog");
    await dialog.getByLabel("Name").fill("Imran Shaikh");
    await dialog.getByLabel("Participant ID").fill("p_imran");
    await dialog.getByLabel("Current location").selectOption("MAINT_ROOM");
    await dialog.getByRole("button", { name: "Save participant" }).click();
    await expect(page.getByText("Imran Shaikh")).toBeVisible();
    let stored = await api<{ participant: { display_name: string } }>(request, "GET", "/v1/participants/p_imran?pack_id=campus_block_c");
    expect(stored.participant.display_name).toBe("Imran Shaikh");

    // A duplicate id is refused by the core and the dialog says why.
    await page.getByRole("button", { name: "Add participant" }).first().click();
    await dialog.getByLabel("Name").fill("Someone Else");
    await dialog.getByLabel("Participant ID").fill("p_riya");
    await dialog.getByLabel("Current location").selectOption("MAINT_ROOM");
    await dialog.getByRole("button", { name: "Save participant" }).click();
    await expect(dialog.getByText("Someone already has this ID.")).toBeVisible();
    await dialog.getByRole("button", { name: "Cancel" }).click();

    const card = page.getByRole("listitem").filter({ hasText: "Imran Shaikh" });
    await card.getByRole("button", { name: "Edit" }).click();
    await dialog.getByLabel("Name").fill("Imran S");
    await dialog.getByRole("button", { name: "Save participant" }).click();
    await expect(page.getByText("Imran S", { exact: true })).toBeVisible();
    stored = await api(request, "GET", "/v1/participants/p_imran?pack_id=campus_block_c");
    expect(stored.participant.display_name).toBe("Imran S");

    await page.getByRole("listitem").filter({ hasText: "Imran S" }).getByRole("button", { name: "Remove" }).click();
    await page.getByRole("dialog").getByRole("button", { name: "Remove" }).click();
    await expect(page.getByText("Imran S", { exact: true })).toHaveCount(0);
    const r = await request.get(`${CORE}/v1/participants/p_imran?pack_id=campus_block_c`, { headers: AUTO });
    expect(r.status()).toBe(404);
  });

  test("an approver can read the directory but not change it", async ({ page, request }) => {
    await seedDirectory(request);
    await signIn(page, "approver", "/app/participants");
    await expect(page.getByText("Mahesh", { exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "Add participant" }).first()).toBeDisabled();
    await expect(page.getByRole("button", { name: "Edit" })).toHaveCount(0);
  });

  test("sites and the pack list", async ({ page, request }) => {
    const packs = await api<{ id: string; title: string }[]>(request, "GET", "/v1/packs");
    await signIn(page, "operator", "/app/sites");
    const select = page.getByLabel("Site model");
    for (const p of packs) await expect(select.locator(`option[value="${p.id}"]`)).toHaveText(p.title);
    await expect(page.getByRole("heading", { level: 2, name: packs[0].title })).toBeVisible();
  });

  test("evaluation runs are listed and shown as written", async ({ page }) => {
    await signIn(page, "approver", "/app/evaluation");
    await expect(page.getByLabel("Benchmark run")).toHaveValue("e2e_fixture");
    await expect(page.getByText("commit e2efixture")).toBeVisible();
    await expect(page.getByText("E_ours").first()).toBeVisible();
  });

  test("investigation list: newest first, search and status filter", async ({ page, request }) => {
    await seedDirectory(request);
    const make = (text: string) =>
      api<{ id: string }>(request, "POST", "/v1/investigations", {
        pack_id: "campus_block_c",
        participants: PEOPLE,
        report: { text, reporter_id: "p_riya" },
        scenario: { seed: 3, fault: "random" },
      });
    const a = await make("Corridor lights off near room 210");
    const b = await make("Floor 3 pe WiFi nahi chal raha");
    await signIn(page, "operator", "/app/investigations");
    const list = page.getByRole("list", { name: "Investigations" });
    await expect(list.getByRole("listitem").first()).toContainText(b.id);
    await page.getByLabel("Search by report or ID").fill("corridor");
    await expect(list.getByRole("listitem")).toHaveCount(1);
    await expect(list.getByRole("listitem").first()).toContainText(a.id);
    await page.getByLabel("Search by report or ID").fill("");
    await page.getByRole("tab", { name: /Settled/ }).click();
    await expect(page.getByRole("link", { name: /Corridor lights off/ })).toHaveCount(0);
    await page.getByRole("tab", { name: /In progress/ }).click();
    await expect(page.getByRole("link", { name: /Corridor lights off/ })).toBeVisible();
  });
});
