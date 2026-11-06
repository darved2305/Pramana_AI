# Staging

## Architecture

The browser opens the production Next.js app through the Cloudflare Worker HTTPS origin. The
Worker uses a private Workers VPC service and remotely managed Tunnel to reach Next.js on
`127.0.0.1:3002`. Next.js proxies to core at `127.0.0.1:8010` and simulator at
`127.0.0.1:8110`. PostgreSQL remains on the local shared cluster at `localhost:5433` and is not
exposed through the tunnel.

For a quick tunnel from the local dev stack instead (no live events over SSE; the console polls),
start the stack first. On Windows PowerShell use
`.\.venv\Scripts\python.exe scripts\dev.py --web`; on macOS or Linux use
`uv run python scripts/dev.py --web`. The direct Windows invocation prevents `uv` from reporting
its own Ctrl-Break status after the stack has shut down.

```bash
cloudflared tunnel --url http://localhost:3002   # prints https://<random>.trycloudflare.com
```

The Worker passes response streams, redirects, repeated `Set-Cookie` headers, and WebSocket
upgrades through the VPC binding. Client-supplied forwarded headers are replaced with values
derived from the public URL. Gnani, simulator, signing, database, and automation keys stay on the
server. The simulator atomically stores scenario snapshots in `.cache/staging-sim/scenarios.json`;
core events remain in PostgreSQL.

## Setup and operation

The staging task runs from `C:\Dev\Pramana-AI\.claude\worktrees\port-staging`. Keep this worktree
available after merge and update it to the merged main revision before using it for subsequent
staging changes.

The worktree `.env` is copied from `C:\Users\Nikhil\pramana-orch\env.master` only when it does not
already exist. Keep it untracked. Store the remotely managed tunnel token only in
`C:\Users\Nikhil\pramana-orch\secrets\tunnel_token.txt`. The VPC service ID belongs in
`infra/staging-worker/wrangler.jsonc`. The Worker deployment and initial Cloudflare setup are
documented in `infra/staging-worker/README.md`. No payment method is required for the current
setup. Workers VPC is beta; review Cloudflare's [VPC guide](https://developers.cloudflare.com/workers-vpc/get-started/)
and [Workers limits](https://developers.cloudflare.com/workers/platform/limits/) before future
changes.

The current-user ONLOGON task is named `PramanaStaging`. It starts
`scripts/staging-start.ps1`, which selects the public origin and runs
`scripts/staging.py --fake-gnani`. The supervisor starts the shared PostgreSQL cluster only if needed, applies
migrations, builds Next.js when its inputs change, then starts the emulator, simulator, core, web,
and tunnel in readiness order. It binds app services to loopback and restarts failed children with
capped backoff. It never stops or resets the shared database. To remove the task, run
`scripts/staging-uninstall-task.ps1`; this does not stop PostgreSQL or delete databases.

## Public URL and checks

Staging URL: <https://pramana-staging.pramana-staging-worker.workers.dev>.

The initial P4 worktree reported a public acceptance run on 2026-11-06. It covered HTTPS and
readiness, both staff roles, cookie flags, CSRF, SSE and resume, participant and media WSS,
streamed WAV, individual child recovery, and supervisor restart using the local fake Gnani provider.
An independent audit later found the URL returning HTTP 502 and the task stopped. Treat that run
as historical evidence, not proof of current availability.

After porting to the `port-staging` worktree on 2026-11-06, the supervisor was restarted from this
worktree and the ONLOGON task was repointed to it and started. Through the public HTTPS URL, `/`
and `/api/core/ready` returned HTTP 200. Readiness reported database, simulator, and packs as
`ok`. The local Gnani protocol emulator was enabled, and no Gnani credit was used.

The post-port public check did not use Playwright. Both-role sign-in, cookie attributes, CSRF,
live SSE and resume, participant and media WSS, streamed WAV, individual child recovery, and a full
supervisor restart have not been re-verified through the public URL after the outage. A real phone
check and a full laptop reboot remain pending.

Local checks cover Worker request and response pass-through, repeated cookies, redirects, streams,
forwarded headers, and WebSocket forwarding and bridging. Supervisor tests cover startup order,
restart delay, child recovery, secure environment construction, build reuse, and the emulator
command. Simulator restart tests cover repaired state, single-use capabilities, participant
position, and closed scenarios remaining revealable. These tests do not prove the Cloudflare path.

## Limits and teardown

The laptop, power, user login, sleep settings, Internet connection, local PostgreSQL cluster, and
one tunnel connector remain single points of failure. The supervisor can restart its child
processes but cannot recover a sleeping or powered-off laptop. Workers VPC is beta, and active
streams and sockets may be interrupted. A WebSocket bridge would run JavaScript per frame; direct
VPC upgrade forwarding is configured. Public requests, SSE connections, and reconnects consume the
account's Worker quota.

To tear staging down, stop the supervisor, remove the logon task, delete the Worker and VPC service,
and delete the remotely managed tunnel when no longer needed. Keep `.env`, the tunnel token,
simulator state, and PostgreSQL data out of source control. Do not stop or reset the shared
PostgreSQL cluster as part of teardown.
