# 0013: One media WebSocket per pending question

**Status:** accepted

**Context.** PLAN.md §11 sketched one media socket per call (`/v1/calls/{call_id}/media`), with a
fresh Prisma session per question inside it. The call runtime that would own such a socket
(consent, re-prompts, preemption) is not wired yet, while the participant page already works
question by question (`pending_question`).

**Decision.** `WS /v1/investigations/{id}/questions/{qid}/media`, one socket per pending
question (`services/core/src/pramana_core/voice/media.py`).
- The socket's lifetime equals one Prisma session's lifetime, so per-question context headers
  (language candidates, `codemix`, keyterms, `x-min-segment-ms` 100) are set at connect time,
  as Prisma requires, and no session approaches the 15-minute cap.
- Authentication is the participant token in the first message (`{"type":"start","token"}`).
  Browsers cannot set WebSocket headers, and a token in the query string would be written to
  access logs. The core verifies its own Ed25519 signature, the scenario, and that the question
  is addressed to the token's participant. One open session per token `jti` (PLAN §18).
- Everything before the Prisma session is free: a bad token, a wrong participant, an unknown or
  answered question, or a governor refusal (stream slots, rate, daily budget) is rejected before
  any credit is spent. Close codes mirror HTTP statuses (4401, 4403, 4404, 4409, 4429, 4503).
- The answer goes through `InvestigationService.answer` with `modality=voice`, the same path as
  typed and uploaded answers, so extraction, decision-critical confirmation and the event log
  are unchanged.
- The session watches the investigation through the event broadcaster (ADR 0009). If the
  question is answered elsewhere, it ends with `QUESTION_NOT_PENDING` instead of transcribing
  audio nobody will use.

**Consequences.** Opening a socket per question costs one WebSocket and one Prisma handshake per
question; the handshake can overlap with question playback because the session opens before
the audio is sent. The call runtime (`calls/runtime.py`) now drives each session (barge-in, one re-prompt,
silence timeout). A per-call socket can later multiplex these per-question sessions without changing the answer path.

**Tests.** `services/core/tests/test_media_ws.py`, against the local Prisma emulation: spoken
answer end to end (headers, frames, transcript, answer, replay identical), empty transcript,
tap answer, forged and wrong-participant tokens, bad first message, unknown and answered
questions, a question answered elsewhere mid-stream, one session per token, bad frames, a TTS
failure that is not fatal, budget and not-configured refusals, and the concurrent-stream cap.
