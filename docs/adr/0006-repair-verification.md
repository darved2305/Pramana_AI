# 0006: Approval-gated repairs and belief-based verification

**Status:** accepted

**Decision.** A consequential action, for example resetting breaker C2-7, needs four things:
1. A decision that calls for it (the pack lists which decision classes each action serves).
2. A named executor holding one of the action's roles.
3. A human approval.
4. A single-use Ed25519 capability token, scoped to the scenario, investigation, executor,
   action and target, and expiring after 5 minutes.

The simulator checks the token, its single use, the executor's role and that the executor is
physically at the target. Its reply never reveals whether the action fixed anything.

**Verification model.** When the executor reports the repair, every hypothesis the action could
clear is split into two branches:
- *fixed* (probability 1 − p, with p = 0.1): later answers are read against the repaired world;
- *not fixed* (probability p): the repair did not hold.

Answers given before the repair count the same in both branches. Verification asks the questions
that best separate *fixed* from *not fixed* per second of effort. Observations not used during
diagnosis get a ×1.25 bonus, because they are stronger "risky predictions".

- **Verified:** at least one new observation, and P(fixed) ≥ 0.97.
- **Not verified:** P(fixed) ≤ 0.10, or no available observation can tell the two apart.

A confident diagnosis alone never verifies a repair: before any new evidence,
P(fixed) = P(cause) × 0.9.

**Tests.**
- A successful reset is verified.
- A reset that does not hold is not verified.
- A diagnosis misled by misreports is caught.
- A repair to a component nobody suspected cannot be verified.
- The capability rules hold (wrong person, reused token, wrong target, not approved).
- The engine rebuilt from events matches the live one.

**Limitation.** One repair per investigation. A failed verification currently ends the
investigation; it does not yet reopen it with the repair applied.
