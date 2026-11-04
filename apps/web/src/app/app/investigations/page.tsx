"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useMemo, useState } from "react";
import {
  Badge,
  Button,
  ButtonLink,
  Card,
  Dialog,
  EmptyState,
  Field,
  Input,
  Notice,
  PageHeader,
  PreviewBadge,
  Tabs,
} from "@/components/ui";
import { IconHistory, IconPlus, IconSearch, IconTrash } from "@/components/ui/icons";
import { history, useHistory, usePreviewMode, type HistoryEntry } from "@/lib/store/local";
import { STATUS_LABEL, STATUS_TONE, relative } from "@/lib/data/derive";
import { PREVIEW_ID } from "@/lib/preview/ids";
import type { InvestigationStatus } from "@/lib/api/types";

type Filter = "all" | "active" | "settled";
const ACTIVE: string[] = ["investigating", "awaiting_approval", "acting", "verifying"];

export default function InvestigationsPage() {
  return (
    <Suspense>
      <InvestigationsInner />
    </Suspense>
  );
}

function InvestigationsInner() {
  const params = useSearchParams();
  const router = useRouter();
  const preview = usePreviewMode();
  const stored = useHistory();
  const [q, setQ] = useState(params.get("q") ?? "");
  const [filter, setFilter] = useState<Filter>("all");
  const [openId, setOpenId] = useState(false);
  const [removing, setRemoving] = useState<HistoryEntry | null>(null);

  const rows: HistoryEntry[] = useMemo(
    () =>
      preview
        ? [
            {
              id: PREVIEW_ID,
              createdAt: "2026-11-04T09:12:00Z",
              packId: "campus_block_c",
              report: "Floor 3 pe WiFi nahi chal raha",
              reporter: "Riya",
              lastStatus: "investigating",
            },
          ]
        : stored,
    [preview, stored],
  );

  const filtered = rows.filter((r) => {
    const s = r.lastStatus ?? "investigating";
    if (filter === "active" && !ACTIVE.includes(s)) return false;
    if (filter === "settled" && ACTIVE.includes(s)) return false;
    const needle = q.trim().toLowerCase();
    if (!needle) return true;
    return [r.id, r.report, r.reporter, r.packId].some((v) => v.toLowerCase().includes(needle));
  });

  const counts = {
    all: rows.length,
    active: rows.filter((r) => ACTIVE.includes(r.lastStatus ?? "investigating")).length,
    settled: rows.filter((r) => !ACTIVE.includes(r.lastStatus ?? "investigating")).length,
  };

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

      {!preview ? (
        <Notice>
          The core does not list investigations yet, so this history holds the ones started from this browser. Open any
          other investigation by its ID.
        </Notice>
      ) : null}

      <div className="flex flex-wrap items-center justify-between gap-3">
        <Tabs<Filter>
          label="Filter investigations"
          value={filter}
          onChange={setFilter}
          items={[
            { value: "all", label: "All", count: counts.all },
            { value: "active", label: "In progress", count: counts.active },
            { value: "settled", label: "Settled", count: counts.settled },
          ]}
        />
        <div className="flex h-[38px] w-full max-w-[300px] items-center gap-2 rounded-full border-[0.8px] border-line px-3.5 focus-within:border-accent/60">
          <IconSearch className="h-4 w-4 text-muted" />
          <label htmlFor="inv-filter" className="sr-only">
            Filter by report, reporter or ID
          </label>
          <input
            id="inv-filter"
            value={q}
            onChange={(e) => {
              setQ(e.target.value);
              router.replace(`/app/investigations${e.target.value ? `?q=${encodeURIComponent(e.target.value)}` : ""}`, { scroll: false });
            }}
            placeholder="Filter by report, reporter or ID"
            className="w-full bg-transparent text-[14px] outline-none placeholder:text-muted"
          />
        </div>
      </div>

      {rows.length === 0 ? (
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
      ) : filtered.length === 0 ? (
        <Card>
          <EmptyState title="No matches" body="Nothing matches this filter. Clear the search or pick another tab." action={<Button onClick={() => { setQ(""); setFilter("all"); }}>Clear filters</Button>} />
        </Card>
      ) : (
        <ul className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {filtered.map((r) => {
            const s = (r.lastStatus as InvestigationStatus) ?? "investigating";
            return (
              <li key={r.id} className="card group relative flex flex-col p-4 transition-colors hover:bg-card-2">
                <div className="flex items-center justify-between gap-2">
                  <Badge tone={STATUS_TONE[s]} dot>
                    {STATUS_LABEL[s]}
                  </Badge>
                  <span className="text-[12px] text-muted">{relative(r.createdAt)}</span>
                </div>
                <Link href={`/app/investigations/${r.id}`} className="mt-3 block text-[16px] leading-snug text-fg after:absolute after:inset-0 after:rounded-[16px]">
                  &ldquo;{r.report}&rdquo;
                </Link>
                <p className="mt-1.5 text-[13px] text-muted">
                  {r.reporter} · {r.packId}
                </p>
                <div className="relative z-10 mt-4 flex items-center justify-between gap-2 border-t border-line pt-3">
                  <span className="truncate font-mono text-[11px] text-muted">{r.id}</span>
                  <div className="flex items-center gap-1">
                    <Link href={`/app/investigations/${r.id}/replay`} className="rounded-full px-2.5 py-1 text-[12px] text-fg-2 hover:bg-white/[.06]">
                      Replay
                    </Link>
                    {!preview ? (
                      <button
                        type="button"
                        onClick={() => setRemoving(r)}
                        className="grid h-7 w-7 place-items-center rounded-full text-muted hover:bg-white/[.06] hover:text-bad"
                        aria-label={`Remove ${r.id} from this browser's history`}
                      >
                        <IconTrash className="h-4 w-4" />
                      </button>
                    ) : null}
                  </div>
                </div>
              </li>
            );
          })}
        </ul>
      )}

      <OpenByIdDialog open={openId} onClose={() => setOpenId(false)} />
      <Dialog
        open={!!removing}
        onClose={() => setRemoving(null)}
        title="Remove from history?"
        description="This only forgets the link in this browser. The investigation itself stays in the core."
        footer={
          <>
            <Button onClick={() => setRemoving(null)}>Cancel</Button>
            <Button
              variant="danger"
              onClick={() => {
                if (removing) history.remove(removing.id);
                setRemoving(null);
              }}
            >
              Remove
            </Button>
          </>
        }
      />
    </div>
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
