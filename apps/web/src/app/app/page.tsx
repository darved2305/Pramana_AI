"use client";

import Link from "next/link";
import { Badge, ButtonLink, Card, CardHeader, EmptyState, PageHeader, PreviewBadge } from "@/components/ui";
import {
  IconBuilding,
  IconChevronRight,
  IconHistory,
  IconPlus,
  IconUsers,
  IconPhone,
} from "@/components/ui/icons";
import { usePreviewMode } from "@/lib/store/local";
import { useDirectory, useInvestigationList, usePack } from "@/lib/data/hooks";
import { STATUS_LABEL, STATUS_TONE, relative } from "@/lib/data/derive";
import type { InvestigationStatus } from "@/lib/api/types";

const ACTIVE: InvestigationStatus[] = ["investigating", "awaiting_approval", "acting", "verifying"];
const ALL = { limit: 1 };
const RUNNING = { status: ACTIVE, limit: 4 };

export default function OverviewPage() {
  const preview = usePreviewMode();
  const pack = usePack("campus_block_c");
  const directory = useDirectory("campus_block_c");
  const people = directory.data ?? [];
  const all = useInvestigationList(ALL);
  const running = useInvestigationList(RUNNING);
  const total = all.data?.total ?? 0;
  const active = (running.data?.items ?? []).map((r) => ({
    id: r.id,
    createdAt: r.created_at,
    report: r.report_text,
    reporter: r.reporter_id,
    lastStatus: r.status as string,
  }));

  const steps = [
    {
      href: "/app/sites",
      icon: IconBuilding,
      title: "Choose a site",
      body: "Load the building model: floors, rooms, closets and what can be checked where.",
      done: pack.status === "ready",
    },
    {
      href: "/app/participants",
      icon: IconUsers,
      title: "Add participants",
      body: "The people who can look, listen and act on site, with their roles and languages.",
      done: preview || people.length > 0,
    },
    {
      href: "/app/investigations/new",
      icon: IconPlus,
      title: "Create an investigation",
      body: "Describe the problem in the reporter's words. Pramana takes it from there.",
      done: total > 0,
    },
  ];

  return (
    <div className="flex flex-col gap-4">
      <PageHeader title="Overview" eyebrow={preview ? <PreviewBadge /> : undefined} />

      <div className="grid gap-4 lg:grid-cols-[1.5fr_1fr]">
        <Card className="p-5">
          <h2 className="font-serif text-[clamp(30px,3vw,40px)] leading-[1.1] tracking-[0.02em] text-accent">Start here</h2>
          <p className="mt-1 text-[15px] tracking-[0.01em] text-fg-2">
            Three steps from a complaint to an investigation that asks the right people.
          </p>
          <ol className="mt-4">
            {steps.map((s, i) => (
              <li key={s.href} className="border-b border-line last:border-none">
                <Link href={s.href} className="group flex items-center gap-4 rounded-[12px] px-2 py-4 transition-colors hover:bg-white/[.025]">
                  <span className="grid h-12 w-12 shrink-0 place-items-center rounded-[12px] bg-accent-soft text-accent">
                    <s.icon />
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="flex items-center gap-2 text-[16px] font-medium text-fg">
                      <span className="text-muted">{i + 1}.</span> {s.title}
                      {s.done ? <Badge tone="ok">Done</Badge> : null}
                    </span>
                    <span className="mt-0.5 block text-[14px] text-muted">{s.body}</span>
                  </span>
                  <IconChevronRight className="shrink-0 text-muted transition-transform duration-300 group-hover:translate-x-0.5" />
                </Link>
              </li>
            ))}
          </ol>
        </Card>

        <Card className="flex flex-col p-4">
          <CardHeader title="Current activity" subtitle="Investigations that can still change" className="px-1 pt-1" />
          <div className="mt-3 flex flex-1 flex-col gap-2">
            {active.length === 0 ? (
              <EmptyState
                className="flex-1 py-8"
                icon={<IconHistory />}
                title="Nothing in progress"
                body="Investigations appear here while they are running."
                action={
                  <ButtonLink href="/app/investigations/new" variant="primary">
                    <IconPlus className="h-4 w-4" /> New investigation
                  </ButtonLink>
                }
              />
            ) : (
              active.slice(0, 4).map((h) => (
                <Link
                  key={h.id}
                  href={`/app/investigations/${h.id}`}
                  className="group rounded-[12px] border-[0.8px] border-line p-4 transition-colors hover:bg-white/[.03]"
                >
                  <div className="flex items-center justify-between gap-3">
                    <Badge tone={STATUS_TONE[(h.lastStatus as InvestigationStatus) ?? "investigating"]} dot>
                      {STATUS_LABEL[(h.lastStatus as InvestigationStatus) ?? "investigating"]}
                    </Badge>
                    <span className="text-[12px] text-muted">{relative(h.createdAt)}</span>
                  </div>
                  <p className="mt-2 line-clamp-2 text-[15px] text-fg">&ldquo;{h.report}&rdquo;</p>
                  <p className="mt-1 text-[13px] text-muted">Reported by {h.reporter}</p>
                </Link>
              ))
            )}
          </div>
        </Card>
      </div>

      <div className="grid gap-4 md:grid-cols-3">
        <QuickCard
          href="/app/investigations"
          icon={<IconHistory />}
          title="Investigations"
          body={all.status === "error" ? "List unavailable" : total ? `${total} in the core` : "None yet"}
        />
        <QuickCard
          href="/app/participants"
          icon={<IconUsers />}
          title="Participants"
          body={directory.status === "error" ? "Directory unavailable" : people.length ? `${people.length} in the directory` : "Directory is empty"}
        />
        <QuickCard
          href="/app/sites"
          icon={<IconBuilding />}
          title="Sites"
          body={
            pack.status === "ready"
              ? pack.data.title
              : pack.status === "error"
                ? "Site model unavailable"
                : "Loading site model..."
          }
        />
      </div>

      <Card className="flex flex-wrap items-center justify-between gap-4 p-5">
        <div className="flex items-center gap-4">
          <span className="grid h-12 w-12 place-items-center rounded-[12px] bg-white/[.05] text-fg-2">
            <IconPhone />
          </span>
          <div>
            <p className="text-[16px] font-medium">Participant experience</p>
            <p className="text-[14px] text-muted">
              Each participant answers on their phone through a personal link created from the investigation.
            </p>
          </div>
        </div>
        <ButtonLink href={preview ? `/join/preview` : "/app/investigations"}>
          {preview ? "Open the preview participant page" : "Create links from an investigation"}
        </ButtonLink>
      </Card>
    </div>
  );
}

function QuickCard({ href, icon, title, body }: { href: string; icon: React.ReactNode; title: string; body: string }) {
  return (
    <Link href={href} className="card group flex items-center gap-4 p-4 transition-colors hover:bg-card-2">
      <span className="grid h-11 w-11 shrink-0 place-items-center rounded-[12px] bg-white/[.05] text-fg-2">{icon}</span>
      <span className="min-w-0 flex-1">
        <span className="block text-[16px] font-medium text-fg">{title}</span>
        <span className="block truncate text-[14px] text-muted">{body}</span>
      </span>
      <IconChevronRight className="text-muted transition-transform duration-300 group-hover:translate-x-0.5" />
    </Link>
  );
}
