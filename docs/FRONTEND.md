# Windcast dashboard

Next.js monorepo with shadcn/ui (Vega, Base UI), Tailwind CSS, TypeScript, npm workspaces, and Turborepo.

## Development

Use Node.js 22.20 or newer and npm 11.

```bash
npm install
npm run dev
```

Open http://localhost:3000.

## Workspace structure

- `apps/web`: Next.js application.
- `packages/ui`: shared UI components, styles, and utilities.
- `packages/eslint-config`: shared ESLint configuration.
- `packages/typescript-config`: shared TypeScript configuration.

## Checks

```bash
npm run build
npm run lint
npm run typecheck
npm test
```

## Adding UI components

Run from the repository root:

```bash
npx shadcn@latest add card -c apps/web
```

Import shared components from `@workspace/ui/components/*`.

## Windcast dashboard

The root page implements a Russian-language dashboard for the [wind farm forecasting case](https://docs.google.com/document/d/1Fn5IJoj87Fx7IAknG26zkfX8c0eq7feCujd0m66PCgY/preview).

- Overview with normalized generation, peak power, wind speed, nMAE, weather, and two turbine cards.
- Interactive hourly forecast: 24/48-hour horizons, turbine/date filters, forecast/actual comparison, illustrative uncertainty band, keyboard and pointer inspection.
- February 1–28, 2026 retrospective dates. A forecast for each day is issued at 23:00 on the previous day, UTC+5.
- Searchable and sortable hourly table, pagination, detail dialogs, and UTF-8 CSV export with source timestamps.
- Six-stage simulated AI-agent cycle with an event log and session-local run history. Open a run to restore its forecast settings.
- Source availability timeline, original turbine map links, and responsive navigation with keyboard support.

### Data and limitations

All displayed values are deterministic synthetic data. No external weather API, SCADA dataset, trained ML model, authentication, or backend persistence is connected. Reloading resets the session history. Source names illustrate potential integrations, not active connections.

Power is expressed as a percentage of nominal capacity because installed MW capacity is not provided by the case. The station view averages both turbines' normalized outputs. Full-load hours are the sum of hourly normalized power fractions. nMAE and RMSE use only available mock observations; they do not claim real model accuracy. The uncertainty band is illustrative and has no calibrated confidence level.

Weather issue and availability timestamps precede forecast issuance. Observed values are generated separately and never used as forecast inputs. A 48-hour forecast beginning February 28 continues into March; March observations remain unavailable. The training cutoff is January 31, 2026, at 23:00 UTC+5.

### Implementation

- `apps/web/lib/forecast-data.ts`: deterministic fixtures, time provenance, metrics, and CSV serialization.
- `apps/web/components/wind-dashboard.tsx`: interactive views and charts.
- `apps/web/app/dashboard.css`: responsive visual system.
- `tests/forecast-data.test.mjs`: chronology, availability, bounds, aggregation, February/March boundary, and CSV checks.

The frontend can be connected to a forecasting service by replacing the mock data generator while retaining the forecast-point schema and source timestamps.
