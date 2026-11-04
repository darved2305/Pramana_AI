# 0009: Server-Sent Events for the event push channel

**Status:** accepted

**Context.** The console polls `GET /v1/investigations/{id}/events?after_seq=N`. It needs pushed
events with resume, heartbeats, backpressure and reconnects. Traffic is one-way (server to
browser); the browser reaches the core only through the Next.js rewrite `/api/core/*`
(`apps/web/next.config.ts`). PLAN.md §5 named a WebSocket (`api/ws_events.py`).

**Evidence (read on 2026-11-04 in the installed sources).**
- *Next.js 16.4.5 rewrites.* External rewrites go through `proxyRequest`
  (`next/dist/server/lib/router-utils/proxy-request.js`), which uses `httpxy` with
  `proxyTimeout` 30 000 ms by default. `httpxy` implements it as `setTimeout` on the proxied
  request, an *idle* timeout, so any stream must send something at least every 30 s. WebSocket
  upgrades are also proxied (`router-server.js`, upgrade handler, `proxy.ws(...)`) without that
  timeout.
- *Compression.* `router-server.js` applies the `compression` middleware to every response
  unless `compress: false`. That middleware gzips `text/*` and buffers until flush, but skips any
  response whose `Cache-Control` contains `no-transform` (its `shouldTransform` check). An SSE
  response without `no-transform` would be delayed behind the proxy.
- *Starlette 1.10 / uvicorn 0.54.* uvicorn's h11 and httptools protocols report ASGI
  `spec_version` 2.3, so `StreamingResponse` runs a disconnect listener alongside the body and
  cancels the generator when the client goes away. uvicorn applies TCP flow control
  (`flow.drain()`), so `send` blocks while a client is not reading.
- *FastAPI 0.162* ships `EventSourceResponse`, but it forces `Cache-Control: no-cache` (no
  `no-transform`) and owns the keepalive timer; we need both under our control.

**Decision.** Server-Sent Events at `GET /v1/investigations/{id}/stream`.
- Log events carry `id: <seq>` and the same `EventEnvelope` JSON as polling. `EventSource`
  resends `Last-Event-ID` on reconnect; the server resumes from the later of that and
  `after_seq`. Control events: `ready`, `reset` (client is ahead of the log, e.g. after a
  database reset: start over), `bye` (maximum duration or shutdown: reconnect).
- Heartbeat `: ping` every 15 s (`EVENT_STREAM_HEARTBEAT_S`, capped at 25 s by settings because
  of the 30 s proxy idle timeout). Headers `Cache-Control: no-cache, no-transform` and
  `X-Accel-Buffering: no`.
- Fan-out is announce-then-read. After a transaction commits, `Database.transaction` reports the
  investigations it appended events to; the broadcaster sets a one-bit wake-up flag on each
  subscriber; the subscriber reads `seq > last_sent` from PostgreSQL in pages of 200. One writer
  per investigation (ADR 0003) makes per-investigation `seq` order equal to commit order, so
  there are no gaps, and the `seq > last` filter removes duplicates when a commit races with the
  initial backfill (the subscription is taken before the backfill).
- Backpressure: writers never block or buffer (the per-subscriber queue is one flag, so ten
  thousand commits cost one wake-up). A client that stops reading blocks only its own stream;
  after `EVENT_STREAM_STALL_S` (10 s) without a successful send it is dropped and resumes on
  reconnect. Caps: 64 streams per investigation, 1 000 per process (`429
  TOO_MANY_SUBSCRIBERS`). Streams end with `bye` after `EVENT_STREAM_MAX_S` (30 min).
- Subscribers re-read the log on every heartbeat, so commits made by another core process show
  up within one heartbeat. Polling stays available and unchanged.
- WebSocket stays the transport for media (bidirectional binary audio), where it is required.

**Rejected.** A WebSocket for events: it adds a protocol for one-way data, `EventSource` already
implements reconnect with `Last-Event-ID`, and it cannot be retried by plain HTTP tooling.
Redis or `LISTEN/NOTIFY`: one core process today (PLAN §2); the heartbeat re-read covers several.

**Tests.** `services/core/tests/test_event_stream.py` runs a real uvicorn server: backfill then
live, reconnect with `Last-Event-ID` (no gaps, no duplicates), `after_seq` resume, position ahead
of the log (`reset`), 404 before streaming, heartbeats, `bye` at maximum duration, release on
disconnect, two identical streams, the subscriber cap, polling unchanged; units for coalescing,
shutdown `bye` and dropping a stalled client.
