# Extraction after attribution (2026-11-06)

All rules-only reports in this directory were generated at commit `fddc502` with `--provider none`. The main junk report evaluates the existing `JUNK` list from `services/core/tests/test_extraction_junk.py` against every pack probe and supported language.

## Blind baseline for main's rules

The first new set and the reviewed second set were committed in `7bc11b5` before either was scored. Main's extractor source remained at `6815f70` through both baseline runs. Baseline outputs are preserved in `eval/reports/extraction-blind-main-2026-11-06/`.

| Set | All fields correct | Invented | Missed | Wrong outcome |
|---|---:|---:|---:|---:|
| `extraction_blind_2026-11-06.jsonl` | 47/80 | 7 | 20 | 1 |
| `extraction_blind2_2026-11-06.jsonl` | 26/40 | 2 | 7 | 2 |

These were the blind scores for main's rules before the attribution change. A historical pre-main report is preserved separately at `eval/reports/extraction-blind-2026-11-06/`; its 47/80 result was scored on the older, pre-main rules at source commit `e23572c`.

## Tuned rules-only results

The attribution changes were tested against both new sets. These figures are tuned and no longer blind. The old Nov 5 blind set was tuned on before this port, and the held-out set was inspected to diagnose a stop-request false positive during this port, so neither is held out for these results. The development set was already used for rule tuning.

| Set | Status | All fields correct | Invented | Missed | Wrong outcome |
|---|---|---:|---:|---:|---:|
| `extraction_blind_2026-11-06.jsonl` | Tuned, no longer blind | 53/80 | 0 | 19 | 0 |
| `extraction_blind2_2026-11-06.jsonl` | Tuned, no longer blind | 27/40 | 0 | 10 | 0 |
| `extraction_blind_2026-11-05.jsonl` | Previously tuned, no longer blind | 69/80 | 0 | 11 | 0 |
| `extraction_heldout.jsonl` | Used for tuning in this port | 71/80 | 0 | 7 | 0 |
| `extraction_set.jsonl` | Development set | 41/48 | 0 | 7 | 0 |

The no-invention requirement is met on every scored set. The remaining missed outcomes are abstentions on answerable lines. On the first new set, misses changed from 20 to 19; on the second, misses increased from 7 to 10. The full field breakdowns and mismatch rows are in each generated `report.md` and `summary.json`.

## Main junk inputs

The generated `main-junk/` report evaluated 21 existing junk phrases against 14 probes in four supported languages: 1,176 extractions. All 1,176 returned `unknown`; none produced a definite outcome. The existing phone-talk, being-here, unrelated-object, and valid-answer regression tests also pass.

## Authorship and limits

Both new sets were written by AI models outside the repository, not by human participants. The first set was independently re-labelled by a second AI model, which changed one hedge label and revised one Marathi sentence. The second set was independently reviewed by another AI model; labels changed by zero and one Marathi sentence was rewritten. Neither the authors nor reviewers are native speakers. Native-speaker review is pending. These are synthetic text answers and do not measure speech recognition or participant language quality.
