# 0003 — Append-only events plus projections, single writer per investigation

**Status:** accepted

**Decision.** PostgreSQL holds an append-only `events` table, which is the source of truth, plus
the `investigations`, `questions` and `observations` projections, all written in one transaction.
Each command takes a per-investigation `asyncio.Lock` and `SELECT … FOR UPDATE`; that is
simpler than PLAN's mailbox actor and gives the same serialisation. The engine is rebuilt by
replaying `QuestionAsked`, `ObservationRecorded` and `ParticipantUnavailable`. The in-memory
engine is a cache keyed by `investigations.version` and is evicted on any failed command.
The API returns the persisted `PlanComputed` trace instead of recomputing it, because asking a
question changes that participant's effort cost (a bug found in a live run).

**Rejected.** Redis, Kafka and Temporal: a single process, no cross-service workflow.

**Tests.** Rollback after a crash mid-command, a concurrent-answer race (exactly one succeeds),
replay equivalence, ordered and resumable events (`services/core/tests/test_investigation_api.py`).

**Engine upgrades.** `InvestigationCreated` records the probability model version
(`pramana_engine.MODEL_VERSION`; "1" when absent). A log written by another model replays
differently by design, so startup recovery and `GET /v1/investigations/{id}/replay` report it as
`engine_changed`, not as a corrupted log, and append no `EngineError`. Bump `MODEL_VERSION`
whenever the same evidence would produce a different belief
(`test_recovery.py::test_a_log_from_an_older_engine_is_an_upgrade_not_corruption`).

**Sealed at reveal.** Replay shows the belief follows from the log, but not that the log was
left alone afterwards. `GroundTruthRevealed` records `log.sha256`, a hash chain over the
`(type, payload)` of every earlier event in order, and `log.events`. `GET .../replay` returns
`log_sealed` and `log_intact`; an edited, deleted, inserted or reordered event makes
`log_intact` false even when the replayed belief is unchanged (`test_log_seal.py`). This
detects edits after the reveal; the digest itself lives in the same database, so it does not
protect against someone rewriting the whole log and the digest together.
