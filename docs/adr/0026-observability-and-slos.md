# 0026: Observability and SLOs

**Status:** proposed

**Amends:** 0002 (per-turn voice latency is traced internally; measured Gnani accuracy and latency
stay private under EULA §16) and 0009 (event delivery lag becomes an SLI).

**Context.** PRODUCTION.md §13.7. Today there are structured JSON logs with request ids and no
traces, metrics, SLOs or alerting. Slow voice turns and stuck investigations go unseen.

**Options compared.**

| Option | For | Against |
|---|---|---|
| Logs only | Exists | No latency picture across services; no alerts |
| A vendor APM agent | Fast setup | Lock-in; personal data in traces by default |
| **OpenTelemetry to Cloud Trace and Cloud Monitoring, SLOs with burn-rate alerts** | Vendor-neutral; GenAI conventions exist; the region keeps data in India | Instrumentation work |

**Decision.**
- One trace per investigation step: request, engine step, question, TTS, media socket, Prisma,
  extraction. GenAI spans follow the OpenTelemetry conventions with prompt content off.
- SLOs [T]: API availability 99.9% monthly; console read p95 under 300 ms; answer commit p95 under
  800 ms; event delivery lag p95 under 2 s; voice turn success at least 97%; notification
  delivery p95 under 60 s; report to first question p95 under 30 s.
- Fast and slow burn-rate alerts; runbooks for database failover, Gnani outage or credit, telephony
  outage, stuck investigation, outbox backlog, suspected tenant leak, personal-data breach (DPDP
  and CERT-In clocks).
- Logs scrubbed of personal data; Sentry with scrubbing in the browser.
- Per-turn voice latency stays on internal dashboards only.

**Consequences.** Dashboards are internal; no Gnani measurement is published. Alert routing needs
an on-call rota before the first pilot.

**Tests.** A test that a traced request produces spans for the engine step and the database; a
log-scrubbing test with a name and a phone number in a request; synthetic checks (sign-in through
the mock issuer in staging, a sandbox investigation by text) run every 5 minutes.
