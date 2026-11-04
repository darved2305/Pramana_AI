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
