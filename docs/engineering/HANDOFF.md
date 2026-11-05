# Handoff prompt

Paste everything below the line into a fresh session to continue the work.

---

You are taking over Pramana (gnani ai hackathon repo, branch `main`). Read these first, in order:
`docs/PLAN.md` (§26 is the day plan), `docs/engineering/DAY2_STATUS.md` (what is done and how it
is verified), `docs/engineering/VOICE_ARCHITECTURE.md`, `docs/engineering/API_GUIDE.md`,
`docs/engineering/STAGING.md`, and the ADRs in `docs/adr/` (0003, 0008 to 0013 matter most).

## Where things stand

- M1 (text loop) is met and automated: S1 decides in 4 questions, approval flow to `verified` or
  reopen, byte-identical replay. Python e2e `tests/e2e/test_m1.py` and real-backend Playwright
  `apps/web/tests-real/` cover it. CI runs both stacks.
- Voice works end to end on live Gnani (Prisma v3.0 stream + REST second decode, Timbre TTS):
  participant call socket (ring, consent, turns, idle heartbeat, barge-in, silence timeout) in
  `services/core/src/pramana_core/voice/call.py` and `voice/media.py`, driven by the state
  machine in `calls/runtime.py`. Three open-source voice bots (`scripts/voice_bot_run.py`, clips
  from `scripts/make_bot_clips.py`, Meta MMS) reach a verified, correct repair. One real person
  on a phone over a Cloudflare quick tunnel also reached a verified repair.
- Extractor (`language/extraction.py`) is rules-first with property tests
  (`services/core/tests/test_extraction_properties.py`, about 400 cases).
- Benchmark (`eval/reports/benchmark-2026-11-05/`): beats checklist and random significantly,
  ties greedy entropy, abstention 68% on unidentifiable scenarios.

## What is left, in priority order

1. **LLM comparison** (the headline claim): run `eval` with an LLM picking questions vs our
   planner. Free tier only (Groq gpt-oss-120b: 200k tokens/day, 1000 req/day; the client in
   `pramana_core/llm.py` fails fast on per-day 429s). Budget runs across days if needed. Report
   honestly, including if it does not win. A one-shot cron for this may exist in the old session.
2. **Parallel calls with preemption** (D17, ADR 0011: go, cap 3). Per-call sockets and
   `(LISTENING, PREEMPT) -> PREEMPTING` exist; build the scheduler that asks up to 3 participants
   at once and withdraws a question (`question_withdrawn`) when another answer makes it moot.
   Test with the three voice bots, then in the browser.
3. **Abstention calibration**: tune the stopping rule so unidentifiable scenarios abstain more
   without hurting accuracy. Re-run the benchmark, keep the old report for comparison.
4. **Fresh blind extraction set**: the held-out set has been seen. Write a new one before
   looking at results.
5. **Demo** (Nov 8): script and record one investigation with parallel calls, approval, and
   replay. Docs and submission Nov 9 to 10.
6. More human phone testers via the tunnel (see STAGING.md).

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
