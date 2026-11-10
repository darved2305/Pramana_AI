# 0002 - Direct FastAPI gateway to Gnani; LiveKit dropped as plan B

**Status:** accepted (supersedes the "LiveKit plan B" line in PLAN.md §2)

**Decision.** Browser audio goes to `/v1/voice/*` on the core, which talks to Prisma and Timbre
directly. The fallback is REST-per-utterance STT in the same gateway. The transport fallback is
Pipecat with `pipecat-gnani`.

**Evidence.** `livekit-plugins-gnani` 1.8.10 sends no model header, so it cannot use Prisma v3.0.
LiveKit also runs each job in a separate process. Details and sources are in
docs/engineering/VOICE_ARCHITECTURE.md.

**Consequences.** We own barge-in and turn handling, using patterns copied from Retell, OpenAI
Realtime and Deepgram. Browser WebSocket audio has no WebRTC jitter buffer; that is acceptable
for short question/answer turns, and is re-evaluated if live tests show drops.
