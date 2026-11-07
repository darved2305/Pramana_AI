import type { NextConfig } from "next";

/**
 * The browser never talks to the backend services directly. Requests go to
 * same-origin paths (`/api/core/*`, `/api/sim/*`) that `src/proxy.ts` forwards,
 * reading the upstream addresses at request time, so one build runs in every
 * environment and the frontend can run on any port without changing the
 * backend's CORS settings.
 */
const CORE_URL = process.env.PRAMANA_CORE_URL ?? "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  // A label only: the core address the build was made for. The proxy reads PRAMANA_CORE_URL at runtime.
  env: { NEXT_PUBLIC_CORE_ADDRESS: new URL(CORE_URL).host },
  poweredByHeader: false,
  // A self-contained server for the container image (apps/web/Dockerfile).
  output: "standalone",
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
