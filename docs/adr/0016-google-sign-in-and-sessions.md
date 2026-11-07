# 0016: Google sign-in in the core; identities keyed by `sub`; linking rules; session hardening

**Status:** proposed

**Amends:** 0010 (authentication). Server-side sessions, the `X-Pramana-CSRF` header rule and
`SELF_APPROVAL` stay. Accounts are no longer created only from the command line, and the shared
automation key is not allowed in production.

**Context.** PRODUCTION.md §5. Accounts are created by `auth/bootstrap.py`; the login page says
"Accounts are created by your site operator" and password reset throws. A product needs
self-serve sign-up, and staff in India mostly have Google accounts (Gmail or Workspace).

**Options compared.**

| Option | For | Against |
|---|---|---|
| **The core implements Google OIDC (Authlib), sessions in PostgreSQL** | One session authority for REST, SSE and both WebSocket kinds; roles live with the data; no extra party holds personal data | We own the flow, the linking rules and their tests |
| Auth.js or Better Auth in Next.js | Mature UI | Two session authorities, or tokens passed between Next and the core |
| Hosted identity (Clerk, WorkOS, Auth0) | SSO and SCIM later | A vendor in every request path; residency to check; per-user cost |
| Supabase Auth or Firebase | Managed Google sign-in | Its own sessions and JWTs beside ours |

**Decision.**
- Authorization code flow with PKCE (S256), `state` and `nonce`, scopes `openid email profile`
  only. In-flight sign-ins live in `auth_flows` (single use, 10 minutes, keyed by the hash of an
  opaque cookie). Google's discovery document advertises S256 (checked 2026-11-07).
- ID token checks: signature against the issuer's JWKS, `iss`, `aud`, `exp`, then `nonce` and
  `hd` ourselves, because Google's library verifiers check only the first four.
- The issuer comes from a configurable discovery URL. Tests use a mock issuer (an in-process fake
  for pytest, `scripts/mock_oidc.py` for local browsers). A production process refuses to start
  with a non-Google issuer or with `CORE_AUTOMATION_KEY` set.
- `user_identities` is keyed by `(provider, sub)`, never by email. Linking follows §5.3: a
  verified existing account is never merged silently; an unverified record with the same email
  is discarded and its sessions revoked (pre-hijacking defence); an email Google is not
  authoritative for cannot accept invitations until verified.
- Sessions: 256-bit ids, only SHA-256 stored; a new id on every sign-in and role change; idle
  timeout 60 minutes, absolute 12 hours; the `__Host-` cookie prefix whenever cookies are
  `Secure`; a signed-in devices list with "sign out other devices"; logout sends
  `Clear-Site-Data`.
- Password sign-in stays for existing and automation accounts.

**Consequences.** Sign-in needs a Google OAuth client per environment and exact redirect URIs.
Sign-in is only as available as Google's endpoints, which is acceptable for a staff console;
password accounts remain a fallback for operators. Enterprise SSO (SAML, SCIM) waits for a
customer who asks.

**Tests.** Rows ID-01 to ID-17 of PRODUCTION.md §6.2 at the API level, with the mock issuer:
bad signature, wrong `aud`, wrong `iss`, expired token, nonce mismatch, replayed callback (ID-17),
stale `state` (ID-16), email change found by `sub` (ID-10), unverified pre-registration (ID-09),
and a production-settings test that refuses a non-Google issuer and the automation key.
