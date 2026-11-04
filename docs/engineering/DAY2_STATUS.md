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

## Current state (main at d9c3871: 730 pytest passed, all checks clean)

| Item | State | Evidence |
|---|---|---|
| D05 actor + event store, recovery | **done** | Startup supervisor rebuilds every open investigation and compares canonical JSON with the last `BeliefUpdated`; `GET /v1/investigations/{id}/replay`. `services/core/tests/test_recovery.py` (repair, reopen, pending confirmation, new app on same DB continues, tampered log flagged). Live: `tests/e2e/test_m1.py` kills and restarts the core mid-investigation, byte-identical final belief |
| D06 push channel | **done (backend)** | SSE `GET /v1/investigations/{id}/stream`, ADR 0009; resume by `after_seq` / `Last-Event-ID`, 15 s heartbeat, non-blocking writers, slow consumers dropped with a resume point. `test_event_stream.py` (15 tests on a real uvicorn server). Polling kept |
| D15 LLM clients | **done** | Typed errors, schema check, keys redacted from messages and logs: `test_llm_client.py`; reasoning-control retry still covered in `eval/tests/test_benchmark.py` |
| D04 voice gateway v1 | **done (fake Gnani)** | AudioWorklet capture (`apps/web/public/worklets/`, `scripts/check-pcm-worklet.mjs` at 48/44.1/16 kHz), media WebSocket per question with Prisma v3.0 context, ADR 0013, `test_media_ws.py` (14 tests). Not yet run against live Gnani |
| D07 call runtime skeleton | **done** | `calls/runtime.py`, every state x event pair tested in `test_call_runtime.py`. Not yet driving the media socket |
| D09 simulator shell | **done** | `test_sim_api.py` |
| N04 belief upgrades | **done** | Reliability integrated out (Gauss-Jacobi), 78 identifiable fault pairs, `MULTIPLE_FAULTS` decision, pair-aware contradictions and `ContradictionDetected`; ADR 0008; Hypothesis order-invariance, normalisation, monotonicity, EIG bounds in `test_belief_model.py`; hand computation still exact |
| N05 planner v0 | **done** | `test_planner.py`, engine-level S1 test: 4 questions, P = 0.973 |
| N11 intake | **done** | `language/intake.py`, 60 reports (`eval/data/intake_set.jsonl`), `test_intake.py`. Development figures only (tuned on that set) |
| N03 simulator core | **done** | Commitment published at creation equals the revealed one; two-fault repairs clear only their own fault (`test_sim_api.py`) |
| N09 extractor + 80 held-out | **done** | `eval/data/extraction_heldout.jsonl` (20 each en/hi/mr/Hinglish). Blind baseline 62/80 (`eval/reports/extraction-2026-11-05-baseline/`); after fixes 72/80, which is no longer blind (see that report's NOTES.md). A new held-out set is needed for an unbiased figure |
| `make dev` | **done** | `scripts/dev.py`, `tests/test_dev_script.py`; live run started and stopped cleanly |
| 12+ probes | **done** | 14 probes; golden physics tests in `packages/domain/tests/test_physics.py` |
| `docs/spike-gnani.md` | **done** | Pointer file |
| M1 Python end to end | **done** | `tests/e2e/test_m1.py` against real sim + core processes: S1 decided in 4 questions, deny then approve, capability single use and expiry, act, report, `verified`, reveal, byte-identical replay; misled run reopens |
| M1 Playwright against real backend | **in progress** | Frontend workstream |

## Frontend gaps (shown as "not connected" at the start)

Sign-in, investigation list, participant directory, packs list (hardcoded `KNOWN_PACKS`),
evaluation results (file upload), event push (polling in `useInvestigation`).
