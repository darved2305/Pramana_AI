# 0020: Several instances: NOTIFY wake-ups, leases, leader election, engine work off the event loop

**Status:** proposed

**Amends:** 0003 (the per-investigation `asyncio.Lock` becomes an optimization; startup recovery
becomes a singleton), 0009 (wake-ups cross instances through `LISTEN/NOTIFY`) and 0013 (the
one-media-session-per-token set becomes a lease row).

**Context.** PRODUCTION.md §1.4 "Per-process state", §3.2 and §3.4. The login throttle, voice rate
windows and stream slots, the SSE broadcaster, the one-session-per-token set, the engine LRU and
startup recovery all live in one process. Two instances would double the Gnani caps, split the
throttles and let a copied link open two sessions (ARCHITECTURE_REVIEW item 4). Planning runs on
the event loop and delays voice frames.

**Options compared.**

| Option | For | Against |
|---|---|---|
| Stay single-instance | Nothing to build | No high availability; voice and planning share one loop |
| **PostgreSQL for wake-ups, leases and leader election** | Already the source of truth; no new service; ADR 0009 already treats notifications as wake-ups with a heartbeat re-read | NOTIFY takes a commit-time lock at very high write rates |
| Redis Pub/Sub and Redis locks | Fast | A new stateful service before any measured need (§3.11) |

**Decision.**
- Inside the committing transaction, `NOTIFY pramana_events, '<org_id>:<investigation_id>'`. Each
  `api` and `media` instance holds one dedicated `LISTEN` connection and pokes local subscribers,
  which read `seq > last_sent` from the table as now. The heartbeat re-read stays as the safety
  net.
- `media_leases` (unique per token `jti`, renewed every 10 s) replace the in-memory set;
  `provider_slots` leases replace per-process Gnani slots; `rate_limits` rows replace the
  in-memory throttle.
- Singletons (startup recovery, outbox relay, reapers) run under `pg_try_advisory_lock` on a
  dedicated connection.
- Engine `observe`, `schedule` and `compile_pack` move off the event loop
  (`asyncio.to_thread`, then a process pool if step p95 exceeds 100 ms). `media` does no planning.

**Consequences.** If PgBouncer runs in transaction mode, `LISTEN` and session advisory locks need
direct connections. Redis arrives only on the measured triggers in §3.11.

**Tests.** Two core processes against one database: an answer committed on one reaches an SSE
client on the other within 2 s; a copied participant link cannot open a second media session on
the other instance; stream slots are shared; killing the leader hands the singleton to the
survivor; event-loop lag stays under 50 ms while a heavy plan runs.
