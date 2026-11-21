# HappyClaw web (`web/`)

The new frontend. It runs beside the existing `dashboard/` until the migration in
[`docs/MIGRATION-PLAN.md`](docs/MIGRATION-PLAN.md) finishes; neither app owns a
backend route the other needs exclusively, so both can be served at once.

## Stack

| Concern | Choice | Why |
| --- | --- | --- |
| Build | Vite 8 + React 19 + TypeScript 5.9 (strict) | Same toolchain the team already runs, one generation newer. |
| Styling | Tailwind CSS 4 + a local component layer | No Ant Design: its reset, spacing rhythm and DOM shape were the thing being replaced. Tokens are CSS variables, so theming is a variable swap. |
| Routing | TanStack Router (file-based, auto code-splitting) | Typed links and params; each route ships as its own chunk. |
| Server state | TanStack Query | Retries, staleness and cache invalidation in one place. |
| Client state | zustand | Theme, locale, sidebar and toasts; no provider pyramid. |
| Copy | i18next (`zh` / `en`, key-parity checked) | `npm run check:i18n` fails on any key that exists in one locale only. |
| API types | `openapi-typescript` + `openapi-fetch` | Types are generated from the backend's own OpenAPI document, never hand-written. |

## Commands

```bash
npm ci               # install exactly what package-lock.json pins
npm run dev          # dev server on http://localhost:5174 (proxies /api)
npm run build        # tsc -b && vite build
npm run typecheck    # tsc -b
npm run lint         # eslint .
npm run check:i18n   # locale key parity
npm run api:sync -- <path-to-live-openapi.json>   # refresh openapi/octop.openapi.json
npm run api:gen                                    # regenerate src/lib/api/schema.gen.ts
```

## Talking to the backend

In development the Vite server proxies `/api` to `HAPPYCLAW_API_ORIGIN`
(default `http://127.0.0.1:8080`, where `octop run` listens), so the browser
sees a single origin and cookies/SSE/websockets behave as they will in
production. Set the variable in `web/.env.local` to point somewhere else.

In production the built `web/dist` is served by FastAPI itself, so the API is
same-origin and `VITE_API_BASE` stays empty. Set it only for a cross-origin
deployment (a separate host serving the SPA).

If the backend is not reachable, the Chat page falls back to sample data and
says so in its toolbar. Nothing else invents data: the Settings page reports the
server as unreachable instead of showing fake values.

## Layout

```
src/
  app/          router, query client, providers, error boundary
  routes/       file-based route tree (thin: each file mounts a feature)
  features/     chat/ settings/ design/ — page + its queries + its components
  components/
    ui/         the design system: 24 primitives, no UI library
    layout/     app shell, sidebar, topbar, mobile navigation
  lib/          api client, i18n, formatting, storage, env
  stores/       zustand UI store (theme, locale, sidebar)
  styles/       tokens.css (the design tokens) + index.css (Tailwind bridge)
  locales/      en/ and zh/, one JSON namespace per feature
openapi/        the backend OpenAPI document the client types are generated from
docs/           migration plan and the dashboard inventory it is based on
```

`/design` renders every token and every component, in both themes. It is the
reference a reviewer opens instead of reading class names.

## Conventions

- Components name semantic roles (`bg-surface`, `text-fg-muted`), never hex
  values or palette steps. A raw colour in a component is a bug.
- A feature owns its API wrappers and queries; `lib/api` owns only the client and
  the generated types.
- Loading, empty and error states come from `LoadingBlock`, `Skeleton*` and
  `EmptyState` — one shape per state across the whole app.
- Every user-visible string goes through i18next, added to both locales in the
  same commit.
