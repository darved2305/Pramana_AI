"use client";

import Link from "next/link";
import { useEffect } from "react";
import { Badge, ErrorState, ProbBar, Skeleton } from "@/components/ui";
import type { InvestigationStatus, InvestigationSummary } from "@/lib/api/types";
import { relative } from "@/lib/data/derive";
import { useInvestigationList } from "@/lib/data/hooks";
import { useInvestigationScope } from "@/lib/data/scope";

/** Where every investigation is, by stage: what each one is waiting on is the column it sits in. */
const COLUMNS: { title: string; hint: string; statuses: InvestigationStatus[] }[] = [
  { title: "Asking people", hint: "Questions are out", statuses: ["investigating"] },
  { title: "Decided", hint: "Propose the repair", statuses: ["decided"] },
  { title: "Waiting for approval", hint: "An approver must say yes", statuses: ["awaiting_approval"] },
  { title: "Being repaired", hint: "Someone is acting", statuses: ["acting"] },
  { title: "Checking the repair", hint: "Asking again to confirm", statuses: ["verifying"] },
  { title: "Concluded", hint: "Verified, held back or closed", statuses: ["verified", "not_verified", "abstained", "closed"] },
];
const QUERY = { limit: 100 };
const REFRESH_MS = 10_000;

export function InvestigationBoard() {
  const scope = useInvestigationScope();
  const list = useInvestigationList(QUERY);
  const { reload } = list;
  useEffect(() => {
    const t = setInterval(reload, REFRESH_MS);
    return () => clearInterval(t);
  }, [reload]);

  if (list.status === "loading") return <Skeleton className="h-[320px]" />;
  if (list.status === "error") return <ErrorState error={list.error} onRetry={list.reload} />;
  const rows = list.data.items;
  return (
    <div className="grid gap-3 md:grid-cols-3 xl:grid-cols-6" aria-label="Investigations by stage">
      {COLUMNS.map((col) => {
        const items = rows.filter((r) => col.statuses.includes(r.status));
        return (
          <section key={col.title} aria-label={col.title} className="flex min-h-[160px] flex-col gap-2 rounded-[16px] bg-white/[.02] p-3 shadow-[inset_0_0_0_0.8px_var(--app-line)]">
            <header className="flex items-baseline justify-between gap-2">
              <h2 className="text-[13px] font-semibold text-fg">{col.title}</h2>
              <span className="tabular-nums text-[12px] text-muted">{items.length}</span>
            </header>
            <p className="-mt-1 text-[11px] text-muted">{col.hint}</p>
            <ul className="flex flex-col gap-2">
              {items.map((r) => (
                <BoardCard key={r.id} r={r} href={`${scope.base}/investigations/${r.id}`} />
              ))}
            </ul>
          </section>
        );
      })}
    </div>
  );
}

function BoardCard({ r, href }: { r: InvestigationSummary; href: string }) {
  return (
    <li>
      <Link href={href} className="flex flex-col gap-1.5 rounded-[12px] bg-card p-3 text-[13px] transition-colors hover:bg-card-2">
        <span className="line-clamp-2 text-fg">{r.report_text}</span>
        <span className="text-[11px] text-muted">
          {r.participant_count} {r.participant_count === 1 ? "person" : "people"} · {relative(r.updated_at)}
        </span>
        {r.decision_probability != null ? (
          <ProbBar value={r.decision_probability} label={`${Math.round(r.decision_probability * 100)}% sure`} />
        ) : null}
        {r.status === "not_verified" ? <Badge tone="bad">Repair did not hold</Badge> : null}
      </Link>
    </li>
  );
}
