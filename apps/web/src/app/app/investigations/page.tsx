"use client";

import { useInvestigationScope } from "@/lib/data/scope";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import {
  Badge,
  Button,
  ButtonLink,
  Card,
  Dialog,
  EmptyState,
  ErrorState,
  Field,
  Input,
  PageHeader,
  PreviewBadge,
  Skeleton,
  Tabs,
} from "@/components/ui";
import { IconHistory, IconPlus, IconSearch } from "@/components/ui/icons";
import { InvestigationBoard } from "@/components/console/InvestigationBoard";
import { usePreviewMode } from "@/lib/store/local";
import { useInvestigationList } from "@/lib/data/hooks";
import { STATUS_LABEL, STATUS_TONE, pct, relative } from "@/lib/data/derive";
import type { InvestigationStatus, InvestigationSummary } from "@/lib/api/types";

type Filter = "all" | "active" | "settled";
const ACTIVE: string[] = ["investigating", "awaiting_approval", "acting", "verifying"];

export default function InvestigationsPage() {
  return (
    <Suspense>
      <InvestigationsInner />
    </Suspense>
  );
}

const PAGE = 24;
const SETTLED_STATUSES: InvestigationStatus[] = ["decided", "abstained", "verified", "not_verified", "closed"];
const STATUS_FILTER: Record<Filter, InvestigationStatus[]> = {
  all: [],
  active: ACTIVE as InvestigationStatus[],
  settled: SETTLED_STATUSES,
};

function useDebounced<T>(value: T, ms: number): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

function InvestigationsInner() {
  const scope = useInvestigationScope();
  const params = useSearchParams();
  const router = useRouter();
  const preview = usePreviewMode();
  // The URL is the source of truth for filters so a filtered list can be shared or bookmarked.
  // The search box keeps its own text while typing and follows the URL on back/forward.
  const urlQ = params.get("q") ?? "";
  const filterParam = params.get("filter");
  const filter: Filter = filterParam === "active" || filterParam === "settled" ? filterParam : "all";
  const [q, setQ] = useState(urlQ);
  const [seenUrlQ, setSeenUrlQ] = useState(urlQ);
  if (urlQ !== seenUrlQ) {
    setSeenUrlQ(urlQ);
    if (urlQ !== q.trim()) setQ(urlQ);
  }
  const [openId, setOpenId] = useState(false);
  const board = params.get("view") === "board";
  const updateUrl = (values: { q?: string; filter?: Filter; view?: "list" | "board" }) => {
    const next = new URLSearchParams(params.toString());
    const nextQ = values.q ?? q;
    const nextFilter = values.filter ?? filter;
    const nextView = values.view ?? (board ? "board" : "list");
    if (nextQ.trim()) next.set("q", nextQ.trim());
    else next.delete("q");
    if (nextFilter !== "all") next.set("filter", nextFilter);
    else next.delete("filter");
    if (nextView === "board") next.set("view", "board");
    else next.delete("view");
    router.replace(`${scope.base}/investigations${next.size ? `?${next}` : ""}`, { scroll: false });
  };
  const setView = (next: "list" | "board") => updateUrl({ view: next });
  const needle = useDebounced(q, 250);
  // The list hook keys on the serialized query, so a fresh object each render is fine.
  const query = { status: STATUS_FILTER[filter], q: needle, limit: PAGE };
  const list = useInvestigationList(query);
  const rows = list.data?.items ?? [];
  const nextCursor = list.data?.next_cursor;
  const filtering = filter !== "all" || needle.trim() !== "";

  return (
    <div className="flex flex-col gap-5">
      <PageHeader
        title="Investigations"
        eyebrow={preview ? <PreviewBadge /> : undefined}
        subtitle="Simulated investigations. Open one to follow its questions, decision and repair."
        actions={
          <>
            <div role="group" aria-label="View" className="flex rounded-full p-0.5 shadow-[inset_0_0_0_0.8px_var(--app-line)]">
              {(["list", "board"] as const).map((v) => (
                <button key={v} type="button" aria-pressed={board === (v === "board")} onClick={() => setView(v)}
                  className={`h-[34px] rounded-full px-3.5 text-[13px] ${board === (v === "board") ? "bg-white/[.07] text-fg" : "text-muted hover:text-fg"}`}>
                  {v === "list" ? "List" : "Board"}
                </button>
              ))}
            </div>
            <Button onClick={() => setOpenId(true)}>Open by ID</Button>
            <ButtonLink href={`${scope.base}/investigations/new`} variant="primary" size="lg">
              <IconPlus className="h-4 w-4" /> New investigation
            </ButtonLink>
          </>
        }
      />

      {board ? (
        <InvestigationBoard
          list={list}
          filtering={filtering}
          onClearFilters={() => {
            setQ("");
            updateUrl({ q: "", filter: "all" });
          }}
        />
      ) : null}
      <div className={board ? "hidden" : "flex flex-wrap items-center justify-between gap-3"}>
        <Tabs<Filter>
          label="Filter investigations"
          value={filter}
          onChange={(f) => {
            updateUrl({ filter: f });
          }}
          items={[
            { value: "all", label: "All" },
            { value: "active", label: "In progress" },
            { value: "settled", label: "Settled" },
          ]}
        />
        <div className="flex h-[38px] w-full max-w-[300px] items-center gap-2 rounded-full border-[0.8px] border-line px-3.5 focus-within:border-accent/60">
          <IconSearch className="h-4 w-4 text-muted" />
          <label htmlFor="inv-filter" className="sr-only">
            Search by report or ID
          </label>
          <input
            id="inv-filter"
            value={q}
            onChange={(e) => {
              setQ(e.target.value);
              updateUrl({ q: e.target.value });
            }}
            placeholder="Search by report or ID"
            className="w-full bg-transparent text-[14px] outline-none placeholder:text-muted"
          />
        </div>
      </div>

      {board ? null : list.status === "loading" ? (
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3" aria-busy="true">
          <Skeleton className="h-[160px]" />
          <Skeleton className="h-[160px]" />
          <Skeleton className="h-[160px]" />
        </div>
      ) : list.status === "error" ? (
        <Card>
          <ErrorState error={list.error} onRetry={list.reload} />
        </Card>
      ) : rows.length === 0 && !filtering ? (
        <Card>
          <EmptyState
            icon={<IconHistory />}
            title="No investigations yet"
            body="Start one from a report. It will be listed here, and you can come back to its command center at any time."
            action={
              <ButtonLink href={`${scope.base}/investigations/new`} variant="primary">
                <IconPlus className="h-4 w-4" /> New investigation
              </ButtonLink>
            }
          />
        </Card>
      ) : rows.length === 0 ? (
        <Card>
          <EmptyState
            title="No matches"
            body="Nothing matches this filter. Clear the search or pick another tab."
            action={
              <Button
                onClick={() => {
                  setQ("");
                  updateUrl({ q: "", filter: "all" });
                }}
              >
                Clear filters
              </Button>
            }
          />
        </Card>
      ) : (
        <>
          <ul className="grid gap-3 md:grid-cols-2 xl:grid-cols-3" aria-label="Investigations">
            {rows.map((r) => (
              <InvestigationCard key={r.id} r={r} />
            ))}
          </ul>
          {list.moreError ? (
            <p role="alert" className="text-[13px] text-bad">Could not load more investigations. <button className="underline" onClick={list.loadMore}>Try again</button></p>
          ) : null}
          {nextCursor ? (
            <div className="flex justify-center">
              <Button size="sm" onClick={list.loadMore} disabled={list.loadingMore}>
                {list.loadingMore ? "Loading..." : "Load more investigations"}
              </Button>
            </div>
          ) : null}
        </>
      )}

      <OpenByIdDialog open={openId} onClose={() => setOpenId(false)} />
    </div>
  );
}

function InvestigationCard({ r }: { r: InvestigationSummary }) {
  const scope = useInvestigationScope();
  const people = r.participant_count === 1 ? "1 person" : `${r.participant_count} people`;
  return (
    <li className="card group relative flex flex-col p-4 transition-colors hover:bg-card-2">
      <div className="flex items-center justify-between gap-2">
        <Badge tone={STATUS_TONE[r.status]} dot>
          {STATUS_LABEL[r.status]}
        </Badge>
        <span className="text-[12px] text-muted">{relative(r.created_at)}</span>
      </div>
      <Link href={`${scope.base}/investigations/${r.id}`} className="mt-3 block text-[16px] leading-snug text-fg after:absolute after:inset-0 after:rounded-[16px]">
        &ldquo;{r.report_text}&rdquo;
      </Link>
      <p className="mt-1.5 text-[13px] text-muted">
        {r.reporter_id} · {people} · {r.pack_id}
      </p>
      {r.decision_class ? (
        <p className="mt-1 text-[13px] text-fg-2">
          {r.decision_class}
          {r.decision_probability != null ? ` (${pct(r.decision_probability)} confident)` : ""}
        </p>
      ) : null}
      <div className="relative z-10 mt-4 flex items-center justify-between gap-2 border-t border-line pt-3">
        <span className="truncate font-mono text-[11px] text-muted">{r.id}</span>
        <Link href={`${scope.base}/investigations/${r.id}/replay`} className="rounded-full px-2.5 py-1 text-[12px] text-fg-2 hover:bg-white/[.06]">
          Replay
        </Link>
      </div>
    </li>
  );
}

function OpenByIdDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const scope = useInvestigationScope();
  const router = useRouter();
  const [id, setId] = useState("");
  const [err, setErr] = useState<string | null>(null);
  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="Open an investigation"
      description="Paste the ID shown in the investigation's command center or returned by the API."
    >
      <form
        onSubmit={(e) => {
          e.preventDefault();
          const v = id.trim();
          if (!v) return setErr("Enter an investigation ID.");
          if (!/^[\w-]{3,}$/.test(v)) return setErr("IDs contain only letters, numbers, dashes and underscores.");
          onClose();
          router.push(`${scope.base}/investigations/${encodeURIComponent(v)}`);
        }}
        className="flex flex-col gap-4"
        noValidate
      >
        <Field label="Investigation ID" error={err}>
          {(p) => (
            <Input
              {...p}
              autoFocus
              value={id}
              onChange={(e) => {
                setId(e.target.value);
                setErr(null);
              }}
              placeholder="inv_..."
              className="font-mono"
            />
          )}
        </Field>
        <div className="flex justify-end gap-2">
          <Button onClick={onClose}>Cancel</Button>
          <Button type="submit" variant="primary">
            Open
          </Button>
        </div>
      </form>
    </Dialog>
  );
}
