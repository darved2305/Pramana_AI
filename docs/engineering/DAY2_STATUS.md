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

## Frontend gaps (shown as "not connected" at the start)

Sign-in, investigation list, participant directory, packs list (hardcoded `KNOWN_PACKS`),
evaluation results (file upload), event push (polling in `useInvestigation`).
