# 0011: Parallel calls: go, with a cap of 3 per investigation

**Status:** accepted (decision due Nov 5 in PLAN.md §26)

**Question.** Can one investigation run calls with several participants at the same time
(PLAN P1, D17), or must calls stay sequential?

## Evidence

All of this is integration fact from the Day 1 spike (docs/engineering/GNANI_INTEGRATION.md),
not accuracy or latency, which stay private under the Gnani EULA.

| Fact | Source |
|---|---|
| Three simultaneous Prisma v3.0 realtime sessions all transcribed, each with its own language candidates | live run, 2026-11-04 (`scripts/gnani_live_check.py --probe-concurrency`) |
| The account dashboard states 20 concurrent STT WebSocket sessions | account dashboard |
| STT REST is 60 requests/min, and Gnani's documented 429 example says "1 active request" | dashboard, docs `api/STT/limits.md` |
| Our governor refuses (does not queue) the 17th stream and checks the worst-case spend first | `voice/governor.py`, `tests/test_voice_governor.py::test_stream_slots_are_capped_and_metered` |
| Investigation state is serialised per investigation (lock + `SELECT ... FOR UPDATE`), so answers arriving from several calls cannot race | ADR 0003, `test_investigation_api.py::test_concurrent_answers_to_one_question` |

## Decision

**Go** for parallel calls, with these constraints:

1. At most **3 concurrent calls per investigation** (the console layout in PLAN §6 shows three
   call cards), and at most 16 streams per core process overall (the governor).
2. Parallel calls use **realtime streams**, one per question, not the REST decode: REST is
   effectively one request in flight, so it would serialise the calls again. REST stays as
   the second-decode and fallback path.
3. Every answer still goes through the single writer. A call whose question became pointless
   after another answer is preempted by the call runtime (`calls/runtime.py`, PREEMPTING),
   never by racing writes.
4. If a live run shows fewer usable concurrent sessions than the dashboard states, fall back
   to sequential calls; the multiplexer (D18) is not needed unless the cap drops to 1.

## How it works (implemented)

- `CreateInvestigation.max_parallel_calls` (1 to 3, default 1). With 1, behaviour is exactly
  the sequential planner.
- After every change of belief the service runs `pramana_engine.schedule` (pure, so replay and
  the benchmark use the same rule):
  1. nothing in flight: plan as before; if the plan asks, add questions for *other* people
     chosen greedily by **conditional** decision gain `I(D; O_new | O_in_flight)`, averaged over
     the answers still on their way (different people's answers are independent given the
     world). Each extra must also pass the planner's own two-step net-value test and add at
     least `parallel_min_bits` (0.05).
  2. something in flight and the belief is already conclusive (confident decision, unmodelled
     cause, verification verdict): withdraw everything in flight and conclude.
  3. otherwise withdraw questions whose answer would now tell us less than `withdraw_bits`
     (0.01) about the decision, judged one by one, and fill free slots by conditional gain.
     The investigation never concludes while a question that still matters is unanswered.
- A withdrawal is a `QuestionWithdrawn` event and question status `withdrawn`; answering it
  returns 409 `QUESTION_NOT_PENDING` ("withdrawn"). The media session already watches its
  question, so the call gets `question_withdrawn` and `PREEMPT`. The engine is unaffected by a
  withdrawal, so replay is unchanged. Repairs are verified one question at a time.
- Tests: `packages/engine/tests/test_parallel.py` (conditional gain against a brute-force
  definition, cap, determinism, S1 run in parallel), `services/core/tests/test_parallel_calls.py`
  (several pending, withdrawal mid-run and at conclusion, visibility per participant, decline,
  replay), `test_call_ws.py::test_two_people_on_calls_at_once_in_one_investigation` (two call
  sockets and recognizer sessions open at once), `apps/web/tests-real/parallel.spec.ts`.

## Benchmark (logic mode, simulated time)

`eval` runs the same rule with a simulated clock: an answer arrives `cost_s` after its question;
a withdrawn question costs the time already spent. 300 scenarios, seeds 10000 to 10299
(`python -m pramana_eval --policies E,P2,P3`):

| | Success | Questions | Participant effort s | Time to conclusion s | Withdrawn |
|---|---|---|---|---|---|
| Sequential (E) | 84.7% | 5.50 | 189 | 189 | 0 |
| Up to 2 at once | 83.0% | 6.70 | 242 | 134 | 0.32 |
| Up to 3 at once | 83.3% | 7.53 | 278 | 119 | 0.58 |

Paired against sequential: success is not significantly different (E minus 3-at-once +1.3
points, 95% CI [-1.7, +4.3]); time to conclusion falls by 70 s [61, 79]; the price is about two
more questions and 89 s more total participant effort. Parallel calls buy speed with people's
time; the console default stays one at a time.

## What is not yet proven

- Sustained load (3 calls for 10 minutes) has not been run; it is the Nov 7 load test (D21).
- Preemption latency on live Gnani (target 1 s) has not been measured.
- Live parallel calls with the voice bots and humans: see `docs/engineering/HANDOFF.md`.
