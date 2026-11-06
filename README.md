# Pramana: an AI that investigates what it cannot see

Pramana diagnoses physical faults (a building's Wi-Fi, power and network) that have no sensors.
It does this by asking consenting people what they can observe, by voice or text, in English,
Hindi, Marathi and Hinglish. **Language models handle language; deterministic Bayesian code makes
the decisions; humans authorise consequential actions.**

Built for the Great Indian AI Internship Challenge 2026 (Gnani AI). Product spec: `docs/PRODUCT.md`.
Engineering plan: `docs/PLAN.md`. Current status and evidence: `docs/engineering/DAY2_STATUS.md`.
Next steps: `docs/engineering/HANDOFF.md`.

## What is real, what is simulated

| Real | Simulated (and labelled as such) |
|---|---|
| The Bayesian engine, the planner, the scheduler and every number they produce | The building (`packs/campus_block_c.yaml`), its faults, and what each person "sees" |
| The API, PostgreSQL event log, exact replay, sign-in, approvals | Participants in automated tests and the voice bots (they observe only through their own simulator token) |
| Gnani Prisma v3.0 (speech recognition) and Timbre (speech), live, behind rate, concurrency and budget guards | |

The hidden fault is sealed inside the simulator service. A SHA-256 commitment is published when
the investigation is created; the core holds no key to read the fault, and the reveal (operators
only) is available only after a decision or abstention.

## How it works

1. **Domain pack and physics.** Power feeds, breakers and loads; ISP, gateway, DHCP and DNS; core
   switch, floor switches and PoE access points; per-location phone experience and indicator
   lights (`packages/domain`).
2. **Engine.** Exact posterior over single faults, fault pairs, `NO_FAULT` and an open-world
   "something not in the model" bucket. Each person's reliability per kind of observation is
   unknown and integrated out (Gauss-Jacobi quadrature), so one person's answers share it.
   Questions are chosen by decision-focused information gain per second of a person's effort; the
   engine asks only while the two-step value of information beats the effort, decides at
   `P >= 0.95`, and otherwise decides at moderate confidence or abstains and names the check that
   would help (`packages/engine`, `docs/adr/0004-engine-model.md`, `docs/adr/0008-engine-reliability-and-pairs.md`).
3. **Parallel calls.** Up to three people can be asked at once. Extra questions are chosen by
   conditional information gain given the answers already on their way, and a question in flight
   is withdrawn when another answer makes it pointless or the decision is reached
   (`packages/engine/src/pramana_engine/scheduler.py`, `docs/adr/0011-parallel-calls-go.md`).
4. **Core.** FastAPI and PostgreSQL. Events are the source of truth, with one writer per
   investigation; a startup supervisor rebuilds open investigations and checks them against the
   log. Answers become evidence through a rules-first multilingual extractor (English, Hindi,
   Marathi, Hinglish) that marks hedges and second-hand reports, flags injection attempts and never
   decides anything (`services/core`).
5. **Simulator.** A separate service holding the sealed truth. Participants are identified by
   Ed25519-signed tokens: the core signs them, the simulator verifies them with the public key
   only (`services/sim`).
6. **Voice.** A direct gateway to Gnani. A participant call rings, asks consent (logged), then asks
   question after question, each with its own Prisma v3.0 session carrying that question's
   language candidates and answer vocabulary. Barge-in stops playback, silence leads to one
   re-prompt and then release. A decision-critical spoken answer is confirmed by a second,
   unsteered decode instead of asking again. Question audio is streamed from Timbre as it is
   synthesised and cached afterwards (`docs/engineering/VOICE_ARCHITECTURE.md`,
   `docs/engineering/GNANI_INTEGRATION.md`).
7. **Closing the loop.** A decision that calls for a repair needs an approver's approval (never
   the operator who asked) and a single-use capability token for the named electrician; the
   simulator refuses anything else. The engine then verifies the fix by belief: answers after the
   repair are read in a "fixed" and a "not fixed" world, and P(fixed) must reach 0.97 from new
   evidence; otherwise the investigation reopens (`docs/adr/0006-repair-verification.md`).
8. **LLMs translate, never decide.** Rules extract answers first; a free-tier LLM gives a
   schema-limited second opinion only when the rules cannot map an answer
   (`docs/adr/0007-free-tier-llms.md`).

## What works today (with evidence)

| Capability | Evidence |
|---|---|
| Text investigation end to end: decision, approval, repair, verification, reveal, byte-identical replay | `tests/e2e/test_m1.py` (real sim and core processes, including a hard crash mid-investigation), `apps/web/tests-real/m1.spec.ts` |
| Console for operators and approvers: live events (with a polling fallback), causes, plan reasoning, evidence ledger, approvals, replay, participant directory, evaluation reports | `apps/web/tests-real/console.spec.ts` |
| Participant page from a personal link: only their own question, simulated surroundings, tap, text or voice answers, incoming call with consent | `apps/web/tests-real/call.spec.ts`, `live-only.spec.ts` |
| Parallel calls with withdrawal | `packages/engine/tests/test_parallel.py`, `services/core/tests/test_parallel_calls.py`, `apps/web/tests-real/parallel.spec.ts`; live run with three voice bots on Gnani (correct, verified, replay identical) |
| Voice on live Gnani: three open-source voice bots, and one real person on a phone over a free tunnel, each reached a verified, correct repair | `scripts/voice_bot_run.py`, `docs/engineering/STAGING.md` |
| Streamed question audio (Timbre SSE), cached for reuse | `services/core/tests/test_media_ws.py`, `apps/web/tests/streamed-audio.spec.ts` |
| Sign-in with server sessions, operator and approver roles, CSRF header, join tokens kept out of URLs | `docs/adr/0010-authentication.md`, `services/core/tests/test_auth*.py` |
| Presence checks (S7): a decisive answer from a restricted place someone walked to is confirmed by reading a label only someone there can see; the core never learns the value | `docs/adr/0014-presence-checks-and-disagreements.md`, `services/core/tests/test_testimony_api.py` (honest people pass, liars fail and the decision stays right or the engine abstains) |
| Disagreements explained (S2): how likely both people are right, who is likelier mistaken, and what only one of them depends on ("room 205 is also covered by Access point 2B") | `packages/engine/tests/test_testimony.py`, `apps/web/tests/testimony.spec.ts` |
| Spoken questions read codes the way people say them ("IDF-2" as "I D F 2", "आई डी एफ़ टू" in Hindi); a linter checks every spoken text in all four languages | `services/core/tests/test_template_lint.py` |

Tests: 1,563 Python tests (unit, property, protocol emulation, end to end), 31 browser UI tests
and 16 browser tests against a real core, simulator and PostgreSQL. CI runs both stacks.

## Results so far (simulated building, logic mode)

From generated reports only; nothing below is typed by hand.

- **Benchmark** (`eval/reports/benchmark-2026-11-05/`, 300 scenarios): our planner succeeds in
  84.7% of scenarios against 64.0% for a checklist and 56.3% for random questions, with about half
  as many questions (differences significant). It is **not** significantly better than greedy
  entropy (83.3%). Where nobody present can tell the causes apart it abstains 68% of the time.
- **Parallel calls** (ADR 0011): asking up to three people at once cuts the simulated time to a
  conclusion by about a third with no significant change in success, at the cost of about two
  more questions per investigation.
- **Stopping-rule calibration** (`eval/reports/calibration-2026-11-05/`): abstaining more is not
  possible without losing accuracy; valuing people's time at half would raise success by 2.7
  points (significant) for 0.37 more questions. Not adopted yet.
- **Extraction** (`eval/reports/extraction-blind-2026-11-05/`): on a fresh blind set the rules got
  60 of 80 fully right, with no wrong outcomes and 2 invented answers (both since fixed). That set
  has since been tuned on, so a new blind set is needed before quoting accuracy.
- **LLM policy comparison**: in progress on the free tier (22 of 100 LLM episodes so far); too
  few to report yet.

Under the Gnani EULA, measured speech-recognition accuracy and latency are kept private.

## Run it

Requires Python 3.11+, [uv](https://docs.astral.sh/uv/), Node 20+, and a native PostgreSQL 15+
(Docker is not needed).

```bash
uv run python scripts/dev_env.py                # once: .env with fresh keys (add GNANI_API_KEY for voice)
uv run python -m pramana_core.auth.bootstrap --email you@example.com --name You --roles operator
uv run python -m pramana_core.auth.bootstrap --email approver@example.com --name Approver --roles approver
```

Start the stack with the project Python directly on Windows. `uv run` can report its own
Ctrl-Break status `0xC000013A` after the services have stopped:

```powershell
.\.venv\Scripts\python.exe scripts\dev.py --web --core-port 8010 --sim-port 8110
```

On macOS or Linux, use:

```bash
uv run python scripts/dev.py --web
```

Use `--core-port`, `--sim-port` and `--web-port` if a port is taken. With `make`: `make setup`,
`make dev`, `make dev-web`, `make check`, `make e2e`. The `make dev` and `make dev-web` targets
select the direct project Python on Windows and `uv run` on POSIX.

Then open http://localhost:3002, sign in, and create an investigation (choose "People asked at
once" for parallel calls). Open each participant's link from **Participant links** and answer from
their "What you can see here (simulation)" card. Phones need HTTPS: see `docs/engineering/STAGING.md`.

Checks:

```bash
uv run pytest                                   # all Python tests (PRAMANA_SKIP_E2E=1 skips the process-level ones)
uv run ruff check . && uv run mypy packages/contracts/src packages/domain/src packages/engine/src services/sim/src services/core/src && uv run lint-imports
cd apps/web && npm run typecheck && npm run lint && npx playwright test && npm run test:e2e:real
uv run python -m pramana_eval --n 300 --seed-start 10000 --out <dir>   # benchmark (logic mode)
uv run python scripts/voice_bot_run.py --clips <dir> --parallel 3     # voice bots on live Gnani (spends a few rupees)
```

The API is described in `docs/engineering/API_GUIDE.md` and `services/core/openapi.json`.

## Repository

```
packages/contracts   Pydantic contracts (source of truth), JSON Schema bundle, token format
packages/domain      domain pack schema and validator, site physics
packages/engine      belief, value of information, stopping rule, parallel scheduler (pure numpy)
services/sim         simulator service with the sealed truth
services/core        API, event store, call runtime, language layer, Gnani adapters, Alembic
apps/web             Next.js console and participant pages
eval                 benchmark harness, policies (including the LLM policy), extraction sets and reports
packs/               campus_block_c.yaml
scripts/             dev stack, voice bots, live Gnani checks, text runs
docs/                product docs, docs/engineering, docs/adr
```

## Known limits

- One simulated building (94 possible causes); real buildings are messier, and the open-world
  bucket only partly covers that.
- Few real human testers so far. Three calls for ten minutes passed with Gnani emulated
  (`eval/reports/load-2026-11-06/`); not yet repeated on live Gnani, and memory over longer runs
  is not yet shown to be flat.
- No hosted deployment yet: the stack runs on a laptop, and phones reach it over a Cloudflare
  quick tunnel (which carries no server-sent events, so the console polls).
- The extractor is rule lists plus an LLM fallback; it needs a fresh blind evaluation.
