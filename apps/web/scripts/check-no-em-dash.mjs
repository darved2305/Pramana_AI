#!/usr/bin/env node
/**
 * Fails if any frontend source file contains an em dash (U+2014). Pramana's copy never
 * uses one, in visible text, labels, placeholders or accessibility strings.
 * Generated API types are excluded: they mirror the backend's schema descriptions.
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = fileURLToPath(new URL("..", import.meta.url));
const DIRS = ["src", "public"];
const EXT = /\.(tsx?|jsx?|mjs|css|md|json|svg|html)$/;
const SKIP = [/schema\.gen\.ts$/];
const EM = "—";

const hits = [];
function walk(dir) {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    const st = statSync(p);
    if (st.isDirectory()) walk(p);
    else if (EXT.test(name) && !SKIP.some((r) => r.test(p))) {
      readFileSync(p, "utf8")
        .split("\n")
        .forEach((line, i) => {
          if (line.includes(EM)) hits.push(`${relative(ROOT, p)}:${i + 1}: ${line.trim().slice(0, 120)}`);
        });
    }
  }
}
for (const d of DIRS) walk(join(ROOT, d));

if (hits.length) {
  console.error(`Found ${hits.length} em dash${hits.length === 1 ? "" : "es"}:\n` + hits.join("\n"));
  process.exit(1);
}
console.log("No em dashes found.");
