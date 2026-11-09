import assert from "node:assert/strict";
import test from "node:test";

import { selectE2EDatabase } from "./e2e-database-safety.mjs";

test("requires an explicit real-stack database", () => {
  assert.throws(
    () => selectE2EDatabase({ PRAMANA_DB_NAMES: "pramana_tn_e2e" }),
    /Set E2E_DATABASE explicitly/,
  );
});

test("refuses a fallback database that is outside the worktree allowlist", () => {
  assert.throws(
    () =>
      selectE2EDatabase({
        E2E_DATABASE: "pramana_web_e2e",
        PRAMANA_DB_NAMES: "pramana_tn,pramana_tn_test,pramana_tn_e2e",
      }),
    /listed in PRAMANA_DB_NAMES/,
  );
});

test("refuses an allowlisted database that is not dedicated to e2e", () => {
  assert.throws(
    () => selectE2EDatabase({ E2E_DATABASE: "pramana_tn", PRAMANA_DB_NAMES: "pramana_tn" }),
    /ending in _e2e/,
  );
});

test("accepts only an explicitly allowlisted e2e database", () => {
  assert.equal(
    selectE2EDatabase({
      E2E_DATABASE: "pramana_tn_e2e",
      PRAMANA_DB_NAMES: "pramana_tn, pramana_tn_test, pramana_tn_e2e",
    }),
    "pramana_tn_e2e",
  );
});
