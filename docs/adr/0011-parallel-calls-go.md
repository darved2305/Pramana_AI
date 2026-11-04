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

## What is not yet proven

- Sustained load (3 calls for 10 minutes) has not been run; it is the Nov 7 load test (D21).
- Barge-in and preemption latency (target 1 s) are measured only after D17 exists.
