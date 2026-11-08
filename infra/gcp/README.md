# infra/gcp: Pramana on Google Cloud (asia-south1)

Terraform for ADR 0025 and PRODUCTION.md §13.3. **Nothing here has been applied.** CI runs
`terraform fmt -check` and `terraform validate` only.

**Budget change, 2026-11-08:** the user's first deployment ceiling is INR 1,000 per month total.
The HA defaults below exceed it and must not be applied unchanged. See the
[budget review](../../docs/engineering/CLOUD_BUDGET_REVIEW_2026-11-08.md) for sourced prices,
starter alternatives and work required before a concrete plan can be approved. No cloud resource,
including the state bucket, may be created ahead of that approval.

## What it creates

| File | Resources |
|---|---|
| `main.tf` | Required APIs, Artifact Registry, one service account per process, Secret Manager secrets (empty), a KMS key for personal data |
| `database.tf` | VPC, private service access, Cloud SQL PostgreSQL 16 (regional HA, PITR, backups in `asia-south2`, private IP, IAM database users) |
| `run.tf` | Cloud Run services `web`, `api`, `media`, `worker`, `sim` and the `migrate` job |
| `edge.tf` | Global HTTPS load balancer with serverless NEGs, path routing, Cloud Armor rate limit on sign-in; certificate only once `domain` is set |
| `storage_logging.tf` | Audio bucket (90-day lifecycle), anchors bucket (versioned, 1-year retention lock), a log bucket in `asia-south1` (180 days minimum, CERT-In) |
| `ci_identity.tf` | Workload identity federation for GitHub Actions and a deployer service account |

## Before the first apply (needs the user's explicit go-ahead)

1. Before approval, prepare the review plan using an isolated local backend. After approval,
   create the state bucket: `gcloud storage buckets create gs://<project>-tfstate --location=asia-south1 --uniform-bucket-level-access`.
2. `terraform init -backend-config="bucket=<project>-tfstate" -backend-config="prefix=staging"`.
3. `terraform plan -var project_id=<project> -var environment=staging -out plan.bin` and show the
   user the plan and the cost estimate below.
4. Apply only after an explicit yes. Then add secret values in Secret Manager by hand, never in
   Terraform.
5. Before migrations, create `pramana_app` (non-superuser, no `BYPASSRLS`) so the migrations grant
   it table privileges. Grant it only to runtime IAM users. The migrator owns the schema and is
   never a runtime identity (ADR 0015).
6. Use `database-url` for the runtime connection and `migration-database-url` for the migrator.
   Runtime service accounts cannot read the migrator credential or `sim-oracle-key`. IAM database
   connection/token-refresh wiring and a staging smoke test remain deployment work; Terraform
   validation does not establish that runtime connectivity works.
7. Production core processes receive `PRAMANA_MODE=production`. Configure the final domain so
   `OIDC_REDIRECT_URL` is HTTPS; startup refuses the local HTTP default in production. Staging
   uses demo mode. No domain has been chosen and no deployment has been run.

## Expected fixed monthly cost (staging, rough) [I]

List prices change; run the Google Cloud pricing calculator for `asia-south1` before applying.
Rough order of magnitude with the defaults:

| Item | Assumption | Rough US$ / month |
|---|---|---|
| Cloud SQL HA | `db-custom-2-7680`, regional (two zones), 20 GB SSD | 180 to 230 |
| Cloud Run minimum instances | `api`, `media`, `worker` at 1 each, 1 vCPU, 1 GiB, instance-based billing | 130 to 170 |
| Load balancer | One forwarding rule plus data processing at low traffic | 20 to 25 |
| Cloud Armor | One policy, two rules | about 7 |
| Logging, storage, KMS, Secret Manager, Artifact Registry | Low volume | under 15 |
| **Total** | | **about 350 to 450** |

Cheaper staging: `availability_type = "ZONAL"` and minimum instances of 0 for `media` and
`worker` roughly halve this, at the cost of cold starts and no database failover.
