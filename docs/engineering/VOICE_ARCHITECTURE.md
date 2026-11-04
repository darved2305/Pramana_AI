# Voice architecture

**Decision: a direct FastAPI WebSocket gateway to Gnani (option A).** Fallback: REST-per-utterance
STT inside the same gateway. Transport fallback, only if browser WebSocket audio proves unreliable:
Pipecat with `pipecat-gnani`. LiveKit is **not** a viable fallback today (see below).
This corrects PLAN.md §2, which named LiveKit as plan B.

Sources were read on 2026-11-04. "Verified" means we read the vendor's documentation page or the
installed package source.

## Requirements that drive the choice

1. Several **isolated 1:1 calls** must feed **one in-process investigation state**. That state is
   serialised per investigation (`services/core/src/pramana_core/investigations.py`).
2. Each question needs its own **Prisma v3.0 context**: language candidates, `keyterms` with that
   question's answer vocabulary, and `codemix` for Hinglish speakers.
3. The Gnani API key must stay server-side. Browsers cannot set WebSocket headers, so a proxy is
   required anyway.
4. It must be testable without credits: protocol emulation in CI, and live calls run only on demand.

## Comparison

| | A. FastAPI WS gateway (chosen) | B. LiveKit Agents + `livekit-plugins-gnani` | C. Pipecat + `pipecat-gnani` |
|---|---|---|---|
| Prisma v3.0 selectable | Yes: we send `model: prisma-v3.0` | **No.** Plugin 1.8.10 sends no model header, so the server default (v2.5) is used. Verified in `livekit/plugins/gnani/stt.py` | Yes: `x-model`, `x-language-candidates`, `x-keywords`. Verified in `pipecat_gnani/stt.py` |
| Per-question context headers | Yes, one session per question | No `keyterms` or language list | Language/keywords yes; changing them forces a reconnect (`_update_settings` reconnect set) |
| Shared in-process state | Direct: the calls are tasks in one event loop | Each job runs **in its own process** ("Each job runs in a separate process", docs.livekit.io/agents/server/job), so state needs IPC or an external store | Possible if pipelines run in our process with the FastAPI WebSocket transport (not verified at scale) |
| Transport robustness | Browser WebSocket (TCP); no jitter buffer or NAT traversal | WebRTC (best on bad networks) | WebSocket or SmallWebRTC |
| Turn detection | Prisma server VAD (`x-min-silence-ms`, `x-min-segment-ms`) | VAD plus a semantic turn model (docs.livekit.io/agents/logic/turns) | VAD and Smart Turn |
| Barge-in / interruption | Our own state machine (per-utterance ids; stop playback on `speech_start`) | Built in (`session.interrupt()`, false-interruption recovery) | Built in (`InterruptionFrame` cancels LLM, TTS and the audio queue) |
| Debuggability | Full control; protocol emulation tests (`tests/fake_gnani.py`) | Framework internals plus a separate process per job | Framework internals |
| Cost / ops | One process; no media server | LiveKit Cloud (free tier: 5 concurrent sessions) or a self-hosted SFU | One process |

## Why A, in one paragraph

The deciding fact is that the official LiveKit plugin cannot select Prisma v3.0. Without v3.0 we
lose code-mixed output, multi-language candidates and context hints, which are the features our
Marathi/Hindi/Hinglish short answers rely on. LiveKit's process-per-job model would also put our
shared belief state behind IPC. Pipecat works, but it brings a frame-pipeline framework built
around an LLM conversation loop. Our "conversation" is a deterministic question/answer exchange
driven by the planner, so we would use little of what Pipecat provides. The gateway is around 300
lines (`voice/gnani.py`, `api/voice.py`), and its wire format is pinned by tests.

## Patterns adopted from production platforms (verified documentation)

- **Turn and utterance ids; drop stale audio.** Retell discards responses whose `response_id` is
  stale (docs.retellai.com/api-references/llm-websocket). Vapi tags turns with `turnId`. The call
  runtime will tag every agent utterance and drop superseded audio.
- **Stop playback first, then reconcile.** OpenAI Realtime stops playback on `speech_started` and
  truncates the assistant item to what was heard. ElevenLabs sends an `interruption` event.
- **Separate end-of-turn tuning from barge-in tuning.** Vapi has `startSpeakingPlan` and
  `stopSpeakingPlan` as separate settings. Our end-of-turn comes from Prisma VAD headers;
  barge-in uses `speech_start`.
- **Explicit flush.** Deepgram uses `Finalize`/`CloseStream`. Prisma provides `{"type":"commit"}`,
  which `GnaniSttStream.commit()` sends after zero-padding the final partial frame.
- **Heartbeats and bounded sessions.** Retell uses a 2 s ping and a 5 s deadline. Deepgram sends
  KeepAlive within 10 s. Prisma documents no keepalive, so we rely on WebSocket pings (20 s), a
  per-session cap (`MAX_STREAM_S = 300`), and Gnani's own idle timeout (`x-idle-timeout-sec`).

## Implemented now

- `GnaniClient.transcribe` (REST, ≤ 30 s, typed errors, retries only 429/5xx/connection errors),
  `GnaniClient.synthesize` (Timbre REST, WAV), and `GnaniClient.open_stream` (realtime, exact
  1,024-byte frames, `commit`, real close codes including 1001).
- `/v1/voice/stt`, `/v1/voice/tts`, and `/v1/voice/stream` (a browser → core → Prisma relay that
  measures end-of-speech → transcript latency).
- A concurrency governor: `GNANI_MAX_CONCURRENCY` (default 1, because the account limit is not
  published).

## Not yet implemented

- The call runtime state machine (PLAN §12): consent, ASKING/LISTENING, barge-in, re-prompts.
- Speaking each planned question with TTS and feeding the transcript into `/answers`. The pieces
  exist: `realize()` gives the text, `/v1/voice/tts` speaks it, `/v1/voice/stt` or the stream
  transcribes the answer, and `/answers` extracts it.
- Any measured latency. No live Gnani call has been made, because no API key was available
  (see GNANI_INTEGRATION.md).
