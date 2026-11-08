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
| Current Slice 3 CI | Pending | Local gates must finish before the slice is committed and pushed |
| Real Google sign-in | Tested locally with the user | User completed Google sign-in on port 3102; an aggregate-only query confirmed one Google identity, verified email and no global staff roles. The core used `pramana_app` against isolated `pramana_prod`; no tokens or profile details were logged |
| Launch budget and database provider | User decision recorded | INR 1,000/month total GCP ceiling; Supabase Free in specific Mumbai region approved, application on GCP Mumbai, no domain. GCP project access/billing linkage checked read-only; scoped Supabase setup token requested in `.env` |
| Staging/production deployment | Not run | STOP 2 remains before any cloud apply; no cloud spend or live calls/messages |
| Onboarding with people | Not run | No usability sessions; no claim against the three-minute target |

## Remaining work

Slice 3 local gates passed. Commit and push it, then watch CI and inspect the run list. Slice 4 moves
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
