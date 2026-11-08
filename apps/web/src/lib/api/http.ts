/**
 * One place where the browser makes network requests. Components never call fetch
 * directly; they call the typed functions in core.ts and sim.ts, which call this.
 *
 * Both services are reached through same-origin rewrites (see next.config.ts):
 *   /api/core/*  -> core service
 *   /api/sim/*   -> simulator
 */

export type Service = "core" | "sim";

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly requestId: string | null;
  /** Structured detail the core attached, such as ``problems`` for an invalid site. */
  readonly details: Record<string, unknown> | null;
  constructor(
    status: number,
    code: string,
    message: string,
    requestId: string | null,
    details: Record<string, unknown> | null = null,
  ) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.requestId = requestId;
    this.details = details;
  }
  /** Readable problems listed by the core (site descriptions), or an empty list. */
  get problems(): string[] {
    const list = this.details?.problems;
    return Array.isArray(list) ? list.filter((p): p is string => typeof p === "string") : [];
  }
  /** The service could not be reached at all (not running, or the proxy failed). */
  get unreachable() {
    return this.code === "NETWORK_UNREACHABLE" || this.code === "UPSTREAM_DOWN" || [502, 503, 504].includes(this.status);
  }
}

const BASE: Record<Service, string> = { core: "/api/core", sim: "/api/sim" };

function newRequestId() {
  return typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : Math.random().toString(36).slice(2);
}

export interface RequestOptions extends Omit<RequestInit, "body"> {
  json?: unknown;
  form?: FormData;
  token?: string;
  signal?: AbortSignal;
}

export async function request<T>(service: Service, path: string, opts: RequestOptions = {}): Promise<T> {
  const res = await raw(service, path, opts);
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

/** The raw response (status already checked), for bodies read as a stream. */
export async function requestStream(service: Service, path: string, opts: RequestOptions = {}): Promise<Response> {
  return raw(service, path, opts);
}

export async function requestBlob(service: Service, path: string, opts: RequestOptions = {}): Promise<Blob> {
  const res = await raw(service, path, opts);
  return res.blob();
}

async function raw(service: Service, path: string, opts: RequestOptions): Promise<Response> {
  const { json, form, token, headers, ...init } = opts;
  const h = new Headers(headers);
  h.set("X-Request-ID", newRequestId());
  // The core requires this on cookie-authenticated writes; a cross-site page cannot add it
  // without a CORS preflight (docs/adr/0010-authentication.md).
  if (service === "core") h.set("X-Pramana-CSRF", "1");
  if (json !== undefined) h.set("Content-Type", "application/json");
  if (token) h.set("Authorization", `Bearer ${token}`);

  let res: Response;
  try {
    res = await fetch(`${BASE[service]}${path}`, {
      ...init,
      headers: h,
      body: json !== undefined ? JSON.stringify(json) : form,
      cache: "no-store",
      credentials: "same-origin",
    });
  } catch (e) {
    if ((e as Error).name === "AbortError") throw e;
    throw new ApiError(0, "NETWORK_UNREACHABLE", `The ${service} service could not be reached.`, null);
  }

  if (!res.ok) {
    const rid = res.headers.get("X-Request-ID");
    let code = `HTTP_${res.status}`;
    let message = res.statusText || "Request failed";
    let details: Record<string, unknown> | null = null;
    try {
      const body = await res.json();
      if (body?.error?.code) {
        code = body.error.code;
        message = body.error.message ?? message;
        if (body.error.details && typeof body.error.details === "object" && !Array.isArray(body.error.details)) {
          details = body.error.details as Record<string, unknown>;
        }
      } else if (Array.isArray(body?.detail)) {
        code = "VALIDATION_ERROR";
        message = body.detail.map((d: { msg?: string }) => d.msg).filter(Boolean).join("; ");
      } else if (typeof body?.detail === "string") {
        message = body.detail;
      }
    } catch {
      // Non-JSON error body: the Next proxy returns one when the upstream is down.
      if (res.status >= 500) code = "UPSTREAM_DOWN";
    }
    throw new ApiError(res.status, code, message, rid, details);
  }
  return res;
}

/** Human wording for the error codes the API guide documents. */
export function describeError(e: unknown): string {
  if (!(e instanceof ApiError)) return e instanceof Error ? e.message : "Something went wrong.";
  switch (e.code) {
    case "NETWORK_UNREACHABLE":
    case "UPSTREAM_DOWN":
      return "The Pramana core is not reachable. Start it with `uv run python scripts/dev.py` and try again.";
    case "AUTH_REQUIRED":
      return "Please sign in to continue.";
    case "AUTH_INVALID_CREDENTIALS":
      return "That email and password do not match an account.";
    case "AUTH_RATE_LIMITED":
      return "Too many attempts. Wait a few minutes and try again.";
    case "ROLE_FORBIDDEN":
      return "Your account does not have permission for this.";
    case "PARTICIPANT_FORBIDDEN":
    case "AUTH_INVALID_TOKEN":
      return "This link is not valid for this investigation. Ask the operator for a new one.";
    case "QUESTION_NOT_PENDING":
      return "Someone has already answered this question.";
    case "VOICE_EMPTY_TRANSCRIPT":
      return "Nothing was heard. Please try again a little closer to the microphone.";
    case "VOICE_RATE_LIMITED_LOCAL":
      return "Too many voice requests this minute. Wait a moment and retry.";
    case "VOICE_TOO_MANY_STREAMS":
      return "Too many voice sessions are open right now.";
    case "VOICE_BUDGET_EXCEEDED":
      return "Today's voice budget has been used up.";
    case "VOICE_NOT_CONFIGURED":
      return "Voice is not configured on the core.";
    case "SITE_DESCRIPTION_INVALID":
      return e.problems.length ? `Fix these first: ${e.problems.join("; ")}` : e.message;
    case "DRAFT_CHANGED":
      return "Someone else changed this draft. Reload it to see their version.";
    case "HEALTH_CHECK_REQUIRED":
      return "Run the health check on this version before publishing it.";
    case "HEALTH_CHECK_FAILED":
      return "The health check found problems. Fix them, then check again.";
    case "SANDBOX_READ_ONLY":
      return "The practice site is fixed. Build your own site instead.";
    default:
      return e.message || `Request failed (${e.code}).`;
  }
}
