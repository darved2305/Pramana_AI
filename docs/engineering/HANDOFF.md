# Day 4 closeout and Day 5 handoff: Sun Nov 8

Pramana, branch main. This is the operational handoff for the next agent. The planned next
workday is **Sun Nov 8, 2026 (Day 5)**; use the actual session date for new evidence timestamps.
Do not label a Nov 7 run as Nov 8 or change the machine clock to reset a provider quota.

**Start a fresh session with [DAY5_PROMPT.md](DAY5_PROMPT.md).** Read this file for execution
detail and [ARTIFACT_INDEX.md](ARTIFACT_INDEX.md) for the planning sheets, research, datasets,
CSV tables, reports and private/local evidence. The factual closeout is
[STATUS_2026-11-07.md](STATUS_2026-11-07.md).

The building is simulated. Language models handle language, the deterministic Bayesian engine
decides, and humans approve physical actions. Voice bots are synthetic participants, even when
Prisma and Timbre are live. That distinction must survive into the recording and submission.

## Update, Sat Nov 7 afternoon

A second session ran the "Day 5" list a day early (system date Nov 7). Read the "Second session"
part of [STATUS_2026-11-07.md](STATUS_2026-11-07.md) first: repair recovery after a reload or
lost report, provider labelling (live Gnani versus emulator), an authenticity audit test, the
self-approval refusal, an adversarial state-machine test and the engine fix it found, a take-log
script, a release-candidate benchmark and [ARCHITECTURE_REVIEW.md](ARCHITECTURE_REVIEW.md).
Human M2, native review, staging recovery, recording takes and the LLM batch are still
**not run**. Use `scripts/take_log.py` after every take's reveal. Run preflight without
`--allow-emulated-voice` before a live take: it now fails if the core points at an emulator.

## Verified starting point

| Item | Audited state |
|---|---|
| Branch and completed implementation | main at `5102c16b7fe265b37bd475cc73143c2e1433410c` before this documentation update |
| Implementation commits | `f660b62` (voice/presence/privacy/tests/CI), `f7a490b` (repair controls, English phrases, evidence) |
| Local verification source | `f7a490b3814017afa3f1ab8e2cf1bedc014badcb`; `5102c16` adds the generated check report |
| Final local tests | 3,453 Python, 35 UI, 19 real-stack browser tests; all recorded checks exit 0 |
| Remote CI | [run 42337589482](https://github.com/darved2305/Pramana-AI-ggw_gnani-hackathon-/actions/runs/42337589482), successful for python, web and browser-real on `5102c16` |
| Memory soak | 40 minutes, 160/160 verified and correct, identical replay, no call errors; growth gates passed |
| Live voice evidence | S1 3/3 with bots; corrected English S2 successful; S7 honest passed its label, adversary failed its label; both S7 runs abstained |
| Open acceptance | Human M2, native-speaker review, real-phone/reboot/public staging validation, final human recording and the below-threshold LLM comparison |

The code and automated verification are complete for the Nov 7 handoff scope. **The entire
human/deployment acceptance list is not closed.** Do not translate "implementation complete"
into "all milestones complete." A fresh session must re-read git status and CI; this table is
historical evidence, not a guarantee that a running process or remote host is current.

## Evidence rule

Done means a passing test or recorded run, with its commit or report path. Write **not run**
for work not exercised, and preserve failures with output. Never invent metrics or call a test
flaky without a trace. After pushing, wait for gh run watch and read gh run list --limit 3 before
claiming CI is green.

## Read in this order

1. This handoff, STATUS_2026-11-07.md, then ARTIFACT_INDEX.md.
2. README.md for the actual product, limitations and run commands.
3. PLAN.md §26 (Nov 7/8), §28, §32 and Appendix A for task IDs and freeze rules.
4. DEMO.md for the briefing, scenarios, storyboard, take selection and honesty checklist.
5. STAGING.md, VOICE_ARCHITECTURE.md, GNANI_INTEGRATION.md and API_GUIDE.md.
6. ADRs 0010 (auth), 0011 (parallel/withdrawn walks), 0013 (media sockets), 0014 (presence and
   disagreement), 0007 (free LLMs) and 0012 (Evon no-go).
7. Research and benchmark documents through ARTIFACT_INDEX.md. Read NOTES before using metrics.

Working code, schemas and generated reports establish observed behavior. PRODUCT/PLAN describe
targets too. ADRs record decisions that supersede older suggestions. Research labels and its
Nov 4 access date must be retained; this handoff does not re-verify every external source.

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

The schedule is a proposed order of work, not evidence that any future item has run. The next
session is primarily validation, recording readiness and fixes found during those flows. It is
not a request to rebuild completed features or start every optional item in the old plan.

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

## Work packages for the next agent

### P0: establish a safe, current baseline

- Read git status, current branch, recent commits and the last three CI runs. Preserve any
  user edits. Fast-forward pull only when safe; inspect divergence rather than resetting it.
- Inspect listeners and project process command lines before starting or stopping services.
  The last observed local layout is in the runtime section below. A git pull does not reload
  an already running Python process or rebuild a production Next.js app.
- Run non-live preflight against the core actually used by the web app. Confirm staff roles
  and participant links with synthetic identities. Never display or copy keys into a report.
- Use existing CI and the saved full check report as the Nov 7 baseline. Run targeted tests
  for a new fix, then every pre-push gate before pushing. Do not rerun the paid rehearsals or
  40-minute soak just to reproduce evidence that already exists.

### P0: recover staging if the hosting laptop is available (D12 carryover)

1. On Nikhil's host, inspect the `PramanaStaging` task, supervisor log, child listeners, shared
   PostgreSQL readiness, tunnel connector and Worker/VPC route. Identify the failed layer
   before changing code. A 502 alone does not prove which layer failed.
2. Confirm the staging worktree and source revision. Preserve its untracked environment and
   token files. Do not delete the worktree, reset the database or reboot Darshan's laptop as
   a substitute for checking the actual host.
3. Restore public home and `/api/core/ready`, then verify staff sign-in, separate roles,
   secure cookies/CSRF, SSE delivery/resume, participant WSS, media WSS and question audio.
4. Inspect `scripts/staging-start.ps1`: it currently invokes `scripts/staging.py --fake-gnani`.
   A configured voice key or a green readiness row is not proof that the real provider is in
   use. For the live switch, inspect effective provider configuration privately, remove the
   emulator mode deliberately, keep the key server-side and verify one real voice answer.
   Update the launcher regression test if the launcher intentionally changes to live mode.
5. With the host owner controlling a real reboot, verify that logon starts the correct stack
   and public readiness returns ok again. Complete an actual phone participant flow with
   SSE and WebSocket. Desktop mobile emulation is not a physical-phone check.
6. Save generated/public-safe outcomes with source revision, actual time, mode, route and
   result. Update STAGING.md, including failures and checks still not run.

No host access: mark this work external/pending and proceed with local preparation. Do not
infer recovery from local success, migrate hosting speculatively or invent a reboot/phone run.
The existing local-plus-tunnel fallback remains usable only with an honest SSE/polling disclosure.

### P0: complete human and language validation (M2 carryover, N10)

- Have the operator arrange consenting volunteers; prepare briefings without sending messages
  to others unless explicitly authorized. Use synthetic character names and fictional data.
- Follow DEMO.md §2. Participants answer from only their own cards in separate rooms, wearing
  headphones. Check each physical device's microphone permission and a real user gesture.
- Human M2 needs three people, separate approval, repair and verification; at least two of three
  clean runs without manual rescue. The original M2 staging requirement stays pending if only
  the local fallback is available. Record the actual deployment used.
- Native speakers review pack question templates, spoken place names, presence questions and
  final captions. Record reviewer role, language, reviewed source revision and accepted edits
  privately as appropriate. Do not turn an AI review into a human review claim.
- A genuinely human-authored blind extraction set must be frozen before scoring/tuning, with
  provenance and consent. Existing sets are AI-authored and have been tuned on. If no author
  is available, retain that limitation rather than rename an old set "blind."

### P0: fix only issues reproduced in the actual flow

Test as a first-time operator, independent approver and participant. Check create steps and
validation, participant links, consent/no/later, walking and withdrawal, typed/tap/voice answers,
the reasoning accordion, Testimony, approval denial/approval, capability collection, repair,
verification, sealed reveal and replay. Confirm the UI against events and generated state.

| Symptom | Start with | Evidence required after a fix |
|---|---|---|
| Label question has colours/choices or wrong ASR hints | investigations.py PendingQuestion, voice/media.py | failing media test, honest/refusal pass, replay unchanged |
| Witness sees other evidence or hypotheses | visibility.py and auth routes | actual participant-token HTTP test, staff view remains complete |
| Stale audio after withdrawal, a bot fails silently | voice_bot_run.py, voice/call.py, voice/media.py | error/trace captured, task cleanup and withdrawal regression |
| English S2 bot uses another language | text_investigation.py NATIVE and voice_bot_run.py | phrase semantics test and honestly labelled rerun if needed |
| Repair button leads to unsupported action | ActivityPanels.tsx and request_approval | unavailable cases hidden/explained, valid breaker path still completes |
| M1 finishes assertions but times out in cleanup | tests-real/m1.spec.ts | preserve concurrent fixture teardown; two clean real-stack runs if changed |
| Public voice/stream failure | staging supervisor, Worker, Next proxy, media client | identify transport layer; do not bypass auth or reveal secrets |

These are debugging locations, not assertions that the fixed issues remain open. Grep first.
Do not remove confirmation, presence weighting, auth or replay checks to make a recording pass.

### P1: resume the free LLM batch once quota is available (N17)

- Darshan's local report has **32 completed / 68 excluded failed** episodes. The provider's
  daily-quota exhaustion sentinel is not a request or episode count.
- Keep `.cache/llm` and the exact policy prompt/model context. Do not edit llm_policy.py,
  clear/reset quota files, combine Nikhil's cache, switch models mid-report or use paid tiers.
- Run the prescribed E/D/B command once on the actual new quota day. Preserve the existing
  local report before overwriting it. Stop spending attempts after a daily-quota refusal.
- Read completed/excluded counts from the generated report/summary. Below 50 completed:
  keep the comparison uncommitted and make no performance headline. At or above 50: inspect
  paired denominators and failures, add honest NOTES and force-add only the eligible report.
- The actual saved comparison model is Groq-hosted `openai/gpt-oss-120b`. The older evaluation
  design names a proposed paid Opus baseline; do not describe that proposed model as measured.

### P0: capture the recording takes (J05, D13)

Prepare the OBS/phone layout, captions and disclosure from DEMO.md. Capture at least five S1
takes and at least two takes per longer S2/S7 scenario. Use an independent approver session;
the automation identity has both roles and is not proof of independent human approval.

Keep a private take sheet with these columns; fill measured/outcome fields from actual runs:

| Field | What to record |
|---|---|
| Identity | take ID, actual date/time, source commit, scenario, seed, local/staging/tunnel mode |
| Participants | human/bot declaration, synthetic roles, actual languages/devices, consent recorded |
| Integrity | starting commitment, investigation ID, matching reveal, replay result |
| Outcome | status before reveal, diagnosis, whether repair verified, correct on reveal or null for abstention |
| Capture | recording path, audio/caption review, selected/rejected with reason, compression labels |

Never commit video/audio, private transcripts, passwords or consent records. Keep a single
take's seal and reveal together. S7's passing and failing labels are the story: both checked
two-person variants abstain, and must not be edited into a confident switch diagnosis.
The existing `.cache/rehearsal-video/video.webm` is an automated text/tap rehearsal only.

### P1: finalize evidence on the frozen revision (N18/N19, release candidate)

- Confirm a clean, tested recording revision. Inspect existing tags before creating
  `v1.0-rc1`; do not replace a tag or imply that the old 300-case report came from a new tag.
- If refreshing the final benchmark, use the same policies and preregistered seeds, record
  actual N and commit, and write to a new output directory. Logic mode is free of Gnani calls.
  The original 500-scenario target is not fulfilled by the historical 300-scenario report.
- Keep calibration at the decided default `lambda_min_per_s = 1/60`. Do not adopt E-ask_more
  before recording; that changes question paths and would need renewed acceptance evidence.
- E beat checklist/random on the saved scenario mix; success did not significantly beat
  greedy entropy. Decision-focus ablation did not show an accuracy gain. Preserve those limits.
- N19 audio measurements, if time/credits allow, remain private. Inspect voice_eval.py and
  preflight first; never put its accuracy/latency output under committed reports.
- Do not rerun the long soak for a documentation change. Repeat it after a relevant cache,
  resource-lifetime or concurrency change, preserving the previous result and any failure.

### P0: package the outputs and produce the next closeout

- Edit the short and longer videos with faithful, native-reviewed captions and labelled time
  compression. Review every item in DEMO.md §7. Use actual report/take counts, not storyboard
  examples. Preserve synthetic-versus-human and simulated-building disclosures.
- Prepare X/LinkedIn copy, submission explanation, contribution statements and nominated-link
  placeholders. Planned posting times are targets, not posting authorization. Do not send
  messages, publish posts, upload the final demo or submit forms without explicit authorization.
- Write STATUS_2026-11-08.md with item/state/evidence, failures, actual CI result, expenses or
  quota limits where generated, and all human/host dependencies. Refresh this handoff for the
  following session. Do not call the work complete if external acceptance is still pending.

## Keep out of the immediate coding queue

| Older plan item | Current decision |
|---|---|
| Parallel planner, presence, second decode, testimony UI | Already implemented; validate or fix a reproduced defect rather than rebuild |
| D18 multiplexer | No automatic rebuild: three sessions worked; promote only if an observed cap/failure requires it |
| D19 caching versus speculation | Question audio caching/streaming exists; speculative future-question TTS and a 70% hit target are not established by current evidence |
| D20/D22 extra dashboards, QR/mic onboarding | Not an open Nov 7 coding requirement; defer unless a real demo-blocking bug fits freeze rules |
| N18 full sweeps and 60 fps / live preemption timing targets | Do not claim measured completion without reports; prioritize recording and relevant regressions |
| Evon hosting | No-go, ADR 0012; no GPU purchase or paid provider migration |
| LiveKit fallback in older PLAN text | Read ADR 0002 and VOICE_ARCHITECTURE first; the investigated plugin did not select Prisma v3.0 |
| Map drift, forecast, water pack, induction, telephony | Deferred/P2 or post-submission; not next-session feature work |

Appendix A names D18 as fallback/governor, D19 as TTS/cache and D22 as onboarding. Do not infer
their meaning from the older Sunday schedule's shorthand alone.

## Runtime snapshot and safe restart

During the handoff audit on Nov 7, the local web readiness route and both core readiness routes
returned 200; database, simulator and packs were ok. The public staging readiness route still
returned 502. Re-probe in the next session; do not treat these observations as permanent.

| Service | Last observed address / caveat |
|---|---|
| Local web | `http://127.0.0.1:3002`, production build, loopback-only listener |
| Web's core upstream | `http://127.0.0.1:8040`, confirmed in apps/web/.next/routes-manifest.json |
| Older dev core | `http://127.0.0.1:8010`, running under an older dev supervisor; not the current web upstream |
| Shared local simulator | `http://127.0.0.1:8110` |
| PostgreSQL | localhost:5433; do not stop/reset the shared cluster |
| Python process-level tests | default core/sim 8030/8130 and dedicated test database |
| Browser real-stack tests | default web/core/sim 3022/8020/8120 and dedicated database |

Do not start a second stack on occupied ports. Prefer reusing the checked local layout for
read-only/rehearsal work. A production Next build fixes its upstream rewrites at build time;
rebuild with the intended PRAMANA_CORE_URL/PRAMANA_SIM_URL before restarting it. `npm ci` needs
the project Next server stopped, or an isolated verification checkout, because of the SWC lock.
Inspect and stop only task-owned processes. Restarting a non-persisted simulator can lose its
sealed scenarios even though core events survive in PostgreSQL; preserve relevant evidence first.

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
