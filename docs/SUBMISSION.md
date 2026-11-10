# Submission draft

A draft for the written explanation the submission form asks for (PLAN.md §32), and a check
of the post drafts in DEMO.md §8. Nothing here has been posted or submitted. Fill the marked
gaps from the actual recording take and the take sheet, never from this draft.

## Written explanation (draft)

**Problem.** When Wi-Fi or power fails in a building, the person responsible usually cannot
see what is wrong. Sensors are rare in Indian campuses and offices, and the people who could
look (a student in a room, a guard with the closet keys, an electrician) speak different
languages and have limited time. Calling around takes long and the answers conflict.

**Users.** Campus IT and facilities staff on duty, and the people already in the building who
can look at something when asked.

**What Pramana does.** It keeps a probability over every cause a model of the building allows
(single faults, pairs of faults, no fault, and "something not in the model"). It picks the
next question by how much it would change the right decision per second of a person's time,
calls that person in their language, reads their spoken or typed answer as evidence with an
estimate of how reliable they are, and stops when it knows what to do or when nobody present
can tell the causes apart (then it says which check would help). A physical repair needs an
approver who is not the person who asked, and a single-use capability for the named
electrician. After the repair it checks, from new answers, that the fault is actually gone.
Language models only translate; deterministic code makes every decision; every decision can
be replayed byte for byte from the event log, and the log is sealed at the reveal.

**What is real and what is simulated.** The building, its faults and what each person can see
are simulated (one pack, `packs/campus_block_c.yaml`). The hidden fault is sealed in a
separate service with a published SHA-256 commitment and revealed only at the end. The
engine, planner, API, event log, approvals, and the Gnani speech services are real.
[Fill from the take: whether the speakers were real people or synthetic voice bots.]

**Gnani technology used and why.**
- **Prisma v3.0 realtime STT** (`wss://.../stt/v3/stream`), one session per question, with that
  question's language candidates (English, Hindi, Marathi, Hinglish code-mixing) and the
  answer's vocabulary as keyterms, so short answers like "breaker neeche hai" are heard in
  context. Barge-in stops question playback; silence gets one re-prompt.
- **Prisma v3.0 REST STT** (`POST /stt/v3`) for uploaded answers and for a second, unsteered
  decode that confirms a decision-critical spoken answer without asking the person again.
- **Timbre v3.0 TTS**, streamed over SSE (`/api/v1/tts/sse`) so a question starts playing
  while it is synthesised, and cached for reuse; **Timbre v2.5** for Hinglish (code-mixed) questions.
- Every call goes through a governor (rate, concurrency, Rs 150 daily budget priced before
  sending).

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

**Limits.** One simulated building. The answer-extraction test sets were written by AI models
and have been tuned on. [Fill: number of real human runs and their outcome, from the take
sheet and `eval/reports/m2-human/` when it exists.] The LLM policy comparison has too few
completed episodes to report.

**Team contributions.** [Each person confirms or rewrites their own line against what they
actually built. The planned split is PLAN.md §25; git history is the record.]
- Darshan: voice gateway to Gnani (per-question Prisma sessions, barge-in, second decode,
  streamed and cached Timbre), call runtime, event-sourced core with recovery and replay,
  authentication, approvals and capabilities, console and participant app, staging and load
  testing. [confirm]
- Nikhil: domain pack and physics, Bayesian engine, planner and verification, simulator
  scenarios, extraction and LLM roles, evaluation harness and benchmarks, staging host and
  validation runs. [confirm]

## Check of the post drafts (DEMO.md §8)

Each line must be true for the take that is posted. Mark it before posting.

| Draft claim | True only if |
|---|---|
| "Watch it find a hidden fault across Marathi, Hindi & Hinglish" | the selected take actually used those languages (take sheet) |
| "Real people, voices and reasoning" | the take's participants were people, not bots; otherwise say "synthetic voices" |
| "Then it verified with a prediction it hadn't used: the recorder must be rebooting" | that verification question appears in the take's event log |
| "Why it asked a guard about the CCTV" | the guard was asked about the NVR screen in that take |
| "It never acts on its own: an authorized human approves every action" | the approver in the take was a separate approver account (automation is not) |
| Any benchmark number | it is copied from `summary.json` with its commit, and greedy entropy is not claimed to be beaten |
| Nikhil's planned interview line "a benchmark against a frontier-LLM policy" (PLAN.md §25) | **not true as of Nov 7**: no frontier model was run; the free-tier comparison is below its threshold. Do not use it |

Also from DEMO.md §7: "Simulated building" on screen in the first 3 s; time compression labelled;
seal and reveal in the same take; no real names, numbers or IDs on screen; no Gnani accuracy
or latency figures.
