# 0022: Personal data outside the event log; crypto-shredding; retention

**Status:** proposed

**Amends:** 0003 (event payloads carry person ids and engine attributes only; explanations are a
template id plus parameters) and 0014 (`DisagreementExplained` stops baking names into text).

**Context.** PRODUCTION.md §4.6. `InvestigationCreated.participants` holds display names,
`ReportReceived` holds free text, `DisagreementExplained` renders names into its explanation
(`investigations.py:362-366`), and transcripts sit in `observations.transcript`. An append-only,
hash-sealed log cannot honour erasure, and DPDP obligations apply from 13 May 2027.

**Options compared.**

| Option | For | Against |
|---|---|---|
| Keep personal data in events, rewrite events on erasure | No new tables | Breaks the seal and exact replay |
| **Person ids in events; names, phones and text in encrypted side tables; erase by deleting a per-person key** | Replay stays byte-identical; erasure is one key deletion | Envelope encryption and KMS; crypto-shredding's legal standing must be confirmed by counsel |
| Pseudonymous ids plus a mapping table deleted on erasure | Simple | Free text in events still identifies people |

**Decision.**
- Events carry person ids and the attributes the engine needs (roles, skill, location, languages,
  availability, question budget). Replay never reads names or free text (checked against
  `_rebuild`).
- `people` stores names and phone numbers encrypted with a per-person data key (KMS envelope),
  with an HMAC blind index for lookup. `utterances` stores reports, transcripts and readings,
  encrypted with the same key, with an expiry (30 days [T]).
- Erasure deletes the data key; the row remains as a tombstone and the UI shows "Erased person".
- Explanations are stored as a template id plus parameters and rendered at read time.
- Old events are read through upcasters; `MODEL_VERSION` rules are unchanged because beliefs do
  not change.

**Consequences.** This lands in R2, not R1: R1 moves routes and adds tenancy without changing
event meaning. Backups keep erased data until they expire; the privacy notice says so. Counsel
must confirm crypto-shredding as erasure under DPDP (PRODUCTION.md §18 item 2).

**Tests.** LC-03: after erasing a participant, every investigation they took part in replays to
an identical digest and the UI shows "Erased person"; no event payload contains a display name
or free text (a schema test over every event type); the purge job deletes expired utterances.
