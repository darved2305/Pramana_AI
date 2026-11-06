/**
 * Pure functions that derive views from API data. Nothing here invents numbers: every
 * output is a regrouping of values the core returned.
 */
import type { EventEnvelope, InvestigationState, InvestigationStatus, Observation, SitePack } from "@/lib/api/types";

export interface Contradiction {
  key: string;
  probeId: string;
  locationId: string;
  observations: Observation[];
  outcomes: string[];
  /** Plausible reasons drawn only from the observations' own metadata. */
  explanations: string[];
}

export interface PresenceChallenge {
  challengeId: string;
  questionId: string;
  participantId: string;
  locationId: string;
  status: "asked" | "passed" | "not_confirmed";
  reason?: string;
}

export interface ReconciliationFamily {
  code: string;
  posteriorMass: number;
  supported: boolean;
}

export interface ReconciliationContext {
  participantIds: [string, string];
  locationIds: [string, string];
  accessPoints: [string | null, string | null];
  posteriorMass: number;
}

export interface ReconciliationExplanation {
  explanationId: string;
  observationIds: [string, string];
  families: ReconciliationFamily[];
  contexts: ReconciliationContext[];
  tieBreakAction: { participant_id: string; probe_id: string; location_id: string; requires_move: boolean } | null;
  tieBreakQuestion?: { questionId: string; text: string };
  resolution?: { questionId: string; outcome: string };
}

/** Build challenge state only from the append-only events returned by the core. */
export function presenceChallenges(events: EventEnvelope[]): PresenceChallenge[] {
  const challenges = new Map<string, PresenceChallenge>();
  const reasons = new Map<string, string>();
  for (const event of events) {
    const payload = event.payload;
    if (event.type === "ChallengeIssued") {
      const challengeId = stringField(payload, "challenge_id");
      const questionId = stringField(payload, "question_id");
      const participantId = stringField(payload, "participant_id");
      const locationId = stringField(payload, "location_id");
      if (challengeId && questionId && participantId && locationId) {
        challenges.set(challengeId, { challengeId, questionId, participantId, locationId, status: "asked" });
      }
    } else if (event.type === "ChallengeResult") {
      const challengeId = stringField(payload, "challenge_id");
      const result = stringField(payload, "result");
      const existing = challengeId ? challenges.get(challengeId) : undefined;
      if (!existing || !result) continue;
      existing.status = result === "passed" ? "passed" : "not_confirmed";
      const reason = stringField(payload, "reason");
      if (reason) reasons.set(challengeId!, reason);
    }
  }
  return [...challenges.values()].map((challenge) => ({
    ...challenge,
    ...(reasons.has(challenge.challengeId) ? { reason: reasons.get(challenge.challengeId) } : {}),
  }));
}

/** Pair explanation and tie-break events by their stable explanation/question ids. */
export function reconciliationExplanations(events: EventEnvelope[]): ReconciliationExplanation[] {
  const explanations = events
    .filter((event) => event.type === "ContradictionExplained")
    .map((event) => {
      const payload = event.payload;
      const explanationId = stringField(payload, "explanation_id");
      const observationIds = stringPair(payload.observation_ids);
      if (!explanationId || !observationIds) return null;
      const action = recordField(payload, "tie_break_action");
      const tieBreakAction = action
        ? {
            participant_id: stringField(action, "participant_id") ?? "",
            probe_id: stringField(action, "probe_id") ?? "",
            location_id: stringField(action, "location_id") ?? "",
            requires_move: action.requires_move === true,
          }
        : null;
      const families = arrayField(payload, "families").flatMap((item) => {
        const row = asRecord(item);
        if (!row) return [];
        const code = stringField(row, "code");
        const mass = numberField(row, "posterior_mass");
        return code && mass !== null ? [{ code, posteriorMass: mass, supported: row.supported === true }] : [];
      });
      const contexts = arrayField(payload, "contexts").flatMap((item) => {
        const row = asRecord(item);
        if (!row) return [];
        const participantIds = stringPair(row.participant_ids);
        const locationIds = stringPair(row.location_ids);
        const accessPoints = nullableStringPair(row.access_points);
        const mass = numberField(row, "posterior_mass");
        return participantIds && locationIds && accessPoints && mass !== null
          ? [{ participantIds, locationIds, accessPoints, posteriorMass: mass }]
          : [];
      });
      return { explanationId, observationIds, families, contexts, tieBreakAction };
    })
    .filter((row): row is ReconciliationExplanation => row !== null);

  return explanations.map((explanation, index) => {
    const nextExplanation = explanations[index + 1];
    const matchingQuestion = events.find((event) => {
      if (event.type !== "QuestionAsked" || event.seq <= (events.find((candidate) => candidate.type === "ContradictionExplained" && stringField(candidate.payload, "explanation_id") === explanation.explanationId)?.seq ?? 0)) return false;
      if (!explanation.tieBreakAction) return false;
      const action = recordField(event.payload, "action");
      return !!action &&
        stringField(action, "participant_id") === explanation.tieBreakAction.participant_id &&
        stringField(action, "probe_id") === explanation.tieBreakAction.probe_id &&
        stringField(action, "location_id") === explanation.tieBreakAction.location_id &&
        (!nextExplanation || event.seq < (events.find((candidate) => candidate.type === "ContradictionExplained" && stringField(candidate.payload, "explanation_id") === nextExplanation.explanationId)?.seq ?? Infinity));
    });
    const resolution = events.find((event) => event.type === "ContradictionResolved" && stringField(event.payload, "explanation_id") === explanation.explanationId);
    const questionId = matchingQuestion ? stringField(matchingQuestion.payload, "question_id") : undefined;
    const resolutionQuestionId = resolution ? stringField(resolution.payload, "question_id") : undefined;
    const outcome = resolution ? stringField(resolution.payload, "outcome") : undefined;
    const questionText = matchingQuestion ? stringField(matchingQuestion.payload, "text") : undefined;
    return {
      ...explanation,
      ...(questionId && questionText ? { tieBreakQuestion: { questionId, text: questionText } } : {}),
      ...(resolutionQuestionId && outcome ? { resolution: { questionId: resolutionQuestionId, outcome } } : {}),
    };
  });
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : null;
}

function stringField(record: Record<string, unknown>, key: string): string | undefined {
  const value = record[key];
  return typeof value === "string" ? value : undefined;
}

function numberField(record: Record<string, unknown>, key: string): number | null {
  const value = record[key];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function recordField(record: Record<string, unknown>, key: string): Record<string, unknown> | null {
  return asRecord(record[key]);
}

function arrayField(record: Record<string, unknown>, key: string): unknown[] {
  return Array.isArray(record[key]) ? record[key] : [];
}

function stringPair(value: unknown): [string, string] | null {
  return Array.isArray(value) && value.length === 2 && value.every((item) => typeof item === "string")
    ? [value[0], value[1]]
    : null;
}

function nullableStringPair(value: unknown): [string | null, string | null] | null {
  return Array.isArray(value) && value.length === 2 && value.every((item) => item === null || typeof item === "string")
    ? [value[0], value[1]]
    : null;
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

export function probeLabel(pack: SitePack | undefined, id: string) {
  return pack?.probes.find((p) => p.id === id)?.label ?? id.replace(/_/g, " ");
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
  ChallengeIssued: "Presence check asked",
  ChallengeResult: "Presence check result",
  ContradictionExplained: "Reconciliation explained",
  ContradictionResolved: "Tie-break answered",
};
