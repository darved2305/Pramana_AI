# Pramana production status, 2026-11-08

Worktree: `gnani ai hackathon-production`, branch `production`. The draft
[PR #3](https://github.com/darved2305/Pramana-AI-ggw_gnani-hackathon-/pull/3) remains unmerged.
No demo database, main worktree file or unrelated process was changed. Terraform remains unapplied.

| Item | State | Evidence |
|---|---|---|
| R0, tenancy and Google auth | Implemented | `3f0ebdc`, `5c9ecea`, `56e5bca`, `87e05bd`; details in the Nov 7 report |
| Google auth and the preceding foundations | CI green | `87e05bd`, [run 42387269258](https://github.com/darved2305/Pramana-AI-ggw_gnani-hackathon-/actions/runs/42387269258): all five jobs passed |
| Accounts and survey state | Implemented on the branch | Migration 0010; private `/v1/me` and onboarding state, partial versioned survey contract, strong ETags, 428/412 autosave behavior, membership-aware routing and removed-access recovery |
| Workspace provisioning | Implemented on the branch | One transaction creates organization, owner/operator membership, immutable stored sandbox model, sandbox site, draft live site, preferences, survey state and audit entry; owners never inherit approver |
| Safe retries | Implemented on the branch | Required scoped keys, canonical fingerprint, exact response bytes and headers, 400/409/422 behavior, committed lease, row-lock ownership, atomic response/business commit and rollback, per-investigation event keys |
| Retry retention | Implemented, scheduling not deployed | Scoped 72-hour reaper skips active locks; runs on mutations and through `scripts/reap_idempotency.py`. No global scheduled maintenance worker is claimed |
| Account/RLS/transaction checks | Tested locally | 80 passed in 341.37 s, exit 0, using owner and `pramana_app`; includes expired leases, simultaneous create, lost-response replay, revoked roles, private state, template immutability, cross-task sessions, notification timing and event-key scope |
| Python static checks | Tested locally | Ruff lint/format (197 files), mypy (92 source files), 3 import contracts and contracts/OpenAPI drift checks exit 0 |
| Web static checks | Tested locally | `npm ci`, typecheck, lint, copy, worklet and API generation exit 0; generated schema staged and drift checked |
| Terraform definitions | Tested locally | Format and validate exit 0; no apply |
| Full Python regression suite | Tested locally | 3,682 passed in 1,137.81 s, exit 0; isolated `pramana_prod_test` and `pramana_prod_e2e`, ports 8230/8330; no process-test skip |
| Current UI browser gate | Tested locally | 48 passed in 2.0 min, exit 0, port 3112 |
| Current real-stack browser gate | Tested locally | 23 passed in 2.2 min, exit 0, ports 3122/8220/8320/8420, isolated `pramana_prod_e2e`; includes mock Google and S1/S2/S7 |
| Current Slice 3 CI | CI green | `b329119`, [run 42440097131](https://github.com/darved2305/Pramana-AI-ggw_gnani-hackathon-/actions/runs/42440097131): all five jobs passed; watched with exit status 0 and run list read |
| Real Google sign-in | Tested locally with the user | User completed Google sign-in on port 3102; an aggregate-only query confirmed one Google identity, verified email and no global staff roles. The core used `pramana_app` against isolated `pramana_prod`; no tokens or profile details were logged |
| Launch budget and database provider | User decision recorded | INR 1,000/month total GCP ceiling; Supabase Free in specific Mumbai region approved, application on GCP Mumbai, no domain. GCP project access/billing linkage checked read-only; scoped Supabase setup token requested in `.env` |
| Staging/production deployment | Not run | STOP 2 remains before any cloud apply; no cloud spend or live calls/messages |
| Onboarding with people | Not run | No usability sessions; no claim against the three-minute target |
| Slice 4: investigations pinned to saved models, org routes | CI green | `c1a44e7` (Codex's work, verified and committed): full Python suite exit 0; UI 48 passed; real-stack 23 passed after `04dc29c` updated two id patterns to typed UUIDv7 ids. [Run 42448480249](https://github.com/darved2305/Pramana-AI-ggw_gnani-hackathon-/actions/runs/42448480249) passed |
| Any-site models (dependency physics, role catalogues, equipment library, builder, health check) | CI green | `36d398e`, fix `87670a7`; full Python suite exit 0 before the builder files; domain, engine and eval suites pass with them. Run 42448406787 failed on that mypy error; the fix's run 42448480249 passed |
| Health check measurements | Tested locally | Water template, 40 runs x 2 seeds: 75-95% correct, at most 7.5% wrong per tested fault. False alarms end in a fault decision 12-22% of the time. Generated retail and ward sites: at least 7/10 correct per tested fault |
| Health check finding on the demo model | Recorded, not changed | `DISPATCH_ELECTRICIAN_DB_C2` spans two breakers (`SPLIT_TARGET_DECISION`); left unchanged to keep replayed beliefs and the submission build |
| Slice B: site builder API | Tested locally, not committed at the time of writing | Migration 0012 (`source`, frozen with the version; one draft per site), `/v1/library/*`, `/v1/orgs/{org}/sites/{site}/draft` save/health/publish/discard with ETag 428/412; 54 site API and cross-org tests pass (owner and runtime roles); full suite running |
| Web builder client | Implemented | `organizationApi` draft methods, `libraryApi`, `ApiError.details/problems`; typecheck and lint pass. No pages use them yet |

## Remaining work

The console and onboarding are the largest gap. The core has `/v1/me` (with `destination`),
onboarding state, organizations, sites, models, the builder and organization-scoped
investigations, but every console page still uses the unscoped single-tenant API, four pages
default to `campus_block_c`, preferences live only in browser storage, and there is no
`/onboarding` route. The ordered plan is in PRODUCTION.md, "Any-site product conversion".
The onboarding survey's `problem` field still offers only Wi-Fi and power; widen it additively
(water, cooling, lifts, payment devices) and use it to choose the starting template.

The uncommitted stored-model loader/cache passes 26 focused checks in 18.58 s using owner and
runtime roles, plus Ruff, mypy (62 source files) and all three import contracts. Coverage includes
organization checks before cache access, different physical models sharing a legacy label,
coalesced compilation, bounded LRU eviction, retired-version recovery and a cold rebuild with
identical engine matrices. Stored field names and aliases load without changing frozen bytes or
hashes. Investigation and route integration are still pending; these changes have not been
committed, pushed or checked in CI.

A dedicated Pramana Supabase organization was created through the supplied token. Its settings
and entitlement reads return HTTP 403, so database creation remains pending the token's resource
scope. The browser/desktop host remains disconnected; the user has the official connection steps.

Slice 3 is pushed as `b329119`, with all local gates and all five CI jobs green. Slice 4 moves
tenant APIs under explicit organizations, pins investigations to stored site models, removes the
named building defaults, and adds the route-complete tenant-leak generator. The review is in
ignored `.cache/production-slice4-design.md`. Team, onboarding UI, adaptive home and the remaining
R1 browser matrix follow in Slices 5 to 7. This branch is not yet a deployable multi-tenant release.

Real Google sign-in now passes locally; its callback is
`http://localhost:3102/api/core/v1/auth/google/callback`. The real browser check used the existing
web build; regression builds used the optional `PRAMANA_NEXT_DIST_DIR=.next/verification` so the
user's sign-in server stayed available. A scripted OAuth probe was blocked by automatic approval
review, and the user completed the normal browser flow instead.

The user explicitly supplied OAuth credentials for `.env`; they were stored only there, and
rotation before deployment was advised because the secret appeared in chat. No credential values
are in this report. `GCP_PROJECT_ID` is also in `.env`. No GCP APIs or resources were enabled or
created. The selected budget architecture and primary-source review are recorded in
`CLOUD_BUDGET_REVIEW_2026-11-08.md`; the original HA defaults must not be applied.

Email can use the local outbox in Slice 5 until a provider and sending identity are configured.
Voice, LLM and telephony credentials are requested only when those integrations need them.

## Failures corrected locally

A new test initially used the nonexistent membership status `removed`; it now deletes the
membership to model removal. During iteration on the uncommitted migration, the isolated test
database still had the earlier event-key constraint. It was aligned with the revised test schema
before rerunning the full downgrade/upgrade and security checks. All 80 checks then passed. No
committed migration was rewritten, and no demo or deployed database was involved.
