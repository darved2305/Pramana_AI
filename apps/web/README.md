# Pramana web

The public site, the investigation console and the participant page.

## Run

```bash
cd apps/web
npm install
npm run dev        # http://localhost:3002
```

The console talks to the core (`make core`, port 8000) and the simulator (`make sim`, port 8100)
through same-origin rewrites in `next.config.ts`, so the backend's CORS settings never need to
change. Override the targets with `PRAMANA_CORE_URL` and `PRAMANA_SIM_URL`.

Open `/preview/app` to explore every screen with clearly labelled sample data and no backend.

## Checks

```bash
npm run typecheck
npm run lint
npm run check:copy   # fails on any em dash in frontend source
npm run build
npm run test:e2e     # Playwright with mocked responses; own server on port 3012 (PW_PORT)
npm run test:e2e:real  # Playwright against a real core, simulator and test database
```

## Layout

| Path | What |
|---|---|
| `src/app` | Routes: `/`, `/login`, `/preview/app`, `/app/**`, `/join/[token]` |
| `src/components/landing` | Public site sections |
| `src/components/voice/VoiceField.tsx` | Canvas voice visual; `level` accepts a live audio level |
| `src/components/app`, `src/components/console` | Console shell, building map and command-center panels |
| `src/components/ui` | Buttons, chips, cards, fields, tabs, dialog, icons |
| `src/lib/api` | The only network layer: typed core and simulator clients, auth boundary |
| `src/lib/api/schema.gen.ts` | Generated from `services/core/openapi.json` with `npm run gen:api` |
| `src/lib/data` | Data hooks (live or preview) and pure derivations |
| `src/lib/preview` | Preview fixtures, loaded only in preview mode |
| `src/lib/store` | Browser storage: display preferences and the preview flag |

## Sign-in and data

- **Staff sign in** at `/login` (email and password; the core sets an httpOnly session cookie,
  docs/adr/0010-authentication.md). Create accounts with
  `uv run python -m pramana_core.auth.bootstrap --email ... --name ... --roles operator,approver`.
  Console pages send a signed-out visitor to `/login` and back afterwards.
- **Approvals** record the signed-in approver; there is no name field to fill in.
- **Participants** never sign in: the link from the command center carries their own token,
  which the core accepts only for their own questions and actions.
- **Investigations, the participant directory, site packs and benchmark runs** all come from
  the core (`GET /v1/investigations`, `/v1/participants`, `/v1/packs`, `/v1/evaluation/reports`).
  Only display preferences are stored in the browser.
- Live updates poll the event log. `useInvestigation` takes an `EventSource`, so a push channel
  can replace polling without touching the screens.

## Tests against a real backend

`npm run test:e2e:real` migrates a fresh test database, starts the simulator, the core and this
app, then drives the console and the participant pages end to end (`tests-real/`). Set both
`E2E_DATABASE` and `PRAMANA_DB_NAMES`; the selected `_e2e` database must appear in that explicit
allowlist. The runner stops before connecting if either value is missing or inconsistent.

## Fonts

Inter, Geist and Besley match the reference. Its display faces, PP Right Slab and FT Activica,
are commercial: put licensed files in `public/fonts/` (see the README there) and they are used
automatically. Until then Zilla Slab and Geist Pixel stand in.

## Security notes

The npm audit finding for `minimatch` comes through the development-only ESLint dependency chain.
The installed `@typescript-eslint/typescript-estree` module imports and invokes it in an optional
project matching path. The current dependency range selects an affected release, while
`npm audit fix --force` would downgrade `eslint-config-next` to Next 15. The scoped override pins
the transitive dependency under `@typescript-eslint/typescript-estree` to patched version
11.0.1, preserving Next 16. Keep the override until the upstream dependency range includes a
patched release.
