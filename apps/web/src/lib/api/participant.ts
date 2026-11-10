/**
 * What a participant's own link may do, with the participant token as its only credential.
 * Links issued inside a workspace use that workspace's routes; older links the legacy ones.
 */
import { actionKey } from "./account";
import { core } from "./core";
import { request, requestStream } from "./http";
import type { AnswerResult, CapabilityGrant, InvestigationState, SubmitAnswer, VoiceAnswerResult } from "./types";
import type { JoinPayload } from "@/lib/join";

export function participantApi(link: JoinPayload) {
  const root = link.o ? `/v1/orgs/${encodeURIComponent(link.o)}/investigations/${encodeURIComponent(link.i)}` : null;
  const post = <T>(path: string, json?: unknown) =>
    request<T>("core", `${root}${path}`, {
      method: "POST",
      json,
      token: link.t,
      headers: { "Idempotency-Key": actionKey("participant") },
    });
  return {
    getInvestigation: () =>
      root ? request<InvestigationState>("core", root, { token: link.t }) : core.getInvestigation(link.i, undefined, link.t),
    answer: (body: SubmitAnswer) => (root ? post<AnswerResult>("/answers", body) : core.answer(link.i, body, link.t)),
    answerByVoice: (questionId: string, audio: Blob) => {
      if (!root) return core.answerByVoice(link.i, questionId, link.p, audio, link.t);
      const form = new FormData();
      form.set("question_id", questionId);
      form.set("participant_id", link.p);
      form.set("audio", audio, "answer.wav");
      return request<VoiceAnswerResult>("core", `${root}/answers/voice`, {
        method: "POST",
        form,
        token: link.t,
        headers: { "Idempotency-Key": actionKey("voice") },
      });
    },
    questionAudioStream: (questionId: string) =>
      root
        ? requestStream("core", `${root}/questions/${encodeURIComponent(questionId)}/audio`, { token: link.t })
        : core.questionAudioStream(link.i, questionId, link.t),
    collectCapability: (approvalId: string) =>
      root
        ? post<CapabilityGrant>(`/approvals/${encodeURIComponent(approvalId)}/capability?participant_id=${encodeURIComponent(link.p)}`)
        : core.collectCapability(link.i, approvalId, link.p, link.t),
    reportIntervention: (approvalId: string) =>
      root
        ? post<InvestigationState>("/interventions", { approval_id: approvalId, participant_id: link.p })
        : core.reportIntervention(link.i, { approval_id: approvalId, participant_id: link.p }, link.t),
  };
}
