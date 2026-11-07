import { NextResponse, type NextRequest } from "next/server";

/**
 * Same-origin forwarding to the backend services, decided per request.
 *
 * The upstream addresses are read from the environment when a request arrives, not when the app is
 * built, so one image runs in every environment (PRODUCTION.md §1.4 "Build-time upstreams"). In the
 * cloud a load balancer routes these paths before they reach Next.js; locally and in tests this
 * proxy does it. It makes no authorization decision: the core does all of that.
 */
const UPSTREAMS: Record<string, { env: string; fallback: string }> = {
  "/api/core": { env: "PRAMANA_CORE_URL", fallback: "http://127.0.0.1:8000" },
  "/api/sim": { env: "PRAMANA_SIM_URL", fallback: "http://127.0.0.1:8100" },
};

export function upstreamFor(pathname: string, search: string, env: Record<string, string | undefined>): URL | null {
  for (const [prefix, { env: name, fallback }] of Object.entries(UPSTREAMS)) {
    if (pathname === prefix || pathname.startsWith(`${prefix}/`)) {
      const base = new URL(env[name] || fallback);
      const rest = pathname.slice(prefix.length) || "/";
      const basePath = base.pathname.replace(/\/$/, "");
      return new URL(`${basePath}${rest}${search}`, base.origin);
    }
  }
  return null;
}

export function proxy(request: NextRequest) {
  const target = upstreamFor(request.nextUrl.pathname, request.nextUrl.search, process.env);
  return target ? NextResponse.rewrite(target) : NextResponse.next();
}

export const config = {
  matcher: ["/api/core/:path*", "/api/sim/:path*"],
};
