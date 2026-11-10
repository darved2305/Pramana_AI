# 0019: Idempotency keys, outbox and inbox

**Status:** proposed

**Amends:** 0003 (event `idempotency_key` becomes unique per investigation instead of globally).

**Context.** PRODUCTION.md §3.6. POSTs carry no request-level idempotency, so a retry after a
lost response can create a second organization, invitation or answer. Today a duplicate answer
gets `409 QUESTION_NOT_PENDING`, which confuses a client that only retried. Real side effects
(messages, calls, work orders) will need exactly-once behaviour across retries and crashes.

**Options compared.**

| Option | For | Against |
|---|---|---|
| Natural keys per endpoint ("one org per owner and slug") | No new table | Different rules everywhere; does not cover side effects |
| **`Idempotency-Key` header, stored responses, outbox for effects, inbox for webhooks** | One mechanism (Stripe, brandur, IETF draft 08); safe retries end to end | A table and middleware; a relay worker |
| A workflow engine (Temporal) | Durable multi-step flows | Too much infrastructure for today's flows (§3.11) |

**Decision.**
- Middleware on POST, PATCH and DELETE. Required on endpoints that create something or trigger an
  effect. Key format `^[A-Za-z0-9_-]{16,128}$`, checked before lookup. Scope
  `(org_id, principal, key)`. Fingerprint: SHA-256 of method, path and canonical body.
- Responses, following IETF `draft-ietf-httpapi-idempotency-key-header-08`: new key runs the
  handler and stores status and body in the same transaction; a finished key with the same
  fingerprint replays the stored response with `Idempotent-Replayed: true`; in flight gives
  `409 IDEMPOTENCY_IN_FLIGHT`; a different fingerprint gives `422 IDEMPOTENCY_KEY_REUSED`; missing
  where required gives `400 IDEMPOTENCY_KEY_REQUIRED`.
- Keys expire after 72 hours; a reaper job deletes them.
- External effects: the state change and an `outbox` row commit together; the worker calls the
  provider with a key derived from the outbox id, or reconciles through status APIs when the
  provider has no idempotency.
- Webhooks: verify signature and timestamp, then insert `inbox (provider, event_id)` under a
  unique constraint in the same transaction as the effect, answer 2xx at once.
- The browser generates one key per user intent (one press of "Create organization") and reuses it
  for every retry of that press.

**Consequences.** Every client mutation must carry a key, including tests and bots. A key stored
before an organization exists (creating one) is scoped by principal with a nil organization.
Outbox and inbox arrive with the channels in R3; the request middleware arrives in R1.

**Tests.** OR-09 (double "Create organization" gives one organization), two concurrent requests
with one key (exactly one runs, the other gets 409 or the replay), a replay after a lost response
returns an identical body, the same key with another body gives 422, a missing key gives 400,
the reaper removes keys older than 72 hours.
