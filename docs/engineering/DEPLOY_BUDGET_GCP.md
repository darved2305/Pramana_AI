# Pramana budget deployment on GCP

Status: deployed and smoke-tested on 2026-11-09. The live stage uses the separate lean path in
this runbook; `infra/gcp` remains the larger HA reference. The web URL is team-only and must not
be shared outside the team.

## Readiness and residency gate

The live stage has a public Cloud Run web service and private Cloud Run core and simulator services
in Mumbai (`asia-south1`). Its Supabase PostgreSQL database is in Singapore (`ap-southeast-1`). The
owner explicitly parked the India move and five credential rotations, so this stage is permitted
only while it contains no real personal data. The deploy script requires
`PRAMANA_ACCEPT_NON_INDIA_DATABASE=true` and `PRAMANA_ROTATIONS_PARKED=true` for this exception and
prints the warning on every deploy. Do not share the live URL outside the team. Do not put real
personal data in the app until a Mumbai Supabase project exists, its session-pooler settings are in
the local `.env`, the database backup and restore path is tested in India, and all required
credentials have been rotated. The current migrator password is also shorter than the 16-character
rule and must be replaced before real data is allowed.

The deployment used the preconfigured local environment. This work did not print or commit any
credential values. The `--dry-run` path uses synthetic values and does not load `.env`, invoke
gcloud, or send HTTP requests.

## Resource and monthly cost plan

All figures are planning estimates in INR. USD conversions use INR 84 per USD and do not replace
the billing account's INR catalogue values. Applicable tax, egress, account-wide free-tier usage,
actual image size, logs and backup storage change the result. Google documents Cloud Run's free
usage and regional prices in its [pricing table](https://cloud.google.com/run/pricing).

| Resource | Configuration | Planning cost per month |
|---|---|---:|
| Cloud Run web, core and simulator | `asia-south1`, request billing, minimum 0 and maximum 2 instances each; one CPU each; 512 MiB web/sim and 1 GiB core; migration job runs only for deploys | INR 0 within the account-wide monthly allowance of 180,000 vCPU-seconds, 360,000 GiB-seconds and 2 million requests; otherwise metered by region |
| Supabase PostgreSQL | Free plan in `ap-south-1`; one project, separate migrator, `pramana_app` and `pramana_sim` roles | INR 0 within Free limits; 500 MB database, may pause after inactivity, and no automatic backup guarantee |
| Cloud Build | Two SHA-tagged images, default `e2-standard-2` workers in Mumbai | INR 0 for the first 2,500 build minutes per billing account each month; then about INR 0.50 per minute at the planning conversion ([Mumbai pricing](https://cloud.google.com/build/pricing-update)) |
| Cloud Build staging bucket | Regional Cloud Storage bucket in `asia-south1` with lifecycle cleanup | Estimate INR 0 to INR 10 per month at low transient volume; actual object bytes were not measured. Cloud Storage's Always Free storage quota applies only in US regions ([pricing](https://cloud.google.com/storage/pricing), [free tier](https://docs.cloud.google.com/free/docs/free-cloud-features)) |
| Artifact Registry | One regional Docker repository; delete untagged images after 7 days, tagged images after 90 days, keep the five newest versions per image package | INR 0 for the first 0.5 GiB of storage; about INR 8.40 per GiB-month above that, before tax ([pricing](https://cloud.google.com/artifact-registry/pricing)) |
| Secret Manager | Eleven active secrets replicated only in `asia-south1`; no service-account JSON keys | About INR 25 per month for five versions beyond the six-version account-wide free allowance, assuming no other project uses it; 10,000 access operations per month are free, then about INR 2.52 per 10,000 ([pricing](https://cloud.google.com/secret-manager/pricing)) |
| Cloud Logging | Regional bucket with 180-day retention; ordinary logs from the three Cloud Run services and migration job are routed, sensitive request URLs are excluded | First 50 GiB ingested per project per month is free; excess ingest is about INR 42 per GiB. Retention beyond 30 days is about INR 0.84 per GiB-month; at 1 GiB per month, roughly INR 4 at steady state ([pricing](https://cloud.google.com/logging)) |
| Billing budget | Existing INR 1,000 monthly project alert `pramana-inr-1000` (created by the billing owner, issue #7) at 50%, 80% and 100% of actual spend. No Cloud Run spend cap is configured | No separate budget-resource charge. An alert notifies; it does not stop spend, and it does not cover Supabase ([budgets](https://docs.cloud.google.com/billing/docs/how-to/budgets)) |
| Database backups | Supabase Free has no automatic backup guarantee. A pg_dump-based backup and restore drill is required below | Not priced until an approved India storage destination and schedule are chosen. Reserve part of the non-Run allowance |

Cloud Run request logs include the full request URL. The `pramana-run` sink excludes Google OAuth
start and callback URLs, consent-link URLs and `/consent/` capability URLs. A matching exclusion on
the `_Default` sink drops those request records instead of storing them in its default destination.
Other Cloud Run request logs and the migration job logs remain in the regional bucket for 180 days.

The deployed core uses a pool size of three and zero overflow, with a maximum of two instances.
That is six `pramana_app` sessions on one revision. The simulator uses one connection per instance,
or two `pramana_sim` sessions. During a rollout, old and new revisions can overlap, so the
configured peak can reach twelve core sessions and four simulator sessions. A read-only database
check reported PostgreSQL 17.11 and `max_connections=60`; the session pooler's configured session
limit was not available to this check. Do not infer that the pooler allows 60 application sessions.
The five-second core pool timeout fails requests instead of queueing them. Deploy outside peak use
and watch for 503s until the approved project's pooler limit and first month of use are confirmed.
See [Supabase connection pool limits](https://supabase.com/docs/guides/database/connecting-to-postgres/pooling-and-limits)
and [Nano compute limits](https://supabase.com/docs/guides/platform/compute-and-disk).

The planning target for normal GCP use is INR 0 to about INR 50 per month while the free usage
allowances apply. Keep a separate INR 200 monthly allowance for registry growth, extra secret
versions, log retention, egress and approved backup storage. These are estimates, not observed
charges; this work did not read billing reports or list budgets. Minimum zero instances, two maximum
instances per revision, one CPU, small memory, request-based billing and Artifact Registry cleanup
limit peak usage and retained artifacts. They do not cap total spend. Continued usage can exceed the
INR 1,000 alert, which notifies but does not stop spend. Review the first month's actual bill before
accepting real users.

The project alert budget `pramana-inr-1000` is scoped to `luminous-slice-514102-f4` on billing
account `014417-27A82C-ACEA10`, with INR 1,000 per calendar month and 50%, 80% and 100% thresholds.
The deploy script does not read, create or change budgets. It prints the budget name and the
reminder that no spend cap exists, so the owner can confirm both in Billing.

Other provisioned resources include five least-privilege service accounts, required API enablement,
and scoped IAM bindings. They have no separate monthly resource fee. The one-task migration job is
included in Cloud Run usage and incurs compute charges only while it runs.

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

## Current staging deployment

The live stage was deployed from code commit `980bf4dd923c` on 2026-11-09. All three services are
ready in `asia-south1` with 100% traffic on the revisions below:

| Service | URL | Ready revision | Image digest |
|---|---|---|---|
| `pramana-web` | `https://pramana-web-nzxslh75pq-el.a.run.app` | `pramana-web-00009-k6j` | `pramana-web@sha256:c4de3687d6b0f1181f54b028b47cde1a451b443d3560d25ed8e9e12b4b4c64c6` |
| `pramana-core` | `https://pramana-core-nzxslh75pq-el.a.run.app` | `pramana-core-00004-ctb` | `pramana-py@sha256:350168dbe5dfd27bd5e340897df5292292696926c2ecaa3ac567c75f9f762bc3` |
| `pramana-sim` | `https://pramana-sim-nzxslh75pq-el.a.run.app` | `pramana-sim-00005-5dk` | `pramana-py@sha256:350168dbe5dfd27bd5e340897df5292292696926c2ecaa3ac567c75f9f762bc3` |

The Cloud Run migration job completed successfully and the schema is at Alembic revision `0019`.
Read-only checks found only the Alembic version table in `public`, confirmed the `pramana` and
`pramana_sim` schemas, and confirmed the runtime roles cannot superuser, bypass row security, create
databases or create roles. No tenant or personal-data rows were read or added.

The deploy smoke returned 200 for `/`, `/login`, a Next static asset, `/api/core/health` through
the web proxy, and `/ready`. Follow-up checks confirmed a 404 for an unknown path and these headers
on the landing page, login page and 404 response: HSTS, CSP, `X-Content-Type-Options`,
`X-Frame-Options`, `Referrer-Policy` and `Permissions-Policy`. The HTTPS login page rendered in
bundled headless Chromium, and the Google sign-in link was visible but not clicked. An HTTP-only
request to the Google start endpoint returned 302 to `accounts.google.com`; the configured client
ID and callback matched, and the state cookie had Secure, HttpOnly, SameSite and Path attributes.
The redirect was not followed and no Google sign-in or email was attempted. Screenshots are in the
ignored `apps/.cache/g-live-final-home.png` and `apps/.cache/g-live-final-login.png` files.

Add this exact callback URI manually to the existing Google OAuth web client before testing a real
sign-in:

```text
https://pramana-web-nzxslh75pq-el.a.run.app/api/core/v1/auth/google/callback
```

The app uses a server-side authorization-code redirect and does not require a JavaScript origin.
No OAuth client edit was attempted.

## Owner actions before real data

1. Keep the URL team-only. The Singapore database is approved for staging only and contains no
   real personal data. Do not use it for real people or backups.
2. Rotate the Supabase database password, runtime role password, Supabase secret API key, Google
   OAuth client secret and Gmail app password. Replace the short migrator password with a value of
   at least 16 characters. Keep secret values out of Git, command arguments and reports.
3. Provision the approved Mumbai Supabase project. Set its region, ref, session-pooler host and
   distinct database and runtime passwords in the local `.env`. Confirm its actual session-pooler
   limit and size runtime pools below that limit, including a two-revision rollout overlap.
4. Choose a restricted encrypted backup destination in India, then complete and record a restore
   drill before putting real personal data in the app.
5. Add the callback URI above by hand in Google Cloud Console. This work did not open a Google page,
   attempt sign-in or send email.
6. Review the owner-confirmed INR 1,000/month alert `pramana-inr-1000` and the actual bill. The
   deploy identity does not have a billing role, and this deployment neither listed nor changed
   budgets. There is no spend cap.
7. After those prerequisites, review the synthetic plan and deploy from a clean, committed tree:

   ```powershell
   uv run python scripts/deploy_gcp_starter.py --dry-run
   git status --short
   ```

   The dry-run uses synthetic credentials and assumes resources are absent. It prints the planned
   gcloud commands, migration job and smoke URLs. It does not load `.env`, invoke gcloud, or send an
   HTTP request. The normal deploy command uses the already authorized CLI identity and must not
   be used to sign in or out:

   ```powershell
   uv run python scripts/deploy_gcp_starter.py
   ```

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

- Complete the owner actions above before the live stage is used with real personal data.
- Review the INR 1,000 project alert and actual bill weekly. No spend cap exists; the alert does not
  stop spend.
- This path has no domain, Cloud SQL, load balancer, Cloud Armor, NAT, VPC connector, paid Supabase
  add-ons, media service, worker service or Cloud Scheduler.

## Teardown

Teardown is documented only; it was not run. These commands remove only the resources named by this
deployment from project `luminous-slice-514102-f4`. They permanently remove the Cloud Run services,
images, build staging objects, secrets and routed logs. Confirm the project and exact bucket URI
before running them. Do not delete the Supabase project or database, the billing account, the
`pramana-inr-1000` budget alert, or the GCP project.

Delete service traffic and the migration job first:

```powershell
gcloud run services delete pramana-web --region=asia-south1 --project=luminous-slice-514102-f4 --quiet
gcloud run services delete pramana-core --region=asia-south1 --project=luminous-slice-514102-f4 --quiet
gcloud run services delete pramana-sim --region=asia-south1 --project=luminous-slice-514102-f4 --quiet
gcloud run jobs delete pramana-migrate --region=asia-south1 --project=luminous-slice-514102-f4 --quiet
```

Delete the exact deployment secrets, routed logging resources, images and build staging bucket:

```powershell
gcloud secrets delete pramana-pii-key --project=luminous-slice-514102-f4 --quiet
gcloud secrets delete pramana-database-simulator-url --project=luminous-slice-514102-f4 --quiet
gcloud secrets delete pramana-google-oauth-client-id --project=luminous-slice-514102-f4 --quiet
gcloud secrets delete pramana-google-oauth-client-secret --project=luminous-slice-514102-f4 --quiet
gcloud secrets delete pramana-gmail-address --project=luminous-slice-514102-f4 --quiet
gcloud secrets delete pramana-gmail-app-password --project=luminous-slice-514102-f4 --quiet
gcloud secrets delete pramana-sim-operator-key --project=luminous-slice-514102-f4 --quiet
gcloud secrets delete pramana-participant-signing-key --project=luminous-slice-514102-f4 --quiet
gcloud secrets delete pramana-participant-public-key --project=luminous-slice-514102-f4 --quiet
gcloud secrets delete pramana-database-migrator-url --project=luminous-slice-514102-f4 --quiet
gcloud secrets delete pramana-database-runtime-url --project=luminous-slice-514102-f4 --quiet
gcloud logging sinks delete pramana-run --project=luminous-slice-514102-f4 --quiet
gcloud logging buckets delete pramana-run --location=asia-south1 --project=luminous-slice-514102-f4 --quiet
gcloud artifacts repositories delete pramana --location=asia-south1 --project=luminous-slice-514102-f4 --quiet
gcloud storage rm --recursive 'gs://luminous-slice-514102-f4-pramana-build/**'
gcloud storage buckets delete gs://luminous-slice-514102-f4-pramana-build --project=luminous-slice-514102-f4 --quiet
```

Then delete only these deployment identities after checking for any other use:

```powershell
gcloud iam service-accounts delete pramana-web@luminous-slice-514102-f4.iam.gserviceaccount.com --project=luminous-slice-514102-f4 --quiet
gcloud iam service-accounts delete pramana-core@luminous-slice-514102-f4.iam.gserviceaccount.com --project=luminous-slice-514102-f4 --quiet
gcloud iam service-accounts delete pramana-sim@luminous-slice-514102-f4.iam.gserviceaccount.com --project=luminous-slice-514102-f4 --quiet
gcloud iam service-accounts delete pramana-migrate@luminous-slice-514102-f4.iam.gserviceaccount.com --project=luminous-slice-514102-f4 --quiet
gcloud iam service-accounts delete pramana-build@luminous-slice-514102-f4.iam.gserviceaccount.com --project=luminous-slice-514102-f4 --quiet
```

Review IAM for stale `pramana-*` service-account bindings and remove only those exact principals.
Leave project APIs and all unrelated resources unchanged.
