/**
 * Friendly names for the core API's schemas. Generated from services/core/openapi.json
 * with `npm run gen:api`; never edit schema.gen.ts by hand.
 */
import type { components } from "./schema.gen";

type S = components["schemas"];

export type InvestigationState = S["InvestigationState"];
export type InvestigationStatus = S["InvestigationStatus"];
export type BeliefSnapshot = S["BeliefSnapshot"];
export type HypothesisBelief = S["HypothesisBelief"];
export type DecisionBelief = S["DecisionBelief"];
export type PlanDecision = S["PlanDecision"];
export type CandidateScore = S["CandidateScore"];
export type OutcomePreview = S["OutcomePreview"];
export type InfeasibleAction = S["InfeasibleAction"];
export type ProbeAction = S["ProbeAction"];
export type Question = S["Question"];
export type Observation = S["Observation"];
export type Approval = S["Approval"];
export type ApprovalStatus = S["ApprovalStatus"];
export type ParticipantSpec = S["ParticipantSpec"];
export type LanguageProfile = S["LanguageProfile"];
export type Role = S["Role"];
export type Skill = S["Skill"];
export type Report = S["Report"];
export type EventEnvelope = S["EventEnvelope"];
export type ReplayResult = S["ReplayResult"];
export type AnswerResult = S["AnswerResult"];
export type VoiceAnswerResult = S["VoiceAnswerResult"];
export type Extraction = S["Extraction"];
export type SttResult = S["SttResult"];
export type CapabilityGrant = S["CapabilityGrant"];
export type CreateInvestigation = S["CreateInvestigation"];
export type SubmitAnswer = S["SubmitAnswer"];
export type GroundTruthComparison = S["GroundTruthComparison"];
export type Hedge = S["Hedge"];
export type Directness = S["Directness"];
export type Modality = S["Modality"];
export type AuthSession = S["AuthSession"];
export type StaffRole = S["StaffRole"];
export type DirectoryParticipant = S["DirectoryParticipant"];
export type ParticipantPatch = S["ParticipantPatch"];
export type InvestigationPage = S["InvestigationPage"];
export type InvestigationSummary = S["InvestigationSummary"];
export type PackSummary = S["PackSummary"];
export type EvaluationReportSummary = S["EvaluationReportSummary"];
export type EvaluationReport = S["EvaluationReport"];
export type PresenceCheckView = S["PresenceCheckView"];
export type DisagreementView = S["DisagreementView"];

export type SttLanguage = LanguageProfile["stt_candidates"][number];
export type TemplateLanguage = LanguageProfile["template_language"];

/** GET /v1/packs/{id}. The OpenAPI spec types this loosely, so the shape is declared here
 * from the observed response and the API guide (section 5). */
export interface SitePack {
  id: string;
  version: string;
  title: string;
  locations: PackLocation[];
  probes: PackProbe[];
  decision_classes: { id: string; label: string }[];
  walking_roles: Role[];
}
export interface PackLocation {
  id: string;
  floor: number;
  kind: string;
  label: string;
  restricted: boolean;
  access_roles: Role[];
}
export interface PackProbe {
  id: string;
  label: string;
  outcomes: string[];
  roles: string[];
  locations: string[];
}

/** POST /v1/investigations/{id}/participants/{pid}/token */
export interface ParticipantToken {
  token: string;
  scenario_id: string;
  sim_url: string;
}

/** GET {sim}/sim/v1/scenarios/{sid}/view */
export interface ParticipantView {
  location_label: string;
  items: { label: string; value: string }[];
  reachable_locations: string[] | { id: string; label?: string }[];
  /** Labels printed on equipment here (presence checks). Only shown to people on site. */
  labels?: { token_id: string; label: string; value: string }[];
}

/** GET /v1/voice/status */
export interface VoiceStatus {
  configured: boolean;
  /** "gnani" only for HTTPS to Gnani's own host; "other" for an emulator or anything else. */
  provider?: "gnani" | "other";
  provider_host?: string | null;
  stt_model?: string;
  tts_models?: string[];
  base_url?: string;
}

/** GET /v1/voice/usage: today's metered spend and the governor's live state. */
export interface VoiceUsage {
  spent_today_inr: number;
  by_service: Record<string, { requests: number; units: number; cost_inr: number }>;
  limits: {
    stt_rest_per_min: number;
    tts_per_min: number;
    max_streams: number;
    rest_max_inflight: number;
    daily_budget_inr: number;
  };
  window_used: { stt_rest: number; tts: number };
  open_streams: number;
}

/** Statuses after which an investigation will not ask anything more. */
export const SETTLED: InvestigationStatus[] = ["decided", "abstained", "verified", "not_verified", "closed"];
