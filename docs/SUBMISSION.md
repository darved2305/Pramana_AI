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

**Evaluation (logic mode, simulated participants).** From
`eval/reports/benchmark-2026-11-10-heldout/summary.json` (300 scenarios; commit and seeds in the
protocol): the table below reports historical success and honest success separately for Pramana,
the checklist, random selection, greedy entropy and three-at-once Pramana. Historical success
retains RC1's pair credit; honest success excludes pair abstentions. Full pair resolution is
reported separately with its denominator. The paired p-values and Holm adjusted values below
come from the frozen analysis; only adjusted comparisons below 0.05 are described as significant.
Speech-recognition accuracy and latency are not published (Gnani EULA §16).

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
