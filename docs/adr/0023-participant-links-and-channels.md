# 0023: Participant links, channels (WhatsApp, SMS, phone), consent and quiet hours

**Status:** proposed

**Amends:** 0010 (participants get a short link and a cookie instead of a token in the URL),
0013 (a phone bridge socket joins the per-question media socket) and 0014 (live presence checks
use printed codes verified by a separate verifier).

**Context.** PRODUCTION.md §5.6 and §9. The participant link carries the Ed25519 token in the
URL path (`lib/join.ts`), which leaks through history, logs and WhatsApp link previews. Real
people need WhatsApp, SMS and phone calls, consent records, quiet hours and an easy way to say no.

**Options compared.**

| Option | For | Against |
|---|---|---|
| Keep token-in-URL links, send them over WhatsApp | Exists | Preview bots fetch and log the token; one link opens on many devices |
| **Short codes stored hashed; GET renders a landing page; POST exchanges the code for a cookie** | Previews consume nothing; tokens never in URLs | A table and an extra tap |
| An app for participants | Rich | Participants never install apps for one question |

**Decision.**
- `/j/<code>` with a 128-bit random code stored hashed in `participant_links`; `GET` only renders
  a landing page; pressing Open (`POST`) sets a short-lived `__Host-pramana_participant` cookie.
- One device at a time through `media_leases` (ADR 0020), with a hand-over prompt.
- Channels: WhatsApp utility templates through a BSP, SMS with DLT registration, phone calls
  through Exotel AgentStream into the `media` service at 8 kHz with DTMF fallback, email for staff
  only. Every send goes through the outbox (ADR 0019).
- No consent, no contact: `consents` per person and purpose with the notice version and language.
  Quiet hours are unavailability for the planner. Adults only by default (DPDP section 9).

**Consequences.** Needs a BSP, DLT registration and an Exotel account (R3). Exotel's 8 kHz format
and Prisma's handling of it must be checked by a staging test call before relying on them.
Nothing here is built before the user approves each real send or call.

**Tests.** PA-01 (preview fetch consumes nothing and shows no personal data), PA-02 (second phone
hand-over), PA-08 (minor not contactable), PA-09 (quiet hours), PA-11 (ring-out retry then
WhatsApp), PA-12 (duplicate and out-of-order webhooks), with captured provider payloads.
