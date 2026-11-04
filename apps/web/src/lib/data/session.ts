"use client";

/**
 * The signed-in staff member, shared by every console screen. Fetched once per page load
 * from the core (the cookie itself is httpOnly and never visible here) and refreshed after
 * sign-in or sign-out.
 */
import { useSyncExternalStore } from "react";
import { auth, type Session } from "@/lib/api/auth";

export type SessionState =
  | { status: "loading" }
  | { status: "signed-in"; session: Session }
  | { status: "signed-out" }
  | { status: "error"; error: unknown };

let state: SessionState = { status: "loading" };
let inflight: Promise<void> | null = null;
const listeners = new Set<() => void>();

function set(next: SessionState) {
  state = next;
  listeners.forEach((l) => l());
}

export function refreshSession(): Promise<void> {
  inflight ??= auth
    .currentSession()
    .then((s) => set(s ? { status: "signed-in", session: s } : { status: "signed-out" }))
    .catch((error) => set({ status: "error", error }))
    .finally(() => {
      inflight = null;
    });
  return inflight;
}

export function setSession(s: Session | null) {
  set(s ? { status: "signed-in", session: s } : { status: "signed-out" });
}

function subscribe(cb: () => void) {
  listeners.add(cb);
  if (state.status === "loading" && !inflight) void refreshSession();
  return () => listeners.delete(cb);
}

const LOADING: SessionState = { status: "loading" };

export function useSession(): SessionState {
  return useSyncExternalStore(
    subscribe,
    () => state,
    () => LOADING,
  );
}

/** The current session, or null while loading, signed out or unreachable. */
export function useCurrentUser(): Session | null {
  const s = useSession();
  return s.status === "signed-in" ? s.session : null;
}
