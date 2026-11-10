# Submission draft and readiness

This document prepares the written fields reported for the official entry. It is not a record of
an external post or submission. No selected public video or post link is recorded in this repository;
external posting status is unknown. Human-owned fields stay blank until the people responsible
confirm them against the selected take and the registered form.

The public requirements reviewed on 2026-11-10 are described by the [programme page](https://www.gnani.ai/internship),
[participation terms](https://www.gnani.ai/great-indian-ai-internship-registration-form), and
[organiser challenge post](https://www.gnani.ai/resources/blogs/great-indian-ai-internship-challenge-2026).
The form shown after registration was not inspected, so reconcile this draft with the actual form
before submission.

## Project title

**Pramana: an AI that investigates what it cannot see**

## Problem

When Wi-Fi or power fails in a building without sensors, the cause may be visible only to people
already there. A student can check a phone, a guard can reach a locked closet, and a technician can
inspect a panel. Calling around takes time, people may disagree, and a consequential repair needs
authorization.

## Users

Campus IT and facilities staff investigating a physical outage, plus consenting people in the
building who can make a safe observation when asked.

## Gnani models and APIs used

- **Prisma v3.0 realtime STT** for participant WebSocket speech turns, and **Prisma v3.0 REST STT**
  for uploaded answers and the second unsteered decode used to confirm a decision-critical spoken
  answer.
- **Timbre v3.0 TTS** streams question audio over SSE. **Timbre v2.5 Poorvi** is used for Hinglish
  (`hi-en`) synthesis because v3.0 has no Hinglish voice.
- The implementation and dated live runs are documented in
  [GNANI_INTEGRATION.md](engineering/GNANI_INTEGRATION.md) and
  [VOICE_PROVENANCE.md](engineering/VOICE_PROVENANCE.md). The challenge page markets Prisma and
  Timbre v2.5; this repository's documented integration uses the versions above. Integration
  evidence does not establish speech accuracy or latency.

## Written explanation

Pramana investigates physical faults in a modeled building by asking consenting people what they
can safely observe, by voice or text. It keeps a probability over the modeled single faults, fault
pairs, no-fault case, and an open-world case. A deterministic Bayesian engine chooses the next
question based on its expected effect on the decision and the person's time. A rules-first language
extractor turns answers into evidence; an optional schema-limited language model can help interpret
an answer the rules cannot map, but it does not make the diagnosis.

The building, hidden fault, participant cards, and observations in practice mode are simulated. The
simulator keeps the fault sealed behind a published SHA-256 commitment. The core records an
append-only event history and can replay it exactly. A physical repair requires an approver who is
not the person who requested the action and a single-use capability for the named technician. New
evidence checks the repair; the system can reopen the investigation or abstain when the evidence is
not enough.

The code integrates Gnani speech services. The local practice run uses no Gnani key. Prior live
integration runs include synthetic voice bots and one documented mixed run with a team member on an
Android phone. The current reproducible local run is text mode with simulator cards, not a live
speech recording. [Fill from the take: whether the speakers were real people or synthetic voice bots.]
See [DEMO.md](DEMO.md) and the committed
[Nov 10 rehearsal timeline](../eval/reports/demo-rehearsal-2026-11-10-s1/timeline.txt) for its exact
observed sequence. See [EVALUATION.md](EVALUATION.md) for metric definitions, denominators,
caveats, and the saved reports.

**Evaluation (logic mode, simulated participants).** From `eval/reports/benchmark-2026-11-10-heldout/summary.json` (run commit `56382dc`, frozen code `cfca50bf31959f828c77936580632c9a9bf3f7ad`, seeds 40000-40299). This run completed 300 scenarios per policy with no failures. The seed conflict, smaller sample than the 500-scenario target, and unavailable LLM baseline are recorded in `eval/protocols/2026-11-10-heldout.md`. Historical success preserves RC1's pair credit; honest success does not count abstentions where pair identifiability is unknown. E's honest success was higher than the checklist and random selection after Holm correction, but not significantly different from greedy entropy or K=3. The report does not claim that E beats greedy entropy. For E, 29/40 pair episodes had a first useful action and 3/40 reached full resolution. Speech-recognition accuracy and latency are not published (Gnani EULA §16).

| Policy | Historical success | Honest success | Completed | Failed |
|---|---:|---:|---:|---:|
| E_ours | 83.3% | 80.3% | 300 | 0 |
| A_checklist | 63.0% | 57.7% | 300 | 0 |
| C_random | 60.7% | 50.3% | 300 | 0 |
| D_greedy_entropy | 84.7% | 82.0% | 300 | 0 |
| E_parallel3 | 83.0% | 78.3% | 300 | 0 |

| Policy | Pair episodes | First useful action | Full pair resolution | Resolution n |
|---|---:|---:|---:|---:|
| E_ours | 40 | 72.5% | 7.5% | 40 |
| A_checklist | 40 | 40.0% | 2.5% | 40 |
| C_random | 40 | 22.5% | 0.0% | 40 |
| D_greedy_entropy | 40 | 75.0% | 7.5% | 40 |
| E_parallel3 | 40 | 57.5% | 2.5% | 40 |

| Outcome | Comparison | Paired n | p | Holm p |
|---|---|---:|---:|---:|
| success | A_checklist | 300 | 1.72924e-15 | 6.91696e-15 |
| success | B_llm | 0 | n/a | n/a |
| success | C_random | 300 | 2.26252e-19 | 1.13126e-18 |
| success | D_greedy_entropy | 300 | 0.522397 | 1 |
| success | E_parallel3 | 300 | 0.361595 | 1 |
| probes | A_checklist | 300 | 1.46818e-49 | 7.34089e-49 |
| probes | B_llm | 0 | n/a | n/a |
| probes | C_random | 300 | 1.66514e-38 | 6.66056e-38 |
| probes | D_greedy_entropy | 300 | 4.75357e-12 | 9.50714e-12 |
| probes | E_parallel3 | 300 | 1.54863e-35 | 4.64588e-35 |
| effort_s | A_checklist | 300 | 1.43803e-50 | 7.19016e-50 |
| effort_s | B_llm | 0 | n/a | n/a |
| effort_s | C_random | 300 | 1.53253e-49 | 6.13011e-49 |
| effort_s | D_greedy_entropy | 300 | 7.22868e-13 | 1.44574e-12 |
| effort_s | E_parallel3 | 300 | 3.06103e-40 | 9.18309e-40 |

**Limits.** The committed evaluation uses a simulated building. The answer-extraction test sets
were written by AI models and have been tuned on. [Fill: number of real human runs and their
outcome, from the take sheet and `eval/reports/m2-human/` when it exists.] Native-language review
and a human-recorded public demo are not documented as complete here. No frontier LLM comparison
or real-site outcome is claimed.

## Individual contributions

Human-owned. Each person must confirm or rewrite their own line against the work they actually did.
The planned split is in `PLAN.md` section 25; the git history records implementation changes but
does not establish personal contribution or eligibility.

- Darshan: voice gateway to Gnani, call runtime, event-sourced core, recovery and replay,
  authentication, approvals and capabilities, console and participant app, staging and load
  testing. [Fill: Darshan confirms or corrects this contribution.]
- Nikhil: domain pack and physics, Bayesian engine, planner and verification, simulator scenarios,
  extraction and LLM roles, evaluation harness and benchmarks, staging host and validation runs.
  [Fill: Nikhil confirms or corrects this contribution.]
- Team members confirm names, number of members, and their eligibility directly in the registered
  form. No eligibility fact is inferred here.

## Video, post, and tags

- Public working demo/video URL: [Fill: link to the selected, verified public take.]
- LinkedIn post URL and nominated post: [Fill: actual public post URL, if used.]
- X post URL and nominated post: [Fill: actual public post URL, if used.]
- Required hashtags: `#GnaniAI` and `#GreatIndianAIInternshipChallenge`.
- Tag Gnani AI's official account on each platform. [Human: confirm the current platform handle
  before publishing; no handle is guessed here.]
- [Fill: final form submission confirmation and timestamp, if submitted.]

The take must be a working demonstration of the app and Gnani technology. Do not splice separate
investigations into one run. The building and participants must be labelled accurately, and every
spoken line, consent record, approver identity, and on-screen claim must be checked against that
take. Use the verification and captions templates in [DEMO.md](DEMO.md). Do not publish Gnani
speech accuracy or latency measurements.

## Submission readiness checklist

| Form field or requirement | State | Evidence or owner |
|---|---|---|
| Project title | Agent-ready draft | This document, title above |
| Problem | Agent-ready draft | This document, problem above |
| Users | Agent-ready draft | This document, users above |
| Gnani models and APIs | Agent-ready draft | Integration code, dated run record, and voice provenance link above |
| Written explanation | Agent-ready draft, take-dependent statements still need review | This document and `docs/DEMO.md` |
| Public working video/demo link | Human-owned, incomplete | Record, verify, publish, and paste the real link |
| Public post link and nominated post | Human-owned, incomplete | Publish on LinkedIn and/or X, then paste and nominate the actual link |
| Required hashtags | Agent-ready | `#GnaniAI` and `#GreatIndianAIInternshipChallenge` |
| Gnani account tag | Human-owned, incomplete | Confirm the official account handle on each platform |
| Individual contributions | Human-owned, incomplete | Each named person confirms their own work |
| Registration and eligibility details | Human-owned, incomplete | Enter and verify in the registered official form |
| Final submission and confirmation | Human-owned, incomplete | Submit through current organiser instructions and retain confirmation |

## Award fit and evidence

These are project-fit assessments, not claims of award eligibility, judging outcome, or completed
human evidence. The official categories and terms are linked above. An award claim belongs in the
entry only when the selected take and any personal eligibility facts support it.

| Official award criterion | Project fit and evidence | Readiness boundary |
|---|---|---|
| Code mixing | The pack contains Hinglish templates, and the voice integration routes `hi-en` synthesis to Timbre v2.5. The Nov 5 integration note documents one team-member Hinglish phone run. | Native review is unchecked; verify the chosen take's actual language and model path. |
| Regional language | Hindi and Marathi questions and UI copy exist; the generated review packet is at `docs/engineering/LANGUAGE_REVIEW.md`. | Every review row is unchecked; do not imply native-speaker approval. |
| Practical impact | The product models campus Wi-Fi and power troubleshooting and includes authorization and repair verification. The current committed rehearsal is simulated. | No real-site pilot or measured field impact is documented. |
| Creativity | The engine chooses observations across participants, models uncertainty in their reports, seals simulated truth, and can abstain. Evidence is in the engine, simulator, ADRs, and generated rehearsal. | Describe the mechanism; do not claim it is first or unique. |
| 60-second demo | The demo runbook has a 60-second shot list and a current reproducible local run. | No selected human-recorded public cut is documented. Submit only a truthful single take with take-specific verification. |
| Noisy telephonic audio | The project has a voice path and one documented mixed run with a team member on an Android phone over a tunnel. That run was not a telephone-network test. | No real telephone-noise robustness result is documented. Do not target this criterion without permitted real evidence. |
| Duo award | The repo records two planned contributors. | Team membership and eligibility are personal facts that the team must confirm. |
| Solo award | No solo-entry fact is established by repository evidence. | Human-owned; do not claim. |
| Tier 2/3 town award | No qualifying town fact is established by repository evidence. | Human-owned; do not claim. |
| Public vote | A public post and engagement link are not recorded here; external status is unknown. | Human-owned; publish truthfully and follow the official terms. |
