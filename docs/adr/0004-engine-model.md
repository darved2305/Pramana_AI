# 0004 - Initial engine model: what it assumes and why

**Status:** accepted for the initial engine. The hypothesis space and the reliability model
are superseded by ADR 0008 (unknown reliability integrated out; identifiable fault pairs).

- **Hypotheses:** every modelled single fault, `NO_FAULT` and `OPEN_WORLD`. Pairs are not
  enumerated. A two-fault world is explained by the best single cause or by `OPEN_WORLD`, and
  several operational decisions are not produced yet.
- **OPEN_WORLD likelihood:** uniform over each probe's outcomes. This is a proper distribution, so
  Bayes stays coherent, and it gains mass only when the modelled causes explain the evidence
  worse than chance.
- **Reliability:** fixed per (skill, probe class) and not learned within an incident. One incident
  cannot identify an individual's reliability (an audit finding). Hedges and hearsay mix toward
  uniform.
- **Duplicates:** a repeated answer by the same person to the same site supersedes the earlier
  one. Different people are conditionally independent given the cause. *Known limitation:*
  correlated errors across people (two people misreading the same screen) are over-counted.
  A live run with two coordinated misreports produced a wrong, moderate-confidence decision,
  which the ground-truth check flagged.
- **Selection vs stopping:** actions are ranked by `(EIG_D + η·EIG_H)/cost`. Asking is allowed
  only when the **two-step adaptive** value of information exceeds the effort cost (single-step
  EVOI is myopic). Confidence `P(d*)` and expected loss are computed and reported separately:
  decide at `P(d*) ≥ 0.95`; otherwise decide at moderate confidence when `P(d*) ≥ 0.80` and
  nothing is worth asking; otherwise abstain; always abstain when `P(OPEN_WORLD) ≥ 0.25`.
- **Explanations** are fixed templates filled from the scoring trace. No LLM writes them.
