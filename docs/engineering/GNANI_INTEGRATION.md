# Gnani integration report

Status on 2026-11-04: **adapters implemented and protocol-tested; no live call made.**
No `GNANI_API_KEY` was available in this environment. Every statement below is labelled as
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

## Blocked: needs a Gnani API key

Put it in `.env` as `GNANI_API_KEY=...`; it is read server-side only. Then run these, in order:

1. `GET /ready`: should show `"gnani": "configured"`.
2. STT REST with short Hindi, Marathi, English and Hinglish answers ("haan", "nahi", "band aahe",
   "chalu", "green", room numbers, negations).
3. TTS: one Marathi and one Hinglish question; play the WAV.
4. Realtime stream: does `model_confirmed` come back true?
5. Concurrency: open 1 → 4 streams, and send a REST burst; record which limit triggers 429.
6. Credit delta for 60 s of streamed speech vs silence (from the dashboard).

Results go in a private section of this report, not in public posts.
