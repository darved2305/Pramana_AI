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
  "/ready": { env: "PRAMANA_CORE_URL", fallback: "http://127.0.0.1:8000" },
};

const METADATA_IDENTITY_URL =
  "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/identity";
const identityTokens = new Map<string, { token: string; expiresAt: number }>();

export function upstreamFor(pathname: string, search: string, env: Record<string, string | undefined>): URL | null {
  for (const [prefix, { env: name, fallback }] of Object.entries(UPSTREAMS)) {
    if (pathname === prefix || pathname.startsWith(`${prefix}/`)) {
      const base = new URL(env[name] || fallback);
      const rest = prefix === "/ready" ? "/ready" : pathname.slice(prefix.length) || "/";
      const basePath = base.pathname.replace(/\/$/, "");
      return new URL(`${basePath}${rest}${search}`, base.origin);
    }
  }
  return null;
}

async function identityToken(audience: string): Promise<string> {
  const cached = identityTokens.get(audience);
  if (cached && Date.now() < cached.expiresAt) return cached.token;

  const url = new URL(METADATA_IDENTITY_URL);
  url.searchParams.set("audience", audience);
  url.searchParams.set("format", "full");
  const response = await fetch(url, {
    headers: { "Metadata-Flavor": "Google" },
    cache: "no-store",
    signal: AbortSignal.timeout(3000),
  });
  if (!response.ok) throw new Error("Cloud Run identity token is unavailable");
  const token = (await response.text()).trim();
  if (!token) throw new Error("Cloud Run identity token is empty");

  let expiresAt = Date.now() + 50 * 60 * 1000;
  try {
    const payload = token.split(".")[1];
    const normalized = payload.replace(/-/g, "+").replace(/_/g, "/");
    const claims = JSON.parse(atob(normalized + "=".repeat((4 - normalized.length % 4) % 4)));
    if (typeof claims.exp === "number") expiresAt = Math.max(Date.now(), claims.exp * 1000 - 60_000);
  } catch {
    // The metadata server is authoritative. This fallback only bounds the local cache lifetime.
  }
  identityTokens.set(audience, { token, expiresAt });
  return token;
}

export async function proxy(request: NextRequest) {
  const target = upstreamFor(request.nextUrl.pathname, request.nextUrl.search, process.env);
  if (!target) return NextResponse.next();

  if (process.env.PRAMANA_CLOUD_RUN_AUTH !== "true") return NextResponse.rewrite(target);
  try {
    const headers = new Headers(request.headers);
    headers.set("X-Serverless-Authorization", `Bearer ${await identityToken(target.origin)}`);
    return NextResponse.rewrite(target, { request: { headers } });
  } catch {
    return NextResponse.json(
      { error: { code: "UPSTREAM_UNAVAILABLE", message: "The service is temporarily unavailable." } },
      { status: 503 },
    );
  }
}

export const config = {
  matcher: ["/api/core/:path*", "/api/sim/:path*", "/ready"],
};
