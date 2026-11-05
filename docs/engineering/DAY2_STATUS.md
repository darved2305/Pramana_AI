# Day 2 status: "Text loop end-to-end" (M1)

Audit of PLAN.md §26 (Thu Nov 5) against the code. An item is **done** only with a passing
test or a recorded live run as evidence. Updated as work lands.

## Baseline (start of the day, commit 9f78fa3)

- Python: ruff, ruff format, mypy (strict, 5 packages), import-linter (3 contracts kept):
  clean. `pytest`: **291 passed**.
- Web: `npm run typecheck`, `lint`, `check:copy`: clean. `npm run test:e2e`: **22 passed**
  (Chrome, production build on port 3012).
- Note: `make` is not installed on the Windows dev machine. The Makefile's commands were run
  directly. `scripts/dev.py` provides the same entry points without make.

## Initial audit

| Item | State at start | Evidence |
|---|---|---|
| D05 actor + event store | **partial** | Single writer via `asyncio.Lock` + `SELECT ... FOR UPDATE` (ADR 0003), `investigations.py`; replay test `test_engine_rebuilt_from_events_matches_live_state`, `test_verification_survives_an_engine_rebuild`. Missing: startup recovery supervisor, byte-for-byte replay check |
| D06 fan-out | **partial** | Polling only: `GET /v1/investigations/{id}/events?after_seq=`, `test_event_log_is_ordered_and_resumable`. No push channel |
| D15 LLM clients | **partial** | `llm.py` with pacing, daily cap, disk cache, reasoning-control retry (`eval/tests/test_benchmark.py`). Errors are one untyped `LlmError` |
| D04 voice gateway v1 | **partial** | Gnani REST/stream adapters, governor, `/v1/voice/stream` relay, push-to-talk voice answers (`test_gnani_adapter.py`, `test_voice_turns.py`). Missing: AudioWorklet capture, per-question media WebSocket, streamed TTS |
| D09 simulator shell | **done** | `services/sim/app.py`; `test_sim_api.py` (operator/oracle/participant auth, capability rules) |
| D08 participant app v0 | **partial** | `apps/web/src/app/join/[token]/page.tsx` (text, tap, WAV voice, view card); covered only by preview-mode Playwright, not against a real backend |
| D07 call runtime skeleton | **missing** | No `calls/` package |
| N04 belief upgrades | **partial** | Singles + NO_FAULT + OPEN_WORLD, contradiction detection, one Hypothesis property test (`test_posterior_is_always_a_distribution`), hand computation at 1e-9. Missing: reliability quadrature, fault pairs, monotonicity / order-invariance properties |
| N05 planner v0 | **done (verify)** | Feasibility, cost, EIG_D/EIG_H, two-step stopping, abstention: `test_planner.py` (16 tests incl. brute-force EIG) |
| N11 intake | **partial** | Report mapped to the `internet_works` probe by the extractor (`_intake`); no intake role or test set |
| N03 simulator core | **done (verify)** | Scenarios, views, moves, interventions, commitment: `test_sim_api.py::test_commitment_binds_the_fault`, `test_approved_reset_changes_the_world_once` |
| N09 extractor v1 + 80 utterances | **partial** | Rules + LLM second opinion; 48-utterance development set only (`eval/data/extraction_set.jsonl`); no held-out set or per-language report |
| `make dev` | **missing** | Makefile has separate targets only |
| 12+ probes | **missing** | Pack has 10 probes |
| `docs/spike-gnani.md` pointer | **missing** | Findings live in `docs/engineering/GNANI_INTEGRATION.md` |
| M1 automated end to end | **missing** | `scripts/run_text_investigation.py` plays one run manually; no automated test against running services; no real-backend Playwright |
| Decision: parallel calls | **done** | ADR 0011 (go, cap 3 per investigation) |
| Decision: Evon GPU | **done** | ADR 0012 (no-go: no quote or GPU obtainable without a payment method) |

## Current state (main at 06c9e9e; CI green on both jobs)

Totals: **776 pytest** (incl. 4 live end-to-end tests against real sim + core processes),
**27 Playwright** (mocked backend) and **10 Playwright against a real core, simulator and
PostgreSQL** (`npm run test:e2e:real`). ruff, ruff format, mypy strict, import-linter, schema
and OpenAPI drift, generated-type drift and the bundle secret scan are clean.

| Item | State | Evidence |
|---|---|---|
| D05 actor + event store, recovery | **done** | Startup supervisor rebuilds every open investigation and compares canonical JSON with the last `BeliefUpdated`; `GET /v1/investigations/{id}/replay`. `test_recovery.py`; live: `tests/e2e/test_m1.py::test_core_crash_mid_investigation_loses_nothing` (hard kill, restart, byte-identical belief) |
| D06 push channel | **done** | SSE `GET /v1/investigations/{id}/stream` (ADR 0009): resume by `after_seq` / `Last-Event-ID`, 15 s heartbeat, non-blocking writers. `test_event_stream.py` (15, real uvicorn). Console uses it with polling fallback; the real-backend M1 Playwright test checks the stream was opened |
| D15 LLM clients | **done** | Typed errors, schema check, keys redacted: `test_llm_client.py`; reasoning-control retry in `eval/tests/test_benchmark.py` |
| D04 voice gateway v1 | **done (emulated)** | AudioWorklet capture (`npm run check:worklet`), per-question media WebSocket with Prisma v3.0 context (ADR 0013), driven by the call runtime (barge-in, one re-prompt, silence timeout). `test_media_ws.py` (18) against the Prisma emulation. **Live turn verified** (`scripts/live_media_turn.py`, synthesised Hinglish answer). The browser socket through the Next rewrite is proven by `apps/web/tests-real/media-proxy.spec.ts` (core close codes 4401 and 4503 reach the browser) |
| D07 call runtime | **done** | `calls/runtime.py`, every state x event pair in `test_call_runtime.py`. It drives a whole participant call over one socket (`voice/call.py`): ring, logged consent, question after question, and release on decline, "later", no answer or silence, after which the engine asks someone else (`test_call_ws.py`, 6 tests; replay identical). The participant page rings and asks consent (`apps/web/tests-real/call.spec.ts`) |
| D08 participant app v0 | **done** | `/join/<token>`: view card, text, tap, live voice with WAV fallback, capability and repair report; real-backend M1 Playwright test |
| D09 simulator shell | **done** | `test_sim_api.py` |
| N04 belief upgrades | **done** | ADR 0008; `test_belief_model.py` (Hypothesis: order invariance, normalisation, monotonicity, EIG bounds); hand computation exact |
| N05 planner v0 | **done** | `test_planner.py`; S1 decided in 4 questions (engine test and live e2e) |
| N11 intake | **done** | `language/intake.py`, `test_intake.py` (development figures) |
| N03 simulator core | **done** | `test_sim_api.py` (commitment published at creation, verified on reveal) |
| N09 extractor + 80 held-out | **done** | Blind baseline 62/80; current 74/80 with no wrong outcomes, **not blind** (see the report's NOTES.md) |
| `make dev`, 14 probes, spike pointer | **done** | `scripts/dev.py`, `test_physics.py`, `docs/spike-gnani.md` |
| M1 line 1: S1 text mode, live console, participant pages, <= 6 questions | **done** | `apps/web/tests-real/m1.spec.ts` (browser) and `tests/e2e/test_m1.py` (Python bot) |
| M1 line 2: approval flow to `verified` or reopen | **done** | Same tests: deny then approve, capability once and expiring, act, report, verify; misled run reopens |
| M1 line 3: byte-identical replay | **done** | `/replay` and `tests/e2e/replay.py` |
| Decisions | **done** | ADR 0011 parallel calls go (cap 3); ADR 0012 Evon no-go (no quote or GPU without a payment method) |

## Frontend wiring

Sign-in (ADR 0010: server sessions, roles operator / approver, approver identity from the
session), investigation list, participant directory, packs list, evaluation reports, SSE events,
top-N causes with "show all", live voice on the participant page. Every "not connected" notice
was removed. A join link sees only its own part of an investigation; the event log, stream,
replay and paid voice test routes are staff only.

## Benchmark (logic mode, `eval/reports/benchmark-2026-11-05/`)

Our planner beats the checklist and random selection with intervals excluding zero; it is not
significantly better than greedy entropy. Where abstaining is the safe answer it abstains 68% of
the time and is right 94% of the time when it decides anyway; it diagnoses two-fault worlds 80%
of the time (best of all policies). An earlier 46% recall counted correct pair diagnoses as
missed abstentions; the metric was fixed. See NOTES.md.

## Known gaps

- Live Gnani: synthesised turns through the media socket only; human recordings (VOICE_SAMPLES.md) still needed.
- Abstention on unidentifiable scenarios (68%) is a calibration target for the stopping rule.
- The held-out extraction set has been seen; a fresh blind set is needed.
- Preemption across parallel calls (D17, Nov 7); the per-call socket and consent exist.
- Phones need HTTPS: the free Cloudflare quick tunnel needs `cloudflared` installed (blocked on
  the user's permission); quick tunnels carry no SSE, so the console falls back to polling.
- Incremental TTS (Timbre streaming chunk format unverified); login throttle is per process.
- Local setup: a dev core now enforces sign-in. Create a user with
  `uv run python -m pramana_core.auth.bootstrap`; scripts use `CORE_AUTOMATION_KEY` from `.env`.
