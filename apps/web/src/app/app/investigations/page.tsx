"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useState } from "react";
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
import { usePreviewMode } from "@/lib/store/local";
import { useInvestigationList } from "@/lib/data/hooks";
import { STATUS_LABEL, STATUS_TONE, relative } from "@/lib/data/derive";
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
  const params = useSearchParams();
  const router = useRouter();
  const preview = usePreviewMode();
  const [q, setQ] = useState(params.get("q") ?? "");
  const [filter, setFilter] = useState<Filter>("all");
  const [page, setPage] = useState(0);
  const [openId, setOpenId] = useState(false);
  const needle = useDebounced(q, 250);
  const query = useMemo(() => ({ status: STATUS_FILTER[filter], q: needle, limit: PAGE, offset: page * PAGE }), [filter, needle, page]);
  const list = useInvestigationList(query);
  const rows = list.data?.items ?? [];
  const total = list.data?.total ?? 0;
  const filtering = filter !== "all" || needle.trim() !== "";

  return (
    <div className="flex flex-col gap-5">
      <PageHeader
        title="Investigations"
        eyebrow={preview ? <PreviewBadge /> : undefined}
        actions={
          <>
            <Button onClick={() => setOpenId(true)}>Open by ID</Button>
            <ButtonLink href="/app/investigations/new" variant="primary" size="lg">
              <IconPlus className="h-4 w-4" /> New investigation
            </ButtonLink>
          </>
        }
      />

      <div className="flex flex-wrap items-center justify-between gap-3">
        <Tabs<Filter>
          label="Filter investigations"
          value={filter}
          onChange={(f) => {
            setFilter(f);
            setPage(0);
          }}
          items={[
            { value: "all", label: "All", count: filter === "all" ? total : undefined },
            { value: "active", label: "In progress", count: filter === "active" ? total : undefined },
            { value: "settled", label: "Settled", count: filter === "settled" ? total : undefined },
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
              setPage(0);
              router.replace(`/app/investigations${e.target.value ? `?q=${encodeURIComponent(e.target.value)}` : ""}`, { scroll: false });
            }}
            placeholder="Search by report or ID"
            className="w-full bg-transparent text-[14px] outline-none placeholder:text-muted"
          />
        </div>
      </div>

      {list.status === "loading" ? (
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3" aria-busy="true">
          <Skeleton className="h-[160px]" />
          <Skeleton className="h-[160px]" />
          <Skeleton className="h-[160px]" />
        </div>
      ) : list.status === "error" ? (
        <Card>
          <ErrorState error={list.error} onRetry={list.reload} />
        </Card>
      ) : rows.length === 0 && !filtering && page === 0 ? (
        <Card>
          <EmptyState
            icon={<IconHistory />}
            title="No investigations yet"
            body="Start one from a report. It will be listed here, and you can come back to its command center at any time."
            action={
              <ButtonLink href="/app/investigations/new" variant="primary">
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
                  setFilter("all");
                  setPage(0);
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
          {total > PAGE ? (
            <nav className="flex items-center justify-between gap-3 text-[13px] text-muted" aria-label="Pages">
              <span>
                {page * PAGE + 1} to {Math.min(total, (page + 1) * PAGE)} of {total}
              </span>
              <span className="flex gap-2">
                <Button size="sm" onClick={() => setPage((p) => p - 1)} disabled={page === 0}>
                  Previous
                </Button>
                <Button size="sm" onClick={() => setPage((p) => p + 1)} disabled={(page + 1) * PAGE >= total}>
                  Next
                </Button>
              </span>
            </nav>
          ) : null}
        </>
      )}

      <OpenByIdDialog open={openId} onClose={() => setOpenId(false)} />
    </div>
  );
}

function InvestigationCard({ r }: { r: InvestigationSummary }) {
  const people = r.participant_count === 1 ? "1 person" : `${r.participant_count} people`;
  return (
    <li className="card group relative flex flex-col p-4 transition-colors hover:bg-card-2">
      <div className="flex items-center justify-between gap-2">
        <Badge tone={STATUS_TONE[r.status]} dot>
          {STATUS_LABEL[r.status]}
        </Badge>
        <span className="text-[12px] text-muted">{relative(r.created_at)}</span>
      </div>
      <Link href={`/app/investigations/${r.id}`} className="mt-3 block text-[16px] leading-snug text-fg after:absolute after:inset-0 after:rounded-[16px]">
        &ldquo;{r.report_text}&rdquo;
      </Link>
      <p className="mt-1.5 text-[13px] text-muted">
        {r.reporter_id} · {people} · {r.pack_id}
      </p>
      {r.decision_class ? (
        <p className="mt-1 text-[13px] text-fg-2">
          {r.decision_class}
          {r.decision_probability != null ? ` at P = ${r.decision_probability.toFixed(2)}` : ""}
        </p>
      ) : null}
      <div className="relative z-10 mt-4 flex items-center justify-between gap-2 border-t border-line pt-3">
        <span className="truncate font-mono text-[11px] text-muted">{r.id}</span>
        <Link href={`/app/investigations/${r.id}/replay`} className="rounded-full px-2.5 py-1 text-[12px] text-fg-2 hover:bg-white/[.06]">
          Replay
        </Link>
      </div>
    </li>
  );
}

function OpenByIdDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
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
          router.push(`/app/investigations/${encodeURIComponent(v)}`);
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
