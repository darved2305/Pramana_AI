# Main extractor blind baseline (2026-11-06)

Both generated reports score main's rules-only extractor at source commit `6815f70`. The two datasets were committed in `7bc11b5` before either was scored. No extractor rules or tests were changed between that data commit and these runs. The command used for each set was `uv run python -m pramana_eval.extraction_eval --set <file> --provider none --out <directory>`.

The sets were written by AI models outside the repository. The second set was independently reviewed by another AI model; that review changed no labels and rewrote one text. Neither author nor reviewer is a native speaker. The sets were blind to main's rules when authored, and main's rules had not been tuned against either set when these scores were produced. Native-speaker review remains pending.

## Generated rules-only results

| Set | All fields correct | Invented | Missed | Wrong outcome |
|---|---:|---:|---:|---:|
| `extraction_blind_2026-11-06.jsonl` | 47/80 | 7 | 20 | 1 |
| `extraction_blind2_2026-11-06.jsonl` | 26/40 | 2 | 7 | 2 |

The generated `report.md` files contain field accuracy, language breakdowns, and each mismatch. `summary.json` is the machine-readable output. These results describe main's extractor before the attribution port. Once any tuning uses these sets, they are no longer blind and later reports must be labelled accordingly.

The first dataset preserves its historical pre-main report in `eval/reports/extraction-blind-2026-11-06/`; that separate report scored 47/80 under the earlier rules. These new reports are the baseline for main.
