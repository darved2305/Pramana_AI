"use client";

import { motion, LayoutGroup } from "motion/react";
import { useState } from "react";
import { clsx } from "clsx";
import { Badge, Card, CardHeader, EmptyState, ProbBar, Tag } from "@/components/ui";
import { IconSpark } from "@/components/ui/icons";
import type { BeliefSnapshot, EventEnvelope, InvestigationState, Observation, SitePack } from "@/lib/api/types";
import { bits, duration, locationLabel, outcomeWord, participantName, pct, probeLabel } from "@/lib/data/derive";

/* ---------- Hypotheses ---------- */

const OPEN_WORLD = "OPEN_WORLD";
/** With single faults and every two-fault pair there are about a hundred causes. */
const TOP_N = 6;

export function HypothesisPanel({ state }: { state: InvestigationState }) {
  const [showAll, setShowAll] = useState(false);
  const b = state.belief;
  // The unknown cause has its own row below, so it is not repeated in the list.
  const hyps = b.hypotheses.filter((h) => h.id !== OPEN_WORLD).sort((a, c) => c.probability - a.probability);
  const shown = showAll ? hyps : hyps.slice(0, TOP_N);
  const hidden = hyps.slice(TOP_N);
  const hiddenMass = hidden.reduce((sum, h) => sum + h.probability, 0);
  const maxBits = Math.log2(Math.max(2, b.hypotheses.length));

  return (
    <Card className="flex flex-col p-4" aria-labelledby="hyp-title">
      <CardHeader
        id="hyp-title"
        title="Competing causes"
        subtitle={`From ${b.observations_used} observation${b.observations_used === 1 ? "" : "s"}`}
        action={<Badge tone="info">{bits(b.hypothesis_entropy_bits)} uncertain</Badge>}
      />
      <UncertaintyMeter value={b.hypothesis_entropy_bits} max={maxBits} />
      <LayoutGroup>
        <ol className={clsx("mt-3 flex flex-col", showAll && hyps.length > 12 && "max-h-[520px] overflow-y-auto pr-1")} aria-label="Causes, most likely first">
          {shown.map((h, i) => (
            <motion.li
              layout
              transition={{ type: "spring", stiffness: 260, damping: 30 }}
              key={h.id}
              className="border-b border-line py-2.5 last:border-none"
            >
              <div className="flex items-baseline justify-between gap-3">
                <span className={clsx("min-w-0 text-[14px]", i === 0 ? "font-medium text-fg" : "text-fg-2")}>{h.label}</span>
                <span className={clsx("shrink-0 font-mono text-[13px] tabular-nums", i === 0 ? "text-accent" : "text-fg-2")}>
                  {pct(h.probability, h.probability < 0.1 ? 1 : 0)}
                </span>
              </div>
              <ProbBar value={h.probability} tone={i === 0 ? "accent" : "muted"} className="mt-1.5" label={`${h.label} probability`} />
            </motion.li>
          ))}
        </ol>
      </LayoutGroup>
      {hidden.length ? (
        <div className="mt-1 flex flex-wrap items-baseline justify-between gap-2 text-[13px]">
          {!showAll ? (
            <span className="text-muted">
              {hidden.length} more {hidden.length === 1 ? "cause" : "causes"}, {pct(hiddenMass, hiddenMass < 0.1 ? 1 : 0)} together
            </span>
          ) : (
            <span />
          )}
          <button type="button" onClick={() => setShowAll((v) => !v)} aria-expanded={showAll} className="text-accent hover:underline">
            {showAll ? "Show fewer" : `Show all ${hyps.length}`}
          </button>
        </div>
      ) : null}
      <div className="mt-3 rounded-[10px] border border-dashed border-line-strong px-3 py-2.5">
        <div className="flex items-baseline justify-between gap-3">
          <span className="text-[13px] text-fg-2">Something not in the model</span>
          <span className="font-mono text-[13px] text-fg-2">{pct(b.open_world_probability, 1)}</span>
        </div>
        <ProbBar value={b.open_world_probability} tone="warn" className="mt-1.5" label="Open-world probability" />
      </div>
    </Card>
  );
}

function UncertaintyMeter({ value, max }: { value: number; max: number }) {
  const cells = 24;
  const lit = Math.round((Math.min(value, max) / max) * cells);
  return (
    <div className="mt-3 flex gap-[3px]" aria-hidden>
      {Array.from({ length: cells }, (_, i) => (
        <span
          key={i}
          className={clsx("h-2.5 flex-1 rounded-[2px] transition-colors duration-500", i < lit ? "bg-info" : "bg-white/[.06]")}
          style={{ transitionDelay: `${i * 12}ms`, opacity: i < lit ? 0.35 + (0.65 * i) / cells : 1 }}
        />
      ))}
    </div>
  );
}

/* ---------- Decision bar ---------- */

export function DecisionBar({ state }: { state: InvestigationState }) {
  const ds = [...state.belief.decisions].sort((a, b) => b.probability - a.probability);
  const palette = ["var(--accent)", "var(--v-blue)", "var(--v-violet)", "var(--v-magenta)", "#7d7d86"];
  const top = ds.slice(0, 4);
  const rest = ds.slice(4).reduce((s, d) => s + d.probability, 0);
  return (
    <Card className="p-4" aria-labelledby="dec-title">
      <CardHeader
        id="dec-title"
        title="What to do"
        subtitle="Probability that each action is the right one"
        action={<Badge tone="info">{bits(state.belief.decision_entropy_bits)}</Badge>}
      />
      <div className="mt-4 flex h-3 overflow-hidden rounded-full bg-white/[.06]" role="img" aria-label="Decision probabilities">
        {top.map((d, i) => (
          <motion.span
            key={d.id}
            className="h-full"
            animate={{ width: `${d.probability * 100}%` }}
            transition={{ duration: 0.8, ease: [0.22, 1, 0.36, 1] }}
            style={{ background: palette[i] }}
          />
        ))}
        {rest > 0 ? <span className="h-full" style={{ width: `${rest * 100}%`, background: palette[4] }} /> : null}
      </div>
      <ul className="mt-3 grid min-w-0 gap-1.5">
        {top.map((d, i) => (
          <li key={d.id} className="flex min-w-0 items-center gap-2 text-[13px]">
            <span className="h-2.5 w-2.5 shrink-0 rounded-[3px]" style={{ background: palette[i] }} />
            <span className="min-w-0 flex-1 truncate text-fg-2">{d.label}</span>
            <span className="font-mono tabular-nums text-fg">{pct(d.probability)}</span>
          </li>
        ))}
        {rest > 0 ? (
          <li className="flex items-center gap-2 text-[13px]">
            <span className="h-2.5 w-2.5 shrink-0 rounded-[3px]" style={{ background: palette[4] }} />
            <span className="flex-1 text-muted">{ds.length - 4} other actions</span>
            <span className="font-mono tabular-nums text-muted">{pct(rest)}</span>
          </li>
        ) : null}
      </ul>
      <p className="mt-3 text-[12px] text-muted">
        Expected cost of deciding now: <span className="text-fg-2">{state.belief.expected_loss_now_min.toFixed(1)} min</span> of wasted effort
      </p>
    </Card>
  );
}

/* ---------- Reasoning: why this question ---------- */

/** Compare adjacent recorded beliefs only when an observation lies between them. */
export function BeliefChange({ events, state, pack }: { events: EventEnvelope[]; state: InvestigationState; pack?: SitePack }) {
  const ordered = [...new Map(events.map((event) => [event.seq, event])).values()].sort((a, b) => a.seq - b.seq);
  let change: { before: BeliefSnapshot; after: BeliefSnapshot; answers: Observation[] } | null = null;
  let prior: { index: number; belief: BeliefSnapshot } | null = null;
  ordered.forEach((event, index) => {
    if (event.type !== "BeliefUpdated" || !Array.isArray(event.payload.hypotheses)) return;
    const belief = event.payload as unknown as BeliefSnapshot;
    if (prior) {
      const answers = ordered.slice(prior.index + 1, index)
        .filter((item) => item.type === "ObservationRecorded")
        .map((item) => (item.payload.evidence ?? item.payload) as unknown as Observation);
      if (answers.length) change = { before: prior.belief, after: belief, answers };
    }
    prior = { index, belief };
  });
  if (!change) return null;
  const { before, after, answers } = change as { before: BeliefSnapshot; after: BeliefSnapshot; answers: Observation[] };
  return (
    <Card className="p-4" aria-labelledby="change-title">
      <CardHeader id="change-title" title="What changed" subtitle="The latest answers with a recorded belief before and after" />
      <p className="mt-3 text-[13px] text-fg-2">
        {answers.map((answer) => `${participantName(state, answer.participant_id)}: ${probeLabel(pack, answer.probe_id)} - ${outcomeWord(answer.outcome)}`).join("; ")}
      </p>
      <div className="mt-3 grid gap-4 sm:grid-cols-2">
        {([ ["Before", before], ["After", after] ] as const).map(([label, belief]) => (
          <div key={label}>
            <h3 className="text-[13px] font-medium text-fg">{label}</h3>
            <ul className="mt-2 space-y-2">
              {[...belief.hypotheses].sort((a, b) => b.probability - a.probability).slice(0, 3).map((cause) => (
                <li key={cause.id} className="text-[13px] text-fg-2">
                  <div className="flex justify-between gap-2"><span>{cause.label}</span><span>{pct(cause.probability)}</span></div>
                  <ProbBar value={cause.probability} className="mt-1" label={`${label}: ${cause.label}`} />
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
    </Card>
  );
}

export function ReasoningPanel({ state, pack }: { state: InvestigationState; pack?: SitePack }) {
  const plan = state.plan;
  const [open, setOpen] = useState<number | null>(0);
  const cands = [...plan.candidates].sort((a, b) => b.score - a.score);
  const decisionLabel = (id: string | null | undefined) =>
    id ? (state.belief.decisions.find((d) => d.id === id)?.label ?? pack?.decision_classes.find((d) => d.id === id)?.label ?? id) : "undecided";

  return (
    <Card className="p-4" aria-labelledby="why-title">
      <CardHeader
        id="why-title"
        title={plan.kind === "ask" ? "Why this question" : plan.kind === "decide" ? "Why this decision" : plan.kind === "abstain" ? "Why Pramana stopped" : "Why this conclusion"}
        subtitle={`Rule: ${plan.rule.replace(/_/g, " ")}`}
        action={plan.moderate_confidence ? <Badge tone="warn">Moderate confidence</Badge> : undefined}
      />
      <p className="mt-3 rounded-[12px] bg-white/[.03] px-3.5 py-3 text-[14px] leading-relaxed text-fg">{plan.reason}</p>
      <p className="mt-1.5 text-[11px] text-muted">Written from the numbers by the planner, not by a language model.</p>

      {cands.length ? (
        <>
          <h3 className="mt-5 text-[13px] font-medium text-fg-2">Questions considered</h3>
          <ol className="mt-2 flex flex-col gap-2">
            {cands.map((c, i) => {
              const chosen =
                plan.action &&
                c.action.participant_id === plan.action.participant_id &&
                c.action.probe_id === plan.action.probe_id &&
                c.action.location_id === plan.action.location_id;
              const expanded = open === i;
              return (
                <li key={i} className={clsx("rounded-[12px] border-[0.8px]", chosen ? "border-accent/50 bg-accent-soft" : "border-line")}>
                  <button
                    type="button"
                    aria-expanded={expanded}
                    onClick={() => setOpen(expanded ? null : i)}
                    className="flex w-full flex-wrap items-center gap-x-4 gap-y-1 px-3 py-2.5 text-left"
                  >
                    <span className="min-w-0 flex-1">
                      <span className="flex items-center gap-2 text-[14px] text-fg">
                        {chosen ? <IconSpark className="h-4 w-4 text-accent" /> : <span className="w-4 text-center text-[12px] text-muted">{i + 1}</span>}
                        {participantName(state, c.action.participant_id)}: {probeLabel(pack, c.action.probe_id)}
                      </span>
                      <span className="ml-6 block text-[12px] text-muted">
                        at {locationLabel(pack, c.action.location_id)}
                        {c.action.requires_move ? " (needs to walk there)" : ""}
                      </span>
                    </span>
                    <span className="grid grid-cols-3 gap-4 text-right font-mono text-[12px] tabular-nums">
                      <Metric k="info gain" v={bits(c.eig_decision_bits)} />
                      <Metric k="cost" v={duration(c.cost_s)} />
                      <Metric k="net value" v={`${c.net_value_min.toFixed(1)} min`} />
                    </span>
                  </button>
                  {expanded ? (
                    <div className="border-t border-line px-3 py-3">
                      <p className="mb-2 text-[12px] text-muted">If the answer is...</p>
                      <ul className="grid gap-1.5">
                        {[...c.outcomes]
                          .sort((a, b) => b.probability - a.probability)
                          .map((o) => (
                            <li key={o.outcome} className="grid grid-cols-[110px_60px_1fr] items-center gap-3 text-[13px]">
                              <Tag>{outcomeWord(o.outcome)}</Tag>
                              <span className="font-mono text-muted">{pct(o.probability)}</span>
                              <span className="truncate text-fg-2">
                                then: {decisionLabel(o.decision)} ({pct(o.decision_probability)})
                              </span>
                            </li>
                          ))}
                      </ul>
                    </div>
                  ) : null}
                </li>
              );
            })}
          </ol>
        </>
      ) : null}

      {plan.infeasible.length ? (
        <>
          <h3 className="mt-5 text-[13px] font-medium text-fg-2">Not possible right now</h3>
          <ul className="mt-2 flex flex-col gap-1.5">
            {plan.infeasible.map((x, i) => (
              <li key={i} className="flex flex-wrap items-baseline gap-x-2 text-[13px]">
                <span className="text-fg-2">
                  {participantName(state, x.participant_id)}: {probeLabel(pack, x.probe_id)}
                </span>
                <span className="text-muted">{x.reasons.join("; ")}</span>
              </li>
            ))}
          </ul>
        </>
      ) : null}

      {!cands.length && !plan.infeasible.length && plan.kind === "ask" ? (
        <EmptyState title="No alternatives recorded" body="The planner did not report other candidates for this step." />
      ) : null}
    </Card>
  );
}

function Metric({ k, v }: { k: string; v: string }) {
  return (
    <span>
      <span className="block text-fg">{v}</span>
      <span className="block text-[10px] uppercase tracking-[0.06em] text-muted">{k}</span>
    </span>
  );
}

/* ---------- Final diagnosis ---------- */

export function DiagnosisPanel({ state, pack, contradictions }: { state: InvestigationState; pack?: SitePack; contradictions: number }) {
  const b = state.belief;
  const plan = state.plan;
  const decided = ["decided", "awaiting_approval", "acting", "verifying", "verified", "not_verified", "closed"].includes(state.status);
  const abstained = state.status === "abstained";
  const approval = state.approvals?.at(-1);
  const decisionLabel =
    (plan.decision_class && (b.decisions.find((d) => d.id === plan.decision_class)?.label ?? pack?.decision_classes.find((d) => d.id === plan.decision_class)?.label)) ||
    (b.map_decision && b.decisions.find((d) => d.id === b.map_decision)?.label) ||
    null;

  const rows: { k: string; v: React.ReactNode; tone?: "ok" | "warn" | "bad" | "muted" | "info" | "accent" }[] = [
    {
      k: "Diagnosis",
      v: decided ? decisionLabel ?? "Decided" : abstained ? "Abstained: the evidence does not settle it" : "Not yet. Still gathering evidence.",
      tone: decided ? "accent" : abstained ? "warn" : "muted",
    },
    {
      k: "Confidence",
      v: decided
        ? pct(plan.decision_probability ?? b.map_decision_probability)
        : `Leading option at ${pct(b.map_decision_probability)}`,
      tone: "info",
    },
    {
      k: "Approval",
      v: approval ? `${approval.action_label}: ${approval.status}` : decided ? "No repair requested yet" : "Not applicable yet",
      tone: approval ? (approval.status === "denied" ? "bad" : approval.status === "pending" ? "warn" : "ok") : "muted",
    },
    {
      k: "Action outcome",
      v:
        approval?.status === "executed"
          ? "Repair reported as done. The simulator does not say whether it worked."
          : state.status === "acting"
            ? "Repair in progress"
            : "No repair carried out",
      tone: approval?.status === "executed" ? "info" : "muted",
    },
    {
      k: "Verification",
      v: state.status === "verified"
        ? `Verified from what people observed (${pct(b.repair?.fixed_probability)} fixed)`
        : state.status === "not_verified"
          ? "Not verified: the problem persists. The investigation reopens."
          : b.repair
            ? `Checking: ${pct(b.repair.fixed_probability)} likely fixed after ${b.repair.post_repair_observations} observation${b.repair.post_repair_observations === 1 ? "" : "s"}`
            : "Waits for a repair",
      tone: state.status === "verified" ? "ok" : state.status === "not_verified" ? "bad" : "muted",
    },
  ];

  const unresolved: string[] = [];
  if (b.open_world_probability >= 0.05) unresolved.push(`${pct(b.open_world_probability)} chance the cause is outside the model.`);
  if (contradictions) unresolved.push(`${contradictions} unresolved contradiction${contradictions === 1 ? "" : "s"} in the evidence.`);
  if (plan.infeasible.length) unresolved.push(`${plan.infeasible.length} check${plan.infeasible.length === 1 ? "" : "s"} nobody available can make.`);
  if (state.pending_question) unresolved.push("A question is still waiting for an answer.");

  return (
    <Card className="p-4" aria-labelledby="diag-title">
      <CardHeader id="diag-title" title="Diagnosis" subtitle="Each stage is reported separately, so a confident guess is never mistaken for a fix." />
      <ol className="mt-4 flex flex-col">
        {rows.map((r, i) => (
          <li key={r.k} className="relative grid grid-cols-[22px_1fr] gap-3 pb-4 last:pb-0">
            {i < rows.length - 1 ? <span aria-hidden className="absolute left-[10px] top-[22px] h-[calc(100%-18px)] w-px bg-line" /> : null}
            <span
              aria-hidden
              className={clsx(
                "mt-[3px] h-[21px] w-[21px] rounded-full border-2",
                r.tone === "accent" && "border-accent bg-accent/25",
                r.tone === "ok" && "border-ok bg-ok/25",
                r.tone === "warn" && "border-warn bg-warn/20",
                r.tone === "bad" && "border-bad bg-bad/20",
                r.tone === "info" && "border-info bg-info/20",
                (!r.tone || r.tone === "muted") && "border-line-strong",
              )}
            />
            <div>
              <p className="text-[12px] uppercase tracking-[0.06em] text-muted">{r.k}</p>
              <p className="mt-0.5 text-[14px] text-fg">{r.v}</p>
            </div>
          </li>
        ))}
      </ol>
      <div className="mt-4 rounded-[12px] bg-white/[.03] px-3.5 py-3">
        <p className="text-[12px] uppercase tracking-[0.06em] text-muted">Unresolved</p>
        {unresolved.length ? (
          <ul className="mt-1 list-disc pl-4 text-[13px] text-fg-2">
            {unresolved.map((u) => (
              <li key={u}>{u}</li>
            ))}
          </ul>
        ) : (
          <p className="mt-1 text-[13px] text-fg-2">Nothing outstanding.</p>
        )}
      </div>
      {state.ground_truth ? (
        <div className="mt-4 rounded-[12px] border-[0.8px] border-line px-3.5 py-3">
          <p className="text-[12px] uppercase tracking-[0.06em] text-muted">Ground truth (revealed)</p>
          <p className="mt-1 text-[14px]">
            {state.ground_truth.reveal.fault_spec.faults.map((f) => `${f.component_id} ${f.mode}`).join(", ") || "No fault"}
          </p>
          <div className="mt-2 flex flex-wrap gap-2">
            <Badge tone={state.ground_truth.reveal.commitment_verified ? "ok" : "bad"}>
              Commitment {state.ground_truth.reveal.commitment_verified ? "verified" : "does not match"}
            </Badge>
            {state.ground_truth.correct != null ? (
              <Badge tone={state.ground_truth.correct ? "ok" : "bad"}>{state.ground_truth.correct ? "Decision correct" : "Decision wrong"}</Badge>
            ) : (
              <Badge>{state.ground_truth.abstained ? "Abstained" : "Not scored"}</Badge>
            )}
          </div>
        </div>
      ) : null}
    </Card>
  );
}
