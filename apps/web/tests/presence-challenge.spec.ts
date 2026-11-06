import { expect, test } from "@playwright/test";

test.use({ launchOptions: { args: ["--use-fake-device-for-media-stream"] } });

test("participant can move to a presence challenge and submit the visible label", async ({ page }) => {
  const question = {
    id: "q_challenge",
    action: {
      participant_id: "p_guard",
      probe_id: "switch_leds",
      location_id: "IDF2",
      requires_move: true,
    },
    language: "en",
    text: "Go to IDF-2 and read the last three characters on the white switch label.",
    outcomes: [],
    status: "asked",
    asked_at: "2026-11-06T00:00:00Z",
    kind: "challenge",
    presence_token_id: "idf2_switch_label",
  };
  const pending = {
    id: "inv_presence",
    status: "investigating",
    participants: [
      { id: "p_guard", display_name: "Mahesh", languages: { template_language: "en" } },
    ],
    pending_question: question,
    pending_questions: [question],
    approvals: [],
    report: { reporter_id: "p_guard" },
  };
  let moved = false;
  await page.route("**/api/core/v1/investigations/inv_presence", (route) =>
    route.fulfill({ json: pending }),
  );
  await page.route("**/api/sim/sim/v1/scenarios/scenario_presence/view", (route) =>
    route.fulfill({
      json: {
        location_id: moved ? "IDF2" : "GUARD_DESK",
        location_label: moved ? "IDF-2" : "the guard desk",
        items: [],
        reachable_locations: [],
        presence_tokens: moved
          ? [{ token_id: "idf2_switch_label", display_texts: { en: "White switch label: K7Q" } }]
          : [],
      },
    }),
  );
  await page.route("**/api/sim/sim/v1/scenarios/scenario_presence/move", async (route) => {
    moved = true;
    await route.fulfill({ json: { location_id: "IDF2" } });
  });
  let submitted: Record<string, unknown> | null = null;
  await page.route("**/api/core/v1/investigations/inv_presence/answers", async (route) => {
    submitted = route.request().postDataJSON() as Record<string, unknown>;
    await route.fulfill({
      json: {
        passed: true,
        message: "I could confirm the location.",
        state: { ...pending, pending_question: null, pending_questions: [] },
      },
    });
  });

  await page.goto("/join/eyJpIjoiaW52X3ByZXNlbmNlIiwicCI6InBfZ3VhcmQiLCJzIjoic2NlbmFyaW9fcHJlc2VuY2UiLCJ0IjoidG9rZW4ifQ");
  await expect(page.getByRole("heading", { name: /white switch label/i })).toBeVisible();
  await page.getByRole("button", { name: "I am there now" }).click();
  await expect(page.getByText("White switch label: K7Q")).toBeVisible();
  await expect(page.getByRole("button", { name: "green" })).toHaveCount(0);
  await page.getByLabel("Type your answer").fill("K 7 Q");
  await page.getByRole("button", { name: "Send" }).click();
  await expect(page.getByRole("status")).toContainText("I could confirm the location.");
  expect(submitted).toMatchObject({ question_id: "q_challenge", participant_id: "p_guard", text: "K 7 Q" });
});

test("participant already at the challenge location can read the visible label", async ({ page }) => {
  const question = {
    id: "q_challenge",
    action: {
      participant_id: "p_guard",
      probe_id: "switch_leds",
      location_id: "IDF2",
      requires_move: true,
    },
    language: "en",
    text: "Go to IDF-2 and read the last three characters on the white switch label.",
    outcomes: [],
    status: "asked",
    asked_at: "2026-11-06T00:00:00Z",
    kind: "challenge",
    presence_token_id: "idf2_switch_label",
  };
  const pending = {
    id: "inv_presence",
    status: "investigating",
    participants: [
      { id: "p_guard", display_name: "Mahesh", languages: { template_language: "en" } },
    ],
    pending_question: question,
    pending_questions: [question],
    approvals: [],
    report: { reporter_id: "p_guard" },
  };
  await page.route("**/api/core/v1/investigations/inv_presence", (route) =>
    route.fulfill({ json: pending }),
  );
  await page.route("**/api/sim/sim/v1/scenarios/scenario_presence/view", (route) =>
    route.fulfill({
      json: {
        location_id: "IDF2",
        location_label: "IDF-2",
        items: [],
        reachable_locations: [],
        presence_tokens: [
          { token_id: "idf2_switch_label", display_texts: { en: "White switch label: K7Q" } },
        ],
      },
    }),
  );
  await page.route("**/api/core/v1/investigations/inv_presence/answers", (route) =>
    route.fulfill({
      json: {
        passed: true,
        message: "Location confirmed.",
        state: { ...pending, pending_question: null, pending_questions: [] },
      },
    }),
  );

  await page.goto("/join/eyJpIjoiaW52X3ByZXNlbmNlIiwicCI6InBfZ3VhcmQiLCJzIjoic2NlbmFyaW9fcHJlc2VuY2UiLCJ0IjoidG9rZW4ifQ");
  await expect(page.getByText("White switch label: K7Q")).toBeVisible();
  await expect(page.getByRole("button", { name: "I am there now" })).toHaveCount(0);
  await page.getByLabel("Type your answer").fill("K seven Q");
  await page.getByRole("button", { name: "Send" }).click();
  await expect(page.getByRole("status")).toContainText("Location confirmed.");
});

test("participant can answer a presence challenge by live voice", async ({ page }) => {
  const question = {
    id: "q_challenge",
    action: {
      participant_id: "p_guard",
      probe_id: "switch_leds",
      location_id: "IDF2",
      requires_move: true,
    },
    language: "en",
    text: "Could you read the last three characters on the white switch label?",
    outcomes: [],
    status: "asked",
    asked_at: "2026-11-06T00:00:00Z",
    kind: "challenge",
    presence_token_id: "idf2_switch_label",
  };
  const pending = {
    id: "inv_presence",
    status: "investigating",
    participants: [
      { id: "p_guard", display_name: "Mahesh", languages: { template_language: "en" } },
    ],
    pending_question: question,
    pending_questions: [question],
    approvals: [],
    report: { reporter_id: "p_guard" },
  };
  await page.context().grantPermissions(["microphone"]);
  await page.route("**/api/core/v1/investigations/inv_presence", (route) =>
    route.fulfill({ json: pending }),
  );
  await page.route("**/api/sim/sim/v1/scenarios/scenario_presence/view", (route) =>
    route.fulfill({
      json: {
        location_id: "IDF2",
        location_label: "IDF-2",
        items: [],
        reachable_locations: [],
        presence_tokens: [
          { token_id: "idf2_switch_label", display_texts: { en: "White switch label: K7Q" } },
        ],
      },
    }),
  );
  await page.routeWebSocket(
    "**/api/core/v1/investigations/inv_presence/questions/q_challenge/media",
    (socket) => {
      socket.onMessage((message) => {
        if (typeof message !== "string") return;
        const request = JSON.parse(message) as { type: string };
        if (request.type === "start") {
          socket.send(JSON.stringify({ type: "ready", question_id: question.id }));
        } else if (request.type === "commit") {
          socket.send(
            JSON.stringify({
              type: "answer",
              result: {
                passed: true,
                message: "Location confirmed.",
                state: { ...pending, pending_question: null, pending_questions: [] },
              },
            }),
          );
        }
      });
    },
  );

  await page.goto("/join/eyJpIjoiaW52X3ByZXNlbmNlIiwicCI6InBfZ3VhcmQiLCJzIjoic2NlbmFyaW9fcHJlc2VuY2UiLCJ0IjoidG9rZW4ifQ");
  await page.getByRole("button", { name: "Answer by voice" }).click();
  await expect(page.getByRole("button", { name: "Stop and send" })).toBeVisible();
  await page.getByRole("button", { name: "Stop and send" }).click();
  await expect(page.getByRole("status")).toContainText("Location confirmed.");
});
