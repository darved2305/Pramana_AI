# Two-fault resolution diagnosis

**Development, post-freeze evidence.** Seeds 60000-60299 were checked as unused before the run
(see [NOTES.md](NOTES.md)). This report does not replace or update the frozen held-out result in
`eval/reports/benchmark-2026-11-10-heldout/`. That report and its protocol were not rerun,
regenerated, edited or reinterpreted.

## Question

The held-out run shows E reaching a first useful action in 29 of 40 pair scenarios, but full pair
resolution in only 3 of 40. Why do two-fault incidents rarely end fully resolved?

## Short answer

Three things stack up, in this order of importance:

1. **Coverage.** The campus pack models one repair action, `reset_breaker`, for tripped breakers.
   A pair can be fully resolved only if both faults are repairable, which is 3 of the 15 single
   faults. That caps full resolution at 2.86% of pair scenarios under the generator's sampling.
   The held-out and development results are both consistent with that cap.
2. **Verification closes too early.** In six of the seven development pair episodes where E
   repaired a breaker, the engine returned `VERIFIED` while the second fault was still present.
   The engine's model gives all pair hypotheses about 1% of the prior, and one consistent probe was
   enough to pass the 0.97 threshold. This is the most important product risk here, because the
   incident is closed while a fault remains.
3. **Stopping after a reopen.** When verification correctly fails and reopens (1 of 7 episodes),
   the follow-up diagnosis stops at the engine's `no_value_confident_enough` rule. It concludes
   `MULTIPLE_FAULTS` without asking a question, and there is no repair action for the residual
   fault.

No step-budget or 30-step limit was reached (`hit_step_limit` is False for every pair row in both
policies).

## Measurement

The before run used code commit `63c4254`. The after run used `9b0686c`, which changes only the
pair-limit paragraph in `docs/EVALUATION.md`. Both runs use the same seeds, E and D policies, and
metrics, in logic mode with no provider calls.

```powershell
uv run python -m pramana_eval --policies E,D --n 300 --seed-start 60000 --out eval/reports/dev-2026-11-10-pairs/before
uv run python -m pramana_eval --policies E,D --n 300 --seed-start 60000 --out eval/reports/dev-2026-11-10-pairs/after
```

The manifest has 202 single-fault, 42 pair, 17 no-fault and 39 access-limited scenarios.

| Policy | First useful action, before and after | Full resolution, before and after | Pair denominator | Mean repairs, before and after | Verification probes, before and after |
|---|---:|---:|---:|---:|---:|
| E | 28/42 (66.7%) | 0/42 (0%) | 42 | 0.17 | 0.14 |
| D, greedy entropy | 32/42 (76.2%) | 0/42 (0%) | 42 | 0.12 | 0.17 |

The two runs are identical except for the `git_sha` field: `episodes.csv` is byte-identical in both
folders. Because no evaluation or engine code changed, this is a reproducibility check. It is not a
measure of a fix.

## Findings

Severity follows the brief: P0 blocks the submission or is a correctness/security bug, P1 clearly
hurts a judging criterion, P3 is a nit.

### F1. Full pair resolution is capped by the repair catalogue (P1, coverage)

- **Evidence.** `packs/campus_block_c.yaml:322-333` defines one action, `reset_breaker`, which fixes
  `tripped` on a `breaker`. `pair-coverage.txt` (from `tools/pair_coverage.py`) reports 3 of 15
  single faults repairable (`CB_MAIN_1`, `CB_C2_5`, `CB_C2_7`), so the upper bound on full pair
  resolution is C(3,2)/C(15,2) = 3/105 = 2.86%. `eval/src/pramana_eval/runner.py:261-262` returns
  incomplete when no action matches, so a pair with an unrepairable fault can never resolve.
- **Held-out cross-check (read-only).** The three full resolutions in the published held-out E rows
  (seeds 40087, 40221, 40299) all carry the `DISPATCH_ELECTRICIAN_DB_C2` decision, a breaker class.
  The same three seeds are the only E pair rows with `pair_full_resolution` True.
- **Sampling check.** Under the cap, P(X >= 3 | n=40, p=0.0286) = 0.106, and P(X = 0 | n=42) =
  0.296. So 3 of 40 held out and 0 of 42 in development are both within sampling noise of the cap,
  not an exact match to it.
- **Why it matters.** It explains the headline gap between first useful action (29/40) and full
  resolution (3/40) without any engine failure. It moves the "two-fault" judging claim: the product
  can show a repair path for a breaker pair, but not for most pairs.
- **Fix.** Product, not evaluator: add approved repair actions for further fault types, each with a
  role, approval and capability, and calibrate the pair prior against deployment data. Changing the
  evaluator to infer repairs would overstate what the product supports, so it is not done here.
- **Acceptance.** A new action in the pack with a test that the pair-resolution loop reaches
  `VERIFIED` with no residual fault, plus a new development-range measurement. Not run here.

### F2. Verification returns VERIFIED with a second fault still present (P1, verification)

- **Evidence.** `pair-traces.md` lists all seven development pair episodes where E repaired.
  Six end with `verification_confirmed` after a single consistent probe, and the evaluator records
  `resolved=False` for each. Examples, from `repair-episodes-raw.txt`:
  - E/60098: `ISP_LINK.down` plus `CB_MAIN_1.tripped`. P(fixed) 0.852, then one `switch_leds@IDF1`
    answer (green, truth green) moves it to 0.970. `verified rule='verification_confirmed'`.
  - E/60244: `AP_1A.dead` plus `CB_C2_7.tripped`. P(fixed) 0.863 to 0.985 after one `switch_leds`
    probe. Verified with `AP_1A` still dead.
- **Mechanism.** The compiled model gives pair hypotheses 1.0147% of prior mass
  (`pair-coverage.txt`). After the breaker is reset, P(fixed) is already about 0.85: the belief that
  the breaker was the whole cause is high, and only about 15% of the posterior sits in worlds where
  something else remains. `verified_threshold` is 0.97
  (`packages/engine/src/pramana_engine/config.py:76`), and one consistent answer lifts P(fixed)
  past it. The verdict is consistent with the model, which is the calibration problem.
- **Why it matters.** The product's central claim is that a repair is verified by belief and
  reopened when service is not restored. Here the incident is closed (`VERIFIED` is terminal in
  `services/core/src/pramana_core/investigations.py` around lines 884-897) while a fault remains.
  That is a user-visible safety and trust risk, and it is the part of the story a judge can test.
- **Why this is not an evaluator bug.** The evaluator correctly records `resolved=False` in all
  seven episodes. The defect is in the model's prior and the verification verdict.
- **Fix options (not made here).** (a) Require a post-repair check of the reported symptom before
  `VERIFIED`. (b) Keep a pair-aware residual mass after a repair, so that one probe cannot move the
  state past the threshold. (c) Recalibrate the pair prior against deployment data. Each changes
  engine decisions, so each needs a product decision and a new frozen protocol.
- **Recommendation for the submission.** Disclose this as a known limitation in the limitations
  section, since the owner of `docs/SUBMISSION.md` decides wording. Do not claim pair resolution.
- **Acceptance.** E/60098 returns `NOT_VERIFIED` or asks a symptom probe before `VERIFIED`, a unit
  test with a residual second fault, and a new development-range measurement.

### F3. Repair candidate order can skip an actionable fault (P2, evaluator metric integrity)

- **Evidence.** `eval/src/pramana_eval/runner.py` in `_complete_pair_repair_loop` sorts the
  candidate faults and previously tried the first one before checking whether it had an available
  action. For a `MULTIPLE_FAULTS` conclusion, unrepairable `AP_1A.dead` sorts before repairable
  `CB_C2_7.tripped`, so the evaluator returned without attempting the breaker repair.
- **Effect.** This can under-count repair attempts and verification probes when a policy concludes
  `MULTIPLE_FAULTS`. It cannot make a pair with an unrepairable remaining fault fully resolved.
  The baseline development check found no affected first choices in its 600 E/D episodes; it did
  not cover later choices after a failed repair.
- **Why it matters.** Repair and verification counts are reported pair-evaluation outcomes.
  Skipping an available repair makes those secondary measures less accurate, though it moved the
  full-resolution rate by 0 percentage points in the measured development range.
- **Fix.** Commit `dbcc64c` now selects the first sorted remaining fault with a modeled action and
  fewer than two attempts. This evaluator change is post-freeze; the frozen protocol and report
  remain unchanged and were not rerun.
- **Acceptance.** `eval/tests/test_benchmark.py::test_multiple_faults_repair_selection_skips_unrepairable_fault`
  passes. The same 300-seed-per-policy development command was rerun at `dbcc64c`; the 600 parsed
  episode rows and pair aggregates match the pre-fix run.

## Trace evidence

[pair-traces.md](pair-traces.md) has the event excerpts for E/60009 (no repair action), E/60058
(failed verification, reopen, stop at `MULTIPLE_FAULTS`), E/60098 and E/60236 (false `VERIFIED`).
The raw logs are `pair-traces-raw.txt` and `repair-episodes-raw.txt`.

Stopping points, answering the brief's questions for these episodes:

- **Does verification detect the remaining fault?** In 1 of 7 (E/60058), by belief alone at P(fixed)
  0.001 with no probe. In 6 of 7 it does not (F2).
- **Does the investigation reopen?** Only after a `verification_failed` result (E/60058). Not after
  `VERIFIED`.
- **Does diagnosis of the second fault start?** In E/60058 a follow-up diagnosis starts and
  immediately decides `MULTIPLE_FAULTS` at confidence 0.880 under `no_value_confident_enough`, with
  zero questions.
- **Where does it stop?** Either at the evaluator's missing action (E/60009, E/60058 residual
  `SW_C2`), at the engine's `VERIFIED` (six episodes), or at the engine's stopping rule after a
  reopen (E/60058). Not at the question budget or the 30-step limit.

## Decision

No engine behavior changed: F1 is pack coverage and F2 is a calibration limit caused by the low
pair prior relative to the development generator. The evaluator-only F3 defect was fixed after the
freeze in `dbcc64c`, with a regression test and a development rerun. Neither the held-out report nor
its protocol was changed or rerun. Do not treat the F3 correction as a new held-out result.

## Reproduce

Commands are in [NOTES.md](NOTES.md). The evidence files are `pair-coverage.txt`,
`candidate-order-check.txt`, `pair-traces-raw.txt`, `repair-episodes-raw.txt`, and the episode CSVs
in `before/`, `after/`, and `after-fix/`.
