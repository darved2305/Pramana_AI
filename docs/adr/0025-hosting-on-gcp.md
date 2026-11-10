# 0025: Hosting on GCP `asia-south1`; environments; CI/CD with canaries

**Status:** proposed (cloud choice confirmed by the user on 2026-11-07)

**Starter budget amendment, 2026-11-08.** The user set an INR 1,000/month total GCP ceiling and
approved Supabase Free PostgreSQL in specific Mumbai, with the application on Cloud Run Mumbai.
The HA Cloud SQL, load balancer and always-on process topology below remains a larger-tier
reference and is not authorized for the launch. The starter uses managed Cloud Run HTTPS URLs,
zero minimum instances, bounded pools/instances, private service invocation, a private database
schema and separate migration/runtime roles. Backups, restoration, free-tier pausing, quotas and
spend controls must be verified. See
[the sourced budget review](../engineering/CLOUD_BUDGET_REVIEW_2026-11-08.md).
This amendment changes the hosting profile, not the deterministic engine or sealed truth boundary.

**Amends:** 0005 (local development stays Docker-free; containers are for deployment only) and
0009 (in the cloud a load balancer routes `/api` and `/media` paths directly, so SSE no longer
passes through the Next.js rewrite and its proxy idle timeout).

**Context.** PRODUCTION.md §13. Staging runs on a laptop behind a Cloudflare Worker and Tunnel;
the public route returned 502 on Nov 7. CERT-In requires ICT logs kept in India for 180 days,
voice latency to an Indian provider matters, and customers will ask where their data is.

**Options compared.**

| Option | For | Against |
|---|---|---|
| **GCP: Cloud Run, Cloud SQL, Cloud Storage, Secret Manager, KMS, Cloud Armor in `asia-south1`** | Mumbai and Delhi regions; WebSockets up to 60 minutes; managed HA PostgreSQL with PITR; no cluster to run | Affinity is best effort (we do not rely on it); open sockets bill as active instances |
| AWS: ECS Fargate, ALB, RDS, S3 in `ap-south-1` | Equal design | More assembly |
| Vercel, Fly.io, Render, Railway, Neon | Easy | No Mumbai region, or long-lived sockets belong elsewhere |

**Decision.**
- Five Cloud Run services from two images: one Python image (`api`, `media`, `worker`, `sim`,
  selected by command) and one Next.js standalone image (`web`). A `migrate` job runs Alembic.
- Upstream URLs are runtime configuration, never baked at build time, so one image runs in every
  environment.
- Cloud SQL PostgreSQL with regional HA and point-in-time recovery; backups copied to
  `asia-south2`. A log bucket in `asia-south1` with at least 180 days' retention.
- Terraform in `infra/gcp/`, one workspace per environment. CI runs `fmt -check` and `validate`
  only; `apply` needs the user's explicit approval of the plan and its fixed costs.
- GitHub Actions authenticates through Workload Identity Federation; no long-lived keys.
- Releases: build once per SHA, migrate (expand), deploy 10% canary, watch SLO burn for 30
  minutes, then 100%; roll back by shifting traffic.

**Consequences.** Fixed monthly cost is dominated by the HA database and the minimum instances of
`api`, `media` and `worker`. Local development is unchanged (no Docker).

**Tests.** CI builds both images; `terraform fmt -check` and `terraform validate` pass; the web
image serves `/` with upstreams set only by environment variables; staging `/ready` returns 200
for 7 days (R0 exit).
