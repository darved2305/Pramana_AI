# Pramana production status, 2026-11-07

Worktree: `gnani ai hackathon-production`, branch `production`. `main` remains at
`e8194cb14ba62b7066c16485e346c59da60d211c`. No demo database or process was changed.

| Item | State | Evidence |
|---|---|---|
| R0 container images and runtime upstreams | Implemented | `3f0ebdc`; root and web Dockerfiles, `docker/entrypoint.sh`, web `proxy.ts` |
| GCP infrastructure definitions | Implemented and tested locally | `terraform fmt -check -recursive` and `terraform validate`, exit 0; never applied |
| Tenancy schema and UUIDv7/public IDs | Implemented | `5c9ecea`; migration 0008, `ids.py`, organization/user transaction context, non-superuser runtime grants |
| Tenancy database boundaries | Tested locally | 25 ID/RLS tests passed as `pramana_app`, with `PRAMANA_REQUIRE_APP_ROLE=1`; includes missing context, cross-tenant writes and site references, pooled connections, own-membership reads, immutable published/retired models and append-only events |
| Google OIDC and account linking | Implemented and tested locally | Migration 0009; injected mock issuer and `scripts/mock_oidc.py`; PKCE S256, state, nonce, signature/issuer/audience/expiry/authorized-party checks, single-use flows, explicit linking and pre-registration replacement tested as owner and `pramana_app` |
| Hardened sessions and shared password limiter | Implemented and tested locally | Rotation, 60-minute idle and 12-hour absolute deadlines, secure `__Host-` cookies, devices API, cross-instance PostgreSQL failure windows, Clear-Site-Data and stream revocation; 153 focused tests passed in 169.05 s |
| Python regression suite | Tested locally | `uv run pytest -vv -x`: 3,625 passed in 1,075.23 s, exit 0; includes process-level tests and four additional JWKS cache/age cases. Two Workspace alias regressions passed afterwards, verifying Google's verified-email-plus-hd rule without assuming the email domain equals hd |
| Python static gates | Tested locally | Ruff lint and format, mypy (86 source files), 3 import contracts, contracts and OpenAPI drift checks all exit 0 |
| Web static gates | Tested locally | `npm ci`, typecheck, lint, copy, worklet and generated API drift checks all exit 0 |
| UI browser suite and build | Tested locally | 48 passed in 2.2 min, exit 0, port 3112 |
| Real-stack browser suite and build | Tested locally | 23 passed in 2.8 min, exit 0; includes mock Google sign-in/cancellation, S1, S2, S7, parallel calls and repair recovery |
| R0 and tenancy CI | CI green | `56e5bca`, [run 42383301031](https://github.com/darved2305/Pramana-AI-ggw_gnani-hackathon-/actions/runs/42383301031): all five jobs passed; Python 3,526, UI 48, real browser 21, both images and Terraform |
| Google auth CI | CI green | `87e05bd`, [run 42387269258](https://github.com/darved2305/Pramana-AI-ggw_gnani-hackathon-/actions/runs/42387269258): all five jobs passed. Draft [PR #3](https://github.com/darved2305/Pramana-AI-ggw_gnani-hackathon-/pull/3) remains unmerged |
| Docker image builds locally | Not run | Docker Desktop was not running. R0/tenancy images were built and smoke-tested in CI |
| Real Google sign-in | Not run | User has the exact redirect URI and .env fields for GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_CLIENT_SECRET. Browser/native control is disconnected; the user must perform the Google console and sign-in steps |
| Staging or production deployment | Not run | No Terraform apply, cloud resources or live provider calls in this session |
| Onboarding with real people | Not run | No usability sessions; the under-three-minute target remains unvalidated |

All database tests used `pramana_prod_test` and `pramana_prod_e2e`. The local logs are in the
ignored `.cache/production-*.log` files. No credentials or provider measurements were committed.

## Remaining work

Slice 1 establishes the schema and database boundaries. Organization-scoped routes, the tenant
leak generator covering every route, and stored sandbox provisioning remain with the later API
slices. Legacy routes do not yet establish tenant context, so this is not a deployable multi-tenant
release.

Slice 2's core mock flow is integrated and tested. Complete Google validation after the user
configures the client. ID-03 through ID-07 require Slice 5 invitations/domains; full ID-01/02
onboarding, ID-11 ownership guidance, ID-13 draft recovery and ID-14 UI banners also depend on
later slices. The auth tests establish their prerequisites, not completion of those product
flows. The Google button, account/device UI and error messages remain Slice 6 work.

Slice 3 is next: idempotency, `/v1/me`, survey state and organization/sandbox provisioning. Notes
are in ignored `.cache/production-slice3-design.md`. Slices 3 through 7 remain pending. Idempotency
must support user scope before an organization exists; the original schema sketch's org-only
primary key cannot represent POST /v1/orgs.

Infrastructure is still unapplied. Production core containers now receive production mode, a
domain-based HTTPS callback, and separate runtime/migrator secret access. Runtime service
accounts cannot read the simulator oracle. IAM database token/connection integration, secret
bootstrap ordering and a staging connectivity check remain deployment work. Validation alone
does not establish a working deployment.

## Failures corrected

The first [CI run 42382918084](https://github.com/darved2305/Pramana-AI-ggw_gnani-hackathon-/actions/runs/42382918084)
failed in the image smoke check: `AttributeError: 'DomainPack' object has no attribute 'id'`.
The image itself built. `56e5bca` changed the check to the real `version` field; the next run
passed all five jobs. A local secure-cookie test initially passed an `httpx.URL` to Starlette's
`httpx2` base URL setter; using a string fixed that test harness mismatch. The focused and full
suites passed afterwards.

STOP 1 is answered: branch work starts now, GCP `asia-south1`, product name Pramana, domain
undecided. Google OAuth client values have been requested in the production `.env` for one real check.
STOP 2 remains in force before any cloud apply. No cloud credentials are needed yet.
