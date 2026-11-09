import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests-proxy",
  workers: 1,
  reporter: "list",
});
