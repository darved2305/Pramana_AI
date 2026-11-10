"use client";

import { useInvestigationScope } from "@/lib/data/scope";
import { useMemo, useState } from "react";
import { clsx } from "clsx";
import { Avatar } from "@/components/app/Avatar";
import { langLabel } from "@/components/app/ParticipantForm";
import { Badge, Button, Card, CardHeader, Dialog, EmptyState, Field, Input, Notice, Select, Tabs, Tag } from "@/components/ui";
import { IconAlert, IconMic, IconShield } from "@/components/ui/icons";
import { describeError } from "@/lib/api/http";
import type { Contradiction } from "@/lib/data/derive";
import { clock, locationLabel, outcomeWord, participantName, probeLabel } from "@/lib/data/derive";
import type { Approval, InvestigationState, Observation, Question, SitePack } from "@/lib/api/types";
import { outcomeTone } from "@/components/app/BuildingMap";
import { hasRole } from "@/lib/api/auth";
import { useCurrentUser } from "@/lib/data/session";
import { useOptionalWorkspace } from "@/lib/org/context";

/* ---------- Live conversation ---------- */

export function ConversationPanel({
  state,
  pack,
  readOnly,
  onState,
  onLinks,
}: {
  state: InvestigationState;
  pack?: SitePack;
  readOnly: boolean;
  onState: (s: InvestigationState) => void;
  onLinks: () => void;
}) {
  const waiting = state.pending_questions?.length ? state.pending_questions : state.pending_question ? [state.pending_question] : [];
  const asking = new Set(waiting.map((w) => w.action.participant_id));
  const parallel = (state.max_parallel_calls ?? 1) > 1;

  return (
    <Card className="flex flex-col p-4" aria-labelledby="conv-title">
      <CardHeader
        id="conv-title"
        title="Conversation"
        subtitle={`${state.questions_asked} question${state.questions_asked === 1 ? "" : "s"} asked so far${parallel ? ` · up to ${state.max_parallel_calls} people at once` : ""}`}
        action={
          <Button size="sm" onClick={onLinks}>
            Participant links
          </Button>
        }
      />

      {waiting.length ? (
        <div className="mt-4 flex flex-col gap-3" aria-live="polite">
          {waiting.length > 1 ? (
            <p className="text-[12px] text-muted" data-testid="parallel-count">
              {waiting.length} questions out at the same time. A question is withdrawn if another answer makes it pointless.
            </p>
          ) : null}
          {waiting.map((q) => (
            <div key={q.id} className="rounded-[14px] border-[0.8px] border-info/40 bg-info/[.06] p-4" data-testid="pending-question">
              <div className="flex flex-wrap items-center gap-2">
                <span className="h-2 w-2 rounded-full bg-info pulse-dot" aria-hidden />
                <span className="text-[13px] font-medium text-info">Waiting for {participantName(state, q.action.participant_id)}</span>
                {q.kind === "confirm" ? <Badge tone="warn">Just checking</Badge> : null}
                {q.action.requires_move ? <Badge>Walk to {locationLabel(pack, q.action.location_id)}</Badge> : null}
                <span className="ml-auto text-[12px] text-muted">asked {clock(q.asked_at)}</span>
              </div>
              <p lang={q.language === "hi-en" ? "hi-Latn" : q.language} className="mt-3 text-[17px] leading-relaxed text-fg">
                {q.text}
              </p>
              <p className="mt-2 text-[12px] text-muted">
                In {langLabel(q.language)} · checks: {probeLabel(pack, q.action.probe_id)} · possible answers:{" "}
                {q.outcomes.map(outcomeWord).join(", ")}
              </p>
              {!readOnly ? <RecordAnswer key={q.id} state={state} question={q} onState={onState} /> : null}
            </div>
          ))}
        </div>
      ) : (
        <Notice className="mt-4">No question is waiting. {state.status === "investigating" ? "The planner is choosing the next one." : "The investigation has stopped asking."}</Notice>
      )}

      <ul className="mt-4 flex flex-col divide-y divide-line">
        {state.participants.map((p) => {
          const theirs = state.observations.filter((o) => o.participant_id === p.id);
          const last = theirs.at(-1);
          const isAsking = asking.has(p.id);
          return (
            <li key={p.id} className="flex gap-3 py-3">
              <div className="relative">
                <Avatar name={p.display_name} size={36} />
                <span
                  aria-hidden
                  className={clsx(
                    "absolute -bottom-0.5 -right-0.5 h-3 w-3 rounded-full border-2 border-card",
                    p.available === false ? "bg-muted" : isAsking ? "bg-info" : "bg-ok",
                  )}
                />
              </div>
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                  <span className="text-[14px] font-medium">{p.display_name}</span>
                  {p.id === state.report.reporter_id ? <Tag>reporter</Tag> : null}
                  <span className="text-[12px] text-muted">
                    {langLabel(p.languages.template_language)} · {locationLabel(pack, p.location_id)}
                  </span>
                  <span className="ml-auto text-[12px] text-muted">
                    {p.available === false ? "Unavailable" : isAsking ? "Answering" : theirs.length ? `${theirs.length} answer${theirs.length === 1 ? "" : "s"}` : "Not asked yet"}
                  </span>
                </div>
                {last?.transcript ? (
                  <p className="mt-1.5 truncate text-[13px] text-fg-2" title={last.transcript}>
                    <IconMic className="mr-1 inline h-3.5 w-3.5 align-[-2px] text-muted" />
                    &ldquo;{last.transcript}&rdquo;
                  </p>
                ) : last ? (
                  <p className="mt-1.5 text-[13px] text-fg-2">
                    Answered {outcomeWord(last.outcome)} by {last.modality}
                  </p>
                ) : null}
              </div>
            </li>
          );
        })}
      </ul>
    </Card>
  );
}

/** Lets the console record an answer someone gave by phone or in person. */
function RecordAnswer({ state, question: q, onState }: { state: InvestigationState; question: Question; onState: (s: InvestigationState) => void }) {
  const scope = useInvestigationScope();
  const [mode, setMode] = useState<"tap" | "text">("tap");
  const [text, setText] = useState("");
  const [outcome, setOutcome] = useState(q.outcomes[0] ?? "");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [understood, setUnderstood] = useState<string | null>(null);

  const send = async () => {
    if (mode === "text" && !text.trim()) return setErr("Type what they said.");
    setBusy(true);
    setErr(null);
    try {
      const r = await scope.answer(state.id, {
        question_id: q.id,
        participant_id: q.action.participant_id,
        ...(mode === "tap" ? { outcome, modality: "tap" as const } : { text: text.trim(), modality: "text" as const }),
      });
      setUnderstood(
        `Understood: ${outcomeWord(r.extraction.outcome)} (${r.extraction.hedge}, ${r.extraction.directness})${r.extraction.injection_suspected ? ". Flagged as a possible instruction injection." : ""}`,
      );
      setText("");
      onState(r.state);
    } catch (e) {
      setErr(describeError(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <details className="group mt-4 rounded-[12px] border-[0.8px] border-line bg-black/20">
      <summary className="cursor-pointer list-none px-3 py-2.5 text-[13px] text-fg-2 marker:hidden">
        <span className="group-open:hidden">Record an answer given by phone or in person</span>
        <span className="hidden group-open:inline">Record an answer for {participantName(state, q.action.participant_id)}</span>
      </summary>
      <div className="flex flex-col gap-3 px-3 pb-3">
        <Tabs<"tap" | "text">
          label="Answer type"
          value={mode}
          onChange={setMode}
          items={[
            { value: "tap", label: "Pick an answer" },
            { value: "text", label: "Their words" },
          ]}
        />
        {mode === "tap" ? (
          <div className="flex flex-wrap gap-2" role="radiogroup" aria-label="Answer">
            {q.outcomes.map((o) => (
              <button
                key={o}
                type="button"
                role="radio"
                aria-checked={outcome === o}
                onClick={() => setOutcome(o)}
                className={clsx(
                  "h-9 rounded-full px-3.5 text-[13px] transition-colors",
                  outcome === o ? "bg-accent text-accent-ink" : "shadow-[inset_0_0_0_0.8px_var(--app-line-strong)] text-fg-2 hover:text-fg",
                )}
              >
                {outcomeWord(o)}
              </button>
            ))}
          </div>
        ) : (
          <Field label="What they said" hint="Any language. Pramana extracts the answer and how sure they were.">
            {(a) => <Input {...a} value={text} onChange={(e) => setText(e.target.value)} placeholder="Haan, lights green hain" />}
          </Field>
        )}
        {err ? <p className="text-[13px] text-bad" role="alert">{err}</p> : null}
        {understood ? <p className="text-[13px] text-ok" role="status">{understood}</p> : null}
        <div className="flex justify-end">
          <Button variant="primary" size="sm" onClick={send} loading={busy}>
            Submit answer
          </Button>
        </div>
      </div>
    </details>
  );
}

/* ---------- Evidence ledger ---------- */

export function EvidenceLedger({ state, pack }: { state: InvestigationState; pack?: SitePack }) {
  const [view, setView] = useState<"all" | "committed" | "set_aside">("all");
  const [q, setQ] = useState("");
  const rows = useMemo(() => {
    return [...state.observations]
      .reverse()
      .filter((o) => (view === "all" ? true : view === "committed" ? o.state === "committed" : o.state !== "committed"))
      .filter((o) => {
        const n = q.trim().toLowerCase();
        if (!n) return true;
        return [participantName(state, o.participant_id), locationLabel(pack, o.location_id), probeLabel(pack, o.probe_id), o.outcome, o.transcript ?? ""]
          .join(" ")
          .toLowerCase()
          .includes(n);
      });
  }, [state, pack, view, q]);

  return (
    <Card className="p-4" aria-labelledby="ledger-title">
      <CardHeader id="ledger-title" title="Evidence ledger" subtitle="Every observation, who made it, where, and how much to trust it" />
      <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
        <Tabs
          label="Filter evidence"
          value={view}
          onChange={setView}
          items={[
            { value: "all", label: "All", count: state.observations.length },
            { value: "committed", label: "In use", count: state.observations.filter((o) => o.state === "committed").length },
            { value: "set_aside", label: "Set aside", count: state.observations.filter((o) => o.state !== "committed").length },
          ]}
        />
        <label className="sr-only" htmlFor="ledger-search">
          Search evidence
        </label>
        <input
          id="ledger-search"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Search evidence"
          className="h-[38px] w-full max-w-[240px] rounded-full border-[0.8px] border-line bg-transparent px-3.5 text-[14px] outline-none placeholder:text-muted focus:border-accent/60"
        />
      </div>
      {rows.length === 0 ? (
        <EmptyState className="py-10" title={state.observations.length ? "Nothing matches" : "No evidence yet"} body={state.observations.length ? "Try another filter." : "Observations appear here as people answer."} />
      ) : (
        <div className="mt-3 overflow-x-auto">
          <table className="w-full min-w-[760px] text-left text-[13px]">
            <caption className="sr-only">Observations, newest first</caption>
            <thead className="text-[11px] uppercase tracking-[0.06em] text-muted">
              <tr className="border-b border-line">
                <th className="py-2 pr-3 font-medium">Time</th>
                <th className="py-2 pr-3 font-medium">Source</th>
                <th className="py-2 pr-3 font-medium">Where</th>
                <th className="py-2 pr-3 font-medium">Observation</th>
                <th className="py-2 pr-3 font-medium">Uncertainty</th>
                <th className="py-2 font-medium">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {rows.map((o) => (
                <LedgerRow key={o.id} o={o} state={state} pack={pack} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

function LedgerRow({ o, state, pack }: { o: Observation; state: InvestigationState; pack?: SitePack }) {
  const tone = outcomeTone(o.outcome);
  return (
    <tr className={clsx("align-top", o.state !== "committed" && "opacity-55")}>
      <td className="py-3 pr-3 font-mono text-[12px] text-muted">{clock(o.committed_at)}</td>
      <td className="py-3 pr-3">
        <span className="block text-fg">{participantName(state, o.participant_id)}</span>
        <span className="text-[12px] text-muted">by {o.modality}</span>
      </td>
      <td className="py-3 pr-3 capitalize text-fg-2">{locationLabel(pack, o.location_id).replace(/^the /, "")}</td>
      <td className="py-3 pr-3">
        <span className="flex items-center gap-2">
          <span className="text-fg-2">{probeLabel(pack, o.probe_id)}:</span>
          <Badge tone={tone === "good" ? "ok" : tone === "bad" ? "bad" : "warn"}>{outcomeWord(o.outcome)}</Badge>
        </span>
        {o.transcript ? <span className="mt-1 block max-w-[46ch] text-[12px] italic text-muted">&ldquo;{o.transcript}&rdquo;</span> : null}
        {o.injection_suspected ? (
          <span className="mt-1 flex items-center gap-1 text-[12px] text-bad">
            <IconAlert className="h-3.5 w-3.5" /> Possible instruction injection
          </span>
        ) : null}
      </td>
      <td className="py-3 pr-3">
        <span className="flex flex-wrap gap-1">
          <Tag>{o.hedge}</Tag>
          <Tag>{o.directness}</Tag>
        </span>
      </td>
      <td className="py-3">
        <Badge tone={o.state === "committed" ? "ok" : o.state === "superseded" ? "warn" : "muted"}>
          {o.state === "committed" ? "In use" : o.state}
        </Badge>
      </td>
    </tr>
  );
}

/* ---------- Contradictions ---------- */

export function ContradictionPanel({ items, state, pack }: { items: Contradiction[]; state: InvestigationState; pack?: SitePack }) {
  return (
    <Card className="p-4" aria-labelledby="contra-title">
      <CardHeader
        id="contra-title"
        title="Contradictions"
        subtitle="Answers about the same thing in the same place that disagree"
        action={items.length ? <Badge tone="warn">{items.length}</Badge> : undefined}
      />
      {items.length === 0 ? (
        <EmptyState className="py-8" title="No conflicts" body="When two answers disagree, they appear here side by side with what could explain it." />
      ) : (
        <ul className="mt-4 flex flex-col gap-3">
          {items.map((c) => (
            <li key={c.key} className="rounded-[12px] border-[0.8px] border-warn/30 p-3">
              <p className="text-[14px] text-fg">
                {probeLabel(pack, c.probeId)} at {locationLabel(pack, c.locationId)}
              </p>
              <div className="mt-2 grid gap-2 sm:grid-cols-2">
                {c.observations.map((o) => (
                  <div key={o.id} className="rounded-[10px] bg-white/[.03] p-2.5 text-[13px]">
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-medium">{participantName(state, o.participant_id)}</span>
                      <Badge tone={outcomeTone(o.outcome) === "good" ? "ok" : outcomeTone(o.outcome) === "bad" ? "bad" : "warn"}>{outcomeWord(o.outcome)}</Badge>
                    </div>
                    <p className="mt-1 text-[12px] text-muted">
                      {clock(o.committed_at)} · {o.hedge} · {o.directness} · {o.state === "committed" ? "in use" : o.state}
                    </p>
                  </div>
                ))}
              </div>
              <p className="mt-3 text-[12px] uppercase tracking-[0.06em] text-muted">Possible explanations</p>
              <ul className="mt-1 list-disc pl-4 text-[13px] text-fg-2">
                {c.explanations.map((e) => (
                  <li key={e}>{e}</li>
                ))}
              </ul>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

/* ---------- Testimony: how disagreements fit, and presence checks ---------- */

const pct = (p: number) => `${Math.round(p * 100)}%`;

const CHECK_TONE = { pending: "warn", passed: "ok", failed: "bad" } as const;
const CHECK_WORD = { pending: "Waiting for the reading", passed: "Confirmed on site", failed: "Could not confirm" } as const;

export function TestimonyPanel({ state, pack }: { state: InvestigationState; pack?: SitePack }) {
  const disagreements = state.disagreements ?? [];
  const checks = state.presence_checks ?? [];
  const count = disagreements.length + checks.length;
  return (
    <Card className="p-4" aria-labelledby="testimony-title">
      <CardHeader
        id="testimony-title"
        title="Testimony"
        subtitle="Why people disagree, and checks that someone really was where they said"
        action={count ? <Badge tone="info">{count}</Badge> : undefined}
      />
      {count === 0 ? (
        <EmptyState
          className="py-8"
          title="Nothing to weigh yet"
          body={
            state.presence_checks_enabled
              ? "When two people answer differently, the engine shows how both could be right. A decisive answer from a restricted place is confirmed with a label only someone there can read."
              : "When two people answer differently, the engine shows how both could be right. Presence checks are off for this investigation."
          }
        />
      ) : (
        <ul className="mt-4 flex flex-col gap-3">
          {checks.map((c) => (
            <li key={c.question_id} className="rounded-[12px] border-[0.8px] border-line p-3" data-testid="presence-check">
              <div className="flex items-center justify-between gap-2">
                <p className="text-[14px] text-fg">
                  <IconShield className="mr-1.5 inline h-4 w-4 align-[-3px] text-muted" />
                  {participantName(state, c.participant_id)} at {locationLabel(pack, c.location_id)}
                </p>
                <Badge tone={CHECK_TONE[c.status]}>{CHECK_WORD[c.status]}</Badge>
              </div>
              <p className="mt-1 text-[13px] text-fg-2">
                {c.status === "failed"
                  ? "Their answer from there now counts for little, and someone else is asked. Nobody is accused."
                  : c.status === "passed"
                    ? "They read the label correctly, so their answer from there counts in full."
                    : "Asked to read a label only someone there can see. Until then, their answer from there counts for little."}
              </p>
            </li>
          ))}
          {disagreements.map((d) => (
            <li key={`${d.observation_id}-${d.earlier.participant_id}`} className="rounded-[12px] border-[0.8px] border-line p-3" data-testid="disagreement">
              <div className="flex items-center justify-between gap-2">
                <p className="text-[14px] text-fg">{probeLabel(pack, d.new.probe_id)}</p>
                <Badge tone={d.kind === "both_right" ? "ok" : "warn"}>{d.kind === "both_right" ? "Both can be right" : "One is likely mistaken"}</Badge>
              </div>
              <div className="mt-2 grid gap-2 sm:grid-cols-2">
                {[d.earlier, d.new].map((side) => (
                  <div key={side.participant_id} className="rounded-[10px] bg-white/[.03] p-2.5 text-[13px]">
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-medium">{participantName(state, side.participant_id)}</span>
                      <Badge tone={outcomeTone(side.outcome) === "good" ? "ok" : outcomeTone(side.outcome) === "bad" ? "bad" : "warn"}>{outcomeWord(side.outcome)}</Badge>
                    </div>
                    <p className="mt-1 text-[12px] text-muted">
                      {locationLabel(pack, side.location_id)} · mistaken {pct(side.p_mistaken)}
                    </p>
                  </div>
                ))}
              </div>
              <p className="mt-3 text-[13px] text-fg-2">{d.explanation}</p>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

/* ---------- Approvals ---------- */

export function ApprovalPanel({
  state,
  pack,
  readOnly,
  onState,
}: {
  state: InvestigationState;
  pack?: SitePack;
  readOnly: boolean;
  onState: (s: InvestigationState) => void;
}) {
  const approvals = state.approvals ?? [];
  const [requesting, setRequesting] = useState(false);
  // Repairs come from the site's own model: the actions that fix the decided cause.
  const options = state.repair_options ?? [];
  const doable = options.some((o) => o.participant_ids.length > 0);
  const canRequest = state.status === "decided" && doable && !readOnly;
  let requestHint = "Repairs can be proposed once the investigation reaches a decision.";
  if (state.status === "decided") {
    if (!options.length) requestHint = "This site's model has no on-site repair for this decision. Follow the decision itself.";
    else if (!doable) requestHint = `Nobody in this investigation may carry it out (needs ${options[0].roles.join(" or ")}).`;
    else requestHint = readOnly ? "An operator can propose the repair for an approver to review." : "The investigation has decided. Propose a repair to send it for approval.";
  }

  return (
    <Card className="p-4" aria-labelledby="appr-title">
      <CardHeader
        id="appr-title"
        title="Approvals"
        subtitle="Nothing on site is changed without a person saying yes"
        action={
          canRequest ? (
            <Button size="sm" variant="primary" onClick={() => setRequesting(true)}>
              Propose repair
            </Button>
          ) : undefined
        }
      />
      {approvals.length === 0 ? (
        <EmptyState
          className="py-8"
          icon={<IconShield />}
          title="No actions proposed"
          body={requestHint}
        />
      ) : (
        <ul className="mt-4 flex flex-col gap-3">
          {approvals.map((a) => (
            <ApprovalCard key={a.id} a={a} state={state} pack={pack} readOnly={readOnly} onState={onState} />
          ))}
        </ul>
      )}
      <RequestApprovalDialog open={requesting} onClose={() => setRequesting(false)} state={state} onState={onState} />
    </Card>
  );
}

function ApprovalCard({
  a,
  state,
  readOnly,
  onState,
}: {
  a: Approval;
  state: InvestigationState;
  pack?: SitePack;
  readOnly: boolean;
  onState: (s: InvestigationState) => void;
}) {
  const scope = useInvestigationScope();
  const workspace = useOptionalWorkspace();
  const me = useCurrentUser();
  const askedByMe = Boolean(me && a.requested_by && a.requested_by === me.userId);
  // Unknown user: the core decides. Whoever asked cannot decide (the core refuses it too).
  const canApprove = workspace
    ? workspace.canApprove && !askedByMe
    : me
      ? hasRole(me, "approver") && !askedByMe
      : true;
  const [busy, setBusy] = useState<"approve" | "deny" | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [confirm, setConfirm] = useState<"approve" | "deny" | null>(null);

  const decide = async (decision: "approve" | "deny") => {
    setBusy(decision);
    setErr(null);
    try {
      // The core records the signed-in approver; nothing about identity is sent from here.
      onState(await scope.decideApproval(state.id, a.id, { decision }));
      setConfirm(null);
    } catch (e) {
      setErr(describeError(e));
    } finally {
      setBusy(null);
    }
  };

  const tone = a.status === "pending" ? "warn" : a.status === "denied" ? "bad" : a.status === "executed" ? "info" : "ok";
  return (
    <li className="rounded-[12px] border-[0.8px] border-line p-3.5">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-[15px] font-medium">{a.action_label}</span>
        <Badge tone={tone} dot>
          {a.status}
        </Badge>
      </div>
      <dl className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 text-[13px] sm:grid-cols-4">
        <div>
          <dt className="text-muted">Target</dt>
          <dd className="font-mono">{a.target}</dd>
        </div>
        <div>
          <dt className="text-muted">Done by</dt>
          <dd>{participantName(state, a.participant_id)}</dd>
        </div>
        <div>
          <dt className="text-muted">Risk</dt>
          <dd className="capitalize">{a.risk}</dd>
        </div>
        <div>
          <dt className="text-muted">Reversible</dt>
          <dd>{a.reversible ? "Yes" : "No"}</dd>
        </div>
      </dl>
      <p className="mt-2 text-[13px] text-fg-2">{a.rationale}</p>
      {a.approver_id ? (
        <p className="mt-1 text-[12px] text-muted">
          {a.status === "denied" ? "Denied" : "Approved"} by {me && a.approver_id === me.userId ? `${me.displayName} (you)` : a.approver_id}
          {a.decided_at ? ` at ${clock(a.decided_at)}` : ""}
        </p>
      ) : null}
      {a.status === "pending" && !readOnly ? (
        <div className="mt-3 flex flex-wrap items-end gap-2 border-t border-line pt-3">
          <div className="min-w-[180px] flex-1 text-[13px]">
            <p className="text-muted">
              {!me
                ? "Your sign-in will be recorded as the approver."
                : askedByMe
                  ? "You asked for this repair, so another approver must decide it."
                  : canApprove
                    ? `Deciding as ${me.displayName}. Your account is recorded on the approval.`
                    : "Only an approver can decide. Ask someone with the approver role."}
            </p>
            {err ? (
              <p role="alert" className="mt-1 text-bad">
                {err}
              </p>
            ) : null}
          </div>
          <Button variant="danger" onClick={() => setConfirm("deny")} disabled={!canApprove}>
            Deny
          </Button>
          <Button variant="primary" onClick={() => setConfirm("approve")} disabled={!canApprove}>
            Approve
          </Button>
        </div>
      ) : null}
      <Dialog
        open={confirm !== null}
        onClose={() => setConfirm(null)}
        title={confirm === "approve" ? "Approve this repair?" : "Deny this repair?"}
        description={
          confirm === "approve"
            ? `${participantName(state, a.participant_id)} will receive a capability to ${a.action_label.toLowerCase()} on ${a.target}. It expires five minutes after it is collected.`
            : "The repair will not go ahead. The investigation keeps its diagnosis."
        }
        footer={
          <>
            <Button onClick={() => setConfirm(null)}>Cancel</Button>
            <Button variant={confirm === "approve" ? "primary" : "danger"} loading={busy !== null} onClick={() => confirm && decide(confirm)}>
              {confirm === "approve" ? "Approve" : "Deny"}
            </Button>
          </>
        }
      />
    </li>
  );
}

function RequestApprovalDialog({
  open,
  onClose,
  state,
  onState,
}: {
  open: boolean;
  onClose: () => void;
  state: InvestigationState;
  onState: (s: InvestigationState) => void;
}) {
  const scope = useInvestigationScope();
  // The core offers only repairs the site's own model allows for this decision.
  const options = state.repair_options ?? [];
  const [choice, setChoice] = useState(0);
  const option = options[Math.min(choice, Math.max(options.length - 1, 0))];
  const people = option ? state.participants.filter((p) => option.participant_ids.includes(p.id)) : [];
  const [pid, setPid] = useState("");
  const chosenPid = people.some((p) => p.id === pid) ? pid : (people[0]?.id ?? "");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="Propose a repair"
      description="Only repairs this site's model allows for the current decision are offered. An approver who did not propose it must say yes before anything is done."
    >
      {options.length === 0 ? (
        <p className="text-[14px] text-muted">
          This site&apos;s model has no on-site repair for this decision. Follow the decision itself (for example, call the vendor or report the outage).
        </p>
      ) : (
        <form
          noValidate
          className="flex flex-col gap-4"
          onSubmit={async (e) => {
            e.preventDefault();
            if (!option || !chosenPid) return setErr("Choose who will carry it out.");
            setBusy(true);
            setErr(null);
            try {
              onState(await scope.requestApproval(state.id, { action: option.action, target: option.target, participant_id: chosenPid }));
              onClose();
            } catch (x) {
              setErr(describeError(x));
            } finally {
              setBusy(false);
            }
          }}
        >
          <Field label="Repair">
            {(a) => (
              <Select {...a} value={choice} onChange={(e) => setChoice(Number(e.target.value))}>
                {options.map((o, i) => (
                  <option key={`${o.action}-${o.target}`} value={i}>
                    {o.action_label}: {o.target_label}
                    {o.place ? ` at ${o.place}` : ""}
                  </option>
                ))}
              </Select>
            )}
          </Field>
          {option ? (
            <p className="text-[13px] text-muted">
              Risk {option.risk}, {option.reversible ? "reversible" : "not reversible"}. Carried out by: {option.roles.join(" or ")}.
            </p>
          ) : null}
          <Field label="Carried out by">
            {(a) =>
              people.length ? (
                <Select {...a} value={chosenPid} onChange={(e) => setPid(e.target.value)}>
                  {people.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.display_name}
                    </option>
                  ))}
                </Select>
              ) : (
                <p className="text-[13px] text-warn">Nobody in this investigation may carry it out (needs {option?.roles.join(" or ")}).</p>
              )
            }
          </Field>
          {err ? <p className="text-[13px] text-bad" role="alert">{err}</p> : null}
          <div className="flex justify-end gap-2">
            <Button onClick={onClose}>Cancel</Button>
            <Button type="submit" variant="primary" loading={busy} disabled={!people.length}>
              Send for approval
            </Button>
          </div>
        </form>
      )}
    </Dialog>
  );
}
