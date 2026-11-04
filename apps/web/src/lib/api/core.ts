/**
 * Core service client. Every route here is in services/core/openapi.json; nothing is
 * invented. Routes the product will need but the core does not expose yet are listed in
 * `MISSING_ROUTES` so screens can say so instead of pretending.
 */
import { request, requestBlob } from "./http";
import type {
  AnswerResult,
  CapabilityGrant,
  CreateInvestigation,
  EventEnvelope,
  InvestigationState,
  ParticipantToken,
  SitePack,
  SttResult,
  SubmitAnswer,
  VoiceAnswerResult,
  VoiceStatus,
} from "./types";

const enc = encodeURIComponent;

export const core = {
  health: (signal?: AbortSignal) => request<string>("core", "/health", { signal }),

  createInvestigation: (body: CreateInvestigation) =>
    request<InvestigationState>("core", "/v1/investigations", { method: "POST", json: body }),

  getInvestigation: (id: string, signal?: AbortSignal) =>
    request<InvestigationState>("core", `/v1/investigations/${enc(id)}`, { signal }),

  events: (id: string, afterSeq: number, signal?: AbortSignal) =>
    request<EventEnvelope[]>("core", `/v1/investigations/${enc(id)}/events?after_seq=${afterSeq}`, { signal }),

  answer: (id: string, body: SubmitAnswer) =>
    request<AnswerResult>("core", `/v1/investigations/${enc(id)}/answers`, { method: "POST", json: body }),

  answerByVoice: (id: string, questionId: string, participantId: string, audio: Blob) => {
    const form = new FormData();
    form.set("question_id", questionId);
    form.set("participant_id", participantId);
    form.set("audio", audio, "answer.wav");
    return request<VoiceAnswerResult>("core", `/v1/investigations/${enc(id)}/answers/voice`, {
      method: "POST",
      form,
    });
  },

  questionAudio: (id: string, questionId: string) =>
    requestBlob("core", `/v1/investigations/${enc(id)}/questions/${enc(questionId)}/audio`),

  requestApproval: (id: string, body: { action: string; target: string; participant_id: string }) =>
    request<InvestigationState>("core", `/v1/investigations/${enc(id)}/approvals`, { method: "POST", json: body }),

  decideApproval: (id: string, approvalId: string, body: { decision: "approve" | "deny"; approver_id: string; note?: string }) =>
    request<InvestigationState>("core", `/v1/investigations/${enc(id)}/approvals/${enc(approvalId)}/decision`, {
      method: "POST",
      json: body,
    }),

  collectCapability: (id: string, approvalId: string, participantId: string) =>
    request<CapabilityGrant>(
      "core",
      `/v1/investigations/${enc(id)}/approvals/${enc(approvalId)}/capability?participant_id=${enc(participantId)}`,
      { method: "POST" },
    ),

  reportIntervention: (id: string, body: { approval_id: string; participant_id: string }) =>
    request<InvestigationState>("core", `/v1/investigations/${enc(id)}/interventions`, { method: "POST", json: body }),

  participantToken: (id: string, participantId: string) =>
    request<ParticipantToken>("core", `/v1/investigations/${enc(id)}/participants/${enc(participantId)}/token`, {
      method: "POST",
    }),

  reveal: (id: string) => request<InvestigationState>("core", `/v1/investigations/${enc(id)}/reveal`, { method: "POST" }),

  pack: (packId: string, signal?: AbortSignal) => request<SitePack>("core", `/v1/packs/${enc(packId)}`, { signal }),

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

/** The one site pack the core ships today (packs/campus_block_c.yaml). */
export const KNOWN_PACKS = ["campus_block_c"] as const;

/**
 * Capabilities the interface is designed for but the core does not provide yet. Screens
 * read this to show an honest notice rather than a fake result.
 */
export const MISSING_ROUTES = {
  listInvestigations: "GET /v1/investigations (list)",
  participantsDirectory: "a participant directory",
  listPacks: "GET /v1/packs (list)",
  auth: "authentication and sessions",
  evaluation: "an evaluation results endpoint",
} as const;
