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
npm run test:e2e     # Playwright; starts its own server on port 3012
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
| `src/lib/store` | Browser storage: history, roster, preferences, preview flag |

## What is not connected yet

The core has no routes for these, so the screens say so instead of faking them:

- Sign-in. `src/lib/api/auth.ts` defines the boundary; every call fails with `AUTH_NOT_CONNECTED`.
- Listing investigations. History holds the ones started from this browser; any other opens by ID.
- A participant directory. The roster lives in this browser and is sent with each new investigation.
- Evaluation results. The page renders a `summary.json` from `eval/reports` that you load.

## Fonts

Inter, Geist and Besley match the reference. Its display faces, PP Right Slab and FT Activica,
are commercial: put licensed files in `public/fonts/` (see the README there) and they are used
automatically. Until then Zilla Slab and Geist Pixel stand in.
