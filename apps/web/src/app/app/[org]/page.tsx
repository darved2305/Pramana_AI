"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { clsx } from "clsx";
import { Badge, Button, ButtonLink, Card, ErrorState, PageHeader, ProbBar, Skeleton } from "@/components/ui";
import { IconBuilding, IconCheck, IconChevronRight, IconEye, IconEyeOff, IconPlus, IconSpark } from "@/components/ui/icons";
import { accountApi, actionKey } from "@/lib/api/account";
import { describeError } from "@/lib/api/http";
import type { HomeInvestigation, HomeModule, HomeSite, InvestigationStatus } from "@/lib/api/types";
import { refreshAccount } from "@/lib/data/account";
import { STATUS_LABEL, STATUS_TONE, relative } from "@/lib/data/derive";
import { useLoad } from "@/lib/data/hooks";
import { useWorkspace } from "@/lib/org/context";

type ModuleId = HomeModule["id"];

function greeting(now = new Date()) {
  const h = now.getHours();
  return h < 12 ? "Good morning" : h < 17 ? "Good afternoon" : "Good evening";
}

export default function WorkspaceHomePage() {
  const ws = useWorkspace();
  const home = useLoad(`home|${ws.org.id}`, (signal) => ws.api.home(signal));
  const [layoutError, setLayoutError] = useState<string | null>(null);
  const remembered = useRef(false);

  // Remember this workspace as the last one used, so the next sign-in lands here.
  useEffect(() => {
    if (remembered.current || ws.account.preferences.last_org_id === ws.org.id) return;
    remembered.current = true;
    accountApi.savePreferences({ last_org_id: ws.org.id }, actionKey("last-org")).catch(() => {
      remembered.current = false; // retried on the next visit; nothing for the person to do
    });
  }, [ws.account.preferences.last_org_id, ws.org.id]);

  const saved = ws.account.preferences.home_layout;
  const layout = { pins: saved?.pins ?? [], hides: saved?.hides ?? [], checklist_dismissed: saved?.checklist_dismissed ?? false };
  async function saveLayout(next: { pins?: string[]; hides?: string[]; checklist_dismissed?: boolean }) {
    setLayoutError(null);
    try {
      await accountApi.savePreferences({ home_layout: { ...layout, ...next } }, actionKey("home-layout"));
      await refreshAccount();
      home.reload();
    } catch (e) {
      setLayoutError(describeError(e));
    }
  }
  const pin = (id: ModuleId, on: boolean) =>
    saveLayout({ pins: on ? [id, ...layout.pins.filter((p) => p !== id)].slice(0, 10) : layout.pins.filter((p) => p !== id) });
  const hide = (id: ModuleId) =>
    saveLayout({ hides: [...layout.hides.filter((h) => h !== id), id].slice(0, 10), pins: layout.pins.filter((p) => p !== id) });
  const unhide = (id: ModuleId) => saveLayout({ hides: layout.hides.filter((h) => h !== id) });

  return (
    <div className="flex flex-col gap-6 pt-4">
      <PageHeader
        eyebrow={<Badge tone="accent">{ws.org.name}</Badge>}
        title={home.status === "ready" ? `${greeting()}, ${home.data.greeting_name}` : greeting()}
        subtitle="What needs you first, and why. Pin what you check every day; hide what you do not need."
        actions={
          ws.canOperate ? (
            <ButtonLink href={`${ws.base}/investigations/new`} variant="primary">
              <IconPlus /> Report a problem
            </ButtonLink>
          ) : null
        }
      />
      {layoutError ? <p role="alert" className="text-[13px] text-bad">{layoutError}</p> : null}

      {home.status === "loading" ? (
        <div className="grid gap-4 lg:grid-cols-2" aria-busy="true" aria-label="Loading your home">
          <Skeleton className="h-48" />
          <Skeleton className="h-48" />
        </div>
      ) : home.status === "error" ? (
        <ErrorState error={home.error} onRetry={home.reload} />
      ) : (
        <>
          <div className="grid gap-4 lg:grid-cols-2">
            {home.data.modules.map((m) => (
              <ModuleCard
                key={m.id}
                module={m}
                base={ws.base}
                wide={m.id === "setup" || m.id === "sites"}
                onPin={(on) => pin(m.id, on)}
                onHide={() => hide(m.id)}
                onDismissSetup={() => saveLayout({ checklist_dismissed: true })}
              />
            ))}
          </div>
          {home.data.hidden?.length ? (
            <div className="flex flex-wrap items-center gap-2 text-[13px] text-muted">
              <span>Hidden:</span>
              {home.data.hidden.map((id) => (
                <button key={id} type="button" onClick={() => unhide(id)} className="inline-flex items-center gap-1.5 rounded-full px-3 py-1 shadow-[inset_0_0_0_0.8px_var(--app-line)] hover:text-fg">
                  <IconEye /> Show {id}
                </button>
              ))}
            </div>
          ) : null}
        </>
      )}
    </div>
  );
}

function ModuleCard({
  module: m,
  base,
  wide,
  onPin,
  onHide,
  onDismissSetup,
}: {
  module: HomeModule;
  base: string;
  wide: boolean;
  onPin: (on: boolean) => void;
  onHide: () => void;
  onDismissSetup: () => void;
}) {
  return (
    <Card className={clsx("flex flex-col gap-4 p-5", wide && "lg:col-span-2")} aria-labelledby={`home-${m.id}`}>
      <header className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 id={`home-${m.id}`} className="text-[16px] font-semibold text-fg">
            {m.title} {m.pinned ? <Badge tone="accent">Pinned</Badge> : null}
          </h2>
          <p className="mt-1 flex items-start gap-1.5 text-[13px] leading-snug text-muted">
            <IconSpark className="mt-[2px] shrink-0" aria-hidden />
            <span>
              <span className="sr-only">Why this is here: </span>
              {m.reason}
            </span>
          </p>
        </div>
        <div className="flex shrink-0 gap-1">
          <Button size="sm" variant="ghost" onClick={() => onPin(!m.pinned)} aria-pressed={m.pinned}>
            {m.pinned ? "Unpin" : "Pin"}
          </Button>
          <Button size="sm" variant="ghost" onClick={onHide} aria-label={`Hide ${m.title}`}>
            <IconEyeOff />
          </Button>
        </div>
      </header>
      {m.steps?.length ? <Checklist steps={m.steps} base={base} onDismiss={onDismissSetup} /> : null}
      {m.sites?.length ? <SiteGrid sites={m.sites} base={base} /> : null}
      {m.investigations?.length ? <InvestigationList items={m.investigations} base={base} /> : null}
    </Card>
  );
}

function Checklist({ steps, base, onDismiss }: { steps: NonNullable<HomeModule["steps"]>; base: string; onDismiss: () => void }) {
  const done = steps.filter((s) => s.done).length;
  return (
    <div className="flex flex-col gap-3">
      <ProbBar value={done / steps.length} label={`${done} of ${steps.length} steps done`} />
      <ol className="grid gap-2 sm:grid-cols-2 xl:grid-cols-5">
        {steps.map((s, i) => (
          <li key={s.id}>
            <Link
              href={s.href ? `${base}/${s.href}` : base}
              className={clsx(
                "flex h-full items-start gap-2.5 rounded-[12px] p-3 text-[13px] transition-colors shadow-[inset_0_0_0_0.8px_var(--app-line)]",
                s.done ? "text-muted" : "text-fg hover:bg-white/[.04]",
              )}
              aria-label={`${s.label}${s.done ? " (done)" : ""}`}
            >
              <span className={clsx("grid h-6 w-6 shrink-0 place-items-center rounded-full text-[12px]", s.done ? "bg-ok/15 text-ok" : "bg-accent-soft text-accent")}>
                {s.done ? <IconCheck /> : i + 1}
              </span>
              <span className={clsx(s.done && "line-through decoration-white/20")}>{s.label}</span>
            </Link>
          </li>
        ))}
      </ol>
      <div>
        <Button size="sm" variant="ghost" onClick={onDismiss}>
          I know my way around, hide this
        </Button>
      </div>
    </div>
  );
}

const DRAFT_LABEL: Record<HomeSite["draft"], string | null> = {
  none: null,
  unchecked: "Draft to check",
  healthy: "Draft ready to publish",
  problems: "Draft has problems",
};

function SiteGrid({ sites, base }: { sites: HomeSite[]; base: string }) {
  return (
    <ul className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
      {sites.map((s) => (
        <li key={s.id}>
          <Link href={`${base}/sites/${s.id}`} className="group flex h-full flex-col gap-2 rounded-[12px] p-4 shadow-[inset_0_0_0_0.8px_var(--app-line)] transition-colors hover:bg-white/[.04]">
            <span className="flex items-center gap-2 text-[14px] font-medium text-fg">
              <IconBuilding aria-hidden /> {s.name}
              <IconChevronRight className="ml-auto opacity-0 transition-opacity group-hover:opacity-100" aria-hidden />
            </span>
            <span className="flex flex-wrap gap-1.5">
              <Badge tone={s.mode === "sandbox" ? "info" : "accent"}>{s.mode === "sandbox" ? "Practice" : "Your site"}</Badge>
              {s.model_version ? <Badge tone="ok">Model v{s.model_version}</Badge> : <Badge>Not modelled yet</Badge>}
              {DRAFT_LABEL[s.draft] ? <Badge tone={s.draft === "problems" ? "bad" : "warn"}>{DRAFT_LABEL[s.draft]}</Badge> : null}
            </span>
            <span className="text-[12px] text-muted">
              {s.open_investigations ? `${s.open_investigations} open investigation${s.open_investigations === 1 ? "" : "s"}` : "No open investigations"}
            </span>
          </Link>
        </li>
      ))}
    </ul>
  );
}

function InvestigationList({ items, base }: { items: HomeInvestigation[]; base: string }) {
  return (
    <ul className="flex flex-col divide-y divide-white/[.06]">
      {items.map((i) => {
        const status = i.status as InvestigationStatus;
        return (
          <li key={i.id}>
            <Link href={`${base}/investigations/${i.id}`} className="flex items-center gap-3 py-3 hover:text-fg">
              <div className="min-w-0 flex-1">
                <p className="truncate text-[14px] text-fg">{i.report_text || "Untitled report"}</p>
                <p className="mt-0.5 truncate text-[12px] text-muted">
                  {i.decision_label ?? "Still narrowing down the cause"} · {relative(i.updated_at)}
                </p>
                {i.decision_probability != null ? (
                  <ProbBar className="mt-1.5 max-w-[220px]" value={i.decision_probability} label={`${Math.round(i.decision_probability * 100)}% confident`} />
                ) : null}
              </div>
              <Badge tone={STATUS_TONE[status] ?? "muted"}>{STATUS_LABEL[status] ?? i.status}</Badge>
            </Link>
          </li>
        );
      })}
    </ul>
  );
}
