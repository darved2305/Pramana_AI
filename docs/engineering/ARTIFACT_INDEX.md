# Pramana artifact, sheet and research index

Historical inventory audited for the Day 4 closeout and Day 5 handoff on Nov 7, 2026. Current
entry points were refreshed on 2026-11-10. Paths are relative to the repository root unless stated
otherwise. This index locates evidence; it does not turn a plan, an old research claim or an ignored
experiment into a verified implementation result.

## 1. Start here

| Artifact | Purpose / authority |
|---|---|
| docs/engineering/STATUS_2026-11-10.md | Current doc/evidence closeout, this worktree's changes, gates, and human-owned items |
| docs/engineering/STATUS_PRODUCTION_2026-11-09.md | Production status report dated 2026-11-10 in its header; filename retains the Nov 9 label |
| docs/engineering/HANDOFF.md | Historical operational handoff dated Nov 8; use only as historical context |
| docs/SUBMISSION.md | Official-form draft, readiness checklist, and award-fit evidence map |
| docs/DEMO.md | Current local walkthrough, take verification and captions templates, and offline emulator disclosure |
| eval/reports/demo-rehearsal-2026-11-10-s1/ | Generated local S1 timeline, summary, and run notes dated Nov 10 |
| docs/engineering/VOICE_PROVENANCE.md | Generated summary of committed and prose-only voice runs, with unknowns labelled |
| docs/engineering/LANGUAGE_REVIEW.md | Generated Hindi, Marathi, and Hinglish review packet; all rows unchecked |
| docs/COMPETITORS.md | Competitor notes with source dates and public-material limits |
| docs/engineering/STATUS_2026-11-07.md | Historical Nov 7 implementation closeout and evidence boundaries |
| eval/reports/verification-2026-11-07/report.md | Human-readable generated local check results |
| eval/reports/verification-2026-11-07/checks.json | Commands, source SHA, exit codes and generated test counts |
| .github/workflows/ci.yml | Actual Python, web and real-stack browser CI jobs |
| README.md | Product overview, actual capabilities, limits and run instructions |

Implementation baseline: `5102c16`. Its [CI run 42337589482](https://github.com/darved2305/Pramana-AI-ggw_gnani-hackathon-/actions/runs/42337589482)
passed all three jobs. The local check report's source is `f7a490b`; `5102c16` adds that report.
Re-read current git/CI in a new session rather than assuming this is still the latest revision.

## 2. Planning sheets and operational tables

These sheets live as Markdown tables, not separate Excel workbooks.

| Source | Sheet/table content | How to use it |
|---|---|---|
| docs/PLAN.md §25 | Contribution, effort, dependency and acceptance matrix | Understand original ownership; one agent may cover both tracks without claiming other people's human work |
| docs/PLAN.md §26 | Nov 4–10 schedule, milestones and deadlines | Read Nov 7/8 together; dates are planned work blocks, not completed runs |
| docs/PLAN.md Appendix A | D01–D23, N01–N23 and joint task catalogue | Exact task IDs, priority and original acceptance targets |
| docs/PLAN.md §29 | Risk register | Match a real trigger before invoking a contingency |
| docs/PLAN.md §30 | Original fallback matrix | Check later ADRs; the old LiveKit suggestion is not the adopted implementation |
| docs/PLAN.md §32 | Publishing/submission checklist | Prepare outputs; the checklist itself does not authorize publishing or messaging |
| docs/DEMO.md, 60-second cut | Shot list and on-screen disclosures for the committed local rehearsal | Editing target only; replace each shot with evidence from one selected take |
| docs/DEMO.md, take verification and captions templates | Same-take evidence fields, consent, synthetic labels, approver identity, and captions | Fill only from the selected take; native review remains unchecked |
| docs/engineering/STATUS_2026-11-06.md | Previous status/evidence table and evening fixes | Historical context; later evidence supersedes old counts/open items |
| docs/engineering/STATUS_2026-11-07.md | Completed/pending/failed closeout table | The Nov 7 result, including external acceptance still open |
| docs/engineering/HANDOFF.md | Next-session work packages and private take-sheet columns | Use for Day 5 execution and the actual take log |
| docs/EVALUATION.md | Policy, metric, ablation and falsification tables | Experimental design; not proof that every proposed experiment/model ran |

Local file discovery found no project `.xlsx`, `.xls` or `.ods` workbooks outside dependency,
cache and alternate-worktree directories. No Google Sheet URL was found in the repository.
Scoped connected-Drive metadata searches for Pramana/Gnani did not identify a confirmed
project spreadsheet. A similarly named folder returned no accessible children; its relationship
to this project was not established. No cloud files were changed. This is a discovery limit,
not a claim that the team owns no other sheets. Add a newly supplied sheet only after grounding
its actual file and project relationship.

## 3. Research library and provenance

| Source | What it contains | Boundary to preserve |
|---|---|---|
| docs/RESEARCH.md | Research questions, Gnani documentation log, paper notes, search/dead-end log | External pages accessed Nov 4; most papers checked at abstract level, classics may be bibliographic only |
| docs/COMPETITORS.md | Direct/adjacent products, comparison matrix, novelty and investor-source notes | Distinguishes primary verification, company claims and secondary sources; no "world first" conclusion |
| docs/USP_LAB.md | U1–U17 capability proposals, rationale, build/defer decisions and scoring matrix | Concept/build decision is not completion evidence; deferred ideas remain deferred |
| docs/PRODUCT.md | Intended product, users, safety, scientific model and scenarios | Product specification includes ambitions beyond shipped behavior |
| docs/PLAN.md | Engineering design and execution plan | Some paths, model names and fallback descriptions are historical proposals |
| docs/EVALUATION.md | Same-menu policies, metrics, statistical plan, ablations and failure analysis | Proposed paid Opus baseline and large N targets are not the actual saved free-tier comparison |
| docs/spike-gnani.md | Pointer to the integration spike and private-measurement rule | Not a public ASR accuracy/latency report |
| docs/engineering/GNANI_INTEGRATION.md | Vendor docs, package-source inspection, wire/API integration findings | Retain doc/src/test labels and dates; provider settings/limits can change |
| docs/engineering/VOICE_ARCHITECTURE.md | Adopted gateway, per-question streams, audio cache and confirmation approach | Supersedes old shared-floor/LiveKit assumptions; human validation remains open |
| docs/engineering/VOICE_SAMPLES.md | Local voice sample provenance and synthetic testing setup | MMS samples are internal synthetic test voices, not human participation or licensed final-demo material by default |
| docs/engineering/API_GUIDE.md | Staff/participant API roles and call/repair flow | Generated OpenAPI/contracts and working routes establish exact current shapes |
| docs/engineering/STAGING.md | Worker/VPC/tunnel topology, supervisor, host paths and verified/pending checks | Historic success is not current availability; Nov 7 public readiness returned 502 |

RESEARCH.md covers these families: decision-theoretic troubleshooting and decision-region
selection; noisy Bayesian active learning; LLM information seeking and abstention; end-user
fault localization/network tomography; unreliable witnesses/truth discovery; non-leading
elicitation; multi-party speech; agentic fault diagnosis; untrusted-input security; and closed-loop
discovery. Read the original labels before citing a paper's result. Full-text review of most
papers, several investor sources and some gated provider sources was not completed there.

This handoff audit inventories the saved research. It does not refresh every vendor, competitor,
programme or legal page. Recheck the relevant primary source before relying on a time-sensitive
claim for a public post, provider migration or submission. Do not replace old caveats with an
uncited current-tense assertion.

## 4. Architecture decisions to retain

| ADR | Decision / next-session implication |
|---|---|
| 0001 workspace/boundaries | Contracts/domain/engine/core/simulator stay separated |
| 0002 direct Gnani gateway | Do not switch to the older investigated LiveKit plugin without proving Prisma v3.0 support |
| 0003 event log/single writer | Preserve serialized updates and deterministic rebuild/replay |
| 0004 engine model | Decisions come from deterministic math, not a language model |
| 0005 native PostgreSQL | Shared native cluster; dedicated test databases; no reset of development/staging data |
| 0006 repair verification | Approval is not proof of a fix; fresh held-out evidence must verify it |
| 0007 free-tier LLMs | Rules first, hosted second opinion, quotas/cache; no paid model migration |
| 0008 reliability and pairs | Reliability coupling, fault pairs and open-world behavior are intentional |
| 0009 event push channel | Database-backed event resume, bounded coalescing wakeups, polling fallback |
| 0010 authentication | Separate staff roles, CSRF/session and scoped participant tokens |
| 0011 parallel calls | Cap three, conditional gain, withdrawal, and uncertainty about a withdrawn walk |
| 0012 Evon no-go | No GPU/provider purchase; revisit only with genuinely available resources |
| 0013 media socket | Participant authentication first; per-question session and paid-call guards |
| 0014 presence/testimony | Simulator alone checks expected labels; pending/failed presence discounts; disagreement explanations are staff-only |

All are under docs/adr/. Some context paragraphs describe the state when the decision was
written; use subsequent addenda/status for completed tests. The Nov 7 audit corrects ADR 0011's
stale sustained-load note, without inventing a live preemption-latency measurement.

## 5. Benchmark CSV sheets and generated reports

| Folder / table | Availability | What it supports |
|---|---|---|
| eval/reports/benchmark-2026-11-05/{episodes.csv,summary.json,report.md,NOTES.md} | Committed | 300 simulated scenarios; E/A/C/D and decision-focus/cost ablations |
| eval/reports/benchmark-2026-11-07-rc1/{episodes.csv,summary.json,report.md,NOTES.md} | Committed | Same 300 seeds on the clean release candidate commit; reproduces the Nov 5 success rates |
| eval/reports/calibration-2026-11-05/{episodes.csv,summary.json,report.md,NOTES.md} | Committed | Stopping-rule comparison; explicit Nov 6 decision keeps the default exchange rate |
| eval/reports/llm-comparison/{episodes.csv,summary.json,report.md,NOTES.md} | Local, ignored; deliberately not committed | 32 completed / 68 excluded LLM episodes; below 50 threshold, no public comparison |
| eval/reports/final_gemma/{episodes.csv,summary.json,report.md} | Local, ignored experiment | Provenance/model comparability not approved for this handoff; do not promote it to the headline benchmark or merge its cache |

The benchmark's historical E success is 84.7%, checklist 64.0%, random 56.3%, greedy entropy
83.3%. NOTES supports the advantage over checklist/random and **no significant success advantage
over greedy entropy**. It does not establish superiority to an LLM policy or an accuracy benefit
from decision focus. Do not present this as a 500-scenario run or as measured on a new release tag.

The current LLM policy source is eval/src/pramana_eval/llm_policy.py. Actual local comparison:
Groq-hosted `openai/gpt-oss-120b`, same-menu E/D/B batch, cached on Darshan's laptop. The report
renderer now exposes completed/excluded counts. The original EVALUATION design's proposed
Opus baseline was not run by this free-tier batch.

The policy configuration remains `lambda_min_per_s = 1/60`; E-ask_more was decided against
for the recording. Do not confuse an interesting measured option with an adopted product change.

## 6. Extraction datasets and report lineage

| Dataset | Current status |
|---|---|
| eval/data/extraction_set.jsonl | Development/tuned |
| eval/data/extraction_heldout.jsonl | Inspected during attribution tuning; no longer a held-out claim |
| eval/data/extraction_blind_2026-11-05.jsonl | Previously tuned; no longer blind |
| eval/data/extraction_blind_2026-11-06.jsonl | AI-authored; frozen before historical main baseline, subsequently tuned |
| eval/data/extraction_blind2_2026-11-06.jsonl | Independently AI-reviewed; subsequently tuned; not native-speaker reviewed |
| eval/data/intake_set.jsonl | Intake evaluation data; inspect its own schema/provenance before extending |

Report folders, all committed unless stated otherwise:

- eval/reports/extraction-2026-11-05-baseline/ and extraction-2026-11-05/: historical baseline/tuned outputs.
- eval/reports/extraction-blind-2026-11-05/: historical output, not a newly blind evaluation now.
- eval/reports/extraction-blind-2026-11-06/: historical pre-main rules; do not substitute it for main's baseline.
- eval/reports/extraction-blind-main-2026-11-06/{set1,set2}/: main rules before attribution tuning;
  read that directory's NOTES for source/data commits and authorship.
- eval/reports/extraction-after-attribution-2026-11-06/: root NOTES plus development, heldout,
  blind-2026-11-05, blind-2026-11-06, blind2-2026-11-06 and main-junk subreports.

Each report uses report.md/summary.json; read the mismatch details as well as scores. The two
new sets were written/reviewed by AI outside the repository. They are not human-authored blind
evidence today. No new extraction score was produced merely by writing this handoff.

## 7. Nov 7 rehearsal evidence: every result file

All paths below are under **eval/reports/demo-freeze-2026-11-07/** and are committed.
Read NOTES.md first for synthetic voices, automation approval and the honest S7 abstentions.

| File | Outcome / interpretation |
|---|---|
| text-S1-honest.json | Parallel three, separate approver-only login, verified repair, correct reveal, matching commitment/replay |
| text-S2-honest.json | Correct decision, matching commitment/replay |
| text-S7-honest.json | Label passed; abstained; matching commitment/replay |
| text-S7-adversary.json | Label failed; abstained; matching commitment/replay |
| voice-S1-1.json | Live Gnani with bots; verified/correct; three in flight; matching commitment/replay |
| voice-S1-2.json | Same acceptance, second actual take |
| voice-S1-3.json | Same acceptance, third actual take |
| voice-S2.json | Initial correct integration result, but Hinglish phrases were sent to English TTS; not English-speech evidence |
| voice-S2-english.json | Corrected English phrases; correct diagnosis and disagreement explanations; matching commitment/replay |
| voice-S7-honest.json | Honest spoken label passed; abstained; matching commitment/replay |
| voice-S7-adversary.json | Preserved failure: wrong nvr probe mapping, bot silence, no presence check |
| voice-S7-adversary-retry.json | Corrected adversary stayed at desk, failed label; abstained; matching commitment/replay |

Both checked S7 variants have only a student and guard. The remaining useful panel question
needs an electrician. Neither is evidence of a verified repair or a confident switch diagnosis.

## 8. Load, staging and verification evidence

| Folder | Contents / boundary |
|---|---|
| eval/reports/load-2026-11-06/ | NOTES, report and summary for the original ten-minute emulated run; memory flatness was unresolved |
| eval/reports/load-2026-11-07/ | NOTES, report and summary for forty minutes on f660b62; 160/160 verified/correct/replay-identical, zero call errors, sessions closed, memory gate passed |
| eval/reports/staging-2026-11-07/public-check.json | Timestamped public home/readiness 502 results; does not diagnose the failed hosting layer |
| eval/reports/staging-2026-11-07/public-check-2.json | 05:00 UTC re-probe: still 502, body from the Worker itself, so the failure is behind it (VPC service, tunnel or host) |
| eval/reports/verification-2026-11-07/{checks.json,report.md} | Sequential full local check results on f7a490b, added in 5102c16; 3,453 Python / 35 UI / 19 real-stack passes |

The load test emulates Gnani, not the simulator/core/database/call lifecycle. Its memory gate
does not prove mathematically flat RSS, unlimited capacity, real speech quality or a multi-day
leak-free workload. The core peak/end were 140.7/135.7 MB; read NOTES for slopes and cache bounds.

## 9. Private and machine-local material

| Location | Handling |
|---|---|
| .env | Server credentials/configuration; never print, commit or copy into a prompt |
| .cache/llm/ | Darshan's resumable provider cache/quota state; preserve, do not merge or reset |
| .cache/tts/ | Local question-audio cache; do not confuse it with recordings or committed evidence |
| .cache/final-checks/ | Private full check logs; generated public summary is in verification-2026-11-07 |
| .cache/ci-final.log | Saved watch output for implementation CI; re-read the remote run for current status |
| .cache/rehearsal-video/video.webm | Saved automated M1 text/tap operator-page rehearsal, not a human/live-voice final take |
| .cache/console-review/{S2-console,S7-honest-console,S7-adversary-console}.png | Local reviewed UI screenshots; final screenshots include the repair-availability correction |
| .cache/voice-*.log | Private live-provider output; do not publish speech measurements/transcripts |
| $env:USERPROFILE/pramana-voice-samples/bot | External-to-repo pre-recorded synthetic answer clips |
| recordings/, recorder/, voice-samples/ | Ignored local capture/sample locations; inspect before using, never bulk force-add |
| apps/web/test-results/ | Transient browser artifacts; another test run overwrites them |
| Nikhil's host: staging .env, tunnel token, scenario snapshot | Host-private resources documented in STAGING.md; not available from this checkout |

Local availability is not guaranteed on a fresh clone or another laptop. The audit confirmed
the saved rehearsal video and three console screenshots existed here. Recheck before referencing
them. Committed JSON/Markdown travels with git; ignored caches/recordings do not.

### Older remote branches (checked Nov 7)

`origin/nikhil/{load-test,presence-challenges,realizer-lint,voice-live-runs}` (Nov 6) hold 25
commits whose subjects are not in main. Their work was re-landed into main through the Nov 6
`land-nov6` merges under new messages (presence checks, voice race fixes, load and staging
work), and main built its own ADR 0014, `scripts/load_test.py` and template lint. **Do not
merge these branches:** their migration `0007_add_presence_token_to_question` collides with
main's `0007_add_approval_requester`, and they duplicate ADR 0014. The one piece ported is
`scripts/generate_language_review.py` (now with presence checks), which writes
`docs/engineering/LANGUAGE_REVIEW.md` for the native-speaker review.

## 10. Source and test map for the shipped changes

| Change | Source | Verification |
|---|---|---|
| Presence question kind / unsteered label media | services/core/src/pramana_core/investigations.py; voice/media.py | services/core/tests/test_media_ws.py, presence_reading test |
| Witness privacy | services/core/src/pramana_core/visibility.py | test_testimony_api.py; apps/web/tests-real/testimony.spec.ts with real tokens |
| Bot scenarios, label speech, cleanup and strict success | scripts/voice_bot_run.py | tests/test_voice_bot_run.py and saved live summaries |
| Shared English phrases | scripts/text_investigation.py NATIVE | English-turn and per-probe semantic tests in test_voice_bot_run.py |
| Status before reveal | scripts/demo_rehearse.py | services/core/tests/test_demo_rehearse.py and text summaries |
| Appropriate repair UI | apps/web/src/components/console/ActivityPanels.tsx | apps/web/tests/repair-availability.spec.ts; real S2 and M1 |
| Concurrent guaranteed teardown | apps/web/tests-real/m1.spec.ts | Two clean full real-stack runs plus final 19-test suite |
| Report denominators | eval/src/pramana_eval/__main__.py | eval/tests/test_benchmark.py report_discloses test |
| Expanded CI | .github/workflows/ci.yml | Successful implementation run with all three jobs |
| Repair recovery (reload, expiry, lost report) | investigations.py capability_for; apps/web/src/app/join/[token]/page.tsx | test_closing_loop.py; tests/e2e/test_m1.py; apps/web/tests-real/repair-recovery.spec.ts |
| Voice provider labelling | voice/gnani.py provider_of; api/voice.py; scripts/preflight.py; scripts/voice_bot_run.py | test_gnani_adapter.py; tests/test_preflight.py |
| Authenticity audit | (checks only) | tests/test_authenticity.py |
| Self-approval refusal | api/investigations.py; investigations.py decide_approval | test_auth.py; test_adversarial_state.py |
| Location after a non-first-hand walk answer | packages/engine/src/pramana_engine/engine.py observe | packages/engine/tests/test_parallel.py; benchmark-2026-11-07-rc1 |
| Adversarial state machine | (checks only) | services/core/tests/test_adversarial_state.py |
| Take sheet | scripts/take_log.py (writes git-ignored .cache/takes/) | services/core/tests/test_take_log.py |

For underlying completed features, use packages/engine/src/pramana_engine/, services/core/src/
pramana_core/{calls,runtime,voice,language}/, services/sim/src/pramana_sim/, the pack YAML and
their adjacent test suites. These existing features are not an empty implementation backlog.
