# Handoff prompt

Paste everything below the line into a fresh session to continue the work.

---

You are taking over Pramana (gnani ai hackathon repo, branch `main`). Read these first, in order:
`docs/PLAN.md` (§26 is the day plan), `docs/engineering/DAY2_STATUS.md` (what is done and how it
is verified), `docs/engineering/VOICE_ARCHITECTURE.md`, `docs/engineering/API_GUIDE.md`,
`docs/engineering/STAGING.md`, and the ADRs in `docs/adr/` (0003, 0008 to 0013 matter most).

## Where things stand (updated 2026-11-05 evening)

- M1 text loop, voice calls, phone over tunnel, extractor, benchmark: as before (DAY2_STATUS.md).
- **Parallel calls (D17) are done.** `CreateInvestigation.max_parallel_calls` (1 to 3).
  `pramana_engine/scheduler.py` picks extra questions by conditional gain and withdraws
  questions that stopped mattering (`QuestionWithdrawn`). See ADR 0011 for the rule, tests and
  the simulated-clock benchmark (3 at once: time to conclusion 189 s -> 119 s, success not
  significantly different, about 2 more questions). Console shows every question in flight;
  the create form has "People asked at once". Browser test: `apps/web/tests-real/parallel.spec.ts`.
  **Live check:** `scripts/voice_bot_run.py --parallel 3` on real Gnani: 3 in flight, decided,
  repaired, verified, correct, replay identical, Rs 0.24. That run found a bug (a question
  withdrawn during answer submission ended the call with an error); fixed in 81ad665 with a test.
  Re-run the live bot check once to confirm the fix live.
- **Abstention calibration: done, negative result.** `eval/reports/calibration-2026-11-05/NOTES.md`.
  Abstention cannot be raised without losing accuracy; do NOT claim it. `E-ask_more`
  (lambda 1/120) gives +2.7 points success (significant) for +0.37 questions: team decision
  whether to make it the default (it changes the S1 path; re-run M1 + voice checks if so).
- **Fresh blind extraction set: done.** `eval/data/extraction_blind_2026-11-05.jsonl`, blind
  score in `eval/reports/extraction-blind-2026-11-05/` (rules: 60/80, 0 wrong, 2 invented).
  The 2 invented readings are fixed (now 62/80, 0 invented, not blind). 13 missed answers remain
  (listed in the report): next extractor round, failing tests first.
- **LLM comparison: running across days.** Command (replays cached calls free, continues):
  `uv run python -m pramana_eval --n 100 --seed-start 10000 --policies E,D,B --llm-n 100 --out eval/reports/llm-comparison`
  Run it once a day (Groq free tier stops it at the daily quota, about 13 episodes/day).
  After day 1, 13 LLM episodes: LLM success 30.8% vs ours 87% (paired +38 pts, CI [+8, +69]),
  too few to publish. When n >= 50, commit the report (`git add -f`) with a NOTES.md, honestly.
  The session-only cron for Nov 6 10:07 dies with the old session; run it by hand.

## What is left, in priority order

1. Daily LLM benchmark runs (above) until about 50 to 100 episodes; write NOTES.md; update
   DEMO.md benchmark line only from summary.json.
2. Re-run `voice_bot_run.py --parallel 3` live once (fix 81ad665), then with a human on a phone
   (`--human p_riya`, tunnel per STAGING.md).
3. Demo (Nov 8): DEMO.md storyboard; use parallel calls (create form "Up to 3"), approval,
   reveal and replay in one take. Docs and submission Nov 9 to 10.
4. Extractor: the 13 missed blind-set phrasings.
5. Decide on `E-ask_more` as default (see calibration NOTES).
6. More human phone testers via the tunnel.

Note: port 8000 on this laptop is used by another project's app (`app.main`); run
`scripts/dev.py --core-port 8010 --sim-port 8110` (and point the web app with PRAMANA_CORE_URL).

## How to run

- `uv run python scripts/dev.py --web` starts PostgreSQL (:5433), migrations, sim (:8100), core
  (:8000), web (:3002). Create a user with `uv run python -m pramana_core.auth.bootstrap`.
  Scripts authenticate with `CORE_AUTOMATION_KEY` from `.env`.
- Python tests: `uv run pytest` (set `PRAMANA_SKIP_E2E=1` if another session uses the e2e DB).
  Lint/types: `uv run ruff check .`, `uv run mypy`, `lint-imports` (set
  `PYTHONIOENCODING=utf-8` on Windows). Web: `npm run lint`, `npm run typecheck`,
  `npx playwright test` in `apps/web`.
- Phone: `cloudflared tunnel --url http://localhost:3002` (installed). Quick tunnels carry
  WebSockets but not SSE; the console falls back to polling.

## Rules (do not break)

- Git identity darved2305. Small, plain commit messages. No AI attribution, no Co-Authored-By,
  no "Day 2 / phase / progress" wording. Push to `main` only when tests are green.
- Never commit secrets, `.env`, recordings, licensed fonts, or measured Gnani accuracy or
  latency (EULA). Gnani key stays server-side.
- Never fabricate metrics, browser results or live-run claims. Research before decisions,
  handle edge cases, add a failing test before each fix.
- No em dashes in user-visible frontend text.
- Spend as little as possible (Gnani budget guard ₹150/day; free LLM tiers). Keep disk use low
  and delete temporary files after testing. The user's browser (Arc) must stay open; do not kill
  it. Do not run heavy jobs concurrently on this laptop.
- Do not delete the existing git worktree.
