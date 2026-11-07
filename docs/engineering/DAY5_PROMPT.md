# Day 5 agent prompt: recording readiness and evidence-backed finishing

Copy the entire prompt below into a fresh session opened in this repository. The detailed
handoff is [HANDOFF.md](HANDOFF.md); the complete artifact/research map is
[ARTIFACT_INDEX.md](ARTIFACT_INDEX.md). Do not paste credentials, raw voice logs or private
recordings into the new session.

---

You are taking over Pramana for the Great Indian AI Internship Challenge. Work autonomously
through the authorized next-session tasks. Complete routine implementation choices without
repeated permission questions, preserve user edits, and continue independent work when human
or hosting access is unavailable. Do not fabricate completion to fill an acceptance checkbox.

The planned workday is **Day 5, Sun Nov 8, 2026**. Read the actual system date: do not relabel
earlier runs, reset clocks or provider quota counters, or treat a planned schedule as an actual
recording. The build deadline in the project plan is Nov 10 at 23:59 IST, with a 14:00 target.

## Read first

1. docs/engineering/HANDOFF.md, including its runtime snapshot and detailed work packages.
2. docs/engineering/STATUS_2026-11-07.md and ARTIFACT_INDEX.md.
3. README.md; docs/PLAN.md §26, §28, §32 and Appendix A; docs/DEMO.md.
4. docs/engineering/STAGING.md, VOICE_ARCHITECTURE.md, GNANI_INTEGRATION.md and API_GUIDE.md.
5. ADRs 0010, 0011, 0013, 0014, 0007 and 0012; research/report NOTES through the artifact index.

Inspect git status, branch, recent commits and remote CI before modifying anything. The
completed implementation baseline is main at **5102c16**, whose CI run **42337589482** passed
python, web and browser-real. Subsequent documentation commits may exist: inspect the actual
tree instead of resetting to that SHA. Local verification on f7a490b recorded **3,453 Python,
35 UI and 19 real-stack browser passes**, plus every static/drift/security/audit gate.

## System and completed work

The building and faults are simulated. Gnani Prisma/Timbre voice integration is real. The
deterministic Bayesian engine selects questions and decisions; LLMs handle language. Actions
need approval and a scoped participant capability; replay and reveal are essential invariants.

Already complete: parallel scheduling/withdrawal, presence checks, testimony explanations,
second-decode confirmation, question audio caching/streaming, auth/roles, repair verification,
participant privacy, the console and automated end-to-end flows. Nov 7 hardened presence-media
metadata/ASR hints, bot cleanup and scenario support, English answer phrases, repair availability,
M1 teardown, report denominators and CI. Grep before building: do not reimplement these.

Saved evidence: live-Gnani bot S1 **3/3**, corrected English S2, honest/adversary S7 label results,
text rehearsals, and a **40-minute emulated soak with 160/160 verified/correct/identical replays**.
The load growth gates passed; that is not proof of zero leaks under every workload. Both checked
S7 variants **abstained** because no electrician could answer the remaining useful panel check.
Bot runs do not satisfy three-human M2. The saved video is automated text/tap, not a human take.

## Execute in priority order

1. **Baseline/runtime:** preserve edits, safely update main, read gh run list --limit 3, inspect
   listeners and source revisions, and run non-live preflight against the web's actual core.
   Last observed local web 3002 proxies to **8040**, simulator 8110. An older core also listens
   on 8010. Do not kill unrelated processes or assume healthy means freshly loaded code.
2. **Staging carryover if access exists:** diagnose the actual failing layer on Nikhil's host.
   The public URL returned 502. The ONLOGON launcher currently selects --fake-gnani. Verify
   public readiness, roles/CSRF, SSE/resume, participant/media WSS and streamed audio; deliberately
   switch provider mode, then verify a real answer, an actual phone and logon after a real reboot.
   Never reboot this laptop as a substitute or describe emulator traffic as live Gnani. Without
   host access, record pending/external and use the disclosed local fallback for independent work.
3. **Human/language acceptance:** prepare briefings and recording setup for consenting people.
   Have humans complete S1 with independent approval, repair/reveal/replay, at least 2/3 clean
   runs. Check device mic permissions manually. Native speakers review Hindi/Marathi questions
   and captions. Existing extraction sets are AI-authored and tuned; no new blind/human claim.
4. **Bug fixes only:** walk through the product as a first-time operator, approver and participant.
   Reproduce any issue with a failing test, make the smallest correction, and retest the actual
   flow. Preserve presence weighting, role separation, withdrawal handling, capabilities and
   deterministic replay. Do not weaken safeguards or script a fake success for the video.
5. **Free LLM batch:** only on Darshan's existing cache, once quota is genuinely available.
   Use the exact E/D/B command in HANDOFF.md. Current report is **32 completed / 68 excluded**;
   keep comparison uncommitted below 50 completed. Preserve prompts/model and quota guards;
   no paid tier, reset or merged Nikhil cache. Actual B is Groq-hosted openai/gpt-oss-120b,
   not the proposed paid model in the old evaluation design.
6. **J05 recording:** at least five S1 takes and two per longer S2/S7 scenario, with actual
   human/bot mode, commit, seed, investigation, commitment, outcome and replay in a private
   take sheet. Keep seal/reveal in one take, separate approval roles, label time compression,
   and preserve honest S7 abstention. Recordings and transcripts never go into git.
7. **Frozen evidence:** inspect existing tags, prepare a tested v1.0-rc1 without replacing tags,
   and regenerate only the needed free logic benchmarks with actual N and source SHA. Read
   report NOTES before wording claims. Do not claim success superiority over greedy entropy,
   a frontier-LLM result that was not run, or that the old 300-scenario report used 500 cases.
   Keep the adopted calibration default at 1/60. Internal audio evaluation stays private.
8. **Deliver:** prepare the short/long edit, captions, submission explanation and contribution
   statements. Use DEMO.md's honesty checklist. Write STATUS_2026-11-08.md with actual results,
   failure evidence and remaining dependencies, then refresh the handoff. Draft publishing
   material, but do not send messages, publish posts/upload the final video or submit forms
   without explicit user authorization.

## Scope, cost and source discipline

Scope freezes Nov 7 23:59; after that only P1a finishing until Nov 8 noon and bug fixes. No new
P2 forecast/map-drift/induction/domain packs, speculative dashboards/onboarding, paid Evon hosting
or architecture rewrite. D18 multiplexer is not required merely because it appears in a plan;
three simultaneous sessions already worked. Read the adopted voice ADR before an old fallback.

Research documents retain Nov 4 source dates and abstract/company-claim labels. Do not convert
them into newly verified facts or novelty claims. The artifact index distinguishes committed
CSV/report tables, local ignored experiments, datasets and private caches. No confirmed cloud
project sheet was discovered; do not guess a Google Sheet ID or promote unrelated material.

Keep the Rs 150/day voice governor and free LLM limits. Never commit .env, keys, recordings,
licensed fonts or measured Gnani accuracy/latency. Use voice_bot_run.py --summary for public
integration facts; stdout and --report contain private speech information. Never close the
user's Arc browser, delete existing worktrees, reset the shared database or stash under a job.

## Checks and definition of done

Run targeted regressions first. Before any push, execute every gate in HANDOFF.md, checking
each exit code, with heavy suites sequential. Full pytest includes tests/e2e. On Windows set
PYTHONIOENCODING=utf-8 and use .venv\Scripts\python.exe scripts\dev.py for the dev supervisor;
uv's Ctrl-Break wrapper can return 0xC000013A. Stop only the identified project Next server before
npm ci, or verify in an isolated checkout, to avoid the SWC lock.

Push only verified changes to main, using short plain commits as darved2305, with no AI
attribution or Co-Authored-By. Wait for the new run with gh run watch --exit-status and read
gh run list --limit 3 before saying CI is green. Existing green CI is not proof for new code.

Every completed task needs a passing test or actual run plus commit/report path. Preserve
failed runs, write not run when appropriate, and distinguish local, public staging, emulated
provider, live provider, synthetic participant and real human. If human or host access is still
missing, report that precisely and finish the useful independent work. Do not claim all
acceptance milestones complete merely because implementation and automated CI pass.
