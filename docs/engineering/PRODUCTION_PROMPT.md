# Production agent prompt: verify the plan, then build accounts, tenants and onboarding

Copy everything below the line into a fresh Claude Code session opened in this repository. The plan
it executes is [docs/PRODUCTION.md](../PRODUCTION.md). Do not paste credentials into the chat: put
keys into the untracked `.env` of the production worktree yourself, and tell the agent their names.

Short version, if you prefer: open a new session here and type
"Read docs/engineering/PRODUCTION_PROMPT.md and execute it end to end."

---

You are taking over **Pramana** to turn the hackathon build into a production system, following
`docs/PRODUCTION.md` (written 2026-11-07 against `main` at `e8194cb`; release candidate `v1.0-rc1`
is `8b24d0d`). Work autonomously through the steps below. Make routine implementation choices
yourself, preserve the user's edits, and stop only at the marked **STOP** points or when a decision
genuinely belongs to the user. Never fabricate a result to tick a box: every "done" needs a passing
test or a recorded run, with its commit or report path.

Read the actual system date first. The hackathon submission deadline is **Nov 10, 23:59 IST**
(target 14:00), and `main` was scope-frozen on Nov 7, 23:59 IST. Production work must never put the
submission at risk.

## 0. Ground rules (read before touching anything)

1. **Branch and worktree.** All production work happens on a branch named `production` in its own
   worktree, never on `main`:
   `git worktree add "../gnani ai hackathon-production" -b production main`
   (a sibling folder, like the existing `gnani ai hackathon-web` worktree; or use the EnterWorktree
   tool). Never delete or reset existing worktrees (`.claude/worktrees/agent-*`, `-web`). Do not
   merge into `main` until the user says the submission is done **and** approves the merge.
   `docs/PRODUCTION.md` and this prompt were written on Nov 7 and may still be **untracked** in the
   main worktree (check `git status` there). If so, copy both files into the new worktree and make
   them the first commit on `production`. Leave the main worktree's copies alone, and do not commit
   them to `main` unless the user asks.
2. **Isolation from the running demo.** The demo stack and its tests share the PostgreSQL cluster on
   `localhost:5433`. In the production worktree, use separate databases and ports:

   | Setting | Value in the production worktree |
   |---|---|
   | `DATABASE_URL` | `postgresql+asyncpg://pramana@localhost:5433/pramana_prod` |
   | `TEST_DATABASE_URL` | `postgresql+asyncpg://pramana@localhost:5433/pramana_prod_test` |
   | `PRAMANA_E2E_DATABASE_URL` | `postgresql+asyncpg://pramana@localhost:5433/pramana_prod_e2e` |
   | `PRAMANA_E2E_CORE_PORT`, `PRAMANA_E2E_SIM_PORT` | `8230`, `8330` |
   | `E2E_WEB_PORT`, `E2E_CORE_PORT`, `E2E_SIM_PORT` | `3122`, `8220`, `8320` |
   | Dev stack | `.\.venv\Scripts\python.exe scripts\dev.py --web --core-port 8210 --sim-port 8310 --web-port 3102` |

   `scripts/dev_db.py` creates only `pramana` and `pramana_test`. Create the three databases above
   (extend `dev_db.py` with an override if that is cleaner) and never stop, reset or drop the shared
   cluster or the demo databases. Even with separate databases, run **one heavy test suite at a
   time** across both worktrees.
3. **Windows.** Set `PYTHONIOENCODING=utf-8`. Run the dev supervisor with `.venv\Scripts\python.exe`
   directly (uv's Ctrl-Break wrapper returns 0xC000013A). `npm ci` fails with EPERM while a Next server
   holds its SWC binary: stop only the identified project server first. Do not kill unrelated
   processes, and never close the user's Arc browser.
4. **Commits.** Small, verified slices as `darved2305`, short plain messages, **no AI attribution or
   Co-Authored-By lines**, and no "Day N", "phase" or "progress" wording (project rules in
   `docs/engineering/HANDOFF.md`). No em dashes in user-visible text (`npm run check:copy`).
5. **CI.** `.github/workflows/ci.yml` runs on pushes to `main` and on pull requests. To get CI for the
   branch, open a **draft** pull request `production` → `main` titled "Production foundations (do not
   merge before the submission)". After each push, wait with `gh run watch --exit-status` and read
   `gh run list --limit 3` before saying CI is green.
6. **Money, people and secrets.** Do not create cloud resources, run `terraform apply`, place live
   Gnani calls beyond a preflight round trip, send WhatsApp, SMS or email to real people, or call a
   real phone number without the user's explicit go-ahead for that specific action. Never commit
   `.env`, keys, recordings or measured Gnani accuracy or latency (EULA §16). Keys live only in the
   untracked `.env` (local) or Secret Manager (cloud); never print them.
7. **Do not weaken what makes Pramana trustworthy:** the deterministic engine, LLMs only at the
   language boundary, separation of duties (`SELF_APPROVAL`), capabilities, presence checks, the
   sealed sandbox truth, exact replay and the log seal. If a change would alter replayed beliefs,
   bump `MODEL_VERSION` as ADR 0003 requires and say so.

## 1. Read, in this order

1. `docs/PRODUCTION.md`: the whole plan. Sections 1.4 (what is demo-only), 3 (architecture), 4
   (schema), 5 (Google sign-in), 6 (routing and the edge-case matrix) and 7 (onboarding) drive this
   session.
2. `README.md`, `docs/engineering/ARCHITECTURE_REVIEW.md`, `docs/engineering/HANDOFF.md` (its
   "Before every push" gates and "Operational rules and gotchas").
3. ADRs 0003 (event log), 0009 (SSE), 0010 (authentication), 0013 (media sockets), 0014 (presence).
4. The code paths cited in PRODUCTION.md §1.4, starting with `services/core/src/pramana_core/`
   (`main.py`, `db.py`, `settings.py`, `investigations.py`, `auth/`, `api/`, `directory.py`) and
   `apps/web/src/` (`app/login`, `app/app`, `lib/api`, `lib/data`, `lib/store`).
5. Next.js 16 is not the Next.js you remember (`apps/web/AGENTS.md`): read
   `apps/web/node_modules/next/dist/docs/01-app/01-getting-started/16-proxy.md` and
   `02-guides/authentication.md` before writing frontend auth code. Middleware is now `proxy.ts`
   (Node.js runtime only), and is only for optimistic redirects.

Then inspect `git status`, the branch, recent commits and `gh run list --limit 3`.

## 2. Verify the plan before building on it (the "check" step)

Produce a short, factual review. Fix the plan where it is wrong.

1. **Code claims.** Re-check every row of PRODUCTION.md §1.4 and every `file:line` the document cites
   against the current tree. Correct any line that moved or any claim that is wrong.
2. **Research claims that drive decisions.** Re-verify, against primary sources, the claims labelled
   [S] or [C] that the R0 and R1 designs depend on:
   - Google OIDC rules (§5.2, §5.3);
   - Cloud Run WebSocket and billing limits (§2.8);
   - the IETF idempotency draft's current revision (§2.2);
   - Sarvam's onboarding facts (§2.12);
   - DPDP dates (§2.14).

   Keep the evidence labels and record today's access date on anything re-checked.
3. **Consistency.** Make sure the schema sketch (§4.3), the edge-case matrix (§6.2) and the roadmap
   (§15) agree with each other. List anything the plan forgot.
4. Commit the corrections to `docs/PRODUCTION.md` on the `production` branch, with a short "Review
   notes, <date>" section at the top saying what changed and why.

**STOP 1: ask the user, in one AskUserQuestion batch:**

1. Start production work now on the branch, or wait until after Nov 10? Recommend: start now, on the
   branch only.
2. Cloud: GCP `asia-south1` (recommended) or AWS `ap-south-1`?
3. Which accounts and keys exist today? Multi-select: Google OAuth clients, a GCP or AWS project, a
   domain, an email provider, a Gnani production key with written limits, a paid LLM key, Exotel,
   WhatsApp BSP, SMS with DLT.
4. Product name and domain to use in the OAuth consent screen and emails.

If the user is away, continue with the defaults marked "recommend" and everything that needs no
keys. The mock Google issuer in step 4 removes the need for real OAuth keys until the very end.

## 3. R0 baseline (no cloud spend)

1. **ADRs.** Draft ADRs 0015 to 0026 from PRODUCTION.md §16 in `docs/adr/`, with status "proposed".
   Write each the way the existing ADRs are written: context, options compared, decision,
   consequences, tests. Each one names the earlier ADR it amends.
2. **Container images.**
   - One Dockerfile for the Python services (core and simulator; entrypoints selectable by command).
   - One Dockerfile for `apps/web` (Next.js standalone output).
   - Upstream URLs come from runtime configuration, not build-time rewrites (PRODUCTION.md §1.4,
     "Build-time upstreams").
   - Local development stays Docker-free (ADR 0005).
   - Add a CI job that builds both images.
3. **Infrastructure as code (no apply).** Write `infra/gcp/` (or `infra/aws/` if the user chose AWS)
   in Terraform or OpenTofu, following PRODUCTION.md §13.3:
   - load balancer, Cloud Run services (`web`, `api`, `media`, `worker`, `sim`), Cloud SQL with HA
     and point-in-time recovery, Cloud Storage, Secret Manager, KMS, Artifact Registry;
   - a log bucket in `asia-south1` with at least 180 days' retention;
   - workload identity federation for GitHub Actions;
   - CI runs `fmt -check` and `validate` only.

   **STOP 2:** before any `terraform apply`, show the user the plan output and the expected fixed
   monthly costs, and wait for an explicit yes.
4. **Exit check for R0:** images build in CI, infrastructure validates, and nothing in `main`
   changed.

## 4. R1: accounts, tenants and onboarding (the main work)

Build it as vertical slices: each one has its migration, contracts, API, UI and tests, then the gates
and a commit. Regenerate contracts, OpenAPI and `npm run gen:api` after contract changes (the drift
checks enforce it).

**Slice 1: tenancy foundation**
- Alembic 0008 onward, expand style. Tables: `organizations`, `memberships`, `sites`, `site_models`
  (store `campus_block_c` as the published sandbox model, `mode='sandbox'`), and `org_id` on every
  tenant table. Use UUIDv7 ids with type-prefixed public ids (§4.1).
- RLS with `FORCE`, and a fail-closed policy on `current_setting('app.org_id', true)`.
- `Database.transaction()` sets `app.org_id` with `set_config(..., true)` from the request's
  organization context.
- Tests:
  - every tenant table returns zero rows without a context;
  - cross-tenant writes fail `WITH CHECK`;
  - the **tenant-leak generator**: for every route in `openapi.json`, a member of org B calling org
    A's resources gets 404 or 403 and never data. It fails when a new route has no tenant test.

**Slice 2: Google sign-in in the core (§5)**
- Authlib with a configurable OIDC discovery URL. In test mode it points at a mock issuer:
  - a small in-process fake for pytest (RSA key, JWKS, token endpoint via `httpx` mock transport, as
    the Gnani emulation already does);
  - `scripts/mock_oidc.py` (a FastAPI app issuing Google-shaped ID tokens with chosen `sub`, `email`,
    `email_verified` and `hd`) for local Playwright without Docker;
  - optionally `navikt/mock-oauth2-server` as a CI service container.
- A production process refuses to start with a non-Google issuer or with `CORE_AUTOMATION_KEY` set.
- Endpoints `/v1/auth/google/start` and `/callback`, the `auth_flows` table (single use, 10 minutes),
  PKCE S256, `state`, `nonce`, and every ID token check in §5.2.
- `user_identities` keyed by `(provider, sub)`; the account-linking rules in §5.3.
- Session hardening (§5.4): rotation on sign-in, idle and absolute expiry, the `__Host-` cookie name
  whenever cookies are `Secure`, a "signed-in devices" list.
- Keep password sign-in for existing and automation accounts.
- Tests: rows ID-01 to ID-17 of §6.2 at the API level.

**Slice 3: idempotency, `/v1/me` and onboarding state (§3.6, §6.1, §7.3)**
- Idempotency middleware and the `idempotency_keys` table: 400, 409 and 422 behaviour, replay of
  stored responses, scope per organization and principal, a 72-hour reaper.
- `GET /v1/me` with the routing rules of §6.1. The `onboarding_state` table and the versioned contract
  for the three survey questions.
- `POST /v1/orgs` creates the organization, the owner membership, the sandbox site (pinned to the
  stored `campus_block_c` model) and a draft live site of the chosen kind, all idempotently.
- Tests: OR-09 (double "Create organization" gives one organization), OR-10 (two tabs), and replays
  after a lost response.

**Slice 4: organization-scoped API and no hard-coded site**
- Move routes under `/v1/orgs/{org}/...` for investigations, people (today's directory) and site
  models (read-only in R1; the builder is R2).
- Investigations pin `site_model_id`; the engine compiles from the stored spec and caches by
  `spec_sha256`.
- Remove every `campus_block_c` default listed in §1.4 (API, readiness, console, preferences). Extend
  `tests/test_authenticity.py` so product code may contain no pack, site or organization ids outside
  the preview fixtures.
- The existing investigation, replay, reveal, approval and voice tests must stay green under the new
  routes: they are the proof that the engine and its guarantees survived. Keep the event payloads'
  meaning; personal data moves out of events in R2, not now.

**Slice 5: team (§7.8)**
- Invitations: create, revoke, accept; expiry; email matching (ID-05 to ID-07).
- Member roles; the last-owner rule (OR-06).
- Domain verification from the `hd` claim and join requests with the `request` policy (ID-03).
- Auto-join stays off by default and grants only viewer (ID-04).
- Email sending is behind an interface. With no provider key yet, log the email to a local outbox file
  and say so.

**Slice 6: the frontend that makes it feel great (§7, §11)**

Keep the existing visual identity: ink and cream theme, display-slab type, `BlurText` and
`VoiceField` motion, reduced-motion support, phone-width layouts, axe-clean pages.

- `/login`: "Continue with Google" first (Google branding guidelines), email second, plain error
  states.
- `/onboarding/[step]`:
  - the three questions, each changing the next screen (§7.3);
  - "Setting up your workspace";
  - the **guided sandbox investigation**. The user plays Riya, simulated colleagues answer, the
    approver is labelled simulated, then the reveal and a four-line "What just happened" (§7.6);
  - "Now your building", which picks the template from the survey and generates a draft model, with
    the builder itself in R2;
  - "Who can help" (invitations);
  - the test call.
- `/app/[org]/...` routes with an organization switcher; `/app` redirects per §6.1.
- Empty states per §7.10 (never "nothing here" while loading).
- The **adaptive home** (§7.5): `GET /v1/orgs/{org}/home` returns ordered modules, each with a
  `reason` ("You approved 9 repairs this week"), computed by a pure, unit-tested rules function. Pins
  and hides are saved server-side.
- Server-side checklist (§7.11). Autosave and conflict dialogs for the forms touched in R1 (§6.3).
- `proxy.ts` only redirects users with no session cookie; every authorization decision stays in the
  core.

**Slice 7: the edge-case suite**
- Every ID, OR and DA row of §6.2 automated: pytest for API rows; Playwright for browser rows, using
  setup projects with one `storageState` per user state (new, invited, returning with one
  organization, returning with several, removed member, approver-only, viewer) and one account per
  parallel worker.
- Name the tests after the rows (`id-06-invite-mismatch.spec.ts`, `test_or_09_create_org_once`).

**Gates before every push** (sequential, check each exit code; from HANDOFF.md, plus the new ones):

```
uv run ruff check . && uv run ruff format --check .
uv run mypy packages/contracts/src packages/domain/src packages/engine/src services/sim/src services/core/src eval/src
uv run lint-imports
uv run python -m pramana_contracts.export --check && uv run python -m pramana_core.openapi_export --check
uv run pytest                                  # includes tests/e2e; one heavy suite at a time
cd apps/web && npm ci && npm run typecheck && npm run lint && npm run check:copy && npm run check:worklet
npm run gen:api && git diff --exit-code -- src/lib/api/schema.gen.ts
npx playwright test
npm run test:e2e:real
terraform fmt -check && terraform validate     # in infra/, once it exists
```

**Exit check for R1** (PRODUCTION.md §15):
- every ID, OR and DA row green;
- the tenant-leak generator covers 100% of routes;
- the S1, S2 and S7 sandbox flows still verify, reveal correctly and replay identically under the new
  organization-scoped routes;
- CI green on the draft pull request.

Report the onboarding timing as **not run** until real people try it. The "under 3 minutes to the
sandbox reveal" target needs five usability sessions with people, not bots.

## 5. If R1 is finished: start R2

Store site models as versioned data with publish, diff and pin; the template generator for "Hostel
block" (generalizing `campus_block_c`); CSV import; the model health check as a job running the
existing `pramana_eval` harness against a draft (§8.6); role and language catalogues replacing the
`Role` and `TemplateLanguage` enums. Same slice discipline.

## 6. Keys: ask only when a slice needs them

| When | Ask the user for | `.env` names (suggested) |
|---|---|---|
| End of slice 2, for one real sign-in check | Google OAuth client for local or staging | `GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET`, `OIDC_ISSUER=https://accounts.google.com` |
| Slice 5, real invitation email | Email provider key and a verified sending domain | `EMAIL_PROVIDER`, `EMAIL_API_KEY`, `EMAIL_FROM` |
| After STOP 2 approval | Cloud project and billing | `GCP_PROJECT_ID` (Terraform variables, never committed) |
| R3 only | Gnani production key and written limits, paid LLM key, Exotel, WhatsApp BSP, SMS with DLT | named in PRODUCTION.md §17 |

Ask the user to add values to the production worktree's `.env` themselves (for example with
`! notepad .env`), not to paste them into the chat. Confirm presence by name only.

## 7. Report and hand over

At the end of the session:

1. Write `docs/engineering/STATUS_PRODUCTION_<YYYY-MM-DD>.md` (the actual date) as an item, state,
   evidence table: what passed, what failed (with output), what is **not run**, and what waits on
   the user (keys, decisions, people).
2. Update `docs/PRODUCTION.md` where reality differed from the plan.
3. Refresh this prompt for the next session: mark finished slices, list the next one first, and keep
   the ground rules.
4. Keep "implemented", "tested locally", "CI green", "deployed to staging" and "validated with real
   people" separate. Never collapse them into "done".
