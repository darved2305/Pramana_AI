# 0014: Presence checks and disagreement explanations

**Status:** accepted

**Context.** PRODUCT.md U4 and U8, plan item N06. Two kinds of testimony problem were not
handled. A person can say they went to a restricted place and report what they "saw" there
without going (scenario S7); the engine trusted the claim up to that person's reliability. And
when two people disagree in different places (scenario S2: room 205 says the Wi-Fi works, room
210 says it does not), the engine weighed both inside the posterior, but nothing showed why, and
the console's contradiction panel only compared answers about the same thing in the same place.

**Decision: presence checks.**
- The pack declares *presence tokens*: a detail at a restricted place (`idf2_switch_label` at
  IDF2, `idf1_rack_label`, `db_c2_door_label`) with a challenge question in every language. The
  value is not in the pack.
- The simulator draws a fresh 3-character value per scenario from an alphabet with no
  look-alike or sound-alike characters (`AFHKLMQRXY345679`), shows it only on the card of
  someone standing there, and checks readings at `POST /sim/v1/scenarios/{sid}/presence/check`
  (operator key; 2 tries per person and token; the response says only `passed`). The core never
  learns the value.
- The engine decides when to check (`Engine.presence_challenge`, pure): the answer is
  decision-critical, it is about what is seen in a restricted place, the place has a token, the
  person is not registered there (they walked there, so their presence is a claim), and they have
  not been checked there yet.
- While the check is pending, and after it fails, that person's answers about that place count at
  `presence_unverified_weight` = 0.2 (PRODUCT.md). Nothing is decided on the claim meanwhile,
  because at that weight it is no longer decision-critical. A pass restores full weight exactly.
  A fail also puts them back at their registered place for planning, so the engine asks someone
  else. Nobody is accused, in the UI or in the participant's words.
- Spoken or typed readings are normalised in the core (`language/presence.py`: letter and digit
  names in English, Hindi, Marathi and Hinglish, Devanagari numerals, words like "I" or "do" kept
  only next to code characters). What Timbre says for a code (`speakable`) reads back to it.
- Events `ChallengeIssued` and `ChallengeResult` are replayed by the rebuild, so replay stays
  byte-identical. The question has `kind: "challenge"` and no outcomes.
- Opt-in per investigation (`presence_checks`, default off) so the benchmark, S1 question counts
  and existing demos are unchanged unless asked. With it on, S1 asks one more question (the
  electrician reads the panel label).

**Decision: disagreement explanations.**
- When a new answer differs from another person's answer to the same probe in the same era,
  `pramana_engine.testimony.explain` reports, from the current posterior: P(both right) (causes
  under which both are what a reliable person would see), P(mistaken) for each side, the most
  probable reconciling cause, and which of its faults only one side depends on (from the compiled
  prediction matrix: a fault that changes what one site predicts and not the other).
- The core words it from those numbers and the pack's names only (`language/explain.py`), e.g.
  "Both can be right if the cause is: Access point 2A failed (93%). Only Neha's place (room 210)
  depends on Access point 2A; room 205 is also covered by Access point 2B." It is logged as
  `DisagreementExplained` and returned in `InvestigationState.disagreements`.
- This is presentation only: the belief already accounts for both readings.

**Evidence.** `packages/engine/tests/test_testimony.py` (S2 reconciliation, posterior sums,
pending/pass/fail weights, when not to check), `services/sim/tests/test_sim_api.py` (label only
on site, value never returned, attempt limit), `services/core/tests/test_testimony_api.py`
(through the API with a real simulator: honest electrician passes and S1 is still correct; a
lying electrician fails and the decision is still correct; the S7 guard fails and the engine
abstains instead of deciding on his word; S2 explained as "different access points"; replay
identical; the label never appears in the core's log), `services/core/tests/test_presence_reading.py`,
`apps/web/tests/testimony.spec.ts`.

**Consequences.** One extra question when a decisive answer comes from a place someone walked
to. The check is rule-based, not valued by the planner; a later version could value it like any
other question. Real buildings would need real labels (asset tags) registered per place; the
simulator stands in for that. A person who really is there but cannot read the label is treated
like one who is not, which only lowers the weight of their answer.
