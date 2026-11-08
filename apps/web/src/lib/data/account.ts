"use client";

/**
 * The signed-in person's account (``GET /v1/me``), shared by every screen: their workspaces and
 * roles, onboarding progress, where they should land and their saved preferences. Everything
 * here is stored by the core, so a returning person on any device sees the same state.
 */
import { useSyncExternalStore } from "react";
import { accountApi } from "@/lib/api/account";
import { ApiError } from "@/lib/api/http";
import type { CurrentAccount } from "@/lib/api/types";

export type AccountState =
  | { status: "loading" }
  | { status: "ready"; account: CurrentAccount }
  | { status: "signed-out" }
  | { status: "error"; error: unknown };

let state: AccountState = { status: "loading" };
let inflight: Promise<AccountState> | null = null;
const listeners = new Set<() => void>();

function set(next: AccountState) {
  state = next;
  listeners.forEach((l) => l());
}

/** Fetch the account again (after creating a workspace, finishing a step, signing in). */
export function refreshAccount(): Promise<AccountState> {
  inflight ??= accountApi
    .me()
    .then((account): AccountState => ({ status: "ready", account }))
    .catch((error): AccountState =>
      error instanceof ApiError && error.status === 401 ? { status: "signed-out" } : { status: "error", error },
    )
    .then((next) => {
      set(next);
      return next;
    })
    .finally(() => {
      inflight = null;
    });
  return inflight;
}

function subscribe(cb: () => void) {
  listeners.add(cb);
  if (state.status === "loading" && !inflight) void refreshAccount();
  return () => listeners.delete(cb);
}

const LOADING: AccountState = { status: "loading" };

export function useAccount(): AccountState {
  return useSyncExternalStore(subscribe, () => state, () => LOADING);
}
