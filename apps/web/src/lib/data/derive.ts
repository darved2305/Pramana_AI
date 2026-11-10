/**
 * Pure functions that derive views from API data. Nothing here invents numbers: every
 * output is a regrouping of values the core returned.
 */
import type {
  BeliefSnapshot,
  EventEnvelope,
  InvestigationState,
  InvestigationStatus,
  JoinRequestView,
  Observation,
  PlanDecision,
  ProbeAction,
  SitePack,
} from "@/lib/api/types";

export interface Contradiction {
  key: string;
  probeId: string;
  locationId: string;
  observations: Observation[];
  outcomes: string[];
  /** Plausible reasons drawn only from the observations' own metadata. */
  explanations: string[];
}

/** Observations of the same thing in the same place that disagree. */
export function findContradictions(obs: Observation[]): Contradiction[] {
  const groups = new Map<string, Observation[]>();
  for (const o of obs) {
    if (o.state === "discarded") continue;
    const k = `${o.probe_id}@${o.location_id}`;
    groups.set(k, [...(groups.get(k) ?? []), o]);
  }
  const out: Contradiction[] = [];
  for (const [key, list] of groups) {
    const outcomes = [...new Set(list.map((o) => o.outcome))];
    if (outcomes.length < 2) continue;
    const explanations: string[] = [];
    if (list.some((o) => o.directness !== "direct"))
      explanations.push("At least one answer is second-hand or assumed rather than seen directly.");
    if (list.some((o) => o.hedge !== "certain")) explanations.push("At least one person was not sure of their answer.");
    const times = list.map((o) => Date.parse(o.committed_at)).sort((a, b) => a - b);
    if (times.length > 1 && times[times.length - 1] - times[0] > 120000)
      explanations.push("The answers were given minutes apart, so the situation may have changed.");
    if (new Set(list.map((o) => o.participant_id)).size > 1)
      explanations.push("Different people answered, possibly looking at different devices.");
    if (list.some((o) => o.state === "superseded")) explanations.push("The core has already superseded one of these answers.");
    if (!explanations.length) explanations.push("No metadata explains the disagreement; a confirmation question can settle it.");
    out.push({ key, probeId: list[0].probe_id, locationId: list[0].location_id, observations: list, outcomes, explanations });
  }
  return out;
}

export function locationLabel(pack: SitePack | undefined, id: string | null | undefined) {
  if (!id) return "unknown place";
  return pack?.locations.find((l) => l.id === id)?.label ?? id;
}

export function probeLabel(pack: SitePack | undefined, id: string | null | undefined) {
  if (!id) return "Unknown check";
  return pack?.probes.find((p) => p.id === id)?.label ?? id.replace(/_/g, " ");
}

export type BeliefChangeAnswer = Pick<Observation, "participant_id" | "probe_id" | "outcome">;

export interface RecordedBeliefChange {
  before: BeliefSnapshot;
  after: BeliefSnapshot;
  answers: BeliefChangeAnswer[];
}

/** Resolve recorded event ids against the canonical observations in the investigation state. */
export function latestBeliefChange(events: EventEnvelope[], observations: Observation[]): RecordedBeliefChange | null {
  const ordered = [...new Map(events.map((event) => [event.seq, event])).values()].sort((a, b) => a.seq - b.seq);
  const observationsById = new Map(observations.map((observation) => [observation.id, observation]));
  let change: RecordedBeliefChange | null = null;
  let prior: { index: number; belief: BeliefSnapshot } | null = null;

  ordered.forEach((event, index) => {
    if (event.type !== "BeliefUpdated" || !Array.isArray(event.payload.hypotheses)) return;
    const belief = event.payload as unknown as BeliefSnapshot;
    if (prior) {
      const answers = ordered.slice(prior.index + 1, index).flatMap((item) => {
        if (item.type !== "ObservationRecorded") return [];
        const observationId = item.payload.observation_id;
        const observation = typeof observationId === "string" ? observationsById.get(observationId) : undefined;
        if (observation) {
          return [{ participant_id: observation.participant_id, probe_id: observation.probe_id, outcome: observation.outcome }];
        }
        // Fall back to the event's own public fields: the core nests them under `evidence`; older
        // preview logs used the flat Observation shape. Anything incomplete is skipped, not shown.
        const evidence = item.payload.evidence;
        const fields = (evidence && typeof evidence === "object" ? evidence : item.payload) as Partial<Observation>;
        return typeof fields.participant_id === "string" && typeof fields.probe_id === "string" && typeof fields.outcome === "string"
          ? [{ participant_id: fields.participant_id, probe_id: fields.probe_id, outcome: fields.outcome }]
          : [];
      });
      if (answers.length) change = { before: prior.belief, after: belief, answers };
    }
    prior = { index, belief };
  });
  return change;
}

export function participantName(state: InvestigationState | undefined, id: string | null | undefined) {
  if (!id) return "Unknown";
  return state?.participants.find((p) => p.id === id)?.display_name ?? id;
}

export const STATUS_LABEL: Record<InvestigationStatus, string> = {
  investigating: "Investigating",
  decided: "Decided",
  abstained: "Abstained",
  awaiting_approval: "Awaiting approval",
  acting: "Repair in progress",
  verifying: "Verifying",
  verified: "Verified",
  not_verified: "Not verified",
  closed: "Closed",
};

export type Tone = "accent" | "ok" | "warn" | "bad" | "info" | "muted";
export const STATUS_TONE: Record<InvestigationStatus, Tone> = {
  investigating: "info",
  decided: "accent",
  abstained: "warn",
  awaiting_approval: "warn",
  acting: "info",
  verifying: "info",
  verified: "ok",
  not_verified: "bad",
  closed: "muted",
};

export function pct(p: number | null | undefined, digits = 0) {
  if (p == null || Number.isNaN(p)) return "n/a";
  const v = p * 100;
  if (v > 0 && v < 1 && digits === 0) return "<1%";
  return `${v.toFixed(digits)}%`;
}

export function bits(b: number | null | undefined) {
  if (b == null || Number.isNaN(b)) return "n/a";
  return `${b.toFixed(2)} bits`;
}

export function duration(seconds: number) {
  if (seconds < 90) return `${Math.round(seconds)} s`;
  return `${(seconds / 60).toFixed(1)} min`;
}

/**
 * Plain-language reason for the chosen check. The engine's own explanation is written for
 * engineers (bits, expected loss, raw ids), so this reads the chosen candidate's structured
 * fields instead: its time cost and the fact that the planner ranked it first.
 */
export function checkRationale(plan: PlanDecision, personName: string): string {
  const chosen = plan.candidates.find((c) => plan.action && sameAction(c.action, plan.action));
  if (!chosen) return "Pramana expects this check to help the investigation most among the checks available.";
  const minutes = Math.max(1, Math.round(chosen.cost_s / 60));
  return `Pramana expects this check to help the investigation most among the checks available, for about ${minutes} min of ${personName}'s time.`;
}

/** Why the planner stopped without a decision: the check that would help, if one is blocked. */
export function abstainRationale(plan: PlanDecision, pack: SitePack | undefined): string {
  const base = "Pramana did not reach a confident answer, so it is not recommending an action yet.";
  const blocked = plan.infeasible[0];
  if (!blocked) return base;
  const reasons = blocked.reasons.length ? ` (${blocked.reasons.join("; ")})` : "";
  return `${base} A check that would help is blocked: ${probeLabel(pack, blocked.probe_id)} at ${locationLabel(pack, blocked.location_id)}${reasons}.`;
}

function sameAction(a: ProbeAction, b: ProbeAction) {
  return a.participant_id === b.participant_id && a.probe_id === b.probe_id && a.location_id === b.location_id;
}

export function clock(iso: string) {
  const d = new Date(iso);
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

export function relative(iso: string, now = Date.now()) {
  const s = Math.round((now - Date.parse(iso)) / 1000);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  return new Date(iso).toLocaleDateString();
}

/** How a request to join by email domain reads to an admin. */
export function joinRequestLabel(r: Pick<JoinRequestView, "status" | "decision_source">): { label: string; tone: Tone } {
  if (r.status === "pending") return { label: "Waiting for you", tone: "warn" };
  if (r.status === "approved") {
    return r.decision_source === "auto" ? { label: "Joined as viewer", tone: "ok" } : { label: "Approved", tone: "ok" };
  }
  if (r.status === "declined") return { label: "Declined", tone: "muted" };
  return { label: "Closed", tone: "muted" };
}

export function outcomeWord(o: string) {
  return o.replace(/_/g, " ");
}

/** Replay: fold the event log up to `upto` (inclusive index). */
export function foldEvents(events: EventEnvelope[], upto: number) {
  let belief: Record<string, unknown> | null = null;
  let plan: Record<string, unknown> | null = null;
  const observations: Observation[] = [];
  const questions: Record<string, unknown>[] = [];
  for (let i = 0; i <= upto && i < events.length; i++) {
    const e = events[i];
    if (e.type === "BeliefUpdated") belief = e.payload;
    else if (e.type === "PlanComputed") plan = e.payload;
    else if (e.type === "ObservationRecorded") observations.push(e.payload as unknown as Observation);
    else if (e.type === "QuestionAsked") questions.push(e.payload);
  }
  return { belief, plan, observations, questions };
}

export const EVENT_LABEL: Record<string, string> = {
  InvestigationCreated: "Investigation opened",
  ReportReceived: "Report received",
  ObservationRecorded: "Observation recorded",
  BeliefUpdated: "Belief updated",
  PlanComputed: "Plan computed",
  QuestionAsked: "Question asked",
  QuestionWithdrawn: "Question withdrawn",
  QuestionCancelled: "Question cancelled",
  DecisionReached: "Decision reached",
  Abstained: "Abstained",
  ApprovalRequested: "Approval requested",
  ApprovalDecided: "Approval decided",
  CapabilityIssued: "Capability issued",
  InterventionReported: "Repair reported",
  VerificationResult: "Verification result",
  Reopened: "Reopened",
  GroundTruthRevealed: "Ground truth revealed",
  ObservationConfirmed: "Confirmation answered",
};
