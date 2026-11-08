"use client";

/**
 * Data hooks used by screens. Each returns live data from the core, or, only in preview
 * mode, the fixtures from lib/preview. Screens never decide this themselves.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { core } from "@/lib/api/core";
import { ApiError } from "@/lib/api/http";
import type { ListQuery } from "@/lib/api/core";
import type {
  DirectoryParticipant,
  EvaluationReport,
  EvaluationReportSummary,
  EventEnvelope,
  InvestigationPage,
  InvestigationState,
  PackSummary,
  SitePack,
  VoiceStatus,
} from "@/lib/api/types";
import { useHydrated, usePrefs, usePreviewMode } from "@/lib/store/local";
import { useInvestigationScope, type InvestigationScope } from "@/lib/data/scope";

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
  /** True while following new events (pushed, or polled as a fallback). */
  live: boolean;
  lastEventAt?: string;
  refresh: () => Promise<void>;
  /** Replace the state after a mutation returned a fresh one. */
  apply: (s: InvestigationState) => void;
}

/**
 * Where new events come from. `subscribe` delivers batches in `seq` order starting after
 * `afterSeq`, and returns a function that stops it. `onReset` means the server's log is behind
 * the client (for example after a database reset): local state must be dropped.
 */
export interface EventFeedSource {
  subscribe(
    id: string,
    afterSeq: () => number,
    onEvents: (batch: EventEnvelope[]) => void,
    onReset?: () => void,
  ): () => void;
}

export function pollingSource(pollMs: number, token?: string, scope?: InvestigationScope): EventFeedSource {
  return {
    subscribe(id, afterSeq, onEvents) {
      let alive = true;
      let timer: ReturnType<typeof setTimeout>;
      const ctrl = new AbortController();
      const tick = async () => {
        try {
          const batch = await (scope ? scope.events(id, afterSeq(), ctrl.signal, token) : core.events(id, afterSeq(), ctrl.signal, token));
          if (!alive) return;
          if (batch.length) onEvents(batch);
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
    },
  };
}

/**
 * Server-sent events from `GET /v1/investigations/{id}/stream` (docs/adr/0009). Log events
 * carry `id: <seq>`, so the browser resumes with `Last-Event-ID` after a dropped connection.
 * Events arriving together are delivered as one batch. If the stream cannot be opened (the
 * server refused it, or it failed three times without delivering anything), this falls back
 * to `fallback` for the rest of the subscription.
 *
 * The server sends `ready` as soon as the stream opens. A proxy that buffers the stream (a
 * Cloudflare quick tunnel does: it does not support server-sent events) answers 200 and then
 * delivers nothing, without any error. If `ready` has not arrived within `readyMs`, the stream
 * is treated as unusable and polling takes over.
 */
export function streamSource(fallback: EventFeedSource, flushMs = 60, readyMs = 5000, apiRoot = "/v1"): EventFeedSource {
  return {
    subscribe(id, afterSeq, onEvents, onReset) {
      if (typeof window === "undefined" || typeof window.EventSource === "undefined") {
        return fallback.subscribe(id, afterSeq, onEvents, onReset);
      }
      let stopped = false;
      let es: globalThis.EventSource | null = null;
      let stopFallback: (() => void) | null = null;
      let failures = 0;
      let pending: EventEnvelope[] = [];
      let flushTimer: ReturnType<typeof setTimeout> | null = null;
      let readyTimer: ReturnType<typeof setTimeout> | null = null;

      const flush = () => {
        flushTimer = null;
        const batch = pending;
        pending = [];
        if (batch.length && !stopped) onEvents(batch);
      };
      const toPolling = () => {
        if (readyTimer) clearTimeout(readyTimer);
        readyTimer = null;
        es?.close();
        es = null;
        if (!stopped && !stopFallback) stopFallback = fallback.subscribe(id, afterSeq, onEvents, onReset);
      };
      const open = () => {
        es = new window.EventSource(`/api/core${apiRoot}/investigations/${encodeURIComponent(id)}/stream?after_seq=${afterSeq()}`);
        if (readyTimer) clearTimeout(readyTimer);
        readyTimer = setTimeout(toPolling, readyMs);
        es.onmessage = (m) => {
          failures = 0;
          try {
            pending.push(JSON.parse(m.data) as EventEnvelope);
          } catch {
            return; // a malformed frame is ignored; the next event or a refresh catches up
          }
          flushTimer ??= setTimeout(flush, flushMs);
        };
        es.addEventListener("ready", () => {
          failures = 0;
          if (readyTimer) clearTimeout(readyTimer);
          readyTimer = null;
        });
        es.addEventListener("reset", () => {
          pending = [];
          onReset?.();
        });
        es.addEventListener("bye", () => {
          // The server ended the stream on purpose: reopen from where we are.
          es?.close();
          if (!stopped) open();
        });
        es.onerror = () => {
          failures++;
          // CLOSED: the server answered with an error status; the browser will not retry.
          if (es?.readyState === 2 || failures >= 3) toPolling();
        };
      };
      open();
      return () => {
        stopped = true;
        es?.close();
        stopFallback?.();
        if (flushTimer) clearTimeout(flushTimer);
        if (readyTimer) clearTimeout(readyTimer);
      };
    },
  };
}

/** Callers should key their component by `id`, so switching investigations starts fresh. */
export function useInvestigation(id: string, source?: EventFeedSource): InvestigationFeed {
  const scope = useInvestigationScope();
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
      const s = await scope.getInvestigation(id);
      if (gen !== genRef.current) return;
      setState(s);
      setStatus("ready");
      setError(undefined);
    } catch (e) {
      if (gen !== genRef.current) return;
      setError(e);
      setStatus("error");
    }
  }, [id, isPreview, scope]);

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

  // Follow the event log while the investigation can still change. A decision is not the end:
  // approval (often from another browser), the repair, verification and the reveal follow, so
  // only a closed investigation stops changing.
  const settled = state ? state.status === "closed" : false;
  const live = !isPreview && status === "ready" && !settled;
  // Pushed over server-sent events, with polling as the fallback. Callers passing their own
  // source should memoise it.
  const feedSource = useMemo(
    () => source ?? streamSource(pollingSource(pollMs, undefined, scope), 60, 5000, scope.apiRoot),
    [source, pollMs, scope],
  );
  useEffect(() => {
    if (!live) return;
    return feedSource.subscribe(
      id,
      () => seqRef.current,
      (batch) => {
        // Drop anything already seen: a reconnecting source may resend from an older seq.
        const fresh = batch.filter((e) => e.seq > seqRef.current);
        if (!fresh.length) return;
        seqRef.current = fresh[fresh.length - 1].seq;
        setEvents((prev) => [...prev, ...fresh]);
        void refresh();
      },
      () => {
        // The log restarted behind us: forget what we had and rebuild from the start.
        seqRef.current = 0;
        setEvents([]);
        void refresh();
      },
    );
  }, [id, live, feedSource, refresh]);

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
  const scope = useInvestigationScope();
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
          const batch = await scope.events(id, after, ctrl.signal);
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
  }, [id, preview, hydrated, scope]);
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

/* ---------- generic loader ---------- */

export function useLoad<T>(key: string | null, fn: (signal: AbortSignal) => Promise<T>): Load<T> & { reload: () => void } {
  const [result, setResult] = useState<{ key: string; load: Load<T> } | null>(null);
  const [tick, setTick] = useState(0);
  const fnRef = useRef(fn);
  useEffect(() => {
    fnRef.current = fn;
  });
  useEffect(() => {
    if (key === null) return;
    let alive = true;
    const ctrl = new AbortController();
    fnRef
      .current(ctrl.signal)
      .then((data) => alive && setResult({ key, load: { status: "ready", data } }))
      .catch((error) => alive && (error as Error).name !== "AbortError" && setResult({ key, load: { status: "error", error } }));
    return () => {
      alive = false;
      ctrl.abort();
    };
  }, [key, tick]);
  const reload = useCallback(() => setTick((t) => t + 1), []);
  const state: Load<T> = result && result.key === key ? result.load : { status: "loading" };
  return { ...state, reload };
}

/* ---------- console lists ---------- */

export function useInvestigationList(q: ListQuery): Load<InvestigationPage> & { reload: () => void; source: Source } {
  const scope = useInvestigationScope();
  const preview = usePreviewMode();
  const hydrated = useHydrated();
  const key = hydrated ? JSON.stringify({ q, preview, root: scope.apiRoot }) : null;
  const load = useLoad<InvestigationPage>(key, async (signal) => {
    if (!preview) return scope.listInvestigations(q, signal);
    const f = await loadFixtures();
    const s = f.previewInvestigation;
    return {
      total: 1,
      limit: q.limit ?? 25,
      offset: 0,
      items: [
        {
          id: s.id,
          pack_id: s.pack_id,
          status: s.status,
          created_at: s.created_at,
          updated_at: s.created_at,
          report_text: s.report.text,
          reporter_id: s.report.reporter_id,
          participant_count: s.participants.length,
          decision_class: null,
          decision_probability: null,
        },
      ],
    };
  });
  return { ...load, source: preview ? "preview" : "live" };
}

export function useDirectory(packId?: string): Load<DirectoryParticipant[]> & { reload: () => void; source: Source } {
  const preview = usePreviewMode();
  const hydrated = useHydrated();
  const key = hydrated ? `${packId ?? "*"}|${preview}` : null;
  const load = useLoad<DirectoryParticipant[]>(key, async (signal) => {
    if (!preview) return core.directory(packId, signal);
    const f = await loadFixtures();
    const now = f.previewInvestigation.created_at;
    return f.previewParticipants.map((participant) => ({
      pack_id: f.previewInvestigation.pack_id,
      participant,
      created_at: now,
      updated_at: now,
    }));
  });
  return { ...load, source: preview ? "preview" : "live" };
}

export function usePacks(): Load<PackSummary[]> & { reload: () => void; source: Source } {
  const preview = usePreviewMode();
  const hydrated = useHydrated();
  const load = useLoad<PackSummary[]>(hydrated ? `packs|${preview}` : null, async (signal) => {
    if (!preview) return core.packs(signal);
    const f = await loadFixtures();
    const p = f.previewPack;
    return [{ id: p.id, version: p.version, title: p.title, locations: p.locations.length, probes: p.probes.length }];
  });
  return { ...load, source: preview ? "preview" : "live" };
}

export function useEvaluationReports(enabled: boolean): Load<EvaluationReportSummary[]> & { reload: () => void } {
  const hydrated = useHydrated();
  return useLoad<EvaluationReportSummary[]>(hydrated && enabled ? "reports" : null, (signal) => core.evaluationReports(signal));
}

export function useEvaluationReport(runId: string | null): Load<EvaluationReport> & { reload: () => void } {
  return useLoad<EvaluationReport>(runId, (signal) => core.evaluationReport(runId as string, signal));
}

/** The map of the site an investigation ran on (its pinned model version in a workspace). */
export function useInvestigationPack(state: InvestigationState | undefined): Load<SitePack> & { source: Source } {
  const scope = useInvestigationScope();
  const preview = usePreviewMode();
  const hydrated = useHydrated();
  const key = state && hydrated ? `${scope.apiRoot}|${state.site_model_id ?? state.pack_id}|${preview}` : null;
  const load = useLoad<SitePack>(key, async (signal) => {
    if (preview) return (await loadFixtures()).previewPack;
    return scope.sitePack(state as InvestigationState, signal);
  });
  return { ...load, source: preview ? "preview" : "live" };
}

