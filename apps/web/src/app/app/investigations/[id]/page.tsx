"use client";

import { useInvestigationScope } from "@/lib/data/scope";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useMemo, useState } from "react";
import {
  Badge,
  Button,
  ButtonLink,
  Card,
  CardHeader,
  Dialog,
  ErrorState,
  Notice,
  PreviewBadge,
  Skeleton,
} from "@/components/ui";
import { IconArrowLeft, IconCopy, IconLink, IconLock, IconPlay } from "@/components/ui/icons";
import { BuildingMap } from "@/components/app/BuildingMap";
import { Avatar } from "@/components/app/Avatar";
import { DecisionBar, DiagnosisPanel, HypothesisPanel, ReasoningPanel } from "@/components/console/BeliefPanels";
import { ApprovalPanel, ContradictionPanel, ConversationPanel, EvidenceLedger, TestimonyPanel } from "@/components/console/ActivityPanels";
import { ForecastPanel } from "@/components/console/ForecastPanel";
import { useInvestigation, useInvestigationPack } from "@/lib/data/hooks";
import { useCurrentUser } from "@/lib/data/session";
import { hasRole } from "@/lib/api/auth";
import { STATUS_LABEL, STATUS_TONE, findContradictions, locationLabel, outcomeWord, participantName, probeLabel, relative } from "@/lib/data/derive";
import { ApiError, describeError } from "@/lib/api/http";
import { encodeJoin } from "@/lib/join";
import type { InvestigationState, SitePack } from "@/lib/api/types";

export default function CommandCenterPage() {
  const { id } = useParams<{ id: string }>();
  return <CommandCenterRoute key={id} id={id} />;
}

function CommandCenterRoute({ id }: { id: string }) {
  const feed = useInvestigation(id);
  const pack = useInvestigationPack(feed.state);
  const [linksOpen, setLinksOpen] = useState(false);
  const [revealOpen, setRevealOpen] = useState(false);
  const readOnly = feed.source === "preview";

  if (feed.status === "loading") return <LoadingCenter />;
  if (feed.status === "error" || !feed.state) {
    const notFound = feed.error instanceof ApiError && feed.error.status === 404;
    return (
      <div className="flex flex-col gap-4">
        <BackLink />
        <Card>
          {notFound ? (
            <ErrorState error={new ApiError(404, "NOT_FOUND", `No investigation with the ID ${id} exists in the core.`, null)} />
          ) : (
            <ErrorState error={feed.error} onRetry={feed.refresh} />
          )}
        </Card>
      </div>
    );
  }

  const s = feed.state;
  return (
    <CommandCenter
      s={s}
      pack={pack.data}
      packError={pack.status === "error" ? pack.error : null}
      feed={feed}
      readOnly={readOnly}
      onLinks={() => setLinksOpen(true)}
      onReveal={() => setRevealOpen(true)}
    >
      <LinksDialog open={linksOpen} onClose={() => setLinksOpen(false)} state={s} preview={readOnly} />
      <RevealDialog open={revealOpen} onClose={() => setRevealOpen(false)} state={s} onState={feed.apply} />
    </CommandCenter>
  );
}

function CommandCenter({
  s,
  pack,
  packError,
  feed,
  readOnly,
  onLinks,
  onReveal,
  children,
}: {
  s: InvestigationState;
  pack?: SitePack;
  packError: unknown;
  feed: ReturnType<typeof useInvestigation>;
  readOnly: boolean;
  onLinks: () => void;
  onReveal: () => void;
  children: React.ReactNode;
}) {
  const scope = useInvestigationScope();
  const [selected, setSelected] = useState<string | null>(null);
  const contradictions = useMemo(() => findContradictions(s.observations), [s.observations]);
  // Only an operator may reveal (the core enforces it); approvers do not see the button.
  const me = useCurrentUser();
  const isOperator = me ? hasRole(me, "operator") : true;
  const canReveal = isOperator && !s.ground_truth && ["decided", "abstained", "verified", "not_verified"].includes(s.status);
  const [copied, setCopied] = useState(false);

  return (
    <div className="flex flex-col gap-4">
      <BackLink />
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone={STATUS_TONE[s.status]} dot>
              {STATUS_LABEL[s.status]}
            </Badge>
            {feed.source === "preview" ? (
              <PreviewBadge />
            ) : feed.live ? (
              <Badge tone="ok">
                <span className="h-1.5 w-1.5 rounded-full bg-current pulse-dot" /> Live
              </Badge>
            ) : (
              <Badge>Not polling: investigation closed</Badge>
            )}
            <span className="text-[13px] text-muted">Opened {relative(s.created_at)}</span>
          </div>
          <h1 className="mt-3 max-w-[30ch] font-serif text-[clamp(28px,3.4vw,44px)] leading-[1.1] tracking-[0.015em]">
            &ldquo;{s.report.text}&rdquo;
          </h1>
          <p className="mt-2 text-[14px] text-muted">
            Reported by {participantName(s, s.report.reporter_id)}
            {s.report.affected_location_id ? ` at ${locationLabel(pack, s.report.affected_location_id)}` : ""} · {pack?.title ?? s.pack_id} ·{" "}
            <span className="font-mono text-[12px]">{s.id}</span>
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <ButtonLink href={`${scope.base}/investigations/${s.id}/replay`}>
            <IconPlay className="h-4 w-4" /> Replay
          </ButtonLink>
          <Button onClick={onLinks}>
            <IconLink className="h-4 w-4" /> Participant links
          </Button>
          {canReveal && !readOnly ? (
            <Button variant="primary" onClick={onReveal}>
              Reveal ground truth
            </Button>
          ) : null}
        </div>
      </header>

      <button
        type="button"
        onClick={() => {
          navigator.clipboard?.writeText(s.sealed_commitment).then(() => {
            setCopied(true);
            setTimeout(() => setCopied(false), 1500);
          });
        }}
        className="group flex w-full items-center gap-3 rounded-[12px] border-[0.8px] border-line bg-white/[.02] px-3.5 py-2.5 text-left transition-colors hover:bg-white/[.04]"
        title="Copy the commitment"
      >
        <IconLock className="h-4 w-4 shrink-0 text-accent" />
        <span className="shrink-0 text-[13px] text-fg-2">Sealed fault commitment</span>
        <span className="min-w-0 flex-1 truncate font-mono text-[12px] text-muted">{s.sealed_commitment}</span>
        <span className="shrink-0 text-[12px] text-muted group-hover:text-fg" aria-live="polite">
          {copied ? "Copied" : <IconCopy className="h-4 w-4" />}
        </span>
      </button>

      {feed.error && feed.status === "ready" ? (
        <Notice tone="bad">Lost contact with the core. Showing the last known state. {describeError(feed.error)}</Notice>
      ) : null}

      {/* Row 1: environment + belief */}
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1.55fr)_minmax(0,1fr)]">
        <Card className="p-4" aria-labelledby="env-title">
          <CardHeader
            id="env-title"
            title="Environment"
            subtitle="People, places and what has been observed in each"
            action={(s.pending_questions?.length ?? 0) > 1 ? <Badge tone="info">Asking {s.pending_questions?.length} people at once</Badge> : s.pending_question ? <Badge tone="info">Asking about {locationLabel(pack, s.pending_question.action.location_id).replace(/^the /, "")}</Badge> : undefined}
          />
          <div className="mt-4">
            {pack ? (
              <BuildingMap
                pack={pack}
                selected={selected}
                onSelect={(id) => setSelected((x) => (x === id ? null : id))}
                overlay={{
                  participants: s.participants,
                  observations: s.observations,
                  affectedId: s.report.affected_location_id,
                  focusId: s.pending_question?.action.location_id,
                  askingId: s.pending_question?.action.participant_id,
                }}
              />
            ) : packError ? (
              <ErrorState error={packError} />
            ) : (
              <Skeleton className="h-[380px]" />
            )}
          </div>
          {selected && pack ? <PlaceDetail id={selected} s={s} pack={pack} onClose={() => setSelected(null)} /> : null}
        </Card>
        <div className="flex flex-col gap-4">
          <HypothesisPanel state={s} />
          <DecisionBar state={s} />
          <ForecastPanel state={s} />
        </div>
      </div>

      {/* Row 2: conversation + reasoning */}
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <ConversationPanel state={s} pack={pack} readOnly={readOnly} onState={feed.apply} onLinks={onLinks} />
        <ReasoningPanel state={s} pack={pack} />
      </div>

      <EvidenceLedger state={s} pack={pack} />

      <TestimonyPanel state={s} pack={pack} />

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
        <ContradictionPanel items={contradictions} state={s} pack={pack} />
        <ApprovalPanel state={s} pack={pack} readOnly={readOnly} onState={feed.apply} />
        <DiagnosisPanel state={s} pack={pack} contradictions={contradictions.length} />
      </div>
      {children}
    </div>
  );
}

function PlaceDetail({ id, s, pack, onClose }: { id: string; s: InvestigationState; pack: SitePack; onClose: () => void }) {
  const loc = pack.locations.find((l) => l.id === id);
  const obs = s.observations.filter((o) => o.location_id === id);
  const people = s.participants.filter((p) => p.location_id === id);
  if (!loc) return null;
  return (
    <div className="mt-4 rounded-[12px] border-[0.8px] border-line bg-white/[.02] p-3.5" aria-live="polite">
      <div className="flex items-center justify-between gap-3">
        <p className="text-[14px] font-medium capitalize">
          {loc.label.replace(/^the /, "")} <span className="font-normal text-muted">· floor {loc.floor}</span>
        </p>
        <button type="button" onClick={onClose} className="text-[13px] text-muted hover:text-fg">
          Close
        </button>
      </div>
      <p className="mt-1 text-[13px] text-muted">
        {people.length ? `Here now: ${people.map((p) => p.display_name).join(", ")}.` : "Nobody in this investigation is here."}{" "}
        {obs.length ? `${obs.length} observation${obs.length === 1 ? "" : "s"}:` : "Nothing observed here yet."}
      </p>
      {obs.length ? (
        <ul className="mt-2 flex flex-col gap-1 text-[13px]">
          {obs.map((o) => (
            <li key={o.id} className="flex flex-wrap gap-x-2">
              <span className="text-fg-2">{probeLabel(pack, o.probe_id)}:</span>
              <span className="text-fg">{outcomeWord(o.outcome)}</span>
              <span className="text-muted">({participantName(s, o.participant_id)}, {o.hedge})</span>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

function BackLink() {
  const scope = useInvestigationScope();
  return (
    <Link href={`${scope.base}/investigations`} className="inline-flex w-fit items-center gap-1.5 text-[14px] text-muted transition-colors hover:text-fg">
      <IconArrowLeft className="h-4 w-4" /> Investigations
    </Link>
  );
}

function LoadingCenter() {
  return (
    <div className="flex flex-col gap-4" aria-busy="true" aria-label="Loading investigation">
      <Skeleton className="h-5 w-32" />
      <Skeleton className="h-12 w-[60%]" />
      <Skeleton className="h-10" />
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1.55fr)_minmax(0,1fr)]">
        <Skeleton className="h-[440px] rounded-[16px]" />
        <Skeleton className="h-[440px] rounded-[16px]" />
      </div>
    </div>
  );
}

function LinksDialog({ open, onClose, state, preview }: { open: boolean; onClose: () => void; state: InvestigationState; preview: boolean }) {
  const scope = useInvestigationScope();
  const [links, setLinks] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [copied, setCopied] = useState<string | null>(null);

  const create = async (pid: string) => {
    setBusy(pid);
    setErr(null);
    try {
      const t = await scope.participantToken(state.id, pid);
      const url = `${window.location.origin}/join/${encodeJoin({ i: state.id, p: pid, s: t.scenario_id, t: t.token, ...(scope.workspace ? { o: (t as { org_id?: string }).org_id ?? scope.workspace } : {}) })}`;
      setLinks((l) => ({ ...l, [pid]: url }));
    } catch (e) {
      setErr(describeError(e));
    } finally {
      setBusy(null);
    }
  };

  return (
    <Dialog
      wide
      open={open}
      onClose={onClose}
      title="Participant links"
      description="Each person answers from their own phone through a personal link. Send it however you normally reach them."
    >
      {preview ? (
        <Notice tone="warn" className="mb-4">
          Preview links open a sample participant page. Real links are issued by the core.
        </Notice>
      ) : null}
      <ul className="flex flex-col divide-y divide-line">
        {state.participants.map((p) => {
          const link = preview ? `/join/preview?p=${p.id}` : links[p.id];
          return (
            <li key={p.id} className="flex flex-wrap items-center gap-3 py-3">
              <Avatar name={p.display_name} size={32} />
              <span className="min-w-[120px] flex-1">
                <span className="block text-[14px] font-medium">{p.display_name}</span>
                <span className="block text-[12px] text-muted">{p.roles.join(", ")}</span>
              </span>
              {link ? (
                <>
                  <a href={link} target="_blank" rel="noreferrer" className="max-w-[220px] truncate font-mono text-[12px] text-accent hover:underline">
                    {link.replace(/^https?:\/\//, "")}
                  </a>
                  {!preview ? (
                    <Button
                      size="sm"
                      onClick={() =>
                        navigator.clipboard?.writeText(link).then(() => {
                          setCopied(p.id);
                          setTimeout(() => setCopied(null), 1500);
                        })
                      }
                    >
                      {copied === p.id ? "Copied" : "Copy"}
                    </Button>
                  ) : null}
                </>
              ) : (
                <Button size="sm" onClick={() => create(p.id)} loading={busy === p.id}>
                  Create link
                </Button>
              )}
            </li>
          );
        })}
      </ul>
      {err ? <p className="mt-3 text-[13px] text-bad" role="alert">{err}</p> : null}
    </Dialog>
  );
}

function RevealDialog({ open, onClose, state, onState }: { open: boolean; onClose: () => void; state: InvestigationState; onState: (s: InvestigationState) => void }) {
  const scope = useInvestigationScope();
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="Reveal the ground truth?"
      description="The simulator discloses the hidden fault and the salt, so the sealed commitment can be checked. This closes the scenario and cannot be undone."
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button
            variant="primary"
            loading={busy}
            onClick={async () => {
              setBusy(true);
              setErr(null);
              try {
                onState(await scope.reveal(state.id));
                onClose();
              } catch (e) {
                setErr(describeError(e));
              } finally {
                setBusy(false);
              }
            }}
          >
            Reveal
          </Button>
        </>
      }
    >
      {err ? <p className="text-[13px] text-bad" role="alert">{err}</p> : null}
    </Dialog>
  );
}
