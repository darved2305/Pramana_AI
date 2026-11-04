# Gnani integration report

Status on 2026-11-04: **adapters implemented, protocol-tested, and exercised live** (TTS v3.0 and
v2.5, STT REST v3.0, STT realtime v3.0, three simultaneous streams). Every statement below is labelled as
**doc** (docs.gnani.ai page), **src** (installed package source), or **test** (our executable
tests against a local protocol emulation). Nothing here is a measured Gnani result. Per EULA §16,
measured Gnani accuracy or latency numbers must not be published outside the team.

## Sources examined

- docs: `llms.txt`, `api/STT/stt-websocket.md`, `api/STT/models/prisma-v3.md`,
  `api/STT/speech-to-text.md`, `api/STT/limits.md`, `api/introduction/errors.md`,
  `api/TTS/tts-websocket.md`, `tts-inference.md`, `tts-sse.md`, `available-voices.md`,
  `tts-input-formating.md`.
- src: `gnani-vachana` 0.9.0, `livekit-plugins-gnani` 1.8.10, `pipecat-gnani` 0.6.0. These were
  downloaded as wheels and read, not executed.

## What was verified and how it changed the plan

| Topic | Finding | Source | Consequence |
|---|---|---|---|
| Default STT model | v2.5 unless v3.0 is requested | doc, src (pipecat `_prisma.py`) | We always send `model: prisma-v3.0` |
| Unknown streaming model | Silently ignored; v2.5 used, no error | doc (stt-websocket) | We check the `connected.config` echo; `model_confirmed=false` is logged and returned to the client |
| Streaming header names | Canonical: `language_code`, `model`, `format`, `keyterms`, `topic`. Legacy (`lang_code`, `x-model`, `x-format`) still accepted | doc | We send canonical names, plus `x-model` for robustness. PLAN.md's names were correct |
| SDK/plugin header names | SDK sends `x-language-candidates` and `x-keywords`, which the docs never mention | src | Not used; we follow the docs |
| Language candidates | v3.0: `language_code` = `indic-auto` or 1–4 comma-separated codes | doc | `LanguageProfile.stt_candidates` (1–4) maps straight to it |
| `previous_text` on streaming | Contradictory: header table lists it, limits table says "REST only" | doc | Not sent on streaming; REST only |
| Frames | Exactly 1,024 bytes of PCM s16le mono at real-time cadence | doc, src | `send_pcm` re-chunks and zero-pads the tail; test asserts `[1024, 1024, 1024]` |
| Transcripts | Final-only; no interim results, no confidence, no word timestamps | doc | No ASR confidence exists; decision-critical confirmation must use re-asking or a second REST decode |
| Short answers | High `x-min-segment-ms` silently drops "yes" | doc | We send 100 (the minimum) |
| Session cap | 15 min, then `error` and close 1001 | doc | We report the real close code. **Bug found by test**: `websockets` ends iteration silently on 1001; fixed |
| Errors | 401 key, 402 credit, 403 scope, 429 (no Retry-After), 504 upstream 5 s | doc | Typed `VOICE_*` codes; retry only 429/5xx/connection errors with 0.5/1/2 s backoff (Gnani's guidance) |
| Concurrency | Per-organisation cap; the number is not published | doc | `GNANI_MAX_CONCURRENCY=1` until measured |
| TTS | REST/SSE/WS with the same JSON body; WS takes one request at a time; no incremental text | doc | REST WAV for now (simplest playable artefact) |
| TTS chunk format | Not documented whether WS/SSE chunks are WAV or raw; SDK strips a RIFF header from every chunk | doc + src | Avoided by using REST WAV; must be checked live before streaming TTS |
| Voices | v3.0: 13 voices × 10 languages, **no Hinglish**; v2.5 Poorvi = `hi-en` | doc | `hi-en` is routed to timbre-v2.5/Poorvi; Marathi defaults to v3.0 Shivani (provisional, pending a listening test) |
| Devanagari TTS | Auto-detect treats Devanagari as Hindi; Marathi must be explicit | doc | We always pass the language explicitly |
| LiveKit plugin | Cannot select v3.0 | src | LiveKit is dropped as plan B (see VOICE_ARCHITECTURE.md) |

## Tested (protocol emulation, `services/core/tests/test_gnani_adapter.py`, 26 tests)

- The REST multipart fields we send: `model`, the language list, `format=codemix`, and
  `keyterms` as a JSON array.
- Parsing of a successful response; an empty transcript is reported, not raised.
- Error mapping and retry counts for 400/401/402/403/429/500/504 and for timeouts.
- Bad WAV and audio over 30 s are rejected before any credit is spent.
- TTS request body, Hinglish routing, and rejection of empty or non-WAV responses.
- Streaming: headers, ASCII-escaped keyterms, frame sizes, `commit`, the event sequence, detection
  of the silent model fallback, 401/429 at handshake, and the close-1001 surface.
- The browser relay `/v1/voice/stream` end to end against the emulation.

## Verified live (2026-11-04), integration facts only

Per the EULA, accuracy and latency results stay out of this repository; they are kept privately.

- **Streaming language candidates (contradicts the docs).** `language_code: mr-IN,hi-IN` is
  rejected with *"exactly one locale is required … Use multi_lang_codes"*. The shape that works
  is `language_code`/`lang_code: indic-auto` plus `x-language-candidates: mr-IN,hi-IN`, as the
  SDK sends it. `GnaniClient.open_stream` now does this, and a test pins it.
- **v3.0 on streaming is confirmed** by the `connected` echo (`model_confirmed: true`).
- **Concurrency:** three simultaneous realtime sessions all transcribed. The account dashboard
  states 20 concurrent sessions; the governor caps us at 16.
- **Account limits (dashboard):** STT REST 60 requests/min, STT WebSocket 20 concurrent, TTS 60
  requests/min. Prices: STT Rs 20/audio hour, TTS Rs 18/10,000 characters; 1 credit = Rs 1.
- **Billing granularity:** a 28-character TTS request was debited Rs 0.06 (list price Rs 0.0504),
  so each request is rounded up to the next paisa. The governor meters the same way.
  Characters are Unicode code points (Python `len` matched Gnani's count).
- **Timbre WAV headers declare a placeholder data length (2³² bytes).** Compute duration from
  the byte count, not the header. `wav_duration_s` already clamps to the real size.
- **Hinglish TTS** routed to timbre-v2.5/Poorvi is accepted.

## Usage guards (`voice/governor.py`)

| Guard | Setting | Default | Account limit |
|---|---|---|---|
| STT REST requests per rolling minute (retries count) | `GNANI_STT_REST_PER_MIN` | 50 | 60 |
| TTS requests per rolling minute (retries count) | `GNANI_TTS_PER_MIN` | 50 | 60 |
| Concurrent realtime sessions (refused, not queued) | `GNANI_MAX_STREAMS` | 16 | 20 |
| Concurrent REST calls | `GNANI_REST_MAX_INFLIGHT` | 1 | "1 active request" in Gnani's 429 example |
| Daily spend, checked before every call (worst case for streams) | `VOICE_DAILY_BUDGET_INR` | 150 | 5,000 credits total |
| Max realtime session length | `VOICE_MAX_STREAM_S` | 300 s | 15 min |

Spend is recorded per call in PostgreSQL (`voice_usage`), so restarts do not reset it.
`GET /v1/voice/usage` shows today's spend and the live limiter state. The limits apply per core
process.

## Remaining live checks

1. Human recordings, not just TTS audio: Marathi, Hindi and Hinglish short answers ("haan",
   "nahi", "band aahe", "chalu", room numbers, negations).
2. Whether more than one REST call can be in flight (raise `GNANI_REST_MAX_INFLIGHT` only if so).
3. Whether streamed silence is billed: compare the dashboard against `/v1/voice/usage`.

Run: `python scripts/gnani_live_check.py --out <dir outside the repo> [--stream-only]
[--probe-concurrency]`.
