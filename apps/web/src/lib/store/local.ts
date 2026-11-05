"use client";

/**
 * Small typed wrappers over browser storage, with a subscription so React can read them
 * through useSyncExternalStore.
 *
 * Only display preferences and the preview flag live here. Investigations and the
 * participant directory come from the core.
 */
import { useSyncExternalStore } from "react";

type Area = "local" | "session";
const listeners = new Set<() => void>();
const cache = new Map<string, { raw: string | null; value: unknown }>();

function storage(area: Area): Storage | null {
  if (typeof window === "undefined") return null;
  try {
    return area === "local" ? window.localStorage : window.sessionStorage;
  } catch {
    return null;
  }
}

function read<T>(area: Area, key: string, fallback: T): T {
  const s = storage(area);
  if (!s) return fallback;
  const raw = s.getItem(key);
  const hit = cache.get(area + key);
  if (hit && hit.raw === raw) return hit.value as T;
  let value: T = fallback;
  if (raw != null) {
    try {
      value = JSON.parse(raw) as T;
    } catch {
      value = fallback;
    }
  }
  cache.set(area + key, { raw, value });
  return value;
}

function write<T>(area: Area, key: string, value: T) {
  const s = storage(area);
  if (!s) return;
  if (value === undefined || value === null) s.removeItem(key);
  else s.setItem(key, JSON.stringify(value));
  listeners.forEach((l) => l());
}

function subscribe(cb: () => void) {
  listeners.add(cb);
  const onStorage = () => cb();
  window.addEventListener("storage", onStorage);
  return () => {
    listeners.delete(cb);
    window.removeEventListener("storage", onStorage);
  };
}

function useStored<T>(area: Area, key: string, fallback: T): T {
  return useSyncExternalStore(
    subscribe,
    () => read(area, key, fallback),
    () => fallback,
  );
}

/* ---------- Preferences ---------- */

export interface Prefs {
  reduceMotion: boolean;
  pollMs: number;
  defaultPack: string;
}
const PREFS = "pramana.prefs.v1";
export const DEFAULT_PREFS: Prefs = { reduceMotion: false, pollMs: 1500, defaultPack: "campus_block_c" };
export const prefs = {
  get: () => ({ ...DEFAULT_PREFS, ...read<Partial<Prefs>>("local", PREFS, DEFAULT_PREFS) }),
  set(p: Partial<Prefs>) {
    write("local", PREFS, { ...prefs.get(), ...p });
  },
};
export function usePrefs(): Prefs {
  const stored = useStored<Partial<Prefs>>("local", PREFS, DEFAULT_PREFS);
  return stored === DEFAULT_PREFS ? DEFAULT_PREFS : { ...DEFAULT_PREFS, ...stored };
}

/* ---------- Preview mode (this tab only) ---------- */

const PREVIEW = "pramana.preview";
/** Sample-data mode is compiled in only for the UI test build (`NEXT_PUBLIC_ENABLE_PREVIEW=1`).
 * The product always talks to the live core. */
export const PREVIEW_ENABLED = process.env.NEXT_PUBLIC_ENABLE_PREVIEW === "1";
export const previewMode = {
  enable: () => {
    if (PREVIEW_ENABLED) write("session", PREVIEW, true);
  },
  disable: () => write("session", PREVIEW, null),
};
export const usePreviewMode = () => {
  const stored = useStored<boolean>("session", PREVIEW, false);
  return PREVIEW_ENABLED && stored;
};

const noop = () => () => {};
/** False during server render and hydration, true once browser storage can be read. */
export const useHydrated = () => useSyncExternalStore(noop, () => true, () => false);

export function clearLocalData() {
  write("local", PREFS, null);
  // Data kept here by earlier versions, before the core had lists and a directory.
  write("local", "pramana.history.v1", null);
  write("local", "pramana.roster.v1", null);
}
