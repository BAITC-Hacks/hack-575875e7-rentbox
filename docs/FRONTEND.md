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

## Interactive Blender turbine

The overview includes an original turbine modeled in Blender 5.2 through [MCP for Blender](https://github.com/ahujasid/mcp-for-blender). No external models or textures were used. This is a visual illustration, not an engineering replica of the case turbines.

- `assets/blender/windcast-turbine.blend`: editable scene, studio lighting, and camera.
- `scripts/blender/create_wind_turbine.py`: procedural source for the tower, nacelle, three profiled blades, foundation, and details.
- `apps/web/public/models/windcast-turbine.glb`: self-contained browser asset, approximately 1.6 MB. The `Rotor` node groups the hub and three blades for animation.
- `apps/web/public/models/windcast-turbine.png`: transparent fallback render.
- `apps/web/components/turbine-stage.tsx`: lazy-loaded Three.js viewer driven by dashboard state, with an animation pause control. Manual camera rotation, zoom, and drag are disabled.
- `apps/web/components/turbine-hero.tsx`: persistent scene panel connected to the section, selected turbine, selected hour, forecast horizon, and mock agent stage.

The browser uses [Three.js](https://threejs.org/) (MIT), installed through npm. Blender and MCP are authoring tools only; they are not needed to run the dashboard. WebGL failure falls back to the still render. Animation respects reduced-motion preferences, pauses offscreen, and releases its GPU resources when leaving the overview.

MOCK: rotor speed is an illustrative function of the displayed synthetic wind speed; it is not measured turbine RPM. The dashboard explicitly labels its demo data and simplified geometry.

To regenerate the GLB and editable scene from the repository root (Blender on PATH):

```bash
blender --background --python scripts/blender/create_wind_turbine.py
```

Add `-- --render` to also regenerate the PNG using Cycles. The script writes only the three generated assets listed above. MCP configuration is local to the author's machine and is not required by the app.

### Scene behavior

| Dashboard interaction                               | 3D response                                                                                                                         |
| --------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------- |
| Overview / forecast                                 | Wind streams and rotor motion follow the selected mock hour.                                                                        |
| AI agent                                            | Close-up cutaway exposes the shaft, gearbox, and generator modeled in Blender. Component buttons change emphasis and camera target. |
| Sources                                             | Wind and air-temperature selections focus the illustrative measurement location. Power opens the nacelle to show the generator.     |
| History                                             | A still turbine shows a snapshot. Opening a saved run restores its filters and resets the selected hour.                            |
| Hour slider, chart pointer/keyboard, hourly details | The scene metrics and animation follow the same selected hourly point.                                                              |
| Weather hour                                        | Opens a labeled ice illustration for a sub-zero mock temperature, or the temperature source view otherwise.                         |
| Running demo agent                                  | Automatically advances through weather inputs, cutaway, forecast, analysis illustration, and publication.                           |

There are no OrbitControls, pointer-driven camera handlers, or drag-to-rotate controls. Camera poses interpolate when the section or inspection target changes. Reduced-motion preferences disable animation and snap camera transitions. A user can pause motion independently.

MOCK: ice is a deliberate educational visualization, not an inferred diagnosis. Humidity, liquid water content, and ice sensor measurements are absent; the UI does not invent an icing probability or loss percentage, and does not change the forecast because the illustration is active. The rotor freezes in ice view to make the blades inspectable, not to claim a real turbine shutdown. Mechanical geometry is a generic geared turbine, not the confirmed design of the case assets.

Reference material: [DOE wind turbine components](https://www.energy.gov/cmei/systems/explore-wind-turbine-text-version) and [IEA Wind Task 19 ice detection guidelines](https://iea-wind.org/wp-content/uploads/2022/09/Task-19-Technical-Report-on-Ice-Detection-Guidelines-for-Wind-Energy-Applications.pdf). The procedural geometry is original; no third-party model was imported.

Checks: `npm test` covers scene selection during agent execution, horizon bounds, illustrative motion rules, and the self-contained GLB's blade/drivetrain structure, alongside the forecast tests. Browser QA covers navigation, component selection, timeline synchronization, and responsive layout.
