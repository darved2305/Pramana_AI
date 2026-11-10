import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { mkdtemp, readFile, readdir, rm } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

const directory = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(directory, "../../..");
const recorder = path.join(root, "scripts", "record_demo.py");

test(
  "the one-command recorder completes S1 in fast no-video mode",
  { timeout: 1_200_000 },
  async () => {
    const output = await mkdtemp(path.join(os.tmpdir(), "pramana-b7-smoke-"));
    try {
      const env = { ...process.env };
      delete env.PW_CHANNEL;
      const run = spawnSync(
        "uv",
        ["run", "python", recorder, "--fast", "--no-video", "--output-dir", output],
        { cwd: root, env, encoding: "utf8", timeout: 1_140_000 },
      );
      assert.equal(
        run.status,
        0,
        "recorder failed\nstdout:\n" + run.stdout.slice(-8_000) + "\nstderr:\n" + run.stderr.slice(-8_000),
      );
      const timeline = JSON.parse(await readFile(path.join(output, "timeline.json"), "utf8"));
      assert.equal(timeline.scenario, "S1");
      assert.equal(timeline.verification_status, "closed");
      assert.equal(timeline.commitment_verified, true);
      assert.equal(timeline.correct, true);
      assert.equal(timeline.replay_identical, true);
      assert.ok(timeline.events.some((event) => event.type === "ApprovalRequested"));
      assert.ok(timeline.events.some((event) => event.type === "ApprovalDecided"));
      assert.ok(timeline.events.some((event) => event.type === "InterventionReported"));
      assert.ok(timeline.events.some((event) => event.type === "VerificationResult"));
      assert.ok(timeline.events.some((event) => event.type === "GroundTruthRevealed"));
      const files = await readdir(output);
      assert.ok(!files.some((file) => file.endsWith(".webm") || file.endsWith(".mp4")));
    } finally {
      await rm(output, { recursive: true, force: true });
    }
  },
);
