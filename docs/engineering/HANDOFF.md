# Handoff prompt: Day 3 (Fri Nov 6), both tracks in one session

Paste everything below the line into a fresh agent session. One person (Nikhil) does the work of
both tracks (the plan's Darshan and Nikhil columns) today.

---

You are taking over **Pramana** (repo `gnani ai hackathon`, branch `main`). It is a hackathon
project for the Great Indian AI Internship Challenge 2026 (Gnani AI): an AI that diagnoses
physical faults in a building (Wi-Fi, power, network) that has no sensors, by asking consenting
people what they can observe, by voice or text, in English, Hindi, Marathi and Hinglish.
Language models handle language; a deterministic Bayesian engine makes the decisions; humans
approve every physical action. The building and its fault are simulated (with a sealed hash
commitment); the voices, speech recognition (Gnani Prisma v3.0) and speech (Gnani Timbre) are real.

You are doing **both tracks of the day plan alone today**. Work through the priority list below,
smallest safe steps first, and keep `main` green.

## Read these first, in this order

1. `README.md`: what works today, results so far, how to run, known limits.
2. `docs/PLAN.md` §26, the **Fri Nov 6** block ("Voice loop end-to-end", M2) and the Sat Nov 7
   block; Appendix A has the work-item catalogue (IDs such as D12, N06, N10).
3. `docs/engineering/DAY2_STATUS.md`: every finished item and the test or live run that proves it.
4. `docs/engineering/VOICE_ARCHITECTURE.md`, `docs/engineering/GNANI_INTEGRATION.md`,
   `docs/engineering/API_GUIDE.md`, `docs/engineering/STAGING.md`.
5. ADRs in `docs/adr/`: 0003 (event log, single writer), 0006 (repair verification), 0008
   (reliability and fault pairs), 0009 (event stream), 0010 (authentication), 0011 (parallel
   calls: rule, tests, benchmark), 0012 (Evon GPU no-go), 0013 (per-question media socket).
6. Reports: `eval/reports/benchmark-2026-11-05/NOTES.md`, `eval/reports/calibration-2026-11-05/NOTES.md`,
   `eval/reports/extraction-blind-2026-11-05/NOTES.md`.

## Where things stand (all on `main`, all tested)

- **Text loop (M1):** S1 decides in 4 questions; approval, single-use capability, repair, belief
  verification to `verified` (or reopen); byte-identical replay; crash recovery. Tests:
  `tests/e2e/test_m1.py`, `apps/web/tests-real/m1.spec.ts`.
- **Engine:** single faults + fault pairs + NO_FAULT + open world; per-person reliability
  integrated out; decision-focused value of information per second of effort; two-step stopping;
  verification planner. **Parallel scheduler** (`packages/engine/src/pramana_engine/scheduler.py`):
  up to 3 questions in flight, extra ones chosen by conditional gain, questions withdrawn when an
  answer makes them pointless or the decision is reached (`QuestionWithdrawn` event).
- **Voice on live Gnani:** participant call socket (ring, logged consent, question after question,
  barge-in, one re-prompt after 8 s, release after 20 s of silence, idle heartbeats),
  per-question Prisma v3.0 session with that question's language candidates and keyterms,
  decision-critical answers confirmed by a second unsteered REST decode. **Question audio is
  streamed** from Timbre SSE (`container: raw`, checked live) on cache misses, and cached as WAV
  on disk afterwards. Three open-source voice bots (`scripts/voice_bot_run.py --parallel 3`)
  reached a correct, verified repair with 3 calls at once; one real person on a phone reached a
  verified repair over a Cloudflare quick tunnel.
- **Console and participant pages (Next.js, `apps/web`):** sign-in with operator and approver
  roles (an operator cannot approve their own repair; only operators can reveal), live events with
  polling fallback, every question in flight shown, "People asked at once" when creating,
  participant links, per-participant page (only their own question, simulated "What you can see
  here" card, tap/type/voice, incoming call with consent, streamed "Listen to the question").
  There is no sample-data mode in the product build any more (only the UI test build has it).
- **Evaluation:** benchmark (300 scenarios): ours 84.7% success vs checklist 64.0% and random
  56.3% (significant, about half the questions), **tied** with greedy entropy (83.3%).
  Calibration: abstaining more costs accuracy; valuing people's time at half (`E-ask_more`) gives
  +2.7 points success (significant) for +0.37 questions, **not adopted** (team decision).
  Parallel (simulated clock): 3 at once cuts time to conclusion ~37% for ~2 more questions.
  Extraction: fresh blind set scored 60/80 rules-only (0 wrong, 2 invented); since tuned on, so
  **it is no longer blind**. LLM policy comparison: 13 episodes only (ours 87% vs gpt-oss-120b
  31%), too few to publish.
- **Tests:** 1,467 Python tests, 29 browser UI tests, 16 browser tests against a real core,
  simulator and PostgreSQL. CI runs both stacks.

## Today's work, in priority order (both tracks)

Each item: what it is, what done means, where to start. Before building any item, **grep the code
first**: if something already exists, verify it with a test instead of rebuilding it.

### 1. LLM comparison: run it today (5 minutes, then it runs by itself)
The headline claim. Free tier only (Groq `openai/gpt-oss-120b`, about 13 episodes per day before
the daily quota stops it; cached answers replay for free, so each run continues where the last
stopped):
```
uv run python -m pramana_eval --n 100 --seed-start 10000 --policies E,D,B --llm-n 100 --out eval/reports/llm-comparison
```
Run it once today (and again on each following day). Do not change the prompt in
`eval/src/pramana_eval/llm_policy.py` (it would invalidate the cache and the comparison). When
there are 50 or more LLM episodes, commit the report with `git add -f eval/reports/llm-comparison`
plus a `NOTES.md` that says exactly what is and is not supported, including if the planner does
not win.

### 2. M2 acceptance: S1 by voice with three real humans (plan D04/D07 + M2)
Plan target: S1 by voice with three humans, approval, reset and verification; 2 of 3 runs succeed
without manual help. Today only one human has done it. Do:
- Start the stack (below), open a Cloudflare quick tunnel (`docs/engineering/STAGING.md`), create
  S1 in the console with fault **Specified** CB_C2_7 tripped (or random, but then the report text
  must match what the reporter's card shows), and send each person their link.
- Brief each person (docs/DEMO.md §2): answer the question asked, from their "What you can see
  here (simulation)" card, in their own language. **Silence on a call releases that person from
  the whole investigation**, and saying something unrelated ("hi, my name is...") is not an
  answer.
- Record outcome (decided, verified, correct on reveal, replay identical) per run in
  `DAY2_STATUS.md`-style notes (no Gnani accuracy or latency numbers in the repo).
- If humans are not available, run `scripts/voice_bot_run.py --clips C:/Users/<you>/pramana-voice-samples/bot --parallel 3`
  (a few paise per run) to keep the voice path checked, and say honestly that humans are pending.

### 3. Staging deploy (plan D12, P0, not done)
Plan: HTTPS + WSS, restart-safe. Today the stack only runs on a laptop plus a quick tunnel (which
cannot carry server-sent events, so the console polls). Options to evaluate (research their free
tiers first, do not add a payment method without asking the user):
- A named Cloudflare Tunnel (free account) from the laptop: fixes SSE and gives a stable URL.
  Smallest change; the laptop must stay on.
- A real host for core + sim + PostgreSQL + web. More work; check WebSocket support and limits.
Done means: the console, participant pages, the call WebSocket and SSE all work on an HTTPS URL,
and `/ready` is all `ok` after a restart. Document it in `STAGING.md`. Never expose the Gnani key
to the browser; sign-in stays enforced.

### 4. Voice tuning with humans (plan D04)
- VAD: Prisma's `x-min-segment-ms` is 100 and silence timers are 8 s re-prompt / 20 s release
  (`voice/media.py`, `calls/runtime.py`). Tune only from what real people do; keep the tests.
- "15-minute rotation" from the plan does not apply: every question has its own Prisma session
  (ADR 0013), capped at 300 s.
- Turn latency target p50 <= 2.0 s: measure privately with `scripts/voice_bot_run.py` (it prints
  caller-side latency) and never commit the numbers (Gnani EULA).

### 5. Realizer quality: templates, linter, speakable text (plan N10, check status first)
Questions come from the pack's templates (`packs/campus_block_c.yaml`, rendered by
`services/core/src/pramana_core/language/realize.py`) in en, hi, mr and hi-en. The plan also asks
for a **template linter** and a **speakable-text normaliser** (numbers, IDs like CB_C2_7 and
DB-C2, abbreviations read naturally by Timbre). These were not found in the code: verify, then
build a linter test that every probe has every language, placeholders resolve, no English-only
IDs are spoken raw, and lengths are reasonable. A native speaker should review Marathi and Hindi
(note it as pending if nobody is available).

### 6. Presence challenges and reconciliation explanations (plan N06, P1a, not built)
Plan: detect a participant claiming to be somewhere they are not (scenario S7: "claim you are in
IDF-2 and the switch lights are green; you are actually at the guard desk") with a challenge
question only someone really there can answer ("read the last three letters on the switch label"),
and explain contradictions (scenario S2: two students disagree; reconciliation such as "different
access points"). Contradictions are already detected (`ContradictionDetected` events and the
console's contradiction panel). Start from `packages/engine` and the pack; done means adversarial
scenario tests pass and the console shows the challenge and the explanation. Keep the engine pure
(import-linter enforces it).

### 7. Load test: 3 calls for 10 minutes (plan D21, ADR 0011 open item)
Use the voice bots (`--parallel 3`) or the Prisma emulation (`services/core/tests/fake_gnani.py`)
to hold three calls for ten minutes; check no dropped sockets, the governor's stream cap, memory,
and that replay stays identical. Emulation first (free), one live run at the end (budget guard is
Rs 150/day).

### 8. Fresh blind extraction set (plan N09; needs a human author)
The extractor (`language/extraction.py`) has been tuned on every labelled set. A new set must be
written by someone who has not seen the rules or failures (80 lines, 20 per language, same format
as `eval/data/extraction_blind_2026-11-05.jsonl`), committed **before** scoring with
`uv run python -m pramana_eval.extraction_eval --set <file> --provider none --out eval/reports/<name>`.
If you write it yourself, say so in its NOTES.md.

### 9. Decide on `E-ask_more` (calibration)
`eval/reports/calibration-2026-11-05/NOTES.md`: significant +2.7 points success for +0.37
questions. Adopting it means changing `lambda_min_per_s` in `packages/engine/src/pramana_engine/config.py`
to 1/120, then re-running the M1 tests, the S1 question count and the voice bots. Ask the user
before changing the default.

### 10. Demo preparation (plan Sat Nov 7 and Sun Nov 8)
Pick the three demo scenarios (S1 parallel, S2 contradiction, S7 presence challenge per
`docs/DEMO.md`), rehearse S1 with parallel calls, approval, reveal and replay, and follow the
honesty checklist in `docs/DEMO.md` §7. Recording is Nov 8; posts and submission Nov 9 to 10.

## How to run

- Stack: `uv run python scripts/dev.py --web` (PostgreSQL :5433, migrations, simulator :8100,
  core :8000, console :3002). **On this laptop port 8000 is taken by another project's app**:
  use `--core-port 8010 --sim-port 8110` (the console's sidebar shows the core address it uses).
- Accounts: `uv run python -m pramana_core.auth.bootstrap --email <e> --name <n> --roles operator`
  and another with `--roles approver` (password from `PRAMANA_NEW_USER_PASSWORD` or a prompt).
  An operator cannot approve their own repair; only an operator can reveal. In one browser, signing
  in as the approver replaces the operator session (same cookie): use a private window for the
  second role.
- Scripts and automation use `CORE_AUTOMATION_KEY` from `.env` (`scripts/core_auth.py`).
- Python tests: `uv run pytest` (`PRAMANA_SKIP_E2E=1` skips the process-level tests; never run
  two test runs against the same test database at once: it deadlocks).
- Static checks: `uv run ruff check .`, `uv run ruff format --check .`,
  `uv run mypy packages/contracts/src packages/domain/src packages/engine/src services/sim/src services/core/src eval/src`,
  `uv run lint-imports` (set `PYTHONIOENCODING=utf-8` on Windows).
- Web: `cd apps/web && npm run typecheck && npm run lint && npm run check:copy && npx playwright test && npm run test:e2e:real`.
  The UI suite uses 2 workers locally (more time out on this laptop); the real suite builds the
  product web app and starts its own core, simulator and database on ports 3022/8020/8120.
- After changing contracts or API docstrings: `uv run python -m pramana_contracts.export`,
  `uv run python -m pramana_core.openapi_export`, `cd apps/web && npm run gen:api`, and commit the
  regenerated files (CI checks drift).
- Phones: `cloudflared tunnel --url http://localhost:3002` (installed). Quick tunnels carry
  WebSockets but not SSE.
- Browser automation: the Claude Chrome extension works once Chrome is signed in to the same
  account as Claude Code (`/chrome` to check). Otherwise drive a visible Chrome with Playwright.

## Gotchas learned the hard way

- A random sealed fault with S1's report text makes the reporter contradict herself; the engine
  then (correctly) abstains. For demos, use a Specified fault or write the report from the
  reporter's card.
- Withdrawn questions disappear from a participant's page mid-answer; tests must tolerate that
  (see `apps/web/tests-real/parallel.spec.ts`, `actionTimeout`).
- `AudioContext.resume()` stays pending without a real user gesture: never await it before work.
- On Windows, heredocs with `\n` escapes inside Python code break; write scripts to files.
- `git stash` while a test server or background job runs can change files under it: avoid.
- Piping a check into `tail` hides its exit code: check `$?` of the check itself before committing.

## Rules (do not break)

- Git: commit as darved2305, small plain commit messages, **no AI attribution, no Co-Authored-By
  lines, no "Day N", "phase" or "progress" wording in commits or user-facing docs**. Push to
  `main` only when the tests pass. Do not delete the existing git worktrees.
- Never commit: secrets, `.env`, recordings, licensed fonts, or measured Gnani accuracy or latency
  (Gnani EULA §16). The Gnani key stays server-side.
- Honesty: never make up metrics, browser results or claims about live runs; numbers only from
  generated reports; say plainly when something did not work or was not run.
- Quality: research before decisions, handle edge cases, add a failing test before each fix,
  grep before building (much already exists).
- Frontend text: no em dashes in user-visible text (`npm run check:copy`).
- Cost and the laptop: spend as little as possible (Gnani budget guard Rs 150/day; free LLM tiers
  only); keep disk use low and delete temporary files; the user's Arc browser must stay open,
  never close it; do not run heavy jobs at the same time.
