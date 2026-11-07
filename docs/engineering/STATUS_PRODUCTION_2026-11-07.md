# Pramana production status, 2026-11-07

Worktree: `gnani ai hackathon-production`, branch `production`. `main` remains at
`e8194cb14ba62b7066c16485e346c59da60d211c`. No demo database or process was changed.

| Item | State | Evidence |
|---|---|---|
| R0 container images and runtime upstreams | Implemented | `3f0ebdc`; root and web Dockerfiles, `docker/entrypoint.sh`, web `proxy.ts` |
| GCP infrastructure definitions | Implemented and tested locally | `terraform fmt -check -recursive` and `terraform validate`, exit 0; never applied |
| Tenancy schema and UUIDv7/public IDs | Implemented | Migration 0008, `ids.py`, organization/user transaction context, non-superuser runtime grants |
| Tenancy database boundaries | Tested locally | 25 ID/RLS tests passed as `pramana_app`, with `PRAMANA_REQUIRE_APP_ROLE=1`; includes missing context, cross-tenant writes and site references, pooled connections, own-membership reads, immutable published/retired models and append-only events |
| Python regression suite | Tested locally | `uv run pytest`: 3,521 passed in 874.89 s, exit 0, including process-level tests. This run preceded the additional migration hardening; the 25-test focused run verified that hardening afterwards |
| Python static gates | Tested locally | Ruff lint and format, mypy (83 source files), 3 import contracts, contracts and OpenAPI drift checks all exit 0 |
| Web static gates | Tested locally | `npm ci`, typecheck, lint, copy, worklet and generated API drift checks all exit 0 |
| UI browser suite and build | Tested locally | 48 passed in 1.7 min, exit 0, port 3112 |
| Real-stack browser suite and build | Tested locally | 21 passed in 2.6 min, exit 0; includes S1, S2, S7, parallel calls and repair recovery |
| CI for production branch | Pending | Draft PR to be opened after the tenancy commit. Local checks are not a CI result |
| Docker image builds locally | Not run | Docker Desktop was not running; the CI images job must establish this result |
| Staging or production deployment | Not run | No Terraform apply, cloud resources or live provider calls in this session |
| Onboarding with real people | Not run | No usability sessions; the under-three-minute target remains unvalidated |

All database tests used `pramana_prod_test` and `pramana_prod_e2e`. The local logs are in the
ignored `.cache/production-*.log` files. No credentials or provider measurements were committed.

## Remaining work

Slice 1 establishes the schema and database boundaries. Organization-scoped routes, the tenant
leak generator covering every route, and stored sandbox provisioning remain with the later API
slices. Legacy routes do not yet establish tenant context, so this is not a deployable multi-tenant
release.

Slice 2 is next: `joserfc` and `httpx`, Google OIDC with an injected mock transport, account-linking
rules and hardened sessions. Local preparation is parked in ignored `.cache/` files until the
tenancy commit is pushed. It is not integrated or tested yet. Slices 3 through 7 remain pending.

STOP 1 is answered: branch work starts now, GCP `asia-south1`, product name Pramana, domain
undecided. Ask for Google OAuth client values in `.env` only after the mock Slice 2 flow passes.
STOP 2 remains in force before any cloud apply. No cloud credentials are needed yet.
