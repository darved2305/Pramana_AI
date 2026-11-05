# Phones on a free tunnel (no server, no cost)

Participants' phones need an HTTPS address: browsers allow the microphone only on secure
origins. The free route is a Cloudflare quick tunnel from the laptop running the stack.

```bash
uv run python scripts/dev.py --web          # database, simulator, core, console on :3002
cloudflared tunnel --url http://localhost:3002   # prints https://<random>.trycloudflare.com
```

Install `cloudflared` once with `winget install Cloudflare.cloudflared`. A quick tunnel needs no
Cloudflare account; its address changes on every run and lasts as long as the command runs.
Cloudflare documents quick tunnels as for testing only, with no uptime guarantee and a limit of
200 requests in flight (https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/).

## What was checked through a live tunnel (2026-11-05)

| Path | Result |
|---|---|
| Pages and the core API through the web app's `/api/core` proxy | Work |
| WebSockets (the voice socket and the participant call) | Work: the core's own close codes reach the client (4401 for a forged token) and a whole call handshake ran (ringing, decline, ended) |
| Server-sent events (the console's live stream) | **Not delivered**: the response opens with status 200 and then nothing arrives, as Cloudflare documents ("Quick Tunnels do not support Server-Sent Events") |

Because the stream fails silently rather than with an error, the console waits at most 5 s for
the server's `ready` event and then polls the event log instead
(`apps/web/src/lib/data/hooks.ts`, `tests/stream-fallback.spec.ts`). Over a quick tunnel the
console therefore updates every few seconds rather than instantly. A named Cloudflare Tunnel
(free account) supports SSE.

## Before opening a tunnel

- Sign-in is enforced; create a staff user with `uv run python -m pramana_core.auth.bootstrap`.
- Join links show a participant only their own part of an investigation.
- Paid voice routes are staff only, and the daily voice budget cap applies.
- Make sure the processes on the tunnelled ports are the current code: an old core left
  running on :8000 will be served instead. Check `GET /ready` (all checks `ok`).
