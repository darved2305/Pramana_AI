// Fails when package-lock.json resolves any package from a host other than the public npm registry.
// A third-party mirror in the lockfile made every Docker build depend on that mirror's uptime.
import { readFileSync } from "node:fs";

const lock = JSON.parse(readFileSync(new URL("../package-lock.json", import.meta.url), "utf8"));
const allowed = "https://registry.npmjs.org/";
const bad = [];
for (const [path, entry] of Object.entries(lock.packages ?? {})) {
  const resolved = entry?.resolved;
  if (typeof resolved === "string" && resolved.startsWith("http") && !resolved.startsWith(allowed)) {
    bad.push(`${path || "(root)"}: ${resolved}`);
  }
}
if (bad.length > 0) {
  console.error(`package-lock.json resolves ${bad.length} package(s) outside ${allowed}:`);
  for (const line of bad.slice(0, 20)) console.error(`  ${line}`);
  console.error("Reinstall against the public registry (npm config get registry) and commit the lockfile.");
  process.exit(1);
}
console.log("All locked packages resolve from the public npm registry.");
