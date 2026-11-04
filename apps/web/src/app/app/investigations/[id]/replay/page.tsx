"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { motion, LayoutGroup } from "motion/react";
import { clsx } from "clsx";
import { Badge, Card, CardHeader, EmptyState, ErrorState, IconButton, PageHeader, PreviewBadge, ProbBar, Skeleton, Tag } from "@/components/ui";
import { IconArrowLeft, IconPause, IconPlay, IconSkipBack, IconSkipFwd } from "@/components/ui/icons";
import { useEventLog } from "@/lib/data/hooks";
import { EVENT_LABEL, clock, foldEvents, outcomeWord, pct } from "@/lib/data/derive";
import type { BeliefSnapshot, EventEnvelope } from "@/lib/api/types";
import { usePrefersReducedMotion } from "@/lib/hooks/useReducedMotion";

export default function ReplayPage() {
  const { id } = useParams<{ id: string }>();
  const log = useEventLog(id);
  return (
    <div className="flex flex-col gap-5">
      <Link href={`/app/investigations/${id}`} className="inline-flex w-fit items-center gap-1.5 text-[14px] text-muted hover:text-fg">
        <IconArrowLeft className="h-4 w-4" /> Command center
      </Link>
      <PageHeader
        title="Replay"
        eyebrow={log.source === "preview" ? <PreviewBadge /> : undefined}
        subtitle="Step through the investigation's event log and watch the belief change with each piece of evidence."
      />
      {log.status === "loading" ? (
        <Skeleton className="h-[420px] rounded-[16px]" />
      ) : log.status === "error" ? (
        <Card>
          <ErrorState error={log.error} />
        </Card>
      ) : log.data.length === 0 ? (
        <Card>
          <EmptyState title="No events yet" body="This investigation has not recorded any events." />
        </Card>
      ) : (
        <Player events={log.data} />
      )}
    </div>
  );
}

function Player({ events }: { events: EventEnvelope[] }) {
  const [i, setI] = useState(0);
  const [playing, setPlaying] = useState(false);
  const reduced = usePrefersReducedMotion();
  const last = events.length - 1;

  useEffect(() => {
    if (!playing || i >= last) return;
    const t = setTimeout(() => {
      const next = Math.min(last, i + 1);
      setI(next);
      if (next >= last) setPlaying(false);
    }, reduced ? 400 : 900);
    return () => clearTimeout(t);
  }, [playing, i, last, reduced]);

  const folded = useMemo(() => foldEvents(events, i), [events, i]);
  const belief = folded.belief as unknown as BeliefSnapshot | null;
  const ev = events[i];

  return (
    <div className="flex flex-col gap-4">
      <Card className="p-4">
        <div className="flex flex-wrap items-center gap-2">
          <IconButton label="First event" onClick={() => setI(0)} disabled={i === 0}>
            <IconSkipBack />
          </IconButton>
          <IconButton label="Previous event" onClick={() => setI((n) => Math.max(0, n - 1))} disabled={i === 0}>
            <IconArrowLeft />
          </IconButton>
          <button
            type="button"
            onClick={() => {
              if (i >= last) setI(0);
              setPlaying((p) => !p);
            }}
            className="grid h-12 w-12 place-items-center rounded-full bg-accent text-accent-ink transition-[filter] hover:brightness-110"
            aria-label={playing ? "Pause" : "Play"}
          >
            {playing ? <IconPause /> : <IconPlay />}
          </button>
          <IconButton label="Next event" onClick={() => setI((n) => Math.min(last, n + 1))} disabled={i === last}>
            <IconArrowLeft className="rotate-180" />
          </IconButton>
          <IconButton label="Last event" onClick={() => setI(last)} disabled={i === last}>
            <IconSkipFwd />
          </IconButton>
          <div className="ml-2 min-w-0 flex-1">
            <label htmlFor="scrub" className="sr-only">
              Event position
            </label>
            <input
              id="scrub"
              type="range"
              min={0}
              max={last}
              value={i}
              onChange={(e) => {
                setPlaying(false);
                setI(Number(e.target.value));
              }}
              className="w-full accent-[var(--accent)]"
            />
            <div className="mt-1 flex justify-between text-[12px] text-muted">
              <span>
                Event {i + 1} of {events.length}
              </span>
              <span className="font-mono">{clock(ev.ts)}</span>
            </div>
          </div>
        </div>
      </Card>

      <div className="grid gap-4 lg:grid-cols-[1fr_1.1fr]">
        <Card className="p-4">
          <CardHeader title="Belief at this point" subtitle={belief ? `${belief.observations_used} observations used` : "Before the first belief update"} />
          {belief ? (
            <LayoutGroup>
              <ol className="mt-3">
                {[...belief.hypotheses]
                  .sort((a, b) => b.probability - a.probability)
                  .slice(0, 7)
                  .map((h, k) => (
                    <motion.li layout key={h.id} transition={{ type: "spring", stiffness: 260, damping: 30 }} className="border-b border-line py-2.5 last:border-none">
                      <div className="flex justify-between gap-3 text-[14px]">
                        <span className={k === 0 ? "text-fg" : "text-fg-2"}>{h.label}</span>
                        <span className="font-mono text-[13px]">{pct(h.probability, 1)}</span>
                      </div>
                      <ProbBar value={h.probability} tone={k === 0 ? "accent" : "muted"} className="mt-1.5" />
                    </motion.li>
                  ))}
              </ol>
            </LayoutGroup>
          ) : (
            <EmptyState className="py-10" title="No belief yet" body="Move forward to the first belief update." />
          )}
        </Card>

        <div className="flex flex-col gap-4">
          <Card className="p-4" aria-live="polite">
            <CardHeader title={EVENT_LABEL[ev.type] ?? ev.type} subtitle={`seq ${ev.seq} · ${new Date(ev.ts).toLocaleString()}`} />
            <EventBody ev={ev} />
          </Card>
          <Card className="p-4">
            <CardHeader title="Timeline" />
            <ol className="scroll-thin mt-3 max-h-[320px] overflow-y-auto pr-1">
              {events.map((e, k) => (
                <li key={e.seq}>
                  <button
                    type="button"
                    onClick={() => {
                      setPlaying(false);
                      setI(k);
                    }}
                    className={clsx(
                      "flex w-full items-center gap-3 rounded-[10px] px-2.5 py-2 text-left text-[13px] transition-colors",
                      k === i ? "bg-accent-soft text-accent" : k < i ? "text-fg-2 hover:bg-white/[.04]" : "text-muted hover:bg-white/[.04]",
                    )}
                    aria-current={k === i ? "step" : undefined}
                  >
                    <span className="w-14 shrink-0 font-mono text-[11px]">{clock(e.ts).slice(0, 8)}</span>
                    <span className="truncate">{EVENT_LABEL[e.type] ?? e.type}</span>
                  </button>
                </li>
              ))}
            </ol>
          </Card>
        </div>
      </div>
      <p className="text-[12px] text-muted">
        {folded.observations.length} observation{folded.observations.length === 1 ? "" : "s"} recorded up to this point.
      </p>
    </div>
  );
}

function EventBody({ ev }: { ev: EventEnvelope }) {
  const p = ev.payload as Record<string, unknown>;
  if (ev.type === "ObservationRecorded")
    return (
      <div className="mt-3 flex flex-wrap items-center gap-2 text-[14px]">
        <Tag>{String(p.participant_id)}</Tag>
        <span className="text-fg-2">{String(p.probe_id).replace(/_/g, " ")}</span>
        <Badge tone="info">{outcomeWord(String(p.outcome))}</Badge>
        {p.transcript ? <p className="mt-1 w-full text-[13px] italic text-muted">&ldquo;{String(p.transcript)}&rdquo;</p> : null}
      </div>
    );
  if (ev.type === "ReportReceived") return <p className="mt-3 text-[15px]">&ldquo;{String(p.text)}&rdquo;</p>;
  if (ev.type === "PlanComputed" && typeof p.reason === "string") return <p className="mt-3 text-[14px] leading-relaxed text-fg-2">{p.reason}</p>;
  if (ev.type === "QuestionAsked" && typeof p.text === "string") return <p className="mt-3 text-[15px]">{p.text}</p>;
  if (ev.type === "BeliefUpdated") return <p className="mt-3 text-[14px] text-fg-2">The belief on the left now reflects this update.</p>;
  return (
    <pre className="scroll-thin mt-3 max-h-[180px] overflow-auto rounded-[10px] bg-black/30 p-3 font-mono text-[11px] text-fg-2">
      {JSON.stringify(p, null, 2)}
    </pre>
  );
}
