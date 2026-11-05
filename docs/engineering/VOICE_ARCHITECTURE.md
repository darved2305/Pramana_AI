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
- A usage governor (`voice/governor.py`): rate windows below the account's 60/min, at most 16
  of the 20 concurrent sessions, one REST call in flight, and a daily rupee budget checked
  before every call and persisted in PostgreSQL.
- Voice turns inside an investigation: `GET /v1/investigations/{id}/questions/{qid}/audio`
  (cached, so a replay costs nothing) and `POST /v1/investigations/{id}/answers/voice`
  (question-conditioned STT, then the same extraction and engine path as typed answers). This
  is half-duplex push-to-talk, verified live.
- **Per-question media WebSocket** (`WS /v1/investigations/{id}/questions/{qid}/media`,
  `voice/media.py`, docs/adr/0013). The participant token goes in the first message, not the
  URL. The core checks it, checks that the question is pending and addressed to that person,
  allows one open session per token, opens a Prisma v3.0 session with that question's context
  (language candidates, `codemix`, answer keyterms, `x-min-segment-ms` 100), sends the question
  audio in 16 KiB binary chunks, relays `speech_start`/`processing`/`transcript`, and submits
  the first non-empty transcript through the normal answer path. Empty transcripts record
  nothing; a question answered elsewhere ends the session with `409 QUESTION_NOT_PENDING`;
  governor refusals arrive as typed error frames and close code 4429. Tested against the
  protocol emulation only (`tests/test_media_ws.py`); not yet run against live Gnani.
- **Browser capture** (`apps/web/public/worklets/pcm16-capture.js`): an AudioWorklet that
  low-pass filters (63-tap windowed sinc) and resamples 48/44.1 kHz input to 16 kHz mono PCM16
  in 1,024-byte frames; `node apps/web/scripts/check-pcm-worklet.mjs` checks frame size, rate,
  passband gain and 12 kHz rejection. `apps/web/src/lib/audio/media.ts` is the client, with
  barge-in (playback stops on `speech_start`).
- **Call runtime skeleton** (`calls/runtime.py`): the PLAN §12 state machine as an explicit
  transition table, with an injected clock for the 30 s ring, 8 s re-prompt (once) and 20 s
  unavailable timers, utterance ids for dropping stale audio, and a preemption hook. Every
  state and event pair is tested (`tests/test_call_runtime.py`).
- **The call runtime drives each media session.** Opening the socket counts as accepted and
  consented, so the session starts in `ASKING`. `playback_done` (or the end of the question
  audio) moves it to `LISTENING`; speech during `ASKING` is barge-in and the server sends
  `stop_playback`. After 8 s of silence the question is asked once more (cached audio, no new
  charge); after 20 s the session ends with `PARTICIPANT_SILENT` (close 4408) and the question
  stays pending. Every transition is sent as `call_state`. Tests: `test_media_ws.py`
  (spoken turn, barge-in, re-prompt then give up, hang up).

- **Decision-critical spoken answers are checked by a second decode, not by asking again.**
  The first recognition is steered toward the expected words (the probe's answer vocabulary as
  `keyterms`, the question as context). When one spoken answer would move the decision, the
  same audio is decoded again through Prisma REST *without* that steering (about Rs 0.02). If
  both readings give the same outcome, the speech discount is removed and the call moves on,
  logged as `ObservationConfirmed {method: "second_decode"}`. If they differ, nothing is heard,
  or the check fails (budget, rate limit), the person is asked again as before
  (`investigations.py::_second_decode_agrees`; `test_voice_turns.py`, `test_media_ws.py`).

- **Question audio is synthesised once.** It is cached by (text, language, voice) in memory
  and on disk (`TTS_CACHE_DIR`, default `.cache/tts`, at most 500 files, least recently used
  evicted), so it survives restarts; question texts come from fixed templates, so they repeat.
  Synthesis of an uncached question runs while the recognizer session connects. Each turn logs
  `turn_setup` (stream open and question audio times) for private tuning, and
  `scripts/voice_bot_run.py` prints the caller-side turn latency. Under the Gnani EULA these
  measurements stay out of the repository.

- **Streamed question audio.** A question that is not cached yet is synthesised over Timbre SSE
  with `container: raw` (checked live on 2026-11-05: headerless PCM16 chunks, the first well
  before the last). The media socket forwards it as `tts_start {format: "pcm_s16le",
  sample_rate: 24000, streaming: true}` plus binary pieces of at least 0.2 s; the browser
  schedules them back to back (`apps/web/src/lib/audio/media.ts`). "Listen to the question"
  streams too: `GET .../audio` sends a WAV header with an open-ended length, then PCM as it
  arrives (`X-Audio-Streamed: true`), played while downloading
  (`apps/web/src/lib/audio/wav-stream.ts`). The joined audio is cached as a normal WAV, so a
  repeat is one WAV at no cost. If the stream fails before its first chunk, one REST WAV is
  used. Tests: `test_gnani_adapter.py` (SSE parsing, typed failures), `test_media_ws.py`
  (streamed then cached, fallback, streamed Listen endpoint), `apps/web/tests/streamed-audio.spec.ts`
  (decoded and scheduled gaplessly in Chrome).

## Template quality and spoken text

`pramana_core.language.realizer_lint` checks every YAML pack under `packs/`. CI runs the pack
coverage test as part of `uv run pytest`; the standalone command is:

```powershell
uv run python -m pramana_core.language.realizer_lint
```

The linter checks all four template languages, stripped text, known placeholders at every valid
probe location, move-prefix rendering, confirmation prefixes, and the consent greeting. It checks
the probe outcome wording against the short answer vocabulary, script balance, unresolved machine
IDs, em dashes, terminal question punctuation, and spoken length. A phone question, including its
move and confirmation wording, is capped at 260 characters and 50 words after normalization. The
longest current combined form is 222 characters and 48 words. The caps leave a small margin for
template changes while catching accidental long questions. The call re-prompt repeats the same
question, so it uses the same checks. There is no separate spoken goodbye line.

`pramana_core.language.speakable.speakable(text, language)` creates text only for Timbre. The
participant page keeps the reviewed display string. Known site IDs such as `DB-C2`, `IDF-1`, and
`MAIN-1` are expanded letter by letter, and their digits are spoken as language-appropriate words.
Wi-Fi spellings, the `NAVA-WiFi` network name, and technical initialisms such as `IP`, `ONT`, `PON`,
and `CCTV` have deterministic language-specific forms. Quotes around names are removed, ellipses
become a short pause, and a literal IPv4 address is spoken digit by digit. Room numbers
such as `room 205` remain numeric so Timbre can read them as quantities. Gnani documents language
aware handling for ordinary numbers, dates, IDs, and common abbreviations in its
[Text Normalization Guide](https://docs.gnani.ai/api/TTS/tts-input-formating).

The normalizer is used for the staff TTS route, the call greeting, cached REST audio, streamed
question audio, and stream fallback. Cache keys use the normalized spoken text, so a changed
pronunciation gets a fresh synthesis. The table-driven behavior and idempotence are tested across
every rendered probe, language, location, move prefix, and confirmation prefix.

The generated [Hindi and Marathi language review sheet](LANGUAGE_REVIEW.md) lists each displayed
question and the normalized spoken text for direct, move, confirmation, and move-confirmation
forms. Native-speaker review of Hindi and Marathi wording and pronunciation is pending.

## Not yet implemented

- Preemption across parallel calls (ADR 0011): several people on calls at once, with a
  question dropped when another answer makes it pointless. The per-call socket
  (`voice/call.py`: ring, logged consent, question after question, release on decline or
  silence) exists; the console does not yet start calls for several people at once.
- Published latency figures. Measurements exist but stay private under the Gnani EULA.
