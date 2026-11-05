import type { NextConfig } from "next";

/**
 * The browser never talks to the backend services directly. Requests go to
 * same-origin paths that Next.js forwards, so the frontend can run on any port
 * without changing the backend's CORS settings.
 */
const CORE_URL = process.env.PRAMANA_CORE_URL ?? "http://127.0.0.1:8000";
const SIM_URL = process.env.PRAMANA_SIM_URL ?? "http://127.0.0.1:8100";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  // Shown in the console so the operator can see which core the proxy really forwards to.
  env: { NEXT_PUBLIC_CORE_ADDRESS: new URL(CORE_URL).host },
  poweredByHeader: false,
  async rewrites() {
    return [
      { source: "/api/core/:path*", destination: `${CORE_URL}/:path*` },
      { source: "/api/sim/:path*", destination: `${SIM_URL}/:path*` },
    ];
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
