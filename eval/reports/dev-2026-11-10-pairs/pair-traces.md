# Pair episode traces

**Development, post-freeze evidence.** All episodes are from seeds 60000-60299. The raw event
logs are reproducible with the committed tool:

```powershell
uv run python eval/reports/dev-2026-11-10-pairs/tools/trace_pair_episodes.py > pair-traces-raw.txt
uv run python eval/reports/dev-2026-11-10-pairs/tools/trace_pair_episodes.py 60058 60098 60236 60244 60250 60285 60290 > repair-episodes-raw.txt
```

`pair-traces-raw.txt` holds the four episodes quoted below (E/60009, E/60058, E/60098, E/60236).
`repair-episodes-raw.txt` holds all seven development pair episodes in which E attempted a repair.
The tool wraps `Engine.plan`, `Engine.observe`, `Engine.apply_intervention`, `Engine.reopen`,
`Answers.ask` and the policy step. Each wrapper logs the call and returns the original result, so
engine state and control flow are unchanged. Re-running the wrapper reproduced the event sequence
of the first run. Each traced episode's `RESULT` line matches its row in
`before/episodes.csv` for `pair_full_resolution`, `pair_repairs` and `pair_resolution_extra_probes`.

`truth` is the evaluator's simulated world after any successful repair. `said` is the simulated
participant answer. `p_fixed` is the engine's P(symptoms resolved).

## Summary of the seven repair episodes

| Episode | True faults | First repair | Engine after repair | Residual fault after repair | Outcome |
|---|---|---|---|---|---|
| 60058 | SW_C2 dead, CB_MAIN_1 tripped | reset_breaker CB_MAIN_1 | NOT_VERIFIED at p_fixed 0.001, 0 probes, reopen | SW_C2 dead (no repair action) | Reopened; follow-up stopped with MULTIPLE_FAULTS |
| 60098 | ISP_LINK down, CB_MAIN_1 tripped | reset_breaker CB_MAIN_1 | ask switch_leds IDF1 (0.852 to 0.970), then VERIFIED | ISP_LINK down | False VERIFIED |
| 60236 | CB_C2_7 tripped, AP_3A dead | reset_breaker CB_C2_7 | ask switch_leds IDF2 (0.867 to 0.987), then VERIFIED | AP_3A dead (no repair action) | False VERIFIED |
| 60244 | AP_1A dead, CB_C2_7 tripped | reset_breaker CB_C2_7 | VERIFIED at 0.985 after one switch_leds probe | AP_1A dead (no repair action) | False VERIFIED |
| 60250 | CB_MAIN_1 tripped, AP_2A dead | reset_breaker CB_MAIN_1 | VERIFIED at 0.980 after one switch_leds probe | AP_2A dead (no repair action) | False VERIFIED |
| 60285 | DNS down, CB_MAIN_1 tripped | reset_breaker CB_MAIN_1 | VERIFIED at 0.981 after one wifi_status probe | DNS down | False VERIFIED |
| 60290 | AP_2B dead, CB_C2_7 tripped | reset_breaker CB_C2_7 | VERIFIED at 0.983 after one wifi_status probe | AP_2B dead (no repair action) | False VERIFIED |

"False VERIFIED" means the engine returned `verification_confirmed` while a true fault remained.
The evaluator recorded `resolved=False` in all seven episodes. In each of the six false-VERIFIED
episodes the verdict rested on exactly one post-repair probe (a switch-LED or Wi-Fi-status check),
because the verdict threshold was reached after that one answer.

## E/60009: no repair action exists

True faults: `GATEWAY.dead` and `AP_3A.dead`. E's initial conclusion was the true constituent
decision `IT_ONSITE_CORE` with confidence `0.965`.

```text
POLICY [initial diagnosis] -> Conclusion(decision='IT_ONSITE_CORE', confidence=0.964994...)
RESULT decision='IT_ONSITE_CORE' correct=True resolved=False repairs=0 extra_probes=0
```

There is no repair request because `campus_block_c` has no action that fixes `GATEWAY.dead`.
`_complete_pair_repair_loop` returns false when its action lookup is empty
(`eval/src/pramana_eval/runner.py:261-262`). This is not a verification or question-budget stop.

## E/60058: failed verification reopens, then diagnosis stops

True faults: `SW_C2.dead` and `CB_MAIN_1.tripped`. E first concluded `MULTIPLE_FAULTS`; the
evaluator reset the breaker (the first sorted candidate that has an action). The engine's
resolved-pair probability was already `0.001` and it had no post-repair observation.

```text
REPAIR request [initial diagnosis] action=reset_breaker target=CB_MAIN_1
REPAIR state p_fixed=0.001 post_obs=0
PLAN [verification 1] not_verified rule='verification_failed' p_fixed=0.001 action=None
REOPEN [verification 1] p_fixed=0.001 post_obs=0
PLAN [follow-up diagnosis 1] decide rule='no_value_confident_enough' decision='MULTIPLE_FAULTS'
POLICY [follow-up diagnosis 1] -> Conclusion(decision='MULTIPLE_FAULTS', confidence=0.879655...)
RESULT decision='MULTIPLE_FAULTS' correct=True resolved=False repairs=1 extra_probes=0
```

The engine did reopen. It used its current evidence to conclude immediately under its
`no_value_confident_enough` stopping rule, so the follow-up diagnosis asked no question. The
remaining `SW_C2.dead` fault has no repair action. This episode did not hit the 30-step limit.

## E/60098: a breaker repair verifies while an ISP fault remains

True faults: `ISP_LINK.down` and `CB_MAIN_1.tripped`. E's initial diagnosis was
`DISPATCH_ELECTRICIAN_MAIN` at confidence `0.947`, and the evaluator reset the breaker. The only
verification question was about switch LEDs, which tests the breaker consequence but not the
remaining ISP service symptom.

```text
REPAIR request [initial diagnosis] action=reset_breaker target=CB_MAIN_1
REPAIR state p_fixed=0.852 post_obs=0
PLAN [verification 1] ask rule='positive_value' p_fixed=0.852 action=p_electrician/switch_leds@IDF1
ANSWER [verification 1] p_electrician/switch_leds@IDF1: truth=green, said=green
OBS [verification 1] ... P(fixed) 0.852 -> 0.970
PLAN [verification 1] verified rule='verification_confirmed' p_fixed=0.970
RESULT decision='DISPATCH_ELECTRICIAN_MAIN' correct=True resolved=False repairs=1 extra_probes=1
```

`ISP_LINK.down` remains in the simulated world, so the evaluator correctly records incomplete
resolution. The engine returns `VERIFIED`, so neither the engine nor evaluator reopens for the
second diagnosis. Before the repair, `p_reporter` had already answered `internet_works = no` at
F1_LOBBY. A tripped breaker explains that answer as well, so the diagnosis weighted the ISP
hypothesis low (the initial conclusion `DISPATCH_ELECTRICIAN_MAIN` had confidence 0.947).

## E/60236: same stop with a dead access point remaining

True faults: `CB_C2_7.tripped` and `AP_3A.dead`. After diagnosing and resetting the breaker, the
engine asks about switch LEDs at IDF2. That answer confirms the breaker reset but does not test
the dead AP.

```text
REPAIR request [initial diagnosis] action=reset_breaker target=CB_C2_7
REPAIR state p_fixed=0.867 post_obs=0
PLAN [verification 1] ask rule='positive_value' p_fixed=0.867 action=p_it/switch_leds@IDF2
ANSWER [verification 1] p_it/switch_leds@IDF2: truth=green, said=green
PLAN [verification 1] verified rule='verification_confirmed' p_fixed=0.987
RESULT decision='DISPATCH_ELECTRICIAN_DB_C2' correct=True resolved=False repairs=1 extra_probes=1
```

The `AP_3A.dead` fault remains. The outcome is consistent with an underweighted pair hypothesis
and verification evidence that establishes the breaker repair, not the full service restoration.

## Reading across the seven episodes

The compiled model gives pair hypotheses 1.0147% of the prior mass (see `pair-coverage.txt`), so a
second fault that the diagnosis has not yet confirmed starts with little weight. The verification
probe is chosen to separate "the repaired fault was the whole cause" from "it was not", and in six
of the seven episodes one consistent answer lifted P(fixed) from about 0.85 to at least the
verified threshold of `0.97` (`verified_threshold` in `packages/engine/src/pramana_engine/config.py`).
The engine's verdict is consistent with its own model. The failure is that the model's prior on a
second fault is far below the evaluator's pair share, so the verdict is miscalibrated for these
episodes. That is a calibration and probe-choice limit, documented in [report.md](report.md), not an
evaluator defect.
