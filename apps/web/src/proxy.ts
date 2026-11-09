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

export async function proxy(request: NextRequest) {
  const target = upstreamFor(request.nextUrl.pathname, request.nextUrl.search, process.env);
  // Next's rewrite proxy logs the full upstream URL when the core is unreachable. Consent
  // links contain bearer secrets, so handle these requests without exposing the URL in logs.
  if (target && request.nextUrl.pathname.startsWith("/api/core/v1/consent-links/")) {
    if (request.method !== "GET" && request.method !== "POST") {
      return new Response(null, { status: 405 });
    }
    try {
      const response = await fetch(target, {
        method: request.method,
        headers: { "Content-Type": "application/json" },
        body: request.method === "POST" ? await request.text() : undefined,
        cache: "no-store",
        signal: AbortSignal.timeout(15_000),
      });
      return new Response(response.body, {
        status: response.status,
        headers: {
          "Content-Type": response.headers.get("content-type") ?? "application/json",
          "Cache-Control": "no-store",
          "Referrer-Policy": "no-referrer",
        },
      });
    } catch {
      return Response.json(
        { error: { code: "UPSTREAM_DOWN", message: "Pramana could not be reached" } },
        { status: 503, headers: { "Cache-Control": "no-store", "Referrer-Policy": "no-referrer" } },
      );
    }
  }
  return target ? NextResponse.rewrite(target) : NextResponse.next();
}

export const config = {
  matcher: ["/api/core/:path*", "/api/sim/:path*"],
};
