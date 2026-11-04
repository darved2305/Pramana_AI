"use client";

/**
 * Data hooks used by screens. Each returns live data from the core, or, only in preview
 * mode, the fixtures from lib/preview. Screens never decide this themselves.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { core } from "@/lib/api/core";
import { ApiError } from "@/lib/api/http";
import type { EventEnvelope, InvestigationState, SitePack, VoiceStatus } from "@/lib/api/types";
import { SETTLED } from "@/lib/api/types";
import { history, useHydrated, usePrefs, usePreviewMode } from "@/lib/store/local";

export type Load<T> =
  | { status: "loading"; data?: undefined; error?: undefined }
  | { status: "ready"; data: T; error?: undefined }
  | { status: "error"; data?: undefined; error: unknown };

export type Source = "live" | "preview";

async function loadFixtures() {
  return import("@/lib/preview/fixtures");
}

/* ---------- core connectivity ---------- */

export type Health = "checking" | "online" | "offline";

export function useCoreHealth(intervalMs = 10000): Health {
  const [h, setH] = useState<Health>("checking");
  useEffect(() => {
    let alive = true;
    const ctrl = new AbortController();
    const check = () =>
      core
        .health(ctrl.signal)
        .then(() => alive && setH("online"))
        .catch((e) => alive && (e as Error).name !== "AbortError" && setH("offline"));
    check();
    const id = setInterval(check, intervalMs);
    return () => {
      alive = false;
      ctrl.abort();
      clearInterval(id);
    };
  }, [intervalMs]);
  return h;
}

/* ---------- site pack ---------- */

export function usePack(packId: string | undefined): Load<SitePack> & { source: Source } {
  const preview = usePreviewMode();
  const hydrated = useHydrated();
  // Results are tagged with the request they answer, so a stale result reads as loading.
  const key = `${packId}|${preview}`;
  const [result, setResult] = useState<{ key: string; load: Load<SitePack> } | null>(null);
  useEffect(() => {
    if (!packId || !hydrated) return;
    let alive = true;
    const ctrl = new AbortController();
    const k = `${packId}|${preview}`;
    const run = preview ? loadFixtures().then((f) => f.previewPack) : core.pack(packId, ctrl.signal);
    run
      .then((data) => alive && setResult({ key: k, load: { status: "ready", data } }))
      .catch((error) => alive && (error as Error).name !== "AbortError" && setResult({ key: k, load: { status: "error", error } }));
    return () => {
      alive = false;
      ctrl.abort();
    };
  }, [packId, preview, hydrated]);
  const state: Load<SitePack> = result?.key === key ? result.load : { status: "loading" };
  return { ...state, source: preview ? "preview" : "live" };
}

/* ---------- one investigation, live ---------- */

export interface InvestigationFeed {
  status: "loading" | "ready" | "error";
  state?: InvestigationState;
  events: EventEnvelope[];
  error?: unknown;
  source: Source;
  /** True while polling for new events. */
  live: boolean;
  lastEventAt?: string;
  refresh: () => Promise<void>;
  /** Replace the state after a mutation returned a fresh one. */
  apply: (s: InvestigationState) => void;
}

/** Callers should key their component by `id`, so switching investigations starts fresh. */
export function useInvestigation(id: string): InvestigationFeed {
  const preview = usePreviewMode();
  const { pollMs } = usePrefs();
  const [state, setState] = useState<InvestigationState>();
  const [events, setEvents] = useState<EventEnvelope[]>([]);
  const [status, setStatus] = useState<InvestigationFeed["status"]>("loading");
  const [error, setError] = useState<unknown>();
  const seqRef = useRef(0);
  const isPreview = preview;
  const hydrated = useHydrated();
  const genRef = useRef(0);

  const refresh = useCallback(async () => {
    if (isPreview) return;
    const gen = genRef.current;
    try {
      const s = await core.getInvestigation(id);
      if (gen !== genRef.current) return;
      setState(s);
      setStatus("ready");
      setError(undefined);
      history.updateStatus(id, s.status);
    } catch (e) {
      if (gen !== genRef.current) return;
      setError(e);
      setStatus("error");
    }
  }, [id, isPreview]);

  // Initial load.
  useEffect(() => {
    if (!hydrated) return;
    let alive = true;
    genRef.current++;
    seqRef.current = 0;
    if (isPreview) {
      loadFixtures().then((f) => {
        if (!alive) return;
        if (id === f.PREVIEW_ID) {
          setState(f.previewInvestigation);
          setEvents(f.previewEvents);
          setStatus("ready");
        } else {
          setError(new ApiError(404, "PREVIEW_NOT_FOUND", "There is no preview investigation with this ID.", null));
          setStatus("error");
        }
      });
      return () => {
        alive = false;
      };
    }
    // refresh() only sets state after awaiting the network.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    refresh();
    return () => {
      alive = false;
    };
  }, [id, isPreview, refresh, hydrated]);

  // Poll the event log while the investigation can still change.
  const settled = state ? SETTLED.includes(state.status) && !state.pending_question : false;
  const live = !isPreview && status === "ready" && !settled;
  useEffect(() => {
    if (!live) return;
    let alive = true;
    let timer: ReturnType<typeof setTimeout>;
    const ctrl = new AbortController();
    const tick = async () => {
      try {
        const batch = await core.events(id, seqRef.current, ctrl.signal);
        if (!alive) return;
        if (batch.length) {
          seqRef.current = batch[batch.length - 1].seq;
          setEvents((prev) => [...prev, ...batch]);
          await refresh();
        }
      } catch (e) {
        if ((e as Error).name === "AbortError") return;
      }
      if (alive) timer = setTimeout(tick, pollMs);
    };
    tick();
    return () => {
      alive = false;
      ctrl.abort();
      clearTimeout(timer);
    };
  }, [id, live, pollMs, refresh]);

  return {
    status,
    state,
    events,
    error,
    source: isPreview ? "preview" : "live",
    live,
    lastEventAt: events.at(-1)?.ts,
    refresh,
    apply: (s) => setState(s),
  };
}

/** Full event log, for replay. */
export function useEventLog(id: string): Load<EventEnvelope[]> & { source: Source } {
  const preview = usePreviewMode();
  const key = `${id}|${preview}`;
  const [result, setResult] = useState<{ key: string; load: Load<EventEnvelope[]> } | null>(null);
  const hydrated = useHydrated();
  useEffect(() => {
    if (!hydrated) return;
    let alive = true;
    const ctrl = new AbortController();
    const k = `${id}|${preview}`;
    const setState = (load: Load<EventEnvelope[]>) => setResult({ key: k, load });
    (async () => {
      try {
        if (preview) {
          const f = await loadFixtures();
          if (id !== f.PREVIEW_ID) throw new ApiError(404, "NOT_FOUND", "There is no preview investigation with this ID.", null);
          if (alive) setState({ status: "ready", data: f.previewEvents });
          return;
        }
        const all: EventEnvelope[] = [];
        let after = 0;
        for (let i = 0; i < 50; i++) {
          const batch = await core.events(id, after, ctrl.signal);
          if (!batch.length) break;
          all.push(...batch);
          after = batch[batch.length - 1].seq;
        }
        if (alive) setState({ status: "ready", data: all });
      } catch (error) {
        if (alive && (error as Error).name !== "AbortError") setState({ status: "error", error });
      }
    })();
    return () => {
      alive = false;
      ctrl.abort();
    };
  }, [id, preview, hydrated]);
  const state: Load<EventEnvelope[]> = result?.key === key ? result.load : { status: "loading" };
  return { ...state, source: preview ? "preview" : "live" };
}

export function useVoiceStatus(): Load<VoiceStatus> {
  const [state, setState] = useState<Load<VoiceStatus>>({ status: "loading" });
  useEffect(() => {
    const ctrl = new AbortController();
    core
      .voiceStatus(ctrl.signal)
      .then((data) => setState({ status: "ready", data }))
      .catch((error) => (error as Error).name !== "AbortError" && setState({ status: "error", error }));
    return () => ctrl.abort();
  }, []);
  return state;
}
