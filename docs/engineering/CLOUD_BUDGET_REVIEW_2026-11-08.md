# Pramana deployment budget review, 2026-11-08

The user set a ceiling of INR 1,000 per month for the first cloud deployment, including the
whole GCP bill. The product must be deployed, not left as a local-only application. GCP Mumbai
remains the app region; no domain is owned. Nothing has been provisioned or applied.

The existing `infra/gcp` defaults are an HA architecture reference. They are **not approved** for
this budget and must not be applied unchanged. Their earlier USD 350 to 450 estimate is far above
the ceiling. Local tests protect the submission and precede deployment; they are not the final
hosting plan. STOP 2 still requires the concrete resource plan and costs before apply.

**User decision, Nov 8:** use Supabase Free in the specific Mumbai region for PostgreSQL, with
the application on GCP Mumbai. The user accepted free-tier pausing and our own backup schedule.
The VM costs below document why the all-GCP database alternative was rejected for this launch.
GCP project access and billing linkage were confirmed read-only. A scoped Supabase setup token
was requested by name in `.env`; no project or paid add-on has been created.

## Findings from primary sources

| Finding | Consequence for this deployment | Source, read 2026-11-08 |
|---|---|---|
| Cloud Run has deterministic managed HTTPS URLs using service name, project number and region | Start with its `run.app` URL; a domain and external load balancer are not prerequisites | [Cloud Run HTTPS](https://docs.cloud.google.com/run/docs/triggering/https-request) |
| Request-based billing and zero minimum instances avoid idle compute charges; concurrency must be measured with the application | Use bounded instances and pools, then measure CPU, memory and latency instead of copying an arbitrary high concurrency value | [Cost optimization](https://docs.cloud.google.com/run/docs/tips/services-cost-optimization), [Google engineering blog](https://cloud.google.com/blog/products/serverless/cost-optimization-for-serverless-workloads) |
| Direct VPC egress has no always-on connector VMs | Avoid Serverless VPC Access connector and NAT baselines | [Cloud Run cost guide](https://docs.cloud.google.com/run/docs/tips/services-cost-optimization) |
| Cloud Billing now supports service-level spend caps for eligible services, including Cloud Run | Use the cap if available for this billing account, in addition to instance/request limits. It is not a project-wide INR 1,000 guarantee: enforcement has delay and overages are billed | [Spend cap budgets](https://docs.cloud.google.com/billing/docs/how-to/budgets-spend-caps) |
| Cloud Run instances and service filesystems are ephemeral | PostgreSQL and sealed simulator state cannot depend on a local container file for durable production state | [Instance persistence limits](https://docs.cloud.google.com/run/docs/instances/create-and-manage-instances) |
| IAM service invocation can use X-Serverless-Authorization separately from application Authorization | Authenticate the Next proxy to private backends without overwriting participant bearer tokens | [Service-to-service auth](https://docs.cloud.google.com/run/docs/authenticating/service-to-service) |
| Persistent Disk is durable and independent of its VM | A private single-VM PostgreSQL pilot is an alternative to Cloud SQL, but requires our own patching, backups and restore verification | [Persistent Disk](https://cloud.google.com/persistent-disk) |
| India GST can be 18%, depending on the contracting/billing arrangement | Reserve 18% in estimates rather than assume a tax exemption | [Google tax guidance](https://docs.cloud.google.com/billing/docs/resources/vat-overview) |

## Database cost comparison

Read-only Cloud Billing Catalog API results were fetched in INR for `asia-south1` on Nov 8.
Raw review files stay in ignored `.cache/gcp-*-catalog.json`. No APIs were enabled by those GETs.
Use a conservative 744-hour month, no free trial credits and no US-only free-VM assumption.

| Catalog item | INR unit price, before tax | Evidence |
|---|---|---|
| F1Micro on-demand shared-core VM | 0.866592999 per hour | Compute SKU `A929-7679-DC50`, resource group `F1Micro` |
| E2 instance core | 2.494959338 per vCPU hour | Compute catalog, Mumbai |
| E2 instance RAM | 0.334325865 per GiB hour | Compute catalog, Mumbai |
| Zonal standard Persistent Disk | 4.571039999 per GiB month | Compute catalog, Mumbai |

The catalog endpoint is
`https://cloudbilling.googleapis.com/v1/services/6F81-5844-456A/skus?currencyCode=INR`.
E2-micro's price calculation uses 0.25 shared vCPU plus 1 GiB RAM; confirm the final plan's
machine type and displayed SKU estimate before apply.

- F1-micro plus 10 GiB boot and 5 GiB data disks: approximately **INR 841.71 including 18% GST**.
- E2-micro with those disks: approximately **INR 922.01 including 18% GST**.
- Both exclude app compute, registry, secrets, logs, backups and transfer. The larger VM leaves
  insufficient comfortable headroom under this ceiling. F1-micro is a candidate only after a
  low-memory PostgreSQL load/restore check. It is one failure domain, with no HA promise.

Cloud SQL is not the baseline at this budget. Even shared-core managed instances leave too little
room for the rest of the application, and shared-core Cloud SQL has no SLA. See
[Cloud SQL pricing](https://cloud.google.com/sql/pricing). Spot/preemptible compute is not a
sensible way to make the only database appear cheaper.

## Candidate starter deployment to evaluate

1. Web, core and sandbox simulator on Cloud Run Mumbai, request-based billing, zero warm instances,
   explicit small maximum instance counts and database pools. Do not deploy duplicate always-on
   media or worker services before their workload needs them. Migrations and maintenance use jobs.
2. Managed HTTPS `run.app` origin, a production-mode OAuth configuration even for staging, and
   service-account invocation between the public proxy and private backends. No service-account
   JSON keys. No external load balancer, Cloud Armor or paid CDN baseline in the starter tier.
3. Compare private F1-micro PostgreSQL against a free managed PostgreSQL service in Mumbai. The VM
   needs a persistent data disk, no public IP or NAT, restricted firewall/IAP access, tested
   backups, restoration and a patching procedure. A third-party database requires the user's
   choice; do not silently move customer data to another provider or region.
4. If the VM survives the checks, an indicative envelope is INR 842 for VM/disks, INR 47 including
   tax for a small Cloud Run spend-cap allowance, and INR 60 for other services, leaving roughly
   INR 51 of headroom. These last allowances are planning bounds, not verified bills. Measure
   image sizes, retention, egress and backup sizes before treating the plan as fitting the budget.
5. Keep only required secret versions and a small image rollback window, bound object lifecycles,
   filter noisy logs, preserve required security/audit retention, and record a monthly bill review.
   Alerts plus cap enforcement and application quotas must be tested; none justifies a promise
   of an instantaneous project-wide spending stop.
6. Live provider calls have their own per-organization budgets, concurrency, timeouts and text
   fallback. GCP free credits do not pay Gnani, LLM or phone-provider invoices. No paid/live
   external actions are authorized by this architecture review.

For the selected Supabase option, replace item 3's VM with the approved free Mumbai project.
Plan a Cloud Run service spend cap below the total ceiling, for example INR 500 before tax,
plus a small measured storage/registry/secrets/backup allowance and at least INR 200 of headroom.
The final amount depends on billing-account currency, eligibility and the exact plan. No paid
Supabase upgrade, IPv4 add-on, PITR or duplicate staging project is authorized. Check free project
quota and organization plan before creation; never pause/delete an unrelated project to make room.

Pramana uses normal PostgreSQL connections and its own Google identity/session implementation.
Place its tables in a private `pramana` schema, with distinct migration/runtime roles and per-role
search paths, outside Supabase's exposed API schemas. Supabase's default public API grants must
not expose global users, sessions or OAuth-flow tables, which deliberately have no tenant RLS.
Audit grants after each migration. Runtime must have no superuser, BYPASSRLS or table ownership;
events and audit remain append-only and global templates SELECT-only.

Before public deployment, add app quotas for workspace creation, active investigations and storage,
so an authenticated signup cannot exhaust the free database. Bound backup frequency by measured
dump size and the free egress allowance. Verify restoration, not merely upload success. Persist
sealed simulator state separately from the core runtime role before scaling sandbox services.

Supabase's Free plan is a possible Mumbai database alternative with more GCP budget headroom:
[specific region](https://supabase.com/docs/guides/platform/regions),
[plan limits](https://supabase.com/pricing), and
[backup requirements](https://supabase.com/docs/guides/platform/backups). Its 500 MB database can
pause after low activity and has no free automatic backup guarantee. Automated off-site exports,
restore tests and explicit approval of that availability tradeoff are required. Neon was also
checked; [its region list](https://neon.com/docs/introduction/regions) does not currently provide
Mumbai, so it is not the default for the India-resident plan.

## Work still required before approval

Finish R1 tenant routes and UI, durable simulator state, private service authentication, migration
bootstrap, deployment automation, actual resource/cost plan, spend control tests and smoke/restore
checks. A validated Terraform file is not evidence that those integrations are deployed or safe.
Do not run the existing HA apply while this budget review is pending.
