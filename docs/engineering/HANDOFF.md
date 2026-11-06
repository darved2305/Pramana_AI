# Handoff prompt: Sat Nov 7 (demo freeze), both tracks in one session

Paste everything below the line into a fresh agent session. One person does the work of both
tracks (the plan's Darshan and Nikhil columns).

---

You are taking over **Pramana** (repo `gnani ai hackathon`, branch `main`). It is a hackathon
project for the Great Indian AI Internship Challenge 2026 (Gnani AI): an AI that diagnoses
physical faults in a building with no sensors (Wi-Fi, power, network) by asking consenting
people what they can see, by voice or text, in English, Hindi, Marathi and Hinglish. Language
models handle the language; a deterministic Bayesian engine makes the decisions; humans approve
every physical action. The building and its fault are simulated, with a sealed hash commitment.
The voices, speech recognition (Gnani Prisma v3.0) and speech synthesis (Gnani Timbre) are real.

Today is **Sat Nov 7: demo freeze (M3)**. Scope freezes at 23:59. After that, only P1a finishing
(until Nov 8 12:00) and bug fixes. Recording is Nov 8. Posts and submission are Nov 9 to 10
(deadline Nov 10 23:59 IST; plan to submit by 14:00).

## Rule zero: nothing is done without evidence

An item is **done** only when a test passes or a run is recorded, and the commit or report path
is written next to it. If something was not run, write "not run". If it failed, write that it
failed and include the output. Never write a number that a generated report did not produce.
Never call a test flaky without a trace that shows why. Before claiming CI is green, run
`gh run list --limit 3` and read the result.

## Read these first, in this order

1. `README.md`: what works, results, how to run, known limits.
2. `docs/PLAN.md` §26, the **Sat Nov 7** and **Sun Nov 8** blocks; Appendix A lists the work
   items (D12, D21, N06 and so on).
3. `docs/engineering/STATUS_2026-11-06.md`: everything finished on Nov 6 and what proves it,
   including the evening section.
4. `docs/DEMO.md`: the three demo scenarios, the rehearsal runbook (`make preflight`,
   `scripts/demo_rehearse.py`) and the honesty checklist (§7).
5. `docs/engineering/STAGING.md`, `VOICE_ARCHITECTURE.md`, `GNANI_INTEGRATION.md`, `API_GUIDE.md`.
6. ADRs `docs/adr/`: 0011 (parallel calls, now including the withdrawn-walk rule), 0013
   (per-question media socket), 0014 (presence checks and disagreement explanations).

## Where things stand (main at the end of Nov 6, all checked)

- **Verified on Nov 6 evening, on main plus the evening fixes:** ruff, ruff format, mypy (81
  files), import-linter, contract and OpenAPI drift, the **full** Python suite *including* the
  process-level e2e tests (`tests/e2e`), web typecheck, lint, copy check, worklet check, API type
  drift, `npm audit` (0 vulnerabilities), the Playwright UI suite and the real-stack browser suite.
  See the "Evening" section of `STATUS_2026-11-06.md` for the exact counts and their caveats.
- **Text loop (M1)** and **voice on live Gnani** (parallel calls, consent, barge-in, re-prompt
  and release timers, second decode, streamed question audio): see README.
- **S2 and S7 exist in the product** (ADR 0014): disagreement explanations, plus presence checks
  that ask someone to read a label code which only the simulator knows. Presence checks are off
  by default (`presence_checks`).
- **Evaluation:** 300-scenario benchmark: ours 84.7% vs checklist 64.0%, random 56.3%, and
  **tied** with greedy entropy (83.3%). Parallel: 3 at once cuts time to conclusion by about 70 s
  and costs about 2 more questions (ADR 0011). `E-ask_more` was **decided against** (keep the
  default; `eval/reports/calibration-2026-11-05/NOTES.md`). Blind extraction sets were written by
  AI and are no longer blind (`eval/reports/extraction-*-2026-11-06/`).
- **LLM comparison:** below the 50 episodes needed to report; see STATUS for the count after the
  Nov 6 evening run. It runs **only on Darshan's laptop**, so the cache (`.cache/llm`, not in git)
  is not split. Nikhil's 12 cached episodes stay on his laptop and are not used.
- **Staging:** `https://pramana-staging.pramana-staging-worker.workers.dev` (Cloudflare Worker, VPC
  and tunnel to Nikhil's laptop; `docs/engineering/STAGING.md`). It runs a **local Gnani emulator**,
  not live Gnani. It has not been tested on a real phone or after a laptop reboot.

## Today's work, in priority order

Grep before building: much already exists. Write a failing test before each fix. Keep `main`
green, and push only after the checks in "Before every push" pass.

### 1. Start of day: prove main is green (30 min)
Run every check in "Before every push" on a fresh `git pull`. Run `gh run list --limit 3`. Fix
anything red before doing anything else.

### 2. LLM comparison: today's free batch (5 min, Darshan's laptop only)
```
uv run python -m pramana_eval --n 100 --seed-start 10000 --policies E,D,B --llm-n 100 --out eval/reports/llm-comparison
```
Do not change the prompt in `eval/src/pramana_eval/llm_policy.py`: that would invalidate the
cache. Report the LLM episode count from `eval/reports/llm-comparison/report.md`. At 50 or more
episodes, commit with `git add -f eval/reports/llm-comparison` plus a `NOTES.md` that states
exactly what the data supports and what it does not.

### 3. M3 demo freeze: S1 parallel 3/3, S2 and S7 by voice (the day's main goal)
- Run `make preflight`, then `scripts/demo_rehearse.py` for S1 (three at once), S2 and S7
  (`docs/DEMO.md`). Record each run's outcome: decided, verified, correct on reveal, replay
  identical.
- **With people if any are available** (this is also the missing M2: S1 by voice with three
  humans, 2 of 3 runs succeeding without manual help). Brief them using DEMO.md §2.
- If nobody is available, use the voice bots on live Gnani
  (`scripts/voice_bot_run.py --parallel 3`, plus `--variants/--think-s/--junk` for human-like
  runs; a few paise per run; the budget guard is Rs 150/day). Say plainly that the run used bots.
- **S7 by voice has not been run live.** Presence-code reading was hardened on Nov 6 evening
  (lowercase typed codes, codes made only of letter names that are also words, all-caps codes
  that spell a letter name; `services/core/tests/test_presence_reading.py`). Check whether
  `voice_bot_run.py` can answer a presence check. If it cannot, add that ability (test first),
  then run S7 live once with an honest bot and once with a lying bot.
- Record a rehearsal video (plan J04). Never commit recordings.

### 4. Real-stack M1 browser test: make teardown robust
On Nov 6, `apps/web/tests-real/m1.spec.ts` once exceeded its 180 s budget **after** every
assertion had passed (the investigation was closed and correct at 108 s). The time was spent in
closing the four browser contexts while the laptop was also running other test suites. It passed
when rerun with the machine less loaded (see STATUS). Fix it: close the contexts in parallel, or
in an `afterEach`/`finally` outside the test budget. Then prove the fix with two clean runs of
`npm run test:e2e:real`.

### 5. Memory soak: is growth warm-up or a leak? (emulated, free)
`uv run python scripts/load_test.py --minutes 40 --out eval/reports/load-2026-11-07`. On Nov 6,
10 minutes went from 111 MB to a 141 MB peak, which is not shown to be flat. Write a `NOTES.md` in
the style of `eval/reports/load-2026-11-06/NOTES.md`. If memory keeps climbing, find the cache
or list that grows, then fix and test it. Run nothing else heavy at the same time.

### 6. Staging: reboot check, phone check, live Gnani (needs Nikhil's laptop)
Done means: after a reboot, the ONLOGON task brings the stack back and `/api/core/ready` is all
`ok`; a real phone completes one participant flow over the public URL (SSE and WebSocket); then
switch from the emulator to live Gnani with the key kept server-side, and check one voice
answer. Update `docs/engineering/STAGING.md` with what was verified and what was not.

### 7. Console polish for the recording (plan D11/D16, only where the demo needs it)
Walk through the console as a viewer would for S1, S2 and S7: the decision bar, the
contradiction/Testimony panel, the presence result, "Why this question?", and the sealed badge
and reveal. Fix only what looks broken or confusing on camera, and add a UI test for each fix.
No em dashes in user-visible text.

### 8. Still waiting on people (note, do not fake)
Native-speaker review of the Hindi and Marathi questions, place names and presence questions
(`packs/campus_block_c.yaml`), and of the two AI-written extraction sets. A human-authored blind
extraction set is needed before any headline blind score.

### 9. End of day
Write `docs/engineering/STATUS_2026-11-07.md` (same table format: item, state, evidence). Then
write the Sun Nov 8 handoff into this file: recording day (plan J05). Freeze scope at 23:59.

## Before every push (all must pass; check each exit code, never pipe a check into `tail`)

```
uv run ruff check . && uv run ruff format --check .
uv run mypy packages/contracts/src packages/domain/src packages/engine/src services/sim/src services/core/src eval/src
uv run lint-imports
uv run python -m pramana_contracts.export --check && uv run python -m pramana_core.openapi_export --check
uv run pytest                      # full suite incl. tests/e2e (about 11 min); never two runs at once
cd apps/web && npm ci && npm run typecheck && npm run lint && npm run check:copy && npm run check:worklet
npm run gen:api && git diff --exit-code -- src/lib/api/schema.gen.ts
npx playwright test                # UI suite, production build
npm run test:e2e:real              # real core, simulator and PostgreSQL (about 9 min)
```
Set `PYTHONIOENCODING=utf-8` on Windows. After pushing, wait for CI (`gh run watch`) and only then
say it is green.

## How to run

- Stack: on Windows run `.\.venv\Scripts\python.exe scripts\dev.py --web`; on POSIX run
  `uv run python scripts/dev.py --web`. Run Python directly on Windows: `uv run` can return the
  Ctrl-Break status `0xC000013A` even after `dev.py` has stopped its children.
  **On Darshan's laptop, port 8000 is taken**: use
  `--core-port 8010 --sim-port 8110`.
- **`npm ci` fails with EPERM while any `next start`/`next dev` from `apps/web` is running**
  (it holds `next-swc.win32-x64-msvc.node`), and by then it has already deleted the rest of
  `node_modules`. Stop the web server first, or verify in a separate worktree
  (`git worktree add --detach ../pramana-verify HEAD`, then `npm ci` there). On Nov 6 evening,
  `apps/web/node_modules` in the main checkout was left half-removed this way: run `npm ci` there
  after stopping the old `next start` on :3002.
- Accounts: `uv run python -m pramana_core.auth.bootstrap --email <e> --name <n> --roles operator`
  and another with `--roles approver`. An operator cannot approve their own repair; only an
  operator can reveal. Use a private window for the second role.
- Scripts use `CORE_AUTOMATION_KEY` from `.env` (`scripts/core_auth.py`).
- After changing contracts or API docstrings, regenerate the contracts, OpenAPI and `gen:api`
  outputs, and commit them (CI checks drift).
- Phones: `cloudflared tunnel --url http://localhost:3002`. Quick tunnels carry WebSockets but
  not SSE. Staging (above) carries both.

## Gotchas learned the hard way

- A random sealed fault combined with S1's report text makes the reporter contradict herself.
  For demos, use a Specified fault.
- Withdrawn questions vanish from a participant's page mid-answer; tests must tolerate that.
- `AudioContext.resume()` stays pending without a real user gesture.
- On Windows, heredocs with `\n` inside Python code break: write scripts to files.
- `git stash` while a test server or background job runs can change files under it.
- Running the Python suite and the real-stack browser suite at the same time slows teardown
  enough to break the 180 s M1 budget. Run heavy suites one at a time when the result matters.
- Piping a check into `tail` hides its exit code.

## Rules (do not break)

- Git: commit as darved2305, with small plain commit messages, **no AI attribution, no
  Co-Authored-By lines, and no "Day N", "phase" or "progress" wording** in commits or user-facing
  docs. Push to `main` only when the checks above pass. Do not delete existing git worktrees.
- Never commit secrets, `.env`, recordings, licensed fonts, or measured Gnani accuracy or latency
  (Gnani EULA §16). The Gnani key stays server-side.
- Honesty: no invented metrics, browser results or live-run claims. Say plainly what was not run.
- Cost and the laptop: spend as little as possible (Gnani Rs 150/day guard, free LLM tiers only);
  delete temporary files; never close the user's Arc browser; run one heavy job at a time.
- Frontend text: no em dashes in user-visible text (`npm run check:copy`).
