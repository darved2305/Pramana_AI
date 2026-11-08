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
| Slice B: site builder API | CI green | `785955c`: migration 0012, `/v1/library/*`, drafts with ETag 428/412, health, publish, discard; full suite exit 0; run 42450596071 passed |
| Slices C and D backend: people per site, workspace home, saved preferences | CI green | `75931b5` (+ format fix `a8fbd98`): migration 0013 `site_people` with forced RLS, `/v1/orgs/{org}/home` pure rules with reasons, `PATCH /v1/me/preferences`, reserved console slugs. 84 focused API tests; full suite exit 0. Run 42453588374 failed on formatting; the fix's run 42453668911 passed |
| Onboarding, workspace console, practice runs, model-driven repairs | CI green | `2f7fa34`: Continue with Google, `/onboarding/[step]` saved server-side, `/app/[org]` home, sites builder, people, investigations under workspace routes, practice on a site's own model (`practice`), `repair_options` from the site's actions, participant links carrying the workspace, general answer vocabulary. Full suite exit 0, UI 48 passed, real-stack 27 passed; CI run for `2f7fa34` passed all jobs |
| Bugs found by the browser journey and fixed | Fixed | A stale draft overwrote the editor; JSONB key order made every saved draft look unsaved; the home counted the legacy directory; the hostel-only repair dialog and decision ids; the extractor returned unknown for any non-hostel outcome |
| Team invitations, members, model health page, settings page | CI green | `090fa3b`: migration 0014 `invitations` (hashed one-time secrets, 7-day expiry, one open link per address, audit entries), `/v1/orgs/{org}/members`, published model documents carry their passed check. Full suite exit 0, UI 48, real-stack 28 (team journey included); CI passed all jobs |
| Member roles and removal, track records, workspace voice, investigations board | Tested locally | Last-owner rule and owner-only owner role with row locks and audit entries; per-person track record counted only against revealed causes and only before repairs; question audio, spoken answers and media/call sockets under the workspace boundary (socket token organization claim must match, 4403 otherwise); production voice status for signed-in people without provider address or spend; a live board by stage. Focused API tests and the real-browser team and workspace journeys pass (a workspace participant link answers on a phone-sized page); full Python suite exit 0, UI 48 passed, real-stack 28 passed |
| CSV equipment import in the site builder | CI green | `ce1051e`: `apps/web/src/lib/builder/csv.ts`; workspace real-stack journey 2 passed; run 42479734853 passed |
| Answer words per outcome | Pushed | `e86e800`: `Probe.outcome_words`, `ServicePoint.words`, passed to all extractors. ruff, mypy, API drift and focused suites pass locally |
| Pending invitations in `/v1/me` | Pushed | `ef29567`: migration 0015 adds read-only policies limited to the signed-in person's verified email; `POST /v1/invitations/accept-pending`; shown on the welcome step. Invitation, account and RLS tests pass as the restricted role; UI 48 passed. The join button has no browser journey of its own yet |
| Personal data vault, consent, erasure | Pushed | `b7ad488`: migration 0016 `person_keys`, `personal_texts`, `consents`; AES-256-GCM with one data key per person, wrapped by a master key held in the process (`PRAMANA_PII_KEY`, required in production). Cloud KMS is not wired: it replaces `MasterKey` at deployment. Directory names sealed, and for site investigations names, reports and transcripts stay out of events and rows; erasure also scrubs saved idempotent responses. `POST .../people/{id}/erase` and consent routes added. No UI for erasure or consent yet. Consent is recorded but nothing enforces it until R3 |

| New kinds of site | Tested locally | `test_new_kinds_of_site.py`, through the real core and simulator by API, under owner and restricted database roles: a hospital, an office and a metro station built from empty, each reaching the right decision for two injected faults, with exact replay and seal. Also a contradicting witness, two simultaneous faults, self-approval refused, no hostel wording, nothing personal in the log. Medical gas and nurse call equipment types added. Not driven through the browser |
| Real Google sign-in | Partly checked | First sign-in with the owner's account verified in the database on `localhost:3102`. Returning user, cancel at Google and wrong-account invitation not yet exercised on real Google |
| Chrome first-time-user review | Partial | About a quarter of the journey. Fixes: `b03c5eb`, `4b15c68`, `2c66c00` |
| Deployment | Not done | New free Supabase project (Singapore, migrated to 0016, `pramana_app` role, anon and authenticated access revoked). Cloud Run APIs enabled; no image or service. Do not apply `infra/gcp` defaults |

## Edge-case audit (PRODUCTION.md 6.2, ID/OR/DA rows)

Matched by test name and scope, not by re-reading each assertion.

| Result | Rows |
|---|---|
| Automated test found | ID-01, 02, 05, 07, 08, 09, 10, 12, 13, 14, 15, 16, 17; OR-03, 06, 09, 10; DA-01, 05 |
| Partly covered | ID-06 (address check and switch-account prompt; the masked message is not asserted in a browser); ID-11 (disabled sign-in only); OR-01, OR-02 (saved preference, no switcher journey); OR-04 (access ends; stream closing not tested for removal); OR-05 (roles change; mid-session refresh not tested); OR-08 (suggestions; slug change and redirects not built); OR-11 (self-approval refused; "Invite an approver" not tested); DA-02, DA-03, DA-06, DA-08 (server rules; banners not tested) |
| Not built | ID-03, ID-04 (domain join); OR-07 (organization deletion, R3); DA-04 (consent gate, R3); DA-07 (list pages use offset, not cursor) |

Known limit of sealing: investigation search matches ids only for sealed reports, because the
text is encrypted.

## Remaining work

Done since the morning plan: onboarding, the workspace console on organization routes, saved
preferences, people per site, the adaptive home, practice investigations on a workspace's own
model, team invitations, model health and settings pages. Still open:

- The legacy single-site console pages remain for accounts with global staff roles and their
  tests; retire them (and `DEFAULT_PACK`) once the real-stack fixtures use workspaces.
- Live investigations with real people (calls, messages, work orders) are R3; a live site can
  only be practised on, and the core says so.
- Email delivery of invitations is not built; the owner shares the one-time link themselves.
  Pending invitations show on the welcome step only, not inside a workspace.
- Real-stack browser runs have voice off (no Gnani key); workspace voice is covered by API tests
  with the Gnani protocol emulation.
- Hindi and Marathi wording everywhere new needs native review.

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
