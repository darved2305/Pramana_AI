# Pramana budget deployment on GCP

Status: prepared and verified locally on 2026-11-09. Nothing in GCP or Supabase was changed by
this work. The deployment is a separate lean path from `infra/gcp`, which remains the larger HA
reference.

## Readiness and residency gate

The selected launch shape is a public Cloud Run web service with private Cloud Run core and
simulator services in Mumbai (`asia-south1`), plus Supabase Free PostgreSQL in Mumbai (`ap-south-1`).
The Cloud Run URL is the initial site origin. The current Supabase ref in the local environment is
in Singapore (`ap-southeast-1`), which is not an eligible home for real personal data. The deploy
script refuses any database outside `ap-south-1` unless `PRAMANA_ACCEPT_NON_INDIA_DATABASE=true` is
set in the local `.env`. That acknowledgement is for a stage with no real personal data only, and
the script prints a warning on every deploy while it is in effect. Do not put real personal data in
the app until a Mumbai Supabase project exists, its session-pooler settings are in the local `.env`,
and the required credentials have been rotated.

The worktree `.env` is still missing deployment prerequisites: `GCP_BILLING_ACCOUNT_ID`, the
approved Mumbai Supabase region/ref/pooler host/database settings, separate rotated migrator and
runtime passwords, and the five rotation acknowledgements below. Existing Google OAuth and Gmail
values also need Darshan's rotations. The script has only synthetic values in `--dry-run`; its
default path does not load `.env` or contact Google Cloud.

## Resource and monthly cost plan

All figures are planning estimates in INR. USD conversions use INR 84 per USD and do not replace
the billing account's INR catalogue values. Applicable tax, egress, account-wide free-tier usage,
actual image size, logs and backup storage change the result. Google documents Cloud Run's free
usage and regional prices in its [pricing table](https://cloud.google.com/run/pricing).

| Resource | Configuration | Planning cost per month |
|---|---|---:|
| Cloud Run web, core and simulator | `asia-south1`, request billing, minimum 0 and maximum 2 instances each; one CPU each; 512 MiB web/sim and 1 GiB core; migration job runs only for deploys | INR 0 within the account-wide monthly allowance of 180,000 vCPU-seconds, 360,000 GiB-seconds and 2 million requests; otherwise metered by region |
| Supabase PostgreSQL | Free plan in `ap-south-1`; one project, separate migrator, `pramana_app` and `pramana_sim` roles | INR 0 within Free limits; 500 MB database, may pause after inactivity, and no automatic backup guarantee |
| Cloud Build | Two SHA-tagged images, default `e2-standard-2` workers | INR 0 for the first 2,500 build minutes per billing account each month; then about INR 0.50 per minute at the planning conversion ([pricing](https://cloud.google.com/build/pricing)) |
| Artifact Registry | One regional Docker repository; delete untagged images after 7 days, tagged images after 90 days, keep the five newest versions per image package | INR 0 for the first 0.5 GiB of storage; about INR 8.40 per GiB-month above that, before tax ([pricing](https://cloud.google.com/artifact-registry/pricing)) |
| Secret Manager | Eleven active secrets replicated only in `asia-south1`; no service-account JSON keys | About INR 25 per month for five versions beyond the six-version account-wide free allowance, assuming no other project uses it; 10,000 access operations per month are free, then about INR 2.52 per 10,000 ([pricing](https://cloud.google.com/secret-manager/pricing)) |
| Cloud Logging | Regional bucket with 180-day retention; only the three Cloud Run services and migration job are routed | First 50 GiB ingested per project per month is free; excess ingest is about INR 42 per GiB. Retention beyond 30 days is about INR 0.84 per GiB-month; at 1 GiB per month, roughly INR 4 at steady state ([pricing](https://cloud.google.com/logging)) |
| Billing budget | Existing INR 1,000 monthly project alert `pramana-inr-1000` (created by the billing owner, issue #7) at 50%, 80% and 100% of actual spend. No Cloud Run spend cap is configured | No separate budget-resource charge. An alert notifies; it does not stop spend, and it does not cover Supabase ([budgets](https://docs.cloud.google.com/billing/docs/how-to/budgets)) |
| Database backups | Supabase Free has no automatic backup guarantee. A pg_dump-based backup and restore drill is required below | Not priced until an approved India storage destination and schedule are chosen. Reserve part of the non-Run allowance |

The core allows six database connections per instance with overflow disabled. With two maximum
instances, that is at most twelve `pramana_app` sessions. The simulator allows one connection per
instance, or two `pramana_sim` sessions. Supabase's Nano plan documents a default pool size of 15;
the shared session pool is configurable, so confirm the approved project's value before deploy.
This sizing accounts for investigation reads that load both the investigation and its pinned site
model. During a Cloud Run rollout the old and new revisions can run side by side for a short time,
so the peak can reach twice the twelve `pramana_app` sessions above, 24, which is over the default
pool size of 15 for the length of the overlap. Requests that cannot get a connection within five
seconds fail rather than queue, so watch for 503s during a deploy and redeploy outside peak use. See [Supabase connection pool limits](https://supabase.com/docs/guides/database/connecting-to-postgres/pooling-and-limits)
and [Nano compute limits](https://supabase.com/docs/guides/platform/compute-and-disk).

Target normal GCP use is INR 0 to about INR 50 per month while the free usage allowances apply.
Keep a separate INR 200 monthly allowance for registry growth, extra secret versions, log
retention, egress and approved backup storage. Without a spend cap, the bill is bounded by
the controls in this runbook, not by a hard limit: minimum 0 instances, a maximum of two instances
per service, one CPU and small memory per service, request-based billing, bounded concurrency and
the Artifact Registry cleanup policy. Measure the first month's bill against the INR 1,000 alert
before accepting real users. A spend cap was not configured because the deploy identity has no
billing role; the billing owner can add one later if they want a hard stop.

The project alert budget `pramana-inr-1000` is scoped to `luminous-slice-514102-f4` on billing
account `014417-27A82C-ACEA10`, with INR 1,000 per calendar month and 50%, 80% and 100% thresholds.
The deploy script does not read, create or change budgets. It prints the budget name and the
reminder that no spend cap exists, so the owner can confirm both in Billing.

## What the deploy script creates

- `pramana-web` is public. `pramana-core` and `pramana-sim` require Cloud Run invoker IAM.
- The web identity invokes core and simulator through `X-Serverless-Authorization`; core also
  invokes the simulator as its service identity. Participant bearer authorization remains intact.
- A one-task, zero-retry Cloud Run migration job creates/hardens database roles, applies Alembic,
  reapplies API-role revokes and fails on grant-audit violations before service rollout.
- Separate web, core, simulator and migration service accounts receive only their needed Secret
  Manager access. Core reads only the application database URL; simulator reads only its own URL;
  only the migration account reads the migrator URL. Oracle secrets are never deployed.
- A new 32-byte `PRAMANA_PII_KEY` is generated in process and sent to Secret Manager over stdin.
  It is never written to `.env`, an argument, or a repository file. Secrets use user-managed
  replication in `asia-south1`.
- The bootstrap web revision uses `--no-traffic`, so existing traffic remains on the old revision
  until the final web deploy. The script checks `/`, `/login`, a Next static asset,
  `/api/core/health` and `/ready` through the public proxy.

## First deployment

1. Darshan provisions or selects the Supabase Free project for the database. For a Mumbai database
   (required before real personal data), use the approved Mumbai project and set
   `PRAMANA_SUPABASE_REGION=ap-south-1`. For the current Singapore project, set
   `PRAMANA_SUPABASE_REGION=ap-southeast-1` and `PRAMANA_ACCEPT_NON_INDIA_DATABASE=true`; this is
   accepted only for a stage with no real personal data. Set `PRAMANA_SUPABASE_REF`,
   `PRAMANA_SUPABASE_POOLER_HOST` (the session pooler host of the same region),
   `PRAMANA_SUPABASE_DATABASE=postgres`, `PRAMANA_SUPABASE_DB_PASSWORD` and
   `PRAMANA_SUPABASE_APP_PASSWORD` from its connection settings. Use distinct passwords.
2. Set `GCP_BILLING_ACCOUNT_ID` to the linked INR billing account. The GCP project ID is fixed to
   `luminous-slice-514102-f4`. Confirm the INR 1,000 alert `pramana-inr-1000` still exists in
   Billing and that the billing account's current month spend is low.
3. Darshan rotates the Supabase database password, Supabase runtime role password, Supabase secret
   API key, Google OAuth client secret and Gmail app password. Set each corresponding
   `*_ROTATED=true` flag in `.env`. The secret API key is not read by the app or uploaded to Google
   Cloud; the acknowledgement confirms the old exposed key was replaced. Keep the app password,
   OAuth secret and database passwords only in `.env` and Secret Manager.
4. From the repository root, review the synthetic plan and confirm the worktree is clean:

   ```powershell
   uv run python scripts/deploy_gcp_starter.py --dry-run
   git status --short
   ```

   The dry-run uses synthetic credentials and assumes resources are absent. It prints the planned
   gcloud commands, migration job and smoke URLs. It does not load `.env`, invoke
   gcloud, or send an HTTP request.
5. After a human signs in with the authorized Google account, run the one deploy command from the
   repository root:

   ```powershell
   uv run python scripts/deploy_gcp_starter.py
   ```

   The script verifies that the active gcloud account is `nikhilpise2006@gmail.com`, enables
   required APIs, records the existing budget, creates regional logs, image cleanup, service accounts and secrets, builds images tagged with
   the committed git SHA, runs migrations and grant audit, deploys the services, then runs live
   smoke checks. It prints the exact `run.app` OAuth callback URI. Darshan must add that URI to the
   Google OAuth client's authorized redirect URIs before a real sign-in works. The scripted smoke
   does not attempt Google sign-in.

The exact sign-in command is `gcloud auth login`. No application-default credentials are required:
the deploy uses the gcloud CLI account to run commands. This preparation did not run either sign-in
command.

## Redeploy and rollback

Commit the code first, then rerun the same `uv run python scripts/deploy_gcp_starter.py` command.
The image tags use the current commit SHA. If a secret value changes, add an explicit
`--rotate-secret NAME` argument. Supported names are listed in the script; `pii-key` is protected
from deploy-time rotation. Rotating `participant-signing-key` also adds its derived public key.
After a successful rollout, disable obsolete secret versions only after confirming no serving
revision depends on them.

The deploy output prints a `gcloud run services update-traffic` command for each service with prior
traffic. Run those commands to restore the previous revision. On a first deploy there is no prior
revision; use the previous committed SHA and rerun the script to build and deploy it. Keep the five
newest tagged Python and web images for this recovery window.

Database password rotation has a brief reconnection risk because PostgreSQL role passwords change
before new Cloud Run revisions are deployed. Schedule a maintenance window, update local `.env`,
use `--rotate-secret database-migrator-url` and/or `--rotate-secret database-runtime-url`, deploy,
and verify health before ending the window. The simulator role password is generated separately
and managed by its own `database-simulator-url` secret.

## Supabase Free backup and restore drill

Supabase Free does not provide an automatic backup guarantee. Before storing real data, agree on a
restricted backup destination in India and a schedule with Darshan. Keep backup copies encrypted,
access-controlled and out of Git. A reasonable initial manual schedule is weekly dumps plus a
monthly restore test; revise it against measured database growth and the Free plan's egress limits.

After the approved Mumbai database exists, use its pooler host and `postgres.<project-ref>` user.
In PowerShell, `pg_dump --password` prompts without echoing the password. Set
`PRAMANA_BACKUP_STAGING_DIR` to a restricted directory on encrypted storage before running the
example. It writes a local archive, encrypts it with the approved age recipient key, and removes
the plaintext before upload:

```powershell
$staging = $env:PRAMANA_BACKUP_STAGING_DIR
if (-not $staging -or -not (Test-Path -LiteralPath $staging)) { throw 'Set an encrypted backup staging directory first.' }
$dump = Join-Path $staging 'pramana-mumbai-restore-drill.dump'
$archive = Join-Path $staging 'pramana-mumbai-restore-drill.dump.age'
pg_dump --host $env:PRAMANA_SUPABASE_POOLER_HOST --port 5432 `
  --username "postgres.$env:PRAMANA_SUPABASE_REF" `
  --dbname $env:PRAMANA_SUPABASE_DATABASE --format=custom `
  --no-owner --no-acl --password --file $dump
if ($LASTEXITCODE -ne 0) { throw 'pg_dump failed; no backup was created.' }
age --encrypt --recipient-file $env:PRAMANA_BACKUP_RECIPIENT_FILE `
  --output $archive $dump
if ($LASTEXITCODE -ne 0) { throw 'age encryption failed; the plaintext dump was kept.' }
Remove-Item -LiteralPath $dump
```

Use a synthetic-only or sanitized archive for a workstation restore. The local cluster must be
running, and the target must be a database explicitly listed in that worktree's `PRAMANA_DB_NAMES`.
For this worktree that test database is `pramana_dp_test`. Restore there after local test processes
have stopped. Use the encrypted archive from the approved staging directory. Decrypt it with an
approved private key kept outside the repository, then restore it:

```powershell
$staging = $env:PRAMANA_BACKUP_STAGING_DIR
$dump = Join-Path $staging 'pramana-mumbai-restore-drill.dump'
$archive = Join-Path $staging 'pramana-mumbai-restore-drill.dump.age'
age --decrypt --identity-file $env:PRAMANA_BACKUP_IDENTITY_FILE `
  --output $dump $archive
if ($LASTEXITCODE -ne 0) { throw 'age decryption failed; restore was not started.' }
pg_restore --clean --if-exists --no-owner --no-acl `
  --dbname 'postgresql://pramana@localhost:5433/pramana_dp_test' $dump
if ($LASTEXITCODE -ne 0) { throw 'pg_restore failed; the restored database needs review.' }
$env:DATABASE_URL = 'postgresql+asyncpg://pramana@localhost:5433/pramana_dp_test'
uv run python -m pramana_core.grant_audit --apply-revokes
if ($LASTEXITCODE -ne 0) { throw 'grant audit failed; do not route traffic to this restore.' }
Remove-Item -LiteralPath $dump
```

Run focused application checks against the restored local database, record the dump timestamp,
schema revision and restore result, then securely delete the decrypted working copy. Keep the
encrypted archive for the approved retention period. Never use the Singapore database for backup
or restore practice. A production recovery test must restore to an approved India database and
re-run the migration grant audit before routing traffic.

## Human handoff and remaining limits

- Provide the Supabase connection settings (Mumbai, or Singapore with the non-personal-data
  acknowledgement) and all five rotation acknowledgements in this worktree's local `.env`; do not
  commit it.
- Sign in with `gcloud auth login`, then run
  `uv run python scripts/deploy_gcp_starter.py` from a clean committed tree.
- Add the printed callback URI to Google OAuth. Do not put real personal data in the app until the
  Supabase database is in India and an India backup destination has been tested.
- Review the INR 1,000 project alert and the actual bill weekly. No spend cap exists; the alert
  does not stop spend.
- This path has no domain, Cloud SQL, load balancer, Cloud Armor, NAT, VPC connector, paid Supabase
  add-ons, media service, worker service or Cloud Scheduler.
