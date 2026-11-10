# Notes

**This folder is development evidence collected after the held-out freeze.** It is not a
replacement for `eval/reports/benchmark-2026-11-10-heldout/`, whose protocol and published numbers
were not rerun, regenerated, edited or reinterpreted. The analysis is in [report.md](report.md).

## Seed range

Development seeds: 60000-60299.

Before the run, a search for 60000-60299 found no use outside this folder. That earlier search used
ripgrep's default ignore rules, and `eval/reports/` is gitignored, so it did not cover the report
folders. The check was therefore repeated on the current tree with the command below. It searches
ignored and hidden files too, which covers the tracked held-out report folder. It excludes only
`uv.lock`, `.git`, `.venv`, `node_modules` and this folder.

```powershell
rg --no-ignore --hidden -n -w '6000[0-9]|60[01][0-9]{2}|602[0-9]{2}' --glob '!eval/reports/dev-2026-11-10-pairs/**' --glob '!uv.lock' --glob '!.venv/**' --glob '!**/node_modules/**' --glob '!.git/**' .
```

Result: 0 matches. The held-out range 40000-40299 was not used for diagnosis or for the new
measurements. The held-out CSV was read once, only to check which of its published pair rows had
full resolution (see report F1).

## Runs

- The original `before/` and `after/` runs were produced at commits `63c4254` and `9b0686c`; their
  only tracked difference was documentation. They are the reproducibility check from the initial
  diagnosis, not a measure of a fix.
- After the post-freeze repair-candidate fix in `dbcc64c`, the same development range was run again
  into `after-fix/` with this command:

  ```powershell
  uv run python -m pramana_eval --policies E,D --n 300 --seed-start 60000 --out eval/reports/dev-2026-11-10-pairs/after-fix
  ```

- Logic mode only (policies E and D): no LLM, Gnani or other provider call. No database and no
  browser were used.
- `before/episodes.csv`, `after/episodes.csv`, and `after-fix/episodes.csv` have identical parsed
  rows. After normalizing line endings to LF, all three have SHA-256
  `76bd1adeaf912ec7a810d08d872992b63a645922c20d9d2a3ddc6b999f568616`. The summaries are equal
  except for `git_sha`; the scenario manifests and reliability diagrams are also equal after line
  ending normalization. The rerun completed 300 episodes per policy with no failures.
- The manifest has 202 single, 42 pair, 17 no-fault and 39 access-limited scenarios.

## Tools and raw evidence

All tools are in `tools/` and print to stdout. Run them from the repository root with `uv run python`.

| File | Produced by | What it shows |
|---|---|---|
| `pair-coverage.txt` | `tools/pair_coverage.py` | Pair prior mass 1.0147%, 3 of 15 single faults repairable, upper bound 2.86% |
| `candidate-order-check.txt` | `tools/candidate_order_check.py` | Baseline check before the fix: 0 affected first choices in E and D; it does not cover later choices after a failed repair |
| `pair-traces.md` | hand-written from `pair-traces-raw.txt` and `repair-episodes-raw.txt` | Episode excerpts and the seven-episode table |
| `pair-traces-raw.txt` | `tools/trace_pair_episodes.py` (default seeds) | Event log for E/60009, 60058, 60098, 60236 |
| `repair-episodes-raw.txt` | `tools/trace_pair_episodes.py 60058 60098 60236 60244 60250 60285 60290` | Event log for all seven E pair episodes with a repair |

The trace tool wraps engine and answer methods and returns the original results. Its `RESULT` lines
match the matching rows of `before/episodes.csv`.

## Counts used in the report

Each count below comes from the CSVs or from a committed tool:

- E pair episodes with a useful constituent decision: 28 of 42 (`before/episodes.csv`, correct and
  not `MULTIPLE_FAULTS`). Of these, 6 carry a breaker-repair decision
  (`DISPATCH_ELECTRICIAN_MAIN` or `DISPATCH_ELECTRICIAN_DB_C2`).
- E pair episodes with a repair attempt: 7 (`pair_repairs` sum 7). Verification probes (sum of
  `pair_resolution_extra_probes`): 6. Episodes hitting the 30-step limit: 0.
- D pair episodes with a useful constituent decision: 32 of 42. Repair attempts: 5. Verification
  probes: 7. Episodes hitting the step limit: 0.
- Full pair resolution: E 0 of 42, D 0 of 42.
- The corrected evaluator produced the same 600 parsed episode rows and pair aggregates on this
  range. The regression test exercises an ordered pair where the first fault has no modeled repair
  and the second has `reset_breaker`.
