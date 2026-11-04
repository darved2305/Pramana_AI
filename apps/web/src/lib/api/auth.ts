/**
 * Authentication boundary (docs/adr/0010-authentication.md).
 *
 * Staff sign in with email and password. The core keeps the session server-side and sets an
 * httpOnly cookie, so no token is ever visible to page scripts or stored by this module.
 * Participants never sign in: they use the signed link the operator sends them.
 */
import { core } from "./core";
import { ApiError } from "./http";
import type { AuthSession, StaffRole } from "./types";

export interface Session {
  userId: string;
  displayName: string;
  email: string;
  roles: StaffRole[];
  expiresAt: string;
  /** "session" for a signed-in person; "open" when the core does not enforce sign-in. */
  method: string;
}

export interface AuthProvider {
  readonly connected: boolean;
  signInWithPassword(email: string, password: string): Promise<Session>;
  requestPasswordReset(email: string): Promise<void>;
  signOut(): Promise<void>;
  currentSession(signal?: AbortSignal): Promise<Session | null>;
}

/** Raised for things the core deliberately does not offer (self-service password reset). */
export class AuthUnavailableError extends Error {
  readonly code = "AUTH_NOT_OFFERED";
  constructor(message: string) {
    super(message);
    this.name = "AuthUnavailableError";
  }
}

function toSession(s: AuthSession): Session {
  return {
    userId: s.user_id,
    displayName: s.display_name || s.email || s.user_id,
    email: s.email,
    roles: s.roles,
    expiresAt: s.expires_at,
    method: s.method ?? "session",
  };
}

export const auth: AuthProvider = {
  connected: true,
  async signInWithPassword(email, password) {
    return toSession(await core.login(email, password));
  },
  async requestPasswordReset() {
    throw new AuthUnavailableError("Passwords are reset by your site operator. Ask them to set a new one for you.");
  },
  async signOut() {
    await core.logout();
  },
  async currentSession(signal) {
    try {
      return toSession(await core.session(signal));
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) return null;
      throw e;
    }
  },
};

export const hasRole = (s: Session | null | undefined, role: StaffRole) => !!s?.roles.includes(role);

export function validateEmail(v: string): string | null {
  const s = v.trim();
  if (!s) return "Enter your email address.";
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(s)) return "That email address does not look right.";
  return null;
}

export function validatePassword(v: string): string | null {
  if (!v) return "Enter your password.";
  if (v.length < 8) return "Passwords have at least 8 characters.";
  return null;
}
