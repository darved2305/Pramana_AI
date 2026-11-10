# Pramana production status, 2026-11-10

Updated after fetching origin and reading the Nov 9-10 build, audit, fix, landing, and live deployment reports. All six feature branches A-F and the G deployment changes are on production. The live stage was deployed from ed3e3cd after the migration, credential and canonical-host fixes. This report is a subsequent documentation-only change.

The stage is team-only. No real personal data, Google sign-in, email, live calls, or messages were used. The live migration and production code are at revision 0022.

## Production history

| Work | Production commit |
|---|---|
| Consent and quiet-hours controls (E) | 2d0fcd5, Merge consent and quiet-hours controls; 3b3b03b, Chain consent migration after personal data |
| Verified domain joining (D) | abb88ea, Merge workspace domain joining |
| Budget-aware deployment preparation (B) | 46ec7f1, Merge budget aware deployment preparation; 54d06a9, Chain simulator migration after domain joins |
| Cursor pagination and workspace deletion (C) | ab06043, Merge workspace deletion and paged lists; 8d82f9b, Chain deletion migration after simulator state |
| First-time-user review and email outbox (A and F) | 602b37d, Merge first-time-user review; d07e536, Merge email outbox and privacy backfill; final integration at 4414dc4 through candidate land/AF-pre and PR #12 |

The current production migration chain has one head at 0022: consent 0017, domain joining 0018, durable simulator state 0019, workspace deletion and cursors 0020, general sandbox copy 0021, and email outbox 0022. The final deploy migrated the stage through 0022 and passed its grant audit.

## CI

The five required jobs are browser-real, images, web, python, and infra. These runs passed:

| Work | Run and result |
|---|---|
| E | [42617239836](https://github.com/darved2305/Pramana-AI-ggw_gnani-hackathon-/actions/runs/42617239836), all five jobs passed |
| D | [42622664541](https://github.com/darved2305/Pramana-AI-ggw_gnani-hackathon-/actions/runs/42622664541) and [42624563803](https://github.com/darved2305/Pramana-AI-ggw_gnani-hackathon-/actions/runs/42624563803), all five jobs passed; the candidate report also records GitGuardian passing |
| B | [42648669917](https://github.com/darved2305/Pramana-AI-ggw_gnani-hackathon-/actions/runs/42648669917) and [42650391032](https://github.com/darved2305/Pramana-AI-ggw_gnani-hackathon-/actions/runs/42650391032), all five jobs passed; the candidate report records GitGuardian passing |
| C | [42661824438](https://github.com/darved2305/Pramana-AI-ggw_gnani-hackathon-/actions/runs/42661824438) and [42663889165](https://github.com/darved2305/Pramana-AI-ggw_gnani-hackathon-/actions/runs/42663889165), all five jobs passed; the candidate report records GitGuardian passing |
| A and F | [42677485007](https://github.com/darved2305/Pramana-AI-ggw_gnani-hackathon-/actions/runs/42677485007) and [42680729255](https://github.com/darved2305/Pramana-AI-ggw_gnani-hackathon-/actions/runs/42680729255), all five required jobs passed |

The deployed code commit ed3e3cd passed all five jobs in [CI run 42711342669](https://github.com/darved2305/Pramana-AI-ggw_gnani-hackathon-/actions/runs/42711342669). Earlier fixes a90bc98 and 57c3917 passed all five jobs in runs 42703532936 and 42707391715. GitGuardian on PR #14 reported generic-password matches. The orchestrator checked them and identified dry-run placeholders, a test label and code handling SCRAM verifiers, rather than exposed credentials; no rotation or history rewrite was requested. The later candidate checks passed GitGuardian.

## Tasks

### A. First-time-user browser review

LANDED through PR #12. The review and fixes cover onboarding, phone layouts, site building and import, investigations, invitations and members, privacy screens, and voice-off states. The fix report adds the missing browser check that a revealed result appears in the person's track record and fixes migration ordering. The orchestrator approved A and classified the local Playwright database as disposable.

### B. Budget deployment preparation

LANDED for preparation. The deploy script and runbook cover public web plus private core and simulator services, the migration job, bounded instances, scoped service identities, Secret Manager, budget checks, durable simulator state, isolated container checks, and a synthetic dry run. The original dry run rendered 91 gcloud commands without contacting GCP or reading .env. Later deployment fixes include executable runtime entrypoints and security headers. The actual GCP stage is recorded below.

The B audit verdict was SHIP. It documented rollout connection overlap and the legacy non-workspace participants page as residual risks. The later live report could not verify the session pooler's configured limit or actual spend.

### C. Cursor pagination and workspace deletion

LANDED in ab06043 and 8d82f9b. Organization-bound cursors, server-side search and filters, load-more controls, workspace export, soft deletion, a 30-day restore period, and purge support are in production. The fix pass added database allowlist checks to destructive test paths, fixed long consent-history status, restored pending join requests on the home page, and repaired the migration chain. The final report records 4,107 Python tests collected without failures, 52 UI tests, and 33 real-stack tests passed. Candidate CI run 42661824438 passed 4,153 Python tests and the five required jobs.

The C audit originally said NOT SHIP after a test reset of pramana_web_e2e. Its code fixes landed. The C landing report records the orchestrator's disposition that this local database was disposable and did not need inspection or restoration. The daily purge role and schedule are not listed among the resources in the G deployment report.

### D. Verified workspace domain joining

LANDED in abb88ea. Verified Google Workspace or DNS claims support request and automatic viewer joins, with tenant-protected requests and admin decisions. The fix pass closed the verified-email, changed DNS challenge, RLS field-protection, join/removal race, and stale answer feedback findings. The browser race was fixed in 8b75cfa. Candidate CI run 42622664541 and production run 42624563803 passed. Local final gates included 4,056 Python tests, 49 UI tests, and 31 real-stack tests.

### E. Consent and quiet hours

LANDED in 2d0fcd5 and 3b3b03b. Saved-site questions require active contact consent and availability outside the person's quiet hours. Decisions and evaluation time are replayable; withdrawal cancels pending questions and replans. A reasoned owner or admin override is audited and does not grant consent. Practice uses synthetic participants. Consent links are encrypted in saved idempotency responses, rollback preserves refusal history, and proxy errors do not log bearer links. The audit verdict was SHIP. The landing report records 4,025 Python tests, 51 UI tests, and 30 real-stack tests passed. Native Hindi and Marathi review is not recorded as complete.

### F. Email outbox and personal-data backfill

LANDED through PR #12. The final migration is 0022. The branch adds a tenant-scoped outbox and attempt history, bounded retries and drain support, invitation and consent delivery states, cancellation when addresses change, and a resumable backfill for pre-sealing data. The fix report closes the seven audit findings, encrypts queued payloads, and chains the migration after production state. SMTP remains at-least-once. The full production backfill and scheduled outbox drain are not listed as completed in the live deployment report.

## G. Live deployment

The team-only stage is in GCP project luminous-slice-514102-f4, asia-south1, deployed from ed3e3cd. All three services have 100% traffic on these revisions:

| Service | URL | Revision | Image digest |
|---|---|---|---|
| web | https://pramana-web-671800103530.asia-south1.run.app | pramana-web-00014-4wh | sha256:b24897f84edf9af4a7225c70560156689f960400152e4e562fbb3d1206335900 |
| core | https://pramana-core-nzxslh75pq-el.a.run.app | pramana-core-00007-hr6 | sha256:cfbe6255b2fbf408028be8b5b7e6684034c73ffb8681ac6579bd424dde8c5c38 |
| simulator | https://pramana-sim-nzxslh75pq-el.a.run.app | pramana-sim-00008-wn6 | sha256:cfbe6255b2fbf408028be8b5b7e6684034c73ffb8681ac6579bd424dde8c5c38 |

The deploy uses min 0 and service max 2 instances. Cloud Run describes max 2; the default minimum 0 has no annotation. Migration execution pramana-migrate-g6gqq succeeded and logged a passed database grant audit after revokes. The preceding execution pramana-migrate-b58nh applied 0019 through 0022. No database reset or destructive data rewrite was performed; migration 0021 includes its normal practice-site metadata updates.

Live curl checks returned 200 for /, /login, a static asset, /api/core/health and /ready; an unknown path returned 404. The legacy web host returned 308 to the canonical host preserving path and query. OAuth start returned 302 to accounts.google.com with redirect_uri exactly https://pramana-web-671800103530.asia-south1.run.app/api/core/v1/auth/google/callback. The redirect was not followed. HSTS, CSP, X-Content-Type-Options, X-Frame-Options, Referrer-Policy and Permissions-Policy were present on the home response.

Migration execution pramana-migrate-sncqb failed because the migrator lacked superuser authority for explicit NOSUPERUSER role options. a90bc98 restored managed PostgreSQL-compatible role statements while preserving the privilege audit. After a subsequent verifier rewrite, core startup briefly failed authentication; both credentials later worked. 57c3917 avoids rewriting working credentials. A pooler cache effect is suspected but not established. A web revision then redirected the canonical URL to itself; traffic was restored while ed3e3cd fixed public host detection, after which the deploy and checks succeeded.

The cost plan estimates INR 0 to about INR 50 monthly while free usage applies, plus a separate INR 200 reserve. These are estimates, not observed billing. The owner confirmed an INR 1,000 monthly project alert at 50%, 80% and 100% of actual spend. The alert is not a spend cap; see the deployment runbook for assumptions and limits.

## Issue decisions and release limits

Issues #4 and #7 confirm that the INR 1,000 alert already exists and no billing role is needed to create it. The owner has parked credential rotation and the move from Singapore to Mumbai. The stage may use the existing settings for now, but real personal data must stay out until credentials are rotated, the database is in Mumbai, and an encrypted India backup and restore drill is complete.

No real Google or Microsoft account sign-in, real email, calls, or messages are claimed. Five usability sessions and native Hindi and Marathi review are not recorded in these deployment reports. The orchestrator classified the referenced local Playwright databases as disposable. Earlier reports record local test database fallback incidents.

## Edge-case rows from PRODUCTION.md section 6.2

| Rows | Status and evidence |
|---|---|
| ID-03, ID-04 | Landed with D. Request and automatic viewer joins run through mock OIDC domain claims. |
| DA-04, PA-09 | Landed with E. Consent and quiet-hours checks affect planning, replay, cancellation, and the audited override. |
| ID-07, ID-13, OR-09 | Landed with A. The first-time-user browser suite covers terminal invitations, expired sessions, double-click creation, and another workspace URL. |
| OR-07, DA-07 | Landed with C. Production now includes workspace export, restore, server-side filters, and signed cursors. |

The Nov 8 status table remains the baseline for all other ID, OR, DA, PA, and LC rows. The task reports use bundled Chromium and mock OIDC for local browser checks.

## Review findings and fixes

- A: code findings and the missing track-record browser check were fixed. The orchestrator classified the local test database as disposable and approved landing.
- B: role controls, Cloud Run identity headers, database reset allowlisting, migration ordering, and runtime limits were reviewed and fixed.
- C: pagination, consent history, test environment isolation, database guards, and pending join requests were fixed and landed.
- D: verified-email, DNS challenge, RLS, join/removal race, and browser feedback issues were fixed and landed.
- E: consent-link storage, rollback, and proxy logging findings were fixed and landed.
- F: outbox routing, delivery status, stale recipients, polling, route inventory, phone layout, payload encryption, and migration ordering were fixed and landed.
- G: the deployment report records a successful stage, but no independent G audit verdict is available.

## Open human verification and actions

- Keep the Singapore stage team-only and free of real personal data. Rotate the Supabase database and runtime passwords, Supabase secret API key, Google OAuth client secret and Gmail app password; replace the short migrator password with at least 16 characters.
- Before real personal data, provision the approved Mumbai database, verify the session pool limit, and complete an encrypted India backup and restore drill. Review the actual bill and alert; the alert does not cap spend.
- The first-time-user review did not cover the following as one fresh-database journey: sign-in cancellation; onboarding back, refresh, double clicks and empty, long, Hindi and Marathi inputs; guided sandbox reveal and adaptive home; site templates, descriptions, CSV edge cases, health, discard and site types; people consent and erasure; investigation board, live updates, approvals, report, forecast and map; participant phone flow; track records, model health and voice-off; member roles, last owner and removal; expired, wrong-account and revoked invitations; 404 and complete session-expiry flows. The final local journey was explicitly skipped under the fast-track instruction. Five usability sessions and native Hindi and Marathi review remain open.
- Decide and implement a scheduled outbox drain, retention purge and any production backfill as appropriate. SMTP is at-least-once. No scheduler is part of the stage. Review G deployment security and IAM independently; no independent G audit verdict was recorded.
- No real account sign-in, email, calls or messages were attempted. OAuth callback registration was owner-reported and the generated redirect URI was verified, but an actual account sign-in was not performed.
