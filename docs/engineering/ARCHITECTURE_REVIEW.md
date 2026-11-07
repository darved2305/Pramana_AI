# Architecture review, Sat Nov 7

A read of the code as it stands on main, looking for what would make Pramana stronger without
rewriting it. Scope freezes tonight; nothing here starts a new feature line. Each item says
whether it was **done** (with its test), is **recommended** (not implemented), or is
**rejected** (with the reason). External sources were not re-checked for this review.

## What to keep

The core architecture is the right one for this problem and should not be replaced.

| Decision | Why it holds up |
|---|---|
| Deterministic engine, LLMs only for language (ADR 0004, 0007) | Every number is reproducible; replay is byte-identical; an LLM cannot decide or approve |
| Append-only events plus projections, one writer per investigation (ADR 0003) | Simple serialisation (asyncio lock plus `SELECT ... FOR UPDATE`), exact rebuild, crash recovery tested at process level |
| Sealed truth in a separate service with commitments (README, `services/sim`) | The core has no oracle key; reveal closes the scenario first, so peeking would end it. Now also checked by `tests/test_authenticity.py` |
| Ed25519 tokens, public key only at the simulator | A compromised simulator cannot mint identities or capabilities |
| SSE for events, a WebSocket per question for media (ADR 0009, 0013) | Each transport fits its traffic; per-question sessions carry per-question ASR context |
| Direct Gnani gateway behind a governor (ADR 0002) | Budget is priced before sending and recorded in PostgreSQL |

Rejected again: Kafka, Temporal, Redis, microservices, LiveKit. One core process carries the
demo; none of these fixes an observed failure.

## Fixed on Nov 7

| Finding | Risk | Fix and evidence |
|---|---|---|
| A collected repair capability lived only in page memory, the core refused to issue it twice, and it expired after 5 minutes | A reload, a discarded tab or a slow walk left the investigation in `acting` with no way out, during a human take | Collecting again returns the same single-use token while it is live and a new one only after it expires (`CapabilityIssued.replaces`). `test_closing_loop.py` (reload, expiry), `apps/web/tests-real/repair-recovery.spec.ts` (reload and a dropped report against the real stack) |
| The participant page re-ran the simulator action when retrying a lost report | `CAPABILITY_USED` on every retry: stuck again | The page reports a reset its own capability already performed; an expired one is collected again |
| Nothing said whether the core was calling Gnani or the staging/load emulator | An emulated run could be described as live | `/v1/voice/status` names the provider host; preflight fails on an emulator unless `--allow-emulated-voice`; voice bot summaries record it |
| Separation of duties was by role only | An account holding both roles could approve its own repair request, contrary to README | `ApprovalRequested.requested_by`; the same signed-in account gets `403 SELF_APPROVAL` (ADR 0010, `test_auth.py`) |
| An unknown, second-hand or conclusion answer to a walk question placed the person there | The next question skipped the walk, and their phone checks were attributed to a place they never reached: wrong evidence | Planned as possibly at either place, as after a withdrawn walk (`test_parallel.py`). Found by the adversarial state machine against the real simulator. Benchmark episodes byte-identical before and after (300 scenarios, six policies) |
| The test database fixture migrated down with rows still present | A leftover `awaiting_approval` row broke the next session's setup | Tables are cleared first (`services/core/tests/conftest.py`) |

## Recommended next (post-submission unless a recording needs it)

Ranked by value for the claims Pramana makes, not by size.

1. **Tamper-evident event log.** Replay proves the belief follows from the log; it does not
   prove the log was not edited afterwards. Add `prev_hash`/`hash` to each event (SHA-256 over
   the canonical payload and the previous hash), written by the single writer, and put the
   head hash into `GroundTruthRevealed`. The replay check then verifies the chain too. Needs a
   migration and a contract change; cheap at runtime.
2. **Simulator-signed action receipts.** `report_intervention` trusts the executor's word
   that the action was done; belief-based verification catches a false report, but only after
   more questions. The simulator could return an Ed25519-signed receipt (its own key, public
   key at the core) that the report must carry. Then "reported" means "performed".
3. **Capability lifecycle as events.** Today the capability's state is spread over the
   approval row, `CapabilityIssued` events and the simulator's ledger. Explicit
   issued / delivered / consumed / expired events (consumption from the receipt above) would
   let the console show where a repair is stuck without guessing.
4. **Multi-process readiness.** Correctness already survives several core processes (row
   locks; SSE subscribers re-read on each heartbeat). Voice rate windows and stream slots are
   per process (governor docstring), so two processes would double the Gnani caps. Move slot
   leases to PostgreSQL before running more than one core.
5. **Durable sealed scenarios everywhere.** The simulator persists only when `SIM_STATE_FILE`
   is set (staging sets it). A local restart loses sealed scenarios and blocks their reveal.
   Make the state file the default outside tests, and keep salts out of logs.
6. **Stateful adversarial testing: done** (`services/core/tests/test_adversarial_state.py`).
   It found the location bug above on its first deep run. Next: add voice media sockets,
   parallel calls and presence checks to the same machine, and run it with more examples in a
   nightly job rather than on every push.
7. **One trace per investigation.** Structured logs exist; an OpenTelemetry trace spanning
   question, TTS, media socket, Prisma, extraction and engine step would show where a slow
   voice turn spends time. Keep measured Gnani latency private (EULA).
8. **Pack-derived speech hints.** The Wi-Fi network name `NAVA-WiFi` is the only
   building-specific string left in core code (an ASR hint). Derive codes from the probe's
   question templates once a second pack exists and voice is re-validated.

## Not recommended

- Letting an LLM choose questions or decisions in the product: the free-tier comparison is
  below its publication threshold, and the product claim rests on deterministic decisions.
- Replacing the per-question media socket with one multiplexed call socket (D18) before an
  observed cap or failure requires it.
- Paid hosting or GPU work (ADR 0012).
