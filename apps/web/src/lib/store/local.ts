"use client";

/**
 * Small typed wrappers over browser storage, with a subscription so React can read them
 * through useSyncExternalStore.
 *
 * These exist because the core has no list endpoints yet: the investigation history and
 * participant roster live in this browser until it does, and the screens say so.
 */
import { useSyncExternalStore } from "react";
import type { ParticipantSpec } from "@/lib/api/types";

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

/* ---------- Investigation history (this browser only) ---------- */

export interface HistoryEntry {
  id: string;
  createdAt: string;
  packId: string;
  report: string;
  reporter: string;
  lastStatus?: string;
}

const HISTORY = "pramana.history.v1";
const EMPTY_HISTORY: HistoryEntry[] = [];

export const history = {
  list: () => read<HistoryEntry[]>("local", HISTORY, EMPTY_HISTORY),
  add(e: HistoryEntry) {
    const cur = history.list().filter((x) => x.id !== e.id);
    write("local", HISTORY, [e, ...cur].slice(0, 200));
  },
  updateStatus(id: string, status: string) {
    const cur = history.list();
    if (!cur.some((x) => x.id === id && x.lastStatus !== status)) return;
    write("local", HISTORY, cur.map((x) => (x.id === id ? { ...x, lastStatus: status } : x)));
  },
  remove(id: string) {
    write("local", HISTORY, history.list().filter((x) => x.id !== id));
  },
};
export const useHistory = () => useStored<HistoryEntry[]>("local", HISTORY, EMPTY_HISTORY);

/* ---------- Participant roster (this browser only) ---------- */

const ROSTER = "pramana.roster.v1";
const EMPTY_ROSTER: ParticipantSpec[] = [];

export const roster = {
  list: () => read<ParticipantSpec[]>("local", ROSTER, EMPTY_ROSTER),
  upsert(p: ParticipantSpec) {
    const cur = roster.list();
    const i = cur.findIndex((x) => x.id === p.id);
    write("local", ROSTER, i >= 0 ? cur.map((x) => (x.id === p.id ? p : x)) : [...cur, p]);
  },
  remove(id: string) {
    write("local", ROSTER, roster.list().filter((x) => x.id !== id));
  },
};
export const useRoster = () => useStored<ParticipantSpec[]>("local", ROSTER, EMPTY_ROSTER);

/* ---------- Preferences ---------- */

export interface Prefs {
  reduceMotion: boolean;
  pollMs: number;
  approverId: string;
  defaultPack: string;
}
const PREFS = "pramana.prefs.v1";
export const DEFAULT_PREFS: Prefs = { reduceMotion: false, pollMs: 1500, approverId: "", defaultPack: "campus_block_c" };
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
export const previewMode = {
  enable: () => write("session", PREVIEW, true),
  disable: () => write("session", PREVIEW, null),
};
export const usePreviewMode = () => useStored<boolean>("session", PREVIEW, false);

const noop = () => () => {};
/** False during server render and hydration, true once browser storage can be read. */
export const useHydrated = () => useSyncExternalStore(noop, () => true, () => false);

export function clearLocalData() {
  write("local", HISTORY, null);
  write("local", ROSTER, null);
  write("local", PREFS, null);
}
