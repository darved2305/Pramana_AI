import type { NextConfig } from "next";

/**
 * The browser never talks to the backend services directly. Requests go to
 * same-origin paths (`/api/core/*`, `/api/sim/*`) that `src/proxy.ts` forwards,
 * reading the upstream addresses at request time, so one build runs in every
 * environment and the frontend can run on any port without changing the
 * backend's CORS settings.
 */
const CORE_URL = process.env.PRAMANA_CORE_URL ?? "http://127.0.0.1:8000";

// React's development build evaluates strings with eval() to rebuild call stacks. The development
// server needs that allowance; the production policy never grants it.
const developmentScripts = process.env.NODE_ENV === "production" ? "" : " 'unsafe-eval'";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  // A label only: the core address the build was made for. The proxy reads PRAMANA_CORE_URL at runtime.
  env: { NEXT_PUBLIC_CORE_ADDRESS: new URL(CORE_URL).host },
  poweredByHeader: false,
  experimental: {
    // The core scales to zero on Cloud Run; a cold start took 36 s on Nov 10 and Next's default
    // 30 s rewrite timeout reset sign-in requests with "socket hang up". Wait for the instance instead.
    proxyTimeout: 120_000,
  },
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "Strict-Transport-Security", value: "max-age=31536000; includeSubDomains" },
          {
            key: "Content-Security-Policy",
            value:
              `default-src 'self'; base-uri 'self'; object-src 'none'; frame-ancestors 'none'; form-action 'self'; img-src 'self' data: blob: https:; font-src 'self' data:; script-src 'self' 'unsafe-inline'${developmentScripts}; style-src 'self' 'unsafe-inline'; connect-src 'self' https:; worker-src 'self' blob:; media-src 'self' blob:`,
          },
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "X-Frame-Options", value: "DENY" },
          { key: "Referrer-Policy", value: "no-referrer" },
          { key: "Permissions-Policy", value: "camera=(), geolocation=(), microphone=(self)" },
        ],
      },
    ];
  },
  // A self-contained server for the container image (apps/web/Dockerfile).
  output: "standalone",
  // Keep verification builds separate from a running local sign-in check.
  distDir: process.env.PRAMANA_NEXT_DIST_DIR ?? ".next",
  // OAuth codes and state arrive in query strings; omit these routes from dev request logs.
  logging: {
    incomingRequests: {
      ignore: [
        /\/api\/core\/v1\/auth\/google\/(?:start|callback)/,
        /\/api\/core\/v1\/consent-links\//,
        /\/consent\/[^/]+/,
      ],
    },
  },
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
