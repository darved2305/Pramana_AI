# Pramana staging Worker

This Worker exposes the production Next.js app on the laptop through a private Workers VPC
service. It is the only public origin. The browser reaches the core and simulator through the
existing same-origin Next.js rewrites.

## Local checks

```powershell
npm ci
npm test
npm run typecheck
```

Wrangler and the test tools are pinned in `package-lock.json`. Worker unit tests use a fake VPC
binding and do not need Cloudflare credentials.

## One-time Cloudflare setup

1. Sign in with `npx wrangler login`, then check `npx wrangler whoami`. Workers VPC is currently
   in beta and available without an upgrade or payment method.
2. Create a remotely managed tunnel in Workers VPC, or use Wrangler:

   ```powershell
   npx wrangler tunnel create pramana-staging
   ```

   Keep the tunnel ID. The connector token is a secret. Save it only as
   `C:\Users\Nikhil\pramana-orch\secrets\tunnel_token.txt`. Do not put it in a command line,
   the repository, logs, or this document. The installed `cloudflared` supports `--token-file`.
3. Create an HTTP VPC service on the tunnel for the loopback Next.js origin:

   ```powershell
   npx wrangler vpc service create pramana-staging-origin --type http --tunnel-id <TUNNEL_ID> --ipv4 127.0.0.1 --http-port 3002
   ```

   Put the returned service ID in the `ORIGIN` entry in `wrangler.jsonc`. Keep the VPC service
   pointed at `127.0.0.1:3002`; do not expose the core or simulator as separate services.
4. Deploy the Worker with `npm run deploy`. Wrangler prints the stable `workers.dev` URL. Set
   `PRAMANA_STAGING_PUBLIC_ORIGIN` in the worktree `.env` to that HTTPS origin. The supervisor
   uses it for public readiness and participant simulator links.

If Wrangler cannot create or bind a tunnel or service, use the Cloudflare dashboard at
**Zero Trust > Networks > Tunnels** and **Workers VPC > VPC Services**. The account role needs
Connectivity Directory Admin to create services and Bind to bind an existing service.

## Proxy behavior

HTTP requests keep their method, path, query, body, and end-to-end headers. Client-supplied
`Forwarded` and `X-Forwarded-*` headers are discarded. The Worker writes trusted forwarded host,
scheme, and port values from the public request URL. Redirects, repeated `Set-Cookie` headers,
and response streams pass through without being reconstructed.

WebSocket upgrades are forwarded directly through the VPC binding by default. If an account test
shows the binding returns an accepted upstream socket but direct 101 pass-through does not work,
set `BRIDGE_WEBSOCKETS` to `true` in Wrangler configuration. That fallback bridges text and binary
frames and closes both sockets on an error. Direct forwarding stays the default to avoid JavaScript
work for every audio frame.
