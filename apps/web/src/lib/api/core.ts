/**
 * Core service client. Every route here is in services/core/openapi.json; nothing is
 * invented. Staff calls ride on the session cookie; participant calls pass the join-link
 * token (`token`), which the core accepts only for that participant's own actions.
 */
import { request, requestBlob, requestStream } from "./http";
import type {
  AnswerResponse,
  AuthSession,
  CapabilityGrant,
  CreateInvestigation,
  DirectoryParticipant,
  EvaluationReport,
  EvaluationReportSummary,
  EventEnvelope,
  InvestigationPage,
  InvestigationState,
  InvestigationStatus,
  PackSummary,
  ParticipantPatch,
  ParticipantSpec,
  ParticipantToken,
  SitePack,
  SttResult,
  SubmitAnswer,
  VoiceAnswerResponse,
  VoiceStatus,
} from "./types";

const enc = encodeURIComponent;

export interface ListQuery {
  status?: InvestigationStatus[];
  q?: string;
  limit?: number;
  offset?: number;
}

export interface InvestigationPreset {
  id: "S2" | "S7";
  title: string;
  description: string;
  request: CreateInvestigation;
}

function listParams(q: ListQuery): string {
  const p = new URLSearchParams();
  q.status?.forEach((s) => p.append("status", s));
  if (q.q?.trim()) p.set("q", q.q.trim());
  if (q.limit) p.set("limit", String(q.limit));
  if (q.offset) p.set("offset", String(q.offset));
  const s = p.toString();
  return s ? `?${s}` : "";
}

export const core = {
  health: (signal?: AbortSignal) => request<string>("core", "/health", { signal }),

  /* ---------- sign-in ---------- */
  login: (email: string, password: string) =>
    request<AuthSession>("core", "/v1/auth/login", { method: "POST", json: { email, password } }),
  logout: () => request<void>("core", "/v1/auth/logout", { method: "POST" }),
  session: (signal?: AbortSignal) => request<AuthSession>("core", "/v1/auth/session", { signal }),

  /* ---------- investigations ---------- */
  listInvestigations: (q: ListQuery = {}, signal?: AbortSignal) =>
    request<InvestigationPage>("core", `/v1/investigations${listParams(q)}`, { signal }),

  createInvestigation: (body: CreateInvestigation) =>
    request<InvestigationState>("core", "/v1/investigations", { method: "POST", json: body }),

  investigationPresets: (signal?: AbortSignal) =>
    request<InvestigationPreset[]>("core", "/v1/investigations/presets", { signal }),

  getInvestigation: (id: string, signal?: AbortSignal, token?: string) =>
    request<InvestigationState>("core", `/v1/investigations/${enc(id)}`, { signal, token }),

  events: (id: string, afterSeq: number, signal?: AbortSignal, token?: string) =>
    request<EventEnvelope[]>("core", `/v1/investigations/${enc(id)}/events?after_seq=${afterSeq}`, { signal, token }),

  answer: (id: string, body: SubmitAnswer, token?: string) =>
    request<AnswerResponse>("core", `/v1/investigations/${enc(id)}/answers`, { method: "POST", json: body, token }),

  answerByVoice: (id: string, questionId: string, participantId: string, audio: Blob, token?: string) => {
    const form = new FormData();
    form.set("question_id", questionId);
    form.set("participant_id", participantId);
    form.set("audio", audio, "answer.wav");
    return request<VoiceAnswerResponse>("core", `/v1/investigations/${enc(id)}/answers/voice`, {
      method: "POST",
      form,
      token,
    });
  },

  questionAudio: (id: string, questionId: string, token?: string) =>
    requestBlob("core", `/v1/investigations/${enc(id)}/questions/${enc(questionId)}/audio`, { token }),
  /** The same audio as a stream: uncached questions start playing before synthesis ends. */
  questionAudioStream: (id: string, questionId: string, token?: string) =>
    requestStream("core", `/v1/investigations/${enc(id)}/questions/${enc(questionId)}/audio`, { token }),

  requestApproval: (id: string, body: { action: string; target: string; participant_id: string }) =>
    request<InvestigationState>("core", `/v1/investigations/${enc(id)}/approvals`, { method: "POST", json: body }),

  /** The core records the signed-in approver; no identity is sent from the browser. */
  decideApproval: (id: string, approvalId: string, body: { decision: "approve" | "deny"; note?: string }) =>
    request<InvestigationState>("core", `/v1/investigations/${enc(id)}/approvals/${enc(approvalId)}/decision`, {
      method: "POST",
      json: body,
    }),

  collectCapability: (id: string, approvalId: string, participantId: string, token?: string) =>
    request<CapabilityGrant>(
      "core",
      `/v1/investigations/${enc(id)}/approvals/${enc(approvalId)}/capability?participant_id=${enc(participantId)}`,
      { method: "POST", token },
    ),

  reportIntervention: (id: string, body: { approval_id: string; participant_id: string }, token?: string) =>
    request<InvestigationState>("core", `/v1/investigations/${enc(id)}/interventions`, {
      method: "POST",
      json: body,
      token,
    }),

  participantToken: (id: string, participantId: string) =>
    request<ParticipantToken>("core", `/v1/investigations/${enc(id)}/participants/${enc(participantId)}/token`, {
      method: "POST",
    }),

  reveal: (id: string) => request<InvestigationState>("core", `/v1/investigations/${enc(id)}/reveal`, { method: "POST" }),

  /* ---------- packs ---------- */
  packs: (signal?: AbortSignal) => request<PackSummary[]>("core", "/v1/packs", { signal }),
  pack: (packId: string, signal?: AbortSignal) => request<SitePack>("core", `/v1/packs/${enc(packId)}`, { signal }),

  /* ---------- participant directory ---------- */
  directory: (packId?: string, signal?: AbortSignal) =>
    request<DirectoryParticipant[]>("core", `/v1/participants${packId ? `?pack_id=${enc(packId)}` : ""}`, { signal }),
  addParticipant: (packId: string, p: ParticipantSpec) =>
    request<DirectoryParticipant>("core", `/v1/participants?pack_id=${enc(packId)}`, { method: "POST", json: p }),
  updateParticipant: (packId: string, id: string, patch: ParticipantPatch) =>
    request<DirectoryParticipant>("core", `/v1/participants/${enc(id)}?pack_id=${enc(packId)}`, {
      method: "PATCH",
      json: patch,
    }),
  removeParticipant: (packId: string, id: string) =>
    request<void>("core", `/v1/participants/${enc(id)}?pack_id=${enc(packId)}`, { method: "DELETE" }),

  /* ---------- evaluation ---------- */
  evaluationReports: (signal?: AbortSignal) =>
    request<EvaluationReportSummary[]>("core", "/v1/evaluation/reports", { signal }),
  evaluationReport: (runId: string, signal?: AbortSignal) =>
    request<EvaluationReport>("core", `/v1/evaluation/reports/${enc(runId)}`, { signal }),

  /* ---------- voice ---------- */
  voiceStatus: (signal?: AbortSignal) => request<VoiceStatus>("core", "/v1/voice/status", { signal }),
  voiceUsage: (signal?: AbortSignal) => request<Record<string, unknown>>("core", "/v1/voice/usage", { signal }),
  stt: (audio: Blob, languageCodes: string[], codemix: boolean) => {
    const form = new FormData();
    form.set("audio", audio, "clip.wav");
    languageCodes.forEach((c) => form.append("language_codes", c));
    form.set("codemix", String(codemix));
    return request<SttResult>("core", "/v1/voice/stt", { method: "POST", form });
  },
};

/** The pack new investigations use when none is chosen. */
export const DEFAULT_PACK = "campus_block_c";
