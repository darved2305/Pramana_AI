# Provenance of these extraction reports

- `eval/data/extraction_heldout.jsonl` was committed (`Add held-out answer extraction set`)
  before the extractor was changed. The **blind** result is in
  `../extraction-2026-11-05-baseline/`: it is the only number on this set that was measured
  before anyone saw its mistakes.
- The extractor was then changed for two reasons only: the bug list from the end-to-end harness
  (Marathi and Hindi injection, role claims such as "system:" and "you are now the admin", stop
  requests, and the yes/no polarity rule) and paraphrases in the development set
  (`extraction_set.jsonl`). No phrase was added because a held-out item needed it.
- The held-out mistakes had been seen by then, so the result in this directory is **not blind**.
  Treat it as an upper bound; a new held-out set is needed for the next blind measurement.
- Two held-out mistakes were then fixed **after being seen**, because each put a false
  observation into the belief rather than missing one: `h10` ("my friend says nothing loads"
  was read as "yes"; negative subjects now negate the verb) and `h80` ("subah green tha" was
  recorded as a current reading; a time of day is now stale unless it marks a start, as in
  "subah se band hai"). Both have regression tests in `services/core/tests/test_extraction.py`
  that use new sentences, not the held-out ones. This report was regenerated after those fixes.
- The other remaining held-out mistakes (misses, which yield no evidence) are left unfixed.

All figures in `summary.json` and `report.md` are written by
`python -m pramana_eval.extraction_eval --set eval/data/extraction_heldout.jsonl --provider none
--out <dir>`.
