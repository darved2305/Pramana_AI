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
| SDK/plugin header names | `x-language-candidates` and `x-keywords` are not listed on the current realtime page | doc, src | The adapter retains these as a live-observed workaround; vendor support for them remains unconfirmed |
| Language candidates | v3.0 documents `indic-auto` or 1–4 comma-separated codes | doc | A previously observed live rejection of the list led to `indic-auto` plus `x-language-candidates`; candidate enforcement needs live verification |
| `previous_text` on streaming | The previous audio's transcript provides context | doc | The live question stream does not send it; using a question as previous text is an experiment, not an established contract |
| Frames | Exactly 1,024 bytes of PCM s16le mono at real-time cadence | doc, src | `send_pcm` re-chunks and zero-pads the tail; test asserts `[1024, 1024, 1024]` |
| Transcripts | Final-only; no interim results, no confidence, no word timestamps | doc | No ASR confidence exists; decision-critical confirmation must use re-asking or a second REST decode |
| Short answers | High `x-min-segment-ms` silently drops "yes" | doc | We send 100 (the minimum) |
| Session cap | 15 min, then `error` and close 1001 | doc | We report the real close code. **Bug found by test**: `websockets` ends iteration silently on 1001; fixed |
| Errors | 401 key, 402 credit, 403 scope, 429 (no Retry-After), 504 upstream 5 s | doc | Typed `VOICE_*` codes; retry only 429/5xx/connection errors with 0.5/1/2 s backoff (Gnani's guidance) |
| Concurrency | Per-organisation cap; the number is not published | doc | `GNANI_MAX_CONCURRENCY=1` until measured |
| TTS | REST/SSE/WS with the same JSON body; WS takes one request at a time; no incremental text | doc | Streaming SSE serves uncached questions; REST WAV is a fallback |
| TTS chunk format | The TTS page describes `container: raw` with `linear_pcm` as headerless 16-bit PCM; it does not state the SSE chunk format explicitly. Audio is base64 in `chunk` events | doc + live | The 2026-11-05 live check with `container: raw` produced headerless PCM16 chunks |
| Voices | v3.0: 13 voices × 10 languages, **no Hinglish**; v2.5 Poorvi = `hi-en` | doc | `hi-en` is routed to timbre-v2.5/Poorvi; Marathi defaults to v3.0 Shivani (provisional, pending a listening test) |
| Devanagari TTS | Auto-detect treats Devanagari as Hindi; Marathi must be explicit | doc | We always pass the language explicitly |
| LiveKit plugin | Cannot select v3.0 | src | LiveKit is dropped as plan B (see VOICE_ARCHITECTURE.md) |

Public contract checked on 2026-11-10:

- [Realtime STT](https://docs.gnani.ai/api/STT/stt-websocket): the page now documents Prisma v3.0 with indic-auto or a comma-separated list of up to four language codes. On 2026-11-04, our authorized live check found the gateway rejected the comma list with "exactly one locale is required". The adapter therefore retains the then-working indic-auto plus x-language-candidates workaround. That earlier live result has not been rechecked against the current service. The realtime page documents keyterms, but not the x-language-candidates or x-keywords header names.
- [Prisma v3.0](https://docs.gnani.ai/api/STT/models/prisma-v3): the model documents per-segment language selection, code-mixed output and detected-language fields. Its streaming previous_text header means what was said just before this audio. The app does not send the question as previous_text; treating a question as that prior audio's transcript remains an experiment.
- [TTS SSE](https://docs.gnani.ai/api/TTS/tts-sse): the page says the audio field is base64 to decode and append in order. Container `raw` with encoding `linear_pcm` is described as headerless 16-bit PCM; `wav` includes a header. The page does not state the SSE chunk format explicitly, so the raw choice rests on the 2026-11-05 live check. The stream adapter requests raw.
- [Timbre voice catalog](https://docs.gnani.ai/api/TTS/available-voices): separate v3.0 and v2.5 voice catalogs are listed, including Poorvi for Hinglish (hi-en) on v2.5.
- [Great Indian AI Internship Challenge](https://www.gnani.ai/internship) and its [model overview](https://www.gnani.ai/resources/blogs/great-indian-ai-internship-challenge-2026): the programme markets Prisma v2.5 and Timbre v2.5, while this integration requests Prisma v3.0 and Timbre v3.0 for their current documented multilingual detection and voice catalogs. Hinglish TTS stays on Timbre v2.5 with Poorvi because that is the selected catalog voice for hi-en and the existing integration path was live-tested. This describes model selection, not a measured quality advantage. Account-specific model entitlement still needs checking before any live run.

Each page above was accessed on 2026-11-10. The [Gnani Vachana SDK](https://github.com/Gnani-AI-Mintlify/Gnani-Vachana) was also read that day: it shows language_candidates and keywords in SDK examples, but that does not document the x-language-candidates or x-keywords names on the realtime API page.
## Tested (protocol emulation, `services/core/tests/test_gnani_adapter.py`, 44 collected tests)

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
- **A complete spoken investigation runs end to end** (`run_text_investigation.py --voice`):
  Timbre speaks each question in the participant's language, the answer audio is transcribed by
  Prisma v3.0 REST with question context (language candidates, `codemix`, the probe's answer
  vocabulary as `keyterms`, and the question as `previous_text`), then extracted and applied.
  Runs covered Hinglish, Hindi and Marathi turns, and the reveal matched in both.
- **Billing minimums:** a 0.03-minute stream was debited Rs 0.02 (list price Rs 0.01), and the
  dashboard counted 20 STT requests where 17 transcribed, which suggests failed session attempts
  are billed. The meter now charges every STT request at least Rs 0.02, including failed
  attempts, so the budget errs high.

- **The per-question media socket works live (2026-11-05)** (`scripts/live_media_turn.py`):
  Timbre spoke the question, a synthesised Hinglish answer streamed as 16 kHz PCM went to
  Prisma v3.0 over the realtime session with the question's context, and the answer was
  recorded as a voice observation matching what that participant sees. The call runtime ran
  `ASKING -> LISTENING -> EXTRACTING -> IDLE -> CLOSING -> ENDED`. Two runs of one turn each;
  synthesised audio, not a human recording.

- **A whole investigation by voice works live (2026-11-05)** (`scripts/voice_bot_run.py`):
  three simulated participants on participant calls (ring, consent, question after question),
  answering from their own simulator views with Meta MMS-TTS voices in Hindi and Marathi
  (`scripts/make_bot_clips.py`). Timbre spoke every question and Prisma v3.0 transcribed every
  answer. The engine decided `DISPATCH_ELECTRICIAN_DB_C2`, the repair was approved and done
  with the capability, verification by voice ended `verified`, the reveal confirmed the decision
  and the commitment, and the replay was identical. Every voice answer was recorded as the
  value the bot meant. Spoken answers the decision hinged on were re-asked once each, so the
  spoken run took more questions than a typed one. Synthetic voices, one run.

- **The WebSocket close runs in the background**, so it does not block the next question
  (`GnaniSttStream.aclose`, `test_gnani_adapter.py`).

- **A real person on a real phone (2026-11-05).** One team member answered as Riya from an
  Android phone over a Cloudflare quick tunnel (`docs/engineering/STAGING.md`), speaking
  Hinglish into the participant page, with two simulated participants on calls alongside
  (`voice_bot_run.py --human p_riya`). The microphone path, the media socket through the
  tunnel, Prisma v3.0 on a human voice and the second-decode confirmation all worked; an
  unclear fragment was recorded as nothing. Two of the person's answers did not match their
  simulated view, and the engine still reached the right decision and verified the repair,
  with more questions. One run.

## Usage guards (`voice/governor.py`)

| Guard | Setting | Default | Account limit |
|---|---|---|---|
| STT REST requests per rolling minute (retries count) | `GNANI_STT_REST_PER_MIN` | 50 | 60 |
| TTS requests per rolling minute (retries count) | `GNANI_TTS_PER_MIN` | 50 | 60 |
| Concurrent realtime sessions (refused, not queued) | `GNANI_MAX_STREAMS` | 16 | 20 |
| Concurrent REST calls | `GNANI_REST_MAX_INFLIGHT` | 1 | "1 active request" in Gnani's 429 example |
| Daily spend, checked before every call (worst case for streams) | `VOICE_DAILY_BUDGET_INR` | 150 | 5,000 credits total |
| Max realtime session length | `VOICE_MAX_STREAM_S` | 300 s | 15 min |

PostgreSQL serializes rate windows, active reservations and settlement across core instances.
Each REST reservation covers up to four attempts, and a stream reservation covers its configured
maximum audio. Uncertain failures retain the worst-case charge; an abandoned reservation expires
after one hour and is charged conservatively. This can overestimate spend. A call is bounded to
less than the lease duration, and stream audio bytes are capped to the reserved duration. The
`GET /v1/voice/usage` response shows settled spend, shared pending reservations and limiter state.
The in-memory governor is used by isolated tests, not for cross-instance enforcement.

Migration 0023 re-applies the private-schema revokes for Supabase API roles; deployments must
also re-run the revoke of `anon` and `authenticated` on the Pramana schema after migrations.

## Remaining live checks

1. Human recordings (see VOICE_SAMPLES.md), not just synthesised audio: Marathi, Hindi and Hinglish short answers ("haan",
   "nahi", "band aahe", "chalu", room numbers, negations).
2. Whether more than one REST call can be in flight (raise `GNANI_REST_MAX_INFLIGHT` only if so).
3. Whether streamed silence is billed: compare the dashboard against `/v1/voice/usage`.

Run: `python scripts/gnani_live_check.py --out <dir outside the repo> [--stream-only]
[--probe-concurrency]`.
