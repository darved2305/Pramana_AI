const DATABASE_NAME = /^[a-z][a-z0-9_]{0,62}$/;

export function selectE2EDatabase(environment) {
  const database = environment.E2E_DATABASE?.trim();
  if (!database) {
    throw new Error("Set E2E_DATABASE explicitly before running the real-stack browser tests.");
  }
  if (!DATABASE_NAME.test(database) || !database.endsWith("_e2e")) {
    throw new Error("E2E_DATABASE must be a dedicated database name ending in _e2e.");
  }

  const allowed = new Set(
    (environment.PRAMANA_DB_NAMES ?? "")
      .split(",")
      .map((entry) => entry.trim())
      .filter(Boolean),
  );
  if (!allowed.has(database)) {
    throw new Error("E2E_DATABASE must be listed in PRAMANA_DB_NAMES before a reset can run.");
  }
  return database;
}
