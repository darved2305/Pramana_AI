# Handoff: Sun Nov 8, recording and submission preparation

Pramana, branch main. Read docs/engineering/STATUS_2026-11-07.md for the latest evidence, then
README, PLAN.md §26 (Sun Nov 8), DEMO.md and STAGING.md. The building is simulated; language
models handle language, the deterministic engine decides, and humans approve physical actions.

## Evidence rule

Done means a passing test or recorded run, with its commit or report path. Write **not run**
for work not exercised, and preserve failures with output. Never invent metrics or call a test
flaky without a trace. After pushing, wait for gh run watch and read gh run list --limit 3 before
claiming CI is green.

## What was exercised on Nov 7

- Fresh starting-main checks passed: 3,439 Python tests including process-level e2e, 32 UI tests,
  16 real-stack browser tests, static checks, contract/OpenAPI/API drift, worklet, copy and audit.
  Read STATUS for final counts and CI.
- **Live Gnani, synthetic bots:** S1 parallel 3/3 verified and correct, matching commitments and
  identical replay; S2 correct with reconciliation explanations; S7 honest label passed and
  adversary label failed. Both S7 variants **abstained**, because a remaining panel check needs
  an electrician absent from that scenario. See eval/reports/demo-freeze-2026-11-07/NOTES.md.
- Text S1/S2/S7 passed. Text S1 used a separate signed-in approver-only account. Voice bots used
  automation approval; do not claim those runs proved independent human approval.
- Presence media turns have no misleading probe choices or ASR vocabulary. Participant responses
  hide staff reconciliation explanations and other people's presence results.
- M1 contexts close concurrently in fixture teardown with a separate budget, including after
  failure. Two full real-stack runs passed before the extra S2/S7 console tests were added.
- An automated M1 text/tap video is local at .cache/rehearsal-video/video.webm. It is rehearsal
  material, not a human or live-voice take. Never commit recordings.
- Read STATUS for the completed soak, console correction, free-tier LLM batch and final checks.
- Staging / and /api/core/ready returned **502** on Nov 7. Reboot, real-phone and live-Gnani
  staging checks are **not run**. The host is Nikhil's laptop, not this one.

## Recording-day priorities

1. Pull main and run every check below. Read the latest three CI runs. Fix red checks first.
2. Restore staging on Nikhil's laptop if using it for recording. Follow STAGING.md: readiness,
   supervisor and tunnel recovery, actual reboot, a real-phone participant flow over SSE and
   WebSocket, then a voice answer after disabling the emulator and enabling live Gnani. Keep
   keys server-side. If hosting stays unavailable, use the documented local fallback and disclose
   it. Local voice rehearsals do not prove the public Cloudflare path.
3. Invite consenting volunteers using DEMO.md §2. The missing human milestone is S1 with three
   people speaking, at least 2 of 3 clean runs without manual help. Bots do not replace this.
   Do not tune timers from bot data alone.
4. **J05:** record five or more S1 takes plus S2 and S7. Keep seal and reveal in the same take,
   record seed and commit, and verify reveal and replay after every take. Never splice takes
   into one investigation. Recordings stay out of git.
5. Native speakers must review Hindi/Marathi questions and captions. Both extraction sets are
   AI-written and now tuned on; a human-authored blind set is still needed for a blind headline.
6. Edit the 60-second and three-minute cuts. Label the simulated building, real versus synthetic
   voices and every time compression. DEMO.md §7 is the publishing checklist. Do not publish
   speech measurements under Gnani EULA §16.
7. Continue LLM comparison only on Darshan's laptop, retaining .cache/llm. Do not change
   eval/src/pramana_eval/llm_policy.py or combine Nikhil's separate cached episodes. At least
   50 completed episodes are needed before committing the comparison with honest NOTES.
   Generated tables now disclose completed and excluded counts. Request counts are not episodes.
   Do not claim the planner beats greedy entropy.
8. Tag v1.0-rc1 and regenerate final benchmark claims from output on that revision. Follow
   PLAN.md for X, LinkedIn and submission. Prepare concrete publishing material; this handoff
   does not authorize posting or messaging others.

Scope freezes Nov 7 at 23:59 IST. Afterwards, only P1a finishing until Nov 8 12:00 and bug fixes.
Submission deadline: Nov 10 23:59 IST; aim for 14:00. Do not add speculative features.

## Run and rehearse

On Windows run Python directly, outside uv's signal wrapper:

    $env:PYTHONIOENCODING = "utf-8"
    .\.venv\Scripts\python.exe scripts\dev.py --web --core-port 8010 --sim-port 8110 --web-port 3002

uv run can return Ctrl-Break status 0xC000013A after dev.py stops its children.
Port 8000 is occupied on Darshan's laptop. On POSIX use uv run python scripts/dev.py --web.

Preflight and text rehearsal:

    uv run python scripts/preflight.py --url http://127.0.0.1:8010 --clips "$env:USERPROFILE\pramana-voice-samples\bot"
    uv run python scripts/demo_rehearse.py --scenario S1 --core http://127.0.0.1:8010 --sim http://127.0.0.1:8110 --report eval/reports/rehearsal-S1.json

Preflight --live spends a little on a Timbre/Prisma round trip. S1 needs
PRAMANA_APPROVER_EMAIL and PRAMANA_APPROVER_PASSWORD for an approver-only account (DEMO.md).
S2 and S7 use --scenario S2 or --scenario S7 --variant honest|adversary.
Text summaries retain status_before_reveal; reveal itself closes the investigation.

Live voice bots spend credits. Standard output contains private speech measurements; do not
publish it. Use --summary for public integration facts and retain the Rs 150/day governor:

    uv run python scripts/voice_bot_run.py --clips "$env:USERPROFILE\pramana-voice-samples\bot" --core http://127.0.0.1:8010 --sim http://127.0.0.1:8110 --parallel 3 --play --summary eval/reports/voice-S1.json

The runner also accepts S2 and both S7 variants. --variants, --think-s, --junk and --silent-p
exercise less tidy bot answers. The honest S7 bot reads its own card; the adversary never moves
to the claimed closet. Synthetic participants must remain labelled as such.

For an automated console video, set E2E_RECORD_VIDEO=1 before the real-stack M1 test.
Copy the .webm out of apps/web/test-results/ before another test run overwrites it.

Free-tier comparison:

    uv run python -m pramana_eval --n 100 --seed-start 10000 --policies E,D,B --llm-n 100 --out eval/reports/llm-comparison

## Before every push

Run heavy suites one at a time and check every exit code. Do not pipe checks into tail.
Set PYTHONIOENCODING=utf-8 on Windows. Do not skip process-level tests.

    uv run ruff check . && uv run ruff format --check .
    uv run mypy packages/contracts/src packages/domain/src packages/engine/src services/sim/src services/core/src eval/src
    uv run lint-imports
    uv run python -m pramana_contracts.export --check && uv run python -m pramana_core.openapi_export --check
    uv run pytest
    cd apps/web && npm ci && npm run typecheck && npm run lint && npm run check:copy && npm run check:worklet
    npm run gen:api && git diff --exit-code -- src/lib/api/schema.gen.ts
    npx playwright test
    npm run test:e2e:real

After pushing: gh run watch, then gh run list --limit 3. CI includes Python, UI and real-stack
browser jobs. If remote CI fails, inspect the log, fix it and rerun relevant local checks.

## Operational rules and gotchas

- Commit as darved2305, short plain messages, no AI attribution or Co-Authored-By lines.
  No "Day N", "phase" or "progress" wording in commits or user-facing docs.
- Never commit secrets, .env, recordings, licensed fonts or measured Gnani accuracy/latency.
  No em dashes in user-visible text. Never close the user's Arc browser or delete worktrees.
- npm ci fails with EPERM while a Next server holds its SWC binary and can leave dependencies
  half-removed. Stop the identified project web server first, or verify in a separate worktree.
  Do not stop unrelated apps. Do not stash files underneath running tests or services.
- Random faults combined with S1's fixed report can contradict the reporter. Use Specified
  faults for rehearsals. Participant pages must tolerate withdrawn questions mid-answer.
- AudioContext.resume() needs a real user gesture. Microphone permission is checked on each
  device; preflight cannot check it.
- Quick Cloudflare tunnels carry WebSockets but not SSE; the console polls. Staging is designed
  for both but is not currently shown available.
- Full Python and real-stack browser suites together can exhaust teardown budgets.
  The memory soak must run without other heavy work.
- Regenerate contracts, OpenAPI and npm run gen:api after contract changes.
- Keep provider keys server-side and live output private. Free-tier LLM caches stay on one laptop.
