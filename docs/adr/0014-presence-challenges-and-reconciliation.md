# 0014: Presence challenges and reconciliation explanations

**Status:** accepted

## Context

An observation from a restricted closet can be useful only if the person was there. The simulator
can show a location-bound label after a real move, but the core must not learn its expected value.
The existing observation model mixes reliability with hedge weights by mixing the predicted
outcome distribution toward uniform. The plan assigns unverified presence a weight of 0.2.

The existing contradiction detector reports pairs that no modelled fault, including an
identifiable pair, can explain without noise. It does not explain an apparent disagreement that
the pack's physical contexts can reconcile. The S2 rooms already have different Wi-Fi coverage:
Room 205 can associate with AP_2B or AP_2A, while Room 210 can associate only with AP_2A.

## Decisions

### Presence

1. A pack declares presence-token definitions, never token values. A definition names its location,
   what to read, and reviewed spoken/display prompts in English, Hindi, Marathi and Hinglish.
2. The simulator derives each value deterministically from the scenario seed and token id using an
   alphabet that avoids ambiguous characters. It returns the value only in that participant's view
   while the participant is at the token location. The value is separate from the sealed fault and
   commitment.
3. The core may ask the simulator to verify `(scenario, participant, token, answer)` using its
   operator key. The simulator checks the participant's current position and returns only pass or
   fail. The core does not log or persist the answer. Neither events, API responses, logs nor the
   pack contain the expected value.
4. An observation from a restricted location, or a location the participant had to move to, has
   presence weight 0.2 until that participant passes a challenge for that location. The engine
   applies that weight through its existing mix-toward-uniform likelihood, in addition to hedge,
   hearsay and voice weights. A pass reweights all of that person's observations at the location
   using their ordinary evidence weights. A fail leaves all of them at 0.2. No person is accused.
5. An observation is challenge-worthy when its full-weight counterfactual changes the leading
   decision or changes that decision's probability by at least `confirm_delta` (0.15). The
   observation remains at weight 0.2 while the challenge is pending. This reuses the engine's
   existing definition of decision-critical evidence and avoids challenging observations that
   cannot affect the action.
6. A challenge is asked at most once for a participant and location. Its event and pending
   question are written by the investigation's single writer. It carries a 12-second effort cost,
   like a probe. A decision reached while it is pending withdraws it. The answer may be given by
   text or on the existing call socket. A refusal, unreadable answer, answer from the wrong place,
   or wrong characters is a failed challenge.
7. `ChallengeIssued` and `ChallengeResult` are append-only events. The result records only
   `passed`, `failed` or `withdrawn`, a language-independent reason code and the question id. Replay
   applies the result to the engine's `(participant, location)` verification state. An issued
   challenge without a result remains pending after recovery.

### Reconciliation explanations

1. Keep `ContradictionDetected`'s existing meaning for replay compatibility: no modelled cause
   predicts both observations. Add `ContradictionExplained` for apparent opposite outcomes that
   may have a physical-context explanation. Do not change the existing event payload.
2. The pure engine ranks language-independent explanation codes from the posterior and the pack's
   physics. `different_access_points` mass is posterior mass on worlds where both readings match
   their site predictions and the phones associate with different APs. `observer_mistake` mass is
   posterior mass on modelled worlds where at least one reading differs from its site prediction.
   The pack and `World` determine the AP names; no S2-specific names or fault are hard-coded.
3. The pack does not model changes over time. `world_changed` is emitted with zero mass and
   `supported: false`, alongside `world_change_not_modelled`; it is not presented as an inferred
   explanation.
4. The explanation includes a deterministic tie-break action selected from feasible probes by
   expected information gain about the ranked explanation families. For the S2 Wi-Fi case, an
   AP-association reading in Room 205 distinguishes the two coverage paths. It is an ordinary
   question, so normal question costs, parallel limits, withdrawal and event replay apply.
5. Emit `ContradictionExplained` as a new event after the observations that support it. Its payload
   contains observation ids, explanation codes and posterior masses, and the tie-break action.
   It contains no generated prose; the console renders reviewed language templates.

## Consequences

- A successful challenge upgrades only evidence from the same person and location. It does not
  verify another person's presence or another location.
- The simulator's operator key becomes usable for a narrow verification route. Its response is
  deliberately less informative than the view route.
- A context explanation and a detected contradiction are different event concepts. S2 can show a
  reconciliation explanation even when the existing physics-aware detector correctly sees that
  both observations are possible.
- The time-change family remains visible as unsupported until the pack has an explicit temporal
  model.

## Required tests

- Engine tests for 0.2 mixing, successful reweighting, decision-critical counterfactuals,
  deterministic explanation ranking, pack-derived AP contexts and tie-break selection.
- Simulator tests for deterministic values, on-site-only visibility, move-before-verification,
  multiple people at one token location, and pass/fail responses that contain no value.
- Core tests for single-writer events, neutral failures, challenge withdrawal, voice and text
  normalization, byte-identical replay and recovery with an issued challenge still pending.
- End-to-end S2 and S7 runs with the real simulator process.
