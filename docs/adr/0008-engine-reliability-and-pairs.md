# 0008: Unknown reliability integrated out, and two-fault hypotheses

**Status:** accepted. Supersedes the "Reliability" and "Hypotheses" bullets of ADR 0004.

## Context

ADR 0004 fixed each answer's reliability per (skill, probe class) and treated every answer as
independent given the cause. Two known problems followed:

1. **Over-counting one person.** Three answers by one student count as much as three students
   agreeing, although a single person who misunderstood the question makes the same kind of
   mistake each time.
2. **Two faults.** A world with two faults (a tripped breaker and an ISP outage) could only be
   explained by `OPEN_WORLD` or by a wrong single fault.

## Decision

### Reliability

- Each person has one unknown reliability per probe class (`device`, `visual`, `panel`). Its
  prior is `r = 0.5 + 0.5 x` with `x ~ Beta(a, b)`: better than chance, never perfect, with the
  mean from `DEFAULT_RELIABILITY` and `a + b = 20` (`reliability_concentration`).
- The likelihood of that person's answers in that class is integrated over `r` with an
  8-node **Gauss-Jacobi** rule (Golub-Welsch, numpy only; `pramana_engine/quadrature.py`).
- The answer model is linear in `r`, so `n` answers form a degree-`n` polynomial in `r`, and
  an 8-node Gauss rule integrates degree `<= 15` exactly. The integral is therefore **exact**,
  not approximate, for up to 15 answers by one person in one class (the question budget is 4,
  plus 2 for verification).
- The predictive distribution of a person's *next* answer under `h` is the likelihood at
  `E[r | h, answers so far]`, again exactly, by linearity. The planner uses this per-hypothesis
  mean (`Engine.effective_reliability`). The two-step lookahead does not re-learn `r` between
  its two steps; that approximation only matters when both steps ask the same person in the
  same class.
- `reliability_model = "fixed"` keeps the earlier model (a point mass at the mean).

### Belief state

The belief is recomputed from stored evidence instead of being accumulated, so superseding an
answer, confirming a spoken one and repairs stay exact under the shared reliability. Repairs
are modelled as **paths**: one hypothesis per era (before the first repair, after each repair).
A repair of fault `f` splits every path whose current world contains `f` into *not fixed*
(weight `p = 0.1`, same world) and *fixed* (weight `1 - p`, the world without `f`). Evidence is
read against each path's world in the era it was given. `P(fixed)` is the weight of paths where
the repair cleared the *whole* cause. A failed verification drops those paths and keeps the
rest, so for a pair whose one fault was cleared, diagnosis resumes on the remaining fault in
today's world.

### Two faults

- Every pair of single faults is a hypothesis with prior `p_a * p_b`, **if it is identifiable**:
  its predictions differ from both single faults. A masked pair (`SW_C2.dead` while
  `CB_C2_7.tripped` already cuts the switch's power) predicts exactly what the single fault
  predicts, so no question can separate them before the masking fault is repaired. Those are
  left out; verification after the repair catches them (it reopens).
- A pair whose faults call for the same decision belongs to that decision (both DB-C2 breakers:
  send the electrician). Otherwise it belongs to `MULTIPLE_FAULTS`. Loss: either fault's own
  decision fixes half the problem (`wrong / 2`); `MULTIPLE_FAULTS` costs nothing under such a
  pair and the full `wrong` loss under a single fault.
- A first version charged `MULTIPLE_FAULTS` only `wrong / 2` under single faults. That made it
  a cheap hedge: at the prior it minimised expected loss, every question's value fell below
  its effort and a student-only investigation abstained without asking anything (caught by
  `test_unidentifiable_with_available_people_abstains`). The full loss fixes this.
- Contradiction detection now counts pairs: answers only a pair explains are not contradictory,
  and `ObserveResult.multiple_faults_suspected` is set instead. The core logs a
  `ContradictionDetected` event when no modelled cause, single or pair, fits.
- At the reveal, a two-fault truth needing two different teams counts `MULTIPLE_FAULTS` as
  correct, as well as either team's own decision.

## Evidence (from code runs on the campus pack)

- Hypotheses: 15 single faults, 76 identifiable pairs (29 masked pairs left out), `NO_FAULT`,
  `OPEN_WORLD`: 93 in total; 15 decisions including `MULTIPLE_FAULTS`. Pairs hold 0.99 % of the
  prior mass.
- Planning p90 for the S1 first question: 11 ms on the development laptop (budget 250 ms in
  `test_plan_latency_budget`).
- Noise-free S1 (breaker C2-7 tripped, Riya, Mahesh, Imran): `DISPATCH_ELECTRICIAN_DB_C2` after
  4 questions at P = 0.973 (3 questions at 0.965 in the single-fault model).
- Correlation: a student answering "no" to the three phone checks leaves
  P(`NO_FAULT`) = 0.00013 with the shared reliability, against 0.00007 when three different
  students give the same answers. With fixed reliability both are 0.00007.
- A world with `CB_C2_7.tripped` and `ISP_LINK.down`, investigated with four staff, ends with
  `MULTIPLE_FAULTS` and the pair as the top cause. After resetting the breaker, verification
  fails and reopening promotes `ISP_LINK.down`, which is then decided.

## Limitations

- Pairs carry only 1 % of the prior. A pair that resembles a likelier single fault (two
  third-floor access points vs switch SW-C2) is diagnosed as the single fault; verification
  after the repair is what exposes it.
- No triples.
- Pair priors use `p_a * p_b` rather than the exact independent-failure ratio
  `p_a p_b / ((1 - p_a)(1 - p_b))`; the difference is under 1 % for these priors.

## Tests

`packages/engine/tests/test_belief_model.py`: quadrature moments exact to degree `2K - 1`; two
same-person answers match the closed-form Beta integral at 1e-12; the fixed model matches the
product of likelihoods; Hypothesis properties (order invariance at 1e-12, monotonicity of
odds, EIG bounds); pair enumeration, priors, decisions and losses; a two-fault investigation;
reopening on the remaining fault of a pair; byte-for-byte replay; S1 in at most 6 questions.
The hand computation in `test_belief.py` still holds at 1e-12 in both models.
