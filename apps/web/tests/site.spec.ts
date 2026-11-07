import { test, expect, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

function trackErrors(page: Page) {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  page.on("console", (m) => {
    if (m.type() === "error" && !/Failed to load resource/.test(m.text())) errors.push(m.text());
  });
  return errors;
}

test.describe("landing", () => {
  test("renders the hero, sections and navigation without errors", async ({ page }) => {
    const errors = trackErrors(page);
    await page.goto("/");
    await expect(page.getByRole("heading", { level: 1 })).toContainText("An AI that investigates what it cannot see");
    await expect(page.getByRole("img", { name: /voice waveform/i }).first()).toBeVisible();
    for (const id of ["how", "evidence", "workflow", "console"]) await expect(page.locator(`#${id}`)).toBeAttached();
    await page.getByRole("navigation", { name: "Primary" }).getByRole("link", { name: "Workflow" }).click();
    await expect(page).toHaveURL(/#workflow$/);
    expect(errors).toEqual([]);
  });

  test("log in button opens the login page", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("banner").getByRole("link", { name: "Log in" }).click();
    await expect(page).toHaveURL(/\/login$/);
    await expect(page.getByRole("heading", { name: "Log in" })).toBeVisible();
  });

  test("contains no em dash in rendered text", async ({ page }) => {
    for (const path of ["/", "/login", "/preview/app"]) {
      await page.goto(path);
      await page.waitForLoadState("networkidle");
      const text = await page.evaluate(() => document.body.innerText + [...document.querySelectorAll("[aria-label],[placeholder],[title]")].map((e) => e.getAttribute("aria-label") + " " + e.getAttribute("placeholder") + " " + e.getAttribute("title")).join(" "));
      expect(text.includes("—"), `em dash on ${path}`).toBe(false);
    }
  });

  test("respects reduced motion", async ({ browser }) => {
    const ctx = await browser.newContext({ reducedMotion: "reduce" });
    const page = await ctx.newPage();
    await page.goto("/");
    const h1 = page.getByRole("heading", { level: 1 });
    await expect(h1).toBeVisible();
    // Letters are fully visible immediately, with no transition.
    const op = await page.locator("h1 [aria-hidden] span span").first().evaluate((e) => getComputedStyle(e).opacity);
    expect(op).toBe("1");
    await ctx.close();
  });

  test("has no serious accessibility violations", async ({ page }) => {
    await page.goto("/");
    const r = await new AxeBuilder({ page }).disableRules(["color-contrast"]).analyze();
    const serious = r.violations.filter((v) => v.impact === "critical" || v.impact === "serious");
    expect(serious.map((v) => `${v.id}: ${v.help}`)).toEqual([]);
  });
});

test.describe("login", () => {
  test("validates input and shows the sign-in refusal from the core", async ({ page }) => {
    await page.route("**/api/core/v1/auth/login", (r) =>
      r.fulfill({
        status: 401,
        json: { error: { code: "AUTH_INVALID_CREDENTIALS", message: "email or password is incorrect", request_id: "t" } },
      }),
    );
    await page.goto("/login");
    await page.getByRole("button", { name: "Log in", exact: true }).click();
    await expect(page.getByText("Enter your email address.")).toBeVisible();
    await expect(page.getByLabel("Email")).toBeFocused();

    await page.getByLabel("Email").fill("not-an-email");
    await page.getByLabel("Password", { exact: true }).fill("short");
    await page.getByRole("button", { name: "Log in", exact: true }).click();
    await expect(page.getByText("That email address does not look right.")).toBeVisible();

    await page.getByLabel("Email").fill("riya@example.com");
    await expect(page.getByText("Passwords have at least 8 characters.")).toBeVisible();
    await page.getByLabel("Password", { exact: true }).fill("a-long-password");
    await page.getByRole("button", { name: "Show password" }).click();
    await expect(page.getByLabel("Password", { exact: true })).toHaveAttribute("type", "text");
    const sent = page.waitForRequest("**/api/core/v1/auth/login");
    await page.getByRole("button", { name: "Log in", exact: true }).click();
    const req = await sent;
    expect(req.headers()["x-pramana-csrf"]).toBe("1");
    expect(req.postDataJSON()).toEqual({ email: "riya@example.com", password: "a-long-password" });
    await expect(page.locator("#form-error")).toContainText("That email and password do not match an account.");
    await expect(page).toHaveURL(/\/login$/);
  });

  test("a successful sign-in opens the page asked for", async ({ page }) => {
    const session = { user_id: "u_1", display_name: "Olu Operator", email: "op@x.test", roles: ["operator"], expires_at: "2099-01-01T00:00:00Z", method: "session" };
    await page.route("**/api/core/v1/auth/login", (r) => r.fulfill({ json: session }));
    await page.route("**/api/core/v1/auth/session", (r) => r.fulfill({ json: session }));
    await page.goto("/login?next=/app/account");
    await page.getByLabel("Email").fill("op@x.test");
    await page.getByLabel("Password", { exact: true }).fill("a-long-password");
    await page.getByRole("button", { name: "Log in", exact: true }).click();
    await expect(page).toHaveURL(/\/app\/account$/);
    await expect(page.getByRole("main").getByText("Olu Operator")).toBeVisible();
  });

  test("never follows a sign-in redirect to another site", async ({ page }) => {
    const session = { user_id: "u_1", display_name: "Olu Operator", email: "op@x.test", roles: ["operator"], expires_at: "2099-01-01T00:00:00Z", method: "session" };
    await page.route("**/api/core/v1/auth/**", (r) => r.fulfill({ json: session }));
    await page.goto("/login?next=//evil.example/steal");
    await page.getByLabel("Email").fill("op@x.test");
    await page.getByLabel("Password", { exact: true }).fill("a-long-password");
    await page.getByRole("button", { name: "Log in", exact: true }).click();
    await expect(page).toHaveURL(/localhost:\d+\/app$/);
  });

  test("a signed-out visitor is sent to sign-in", async ({ page }) => {
    await page.route("**/api/core/v1/auth/session", (r) =>
      r.fulfill({ status: 401, json: { error: { code: "AUTH_REQUIRED", message: "not signed in", request_id: "t" } } }),
    );
    await page.goto("/app/participants");
    await expect(page).toHaveURL(/\/login\?next=%2Fapp%2Fparticipants$/);
  });

  test("has no Apple sign-in", async ({ page }) => {
    await page.goto("/login");
    await expect(page.getByText(/apple/i)).toHaveCount(0);
  });
});

test.describe("preview console", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/preview/app");
    await expect(page).toHaveURL(/\/app$/);
    await expect(page.getByText("Development preview.")).toBeVisible();
  });

  test("every console route loads from the sidebar", async ({ page }) => {
    const nav = page.getByRole("navigation", { name: "Application" });
    for (const [label, heading] of [
      ["Investigations", "Investigations"],
      ["Participants", "Participants"],
      ["Sites", "Sites"],
      ["Evaluation", "Evaluation"],
      ["Overview", "Overview"],
    ]) {
      await nav.getByRole("link", { name: label }).click();
      await expect(page.getByRole("heading", { level: 1, name: heading })).toBeVisible();
    }
    await page.getByRole("navigation", { name: "Workspace" }).getByRole("link", { name: "Settings" }).click();
    await expect(page.getByRole("heading", { level: 1, name: "Settings" })).toBeVisible();
  });

  test("command center shows every panel with preview labels", async ({ page }) => {
    const errors = trackErrors(page);
    await page.goto("/app/investigations/preview-0001");
    for (const h of ["Environment", "Competing causes", "What to do", "Conversation", "Why this question", "Evidence ledger", "Testimony", "Contradictions", "Approvals", "Diagnosis"]) {
      await expect(page.getByRole("heading", { name: h, exact: true })).toBeVisible();
    }
    await expect(page.getByText("Preview data").first()).toBeVisible();
    // Evidence filter tabs.
    await page.getByRole("tab", { name: /Set aside/ }).click();
    await expect(page.getByRole("table", { name: /Observations/ }).getByRole("row")).toHaveCount(2);
    // Selecting a place shows its details.
    await page.getByRole("button", { name: /^room 304/ }).click();
    await expect(page.getByText(/Here now: Riya/)).toBeVisible();
    // Destructive controls are not offered in preview.
    await expect(page.getByRole("button", { name: "Reveal ground truth" })).toHaveCount(0);
    expect(errors).toEqual([]);
  });

  test("replay steps through events", async ({ page }) => {
    await page.goto("/app/investigations/preview-0001/replay");
    await expect(page.getByText(/Event 1 of \d+/)).toBeVisible();
    await page.getByRole("button", { name: "Next event" }).click();
    await expect(page.getByText(/Event 2 of \d+/)).toBeVisible();
    await page.getByRole("button", { name: "Last event" }).click();
    await expect(page.getByRole("heading", { name: "Question asked" })).toBeVisible();
  });

  test("create flow validates and stays disabled in preview", async ({ page }) => {
    await page.goto("/app/investigations/new");
    await expect(page.getByText(/3 floors, 12 places/)).toBeVisible();
    await page.getByRole("button", { name: "Continue" }).click();
    await expect(page.getByRole("heading", { name: "What is wrong?" })).toBeVisible();
    await page.getByRole("button", { name: "Continue" }).click();
    await expect(page.getByText(/Describe the problem in a few words/)).toBeVisible();
    await page.getByLabel("What is wrong?").fill("Floor 2 lights are off");
    await page.getByRole("button", { name: "Continue" }).click();
    await expect(page.getByRole("heading", { name: "Who can help?" })).toBeVisible();
    await page.getByRole("button", { name: "Continue" }).click();
    await expect(page.getByText("Choose at least one participant.")).toBeVisible();
  });

  test("participant page answers locally in preview", async ({ page }) => {
    await page.goto("/join/preview?p=p_mahesh");
    await expect(page.getByText("Preview data")).toBeVisible();
    await page.getByRole("button", { name: "I am there now" }).click();
    await page.getByRole("group", { name: "Answers" }).getByRole("button", { name: "off" }).click();
    await expect(page.getByRole("status")).toContainText("Preview: nothing was sent");
  });

  test("exit preview returns to live mode", async ({ page }) => {
    await page.getByRole("button", { name: "Exit preview" }).click();
    await expect(page.getByText("Development preview.")).toHaveCount(0);
  });
});

test.describe("live console without a backend", () => {
  test("shows a truthful unreachable state", async ({ page }) => {
    await page.route("**/api/core/**", (r) => r.abort());
    await page.goto("/app/investigations/inv_missing");
    await expect(page.getByText("Core not reachable")).toBeVisible();
    await page.goto("/app");
    await expect(page.getByRole("complementary").getByText("Core offline")).toBeVisible();
  });

  test("lists nothing it does not have", async ({ page }) => {
    await page.route("**/api/core/v1/investigations?**", (r) => r.fulfill({ json: { items: [], total: 0, limit: 24, offset: 0 } }));
    await page.goto("/app/investigations");
    await expect(page.getByText("No investigations yet")).toBeVisible();
  });

  test("an unreachable core is shown, not an empty list", async ({ page }) => {
    await page.route("**/api/core/**", (r) => r.abort());
    await page.goto("/app/investigations");
    await expect(page.getByText("Core not reachable")).toBeVisible();
    await expect(page.getByText("No investigations yet")).toHaveCount(0);
  });

  test("adds a participant to the directory with validation", async ({ page }) => {
    const directory: unknown[] = [];
    await page.route("**/api/core/v1/packs/**", (r) =>
      r.fulfill({
        json: {
          id: "campus_block_c",
          version: "0.1.0",
          title: "Hostel Block C (simulated)",
          walking_roles: [],
          probes: [],
          decision_classes: [],
          locations: [{ id: "F3_R304", floor: 3, kind: "room", label: "room 304", restricted: false, access_roles: [] }],
        },
      }),
    );
    await page.route("**/api/core/v1/participants?**", async (r) => {
      if (r.request().method() === "POST") {
        const participant = r.request().postDataJSON();
        const entry = { pack_id: "campus_block_c", participant, created_at: "2026-11-05T00:00:00Z", updated_at: "2026-11-05T00:00:00Z" };
        directory.push(entry);
        return r.fulfill({ status: 201, json: entry });
      }
      return r.fulfill({ json: directory });
    });
    await page.route("**/api/core/health", (r) => r.fulfill({ json: "ok" }));
    await page.goto("/app/participants");
    await page.getByRole("button", { name: /Add the first participant/ }).click();
    const dialog = page.getByRole("dialog");
    await dialog.getByRole("button", { name: "Save participant" }).click();
    await expect(dialog.getByText("Enter a name people will recognise.")).toBeVisible();
    await dialog.getByLabel("Name").fill("Riya Sharma");
    await expect(dialog.getByLabel("Participant ID")).toHaveValue("p_riya_sharma");
    await dialog.getByLabel("Current location").selectOption("F3_R304");
    await dialog.getByRole("button", { name: "Save participant" }).click();
    await expect(page.getByText("Riya Sharma")).toBeVisible();
    expect(directory).toHaveLength(1);
    await page.reload();
    await expect(page.getByText("Riya Sharma")).toBeVisible();
  });

  test("a refused save keeps the dialog open with the reason", async ({ page }) => {
    await page.route("**/api/core/v1/packs/**", (r) =>
      r.fulfill({
        json: {
          id: "campus_block_c",
          version: "0.1.0",
          title: "Hostel Block C (simulated)",
          walking_roles: [],
          probes: [],
          decision_classes: [],
          locations: [{ id: "F3_R304", floor: 3, kind: "room", label: "room 304", restricted: false, access_roles: [] }],
        },
      }),
    );
    await page.route("**/api/core/v1/participants?**", (r) =>
      r.request().method() === "POST"
        ? r.fulfill({ status: 403, json: { error: { code: "ROLE_FORBIDDEN", message: "this needs the operator role", request_id: "t" } } })
        : r.fulfill({ json: [] }),
    );
    await page.goto("/app/participants");
    await page.getByRole("button", { name: /Add the first participant/ }).click();
    const dialog = page.getByRole("dialog");
    await dialog.getByLabel("Name").fill("Riya Sharma");
    await dialog.getByLabel("Current location").selectOption("F3_R304");
    await dialog.getByRole("button", { name: "Save participant" }).click();
    await expect(dialog.getByRole("alert")).toContainText("Your account does not have permission for this.");
  });
});

test("unknown routes show the 404 page", async ({ page }) => {
  const res = await page.goto("/does-not-exist");
  expect(res?.status()).toBe(404);
  await expect(page.getByRole("heading", { name: "Nothing was observed here" })).toBeVisible();
});

test("direct refresh works on nested routes", async ({ page }) => {
  for (const path of ["/app/investigations/new", "/app/sites", "/app/settings", "/login"]) {
    const res = await page.goto(path);
    expect(res?.status(), path).toBe(200);
  }
});

test("every console page fits a phone screen without sideways scrolling", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/preview/app");
  await expect(page).toHaveURL(/\/app$/);
  for (const path of [
    "/app", "/app/investigations", "/app/investigations/new", "/app/investigations/preview-0001",
    "/app/investigations/preview-0001/replay", "/app/participants", "/app/sites", "/app/evaluation",
    "/app/settings", "/app/account", "/join/preview?p=p_mahesh",
  ]) {
    await page.goto(path);
    await expect(page.getByRole("heading").first()).toBeVisible();
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth), { message: path }).toBeLessThanOrEqual(390);
  }
});
