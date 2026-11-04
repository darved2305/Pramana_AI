# Pramana — an AI that investigates what it cannot see

Pramana diagnoses physical faults (a building's Wi-Fi, power, network) that have no sensors. It does
this by asking consenting people what they can observe. **Language models handle language;
deterministic Bayesian code makes the decisions; humans authorise consequential actions.**

Built for the Great Indian AI Internship Challenge 2026 (Gnani AI). Product spec: `docs/PRODUCT.md`.
Engineering plan: `docs/PLAN.md`.

## What is real, what is simulated

| Real | Simulated (and labelled as such) |
|---|---|
| The Bayesian engine, the planner and their numbers | The building (`packs/campus_block_c.yaml`), its faults, and what each person "sees" |
| The API, database, event log and replay | Participants in automated tests (they observe only through their own simulator token) |
| Gnani Prisma v3.0 and Timbre, verified live, behind rate, concurrency and budget guards | |

The hidden fault is sealed inside the simulator service. A SHA-256 commitment is published when
the investigation is created; the core holds no key to read the fault, and the reveal is
available only after a decision or abstention.

## How it works

1. **Domain pack → physics.** Power feeds → breakers → loads; ISP → gateway → DHCP/DNS; core
   switch → floor switch → PoE access points; per-location phone experience and indicator lights
   (`packages/domain`).
2. **Engine.** Exact posterior over single faults, plus `NO_FAULT` and `OPEN_WORLD`. Questions are
   chosen by decision-focused information gain per second of human effort. The engine asks only
   when the two-step value of information beats the effort; it decides at `P ≥ 0.95` and
   otherwise decides at moderate confidence or abstains with what would help
   (`packages/engine`, `docs/adr/0004-engine-model.md`).
3. **Core.** FastAPI and PostgreSQL. Events are the source of truth, with one writer per
   investigation. Answers are converted into evidence by a narrow multilingual extractor
   (English, Hindi, Marathi, Hinglish) that flags injection attempts and never makes decisions
   (`services/core`).
4. **Simulator.** A separate service holding the sealed truth. Participants are identified by
   Ed25519-signed tokens: the core signs them, the simulator verifies them with the public key
   only (`services/sim`).
5. **Voice.** A direct gateway to Gnani Prisma v3.0 and Timbre
   (`docs/engineering/VOICE_ARCHITECTURE.md`, `docs/engineering/GNANI_INTEGRATION.md`).
6. **Closing the loop.** A decision that calls for a repair needs a human approval and a
   single-use capability token for the named electrician; the simulator refuses anything
   else. Then the engine verifies the fix by belief: answers after the repair are read in a
   "fixed" and a "not fixed" world, and P(fixed) must reach 0.97 from new evidence
   (`docs/adr/0006-repair-verification.md`).
7. **LLMs translate, never decide.** Rules extract answers first. A free-tier LLM (Gemini
   Flash-Lite) gives a schema-limited second opinion only when the rules cannot map an answer
   (`docs/adr/0007-free-tier-llms.md`).

## Run it

Requires Python 3.11+, [uv](https://docs.astral.sh/uv/), and a native PostgreSQL 15+ (Docker is
not needed).

```bash
make setup        # uv sync + .env with fresh keys (add GNANI_API_KEY to .env for voice)
make dev          # PostgreSQL :5433 + migrations + simulator :8100 + core :8000; Ctrl+C stops all
make dev-web      # the same, plus the console on :3002
make run-text     # in another terminal: one full sealed investigation, simulated participants
make check        # lint, types, import isolation, all tests
make e2e          # M1 acceptance against real sim + core processes (ports 8030/8130)
```

Without `make` (for example on Windows): `uv run python scripts/dev.py [--web] [--core-port N]
[--sim-port N]` does the same as `make dev`. The services can also be started one at a time:
`make db-up`, `make migrate`, `make sim`, `make core`.

`make e2e` (`uv run pytest tests/e2e`) starts the simulator and the core as separate processes on
a dedicated `pramana_e2e` database (created if missing, re-migrated on every run) with fresh
keys, then plays scenario S1 over HTTP: participants answer through their own simulator tokens,
the engine must dispatch the electrician in at most 6 questions, the repair goes through
deny/approve, a single-use capability and verification, the event log must replay to the same
belief byte for byte, and a hard crash of the core mid-investigation must lose nothing. The
tests also run as part of `make test`; set `PRAMANA_SKIP_E2E=1` to skip them.

Main endpoints: `POST /v1/investigations`, `GET /v1/investigations/{id}`,
`POST /v1/investigations/{id}/answers`, `POST /v1/investigations/{id}/reveal`,
`GET /v1/investigations/{id}/events?after_seq=`, `GET /v1/investigations/{id}/questions/{qid}/audio`,
`POST /v1/investigations/{id}/answers/voice`, `POST /v1/voice/stt`, `POST /v1/voice/tts`,
`WS /v1/voice/stream`, `GET /v1/voice/usage`, `GET /health`, `GET /ready`.

Approvals: `POST /v1/investigations/{id}/approvals`, `.../approvals/{aid}/decision`,
`.../approvals/{aid}/capability?participant_id=`, `POST /v1/investigations/{id}/interventions`.

`make run-text` plays an investigation in text; add `--repair` for approve, reset and verify. `uv run python scripts/run_text_investigation.py --voice`
speaks every turn through Gnani, and spends credits.

## Repository

```
packages/contracts   Pydantic contracts (source of truth) + JSON Schema bundle + token format
packages/domain      domain pack schema/validator, site physics
packages/engine      belief, value of information, stopping rule (pure numpy)
services/sim         simulator service with sealed truth
services/core        API, event store, runtime, language layer, Gnani adapters, Alembic
packs/               campus_block_c.yaml
scripts/             dev_db.py, dev_env.py, run_text_investigation.py
docs/                product docs, docs/engineering, docs/adr
```

## Status

The backend, the engine and the simulator are implemented and tested. The current state:

- **Frontend:** being built separately.
- **Voice:** push-to-talk spoken investigations work live. Full-duplex calls with barge-in are
  not built yet.
- **Benchmark:** `python -m pramana_eval --n 300 --seed-start 10000 --out <dir>` compares our
  planner with a checklist, random questions, greedy entropy, ablations and LLM policies
  (Groq, Gemini). Results go to `summary.json` and `report.md`.
- **Not yet built:** two-fault diagnosis, and full-duplex voice calls with barge-in.
