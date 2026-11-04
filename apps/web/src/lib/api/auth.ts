/**
 * Authentication boundary.
 *
 * The core has no authentication routes yet. This module defines the shape the login
 * screen depends on so a real provider can be dropped in later. Until then every call
 * fails with `AUTH_NOT_CONNECTED`: no credentials are checked, no session is created and
 * nothing is stored.
 */

export interface Session {
  userId: string;
  displayName: string;
  email: string;
  expiresAt: string;
}

export interface AuthProvider {
  readonly connected: boolean;
  signInWithPassword(email: string, password: string): Promise<Session>;
  signInWithGoogle(): Promise<Session>;
  requestPasswordReset(email: string): Promise<void>;
  signOut(): Promise<void>;
  currentSession(): Promise<Session | null>;
}

export class AuthUnavailableError extends Error {
  readonly code = "AUTH_NOT_CONNECTED";
  constructor() {
    super("Sign-in is not connected yet. Use the development preview to explore the console.");
    this.name = "AuthUnavailableError";
  }
}

const notConnected: AuthProvider = {
  connected: false,
  async signInWithPassword() {
    await delay(650);
    throw new AuthUnavailableError();
  },
  async signInWithGoogle() {
    await delay(400);
    throw new AuthUnavailableError();
  },
  async requestPasswordReset() {
    await delay(500);
    throw new AuthUnavailableError();
  },
  async signOut() {},
  async currentSession() {
    return null;
  },
};

export const auth: AuthProvider = notConnected;

function delay(ms: number) {
  return new Promise((r) => setTimeout(r, ms));
}

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
