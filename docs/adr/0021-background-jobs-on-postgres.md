# 0021: Background jobs on PostgreSQL

**Status:** proposed

**Amends:** 0003 (timers that outlive a process become jobs that go through the single writer).

**Context.** PRODUCTION.md §3.8. Call timers live in process memory and there is no job queue.
"Ring again after 60 s", 15-minute cool-downs, approval expiry, reminders, the outbox relay,
retention purges and reapers all need durable timers that survive a restart.

**Options compared.**

| Option | For | Against |
|---|---|---|
| **Procrastinate** (PostgreSQL task queue for asyncio) | Maintained; periodic tasks, retries, locks; no new service | A dependency with its own schema |
| **An owned `jobs` table with `FOR UPDATE SKIP LOCKED`** | Full control; tiny | We own retries, scheduling and periodic tasks |
| Celery or RQ with Redis | Mature | A broker and Redis before any trigger |
| Temporal or DBOS workflows | Durable multi-step flows | Heavy for single-step jobs (§3.11 trigger) |

**Decision.** A PostgreSQL-backed queue run by the `worker` process. Start with Procrastinate; if
its schema or asyncio integration conflicts with the RLS context or Alembic, fall back to an
owned `jobs` table. Every job is delivered at least once, so every handler is idempotent and
keyed by the dedupe key in §3.8. Each job carries its `org_id` and sets the RLS context before
touching tenant data. Jobs that change an investigation go through `InvestigationService` and its
row lock. Periodic work gets jitter.

**Consequences.** One more process (`worker`) with at least one instance. Queue depth becomes a
metric with an alert. The R1 slices need only the idempotency reaper and the `auth_flows` reaper,
which can run as periodic jobs or a simple loop under an advisory lock until the queue lands.

**Tests.** A job survives a worker crash and runs once; two workers never run the same job; a
retried job produces one side effect; a job without an `org_id` cannot read tenant rows; the
idempotency reaper deletes only keys older than 72 hours.
