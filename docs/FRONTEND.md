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

The Russian-language dashboard uses the real FastAPI service. Start both services
with `./run.sh all`, select a turbine/date/horizon, and click «Рассчитать прогноз».
The browser uses the same-origin `/api` proxy configured by `RENTBOX_API_URL`.
See [integration guide](frontend-integration.md) for configuration and API mappings.

- Real 24/48-hour model predictions, normalized power displayed as percent.
- Actual agent status, progress, events and errors; polling every 1.5 seconds.
- Server history from DuckDB: the latest 100 runs, including failed and pending jobs.
- Hourly table, point inspection, source metadata and original server CSV download.
- Turbine names and coordinates from the API; dataset audit and research-mode warnings.
- Display time UTC+5; the date picker maps February 1 to issuance January 31, 18:00 UTC.

February observations, forecast error, calibrated uncertainty intervals, and numerical
weather fields are unavailable in the current API. They remain null/blank; synthetic
values are not substituted. The station view averages normalized power across the two
turbines. It does not represent a sum in MW. CSV preserves the server's 0–1 scale and
contains the entire selected run, even when the chart shows just one turbine.

### Implementation

- `apps/web/lib/forecast-api.ts`: contract types, requests, export and display mapping.
- `apps/web/lib/use-forecast-dashboard.ts`: loading, submission, polling and recovery.
- `apps/web/lib/forecast-data.ts`: shared display types/metrics plus retained legacy fixtures;
  the running dashboard does not call its synthetic generator or CSV serializer.
- `apps/web/components/wind-dashboard.tsx`: interactive views and charts.
- `apps/web/app/dashboard.css`: responsive visual system.

TypeScript and ESLint are the static checks for this integration. Automated tests,
browser QA and a Docker build were not run for this change. Existing legacy fixture
tests are not evidence of a working API integration.

## Interactive Blender turbine

The overview includes an original turbine modeled in Blender 5.2 through [MCP for Blender](https://github.com/ahujasid/mcp-for-blender). No external models or textures were used. This is a visual illustration, not an engineering replica of the case turbines.

- `assets/blender/windcast-turbine.blend`: editable scene, studio lighting, and camera.
- `scripts/blender/create_wind_turbine.py`: procedural source for the tower, nacelle, three profiled blades, foundation, and details.
- `apps/web/public/models/windcast-turbine.glb`: self-contained browser asset, approximately 1.6 MB. The `Rotor` node groups the hub and three blades for animation.
- `apps/web/public/models/windcast-turbine.png`: transparent fallback render.
- `apps/web/components/turbine-stage.tsx`: lazy-loaded Three.js viewer driven by dashboard state, with an animation pause control. Manual camera rotation, zoom, and drag are disabled.
- `apps/web/components/turbine-hero.tsx`: persistent scene panel connected to the section, selected turbine, selected hour, forecast horizon, and server agent stage.

The browser uses [Three.js](https://threejs.org/) (MIT), installed through npm. Blender and MCP are authoring tools only; they are not needed to run the dashboard. WebGL failure falls back to the still render. Animation respects reduced-motion preferences, pauses offscreen, and releases its GPU resources when leaving the overview.

Rotor motion is illustrative, not measured RPM. The current API does not provide numerical wind values, so flow and rotor motion remain stopped. The model power values are real predictions; the geometry remains illustrative.

To regenerate the GLB and editable scene from the repository root (Blender on PATH):

```bash
blender --background --python scripts/blender/create_wind_turbine.py
```

Add `-- --render` to also regenerate the PNG using Cycles. The script writes only the three generated assets listed above. MCP configuration is local to the author's machine and is not required by the app.

### Scene behavior

| Dashboard interaction                               | 3D response                                                                                                                         |
| --------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------- |
| Overview / forecast                                 | Power follows the selected forecast hour; wind-driven motion requires weather values.                                                                        |
| AI agent                                            | Close-up cutaway exposes the shaft, gearbox, and generator modeled in Blender. Component buttons change emphasis and camera target. |
| Sources                                             | Wind and air-temperature selections focus the illustrative measurement location. Power opens the nacelle to show the generator.     |
| History                                             | A still turbine shows a snapshot. Opening a saved run restores its filters and resets the selected hour.                            |
| Hour slider, chart pointer/keyboard, hourly details | The scene metrics and animation follow the same selected hourly point.                                                              |
| Weather hour                                        | Opens the source view; no ice diagnosis is inferred from missing weather values.                         |
| Running API agent                                  | Follows actual backend stages through inputs, model, prediction, review and saving.                           |

There are no OrbitControls, pointer-driven camera handlers, or drag-to-rotate controls. Camera poses interpolate when the section or inspection target changes. Reduced-motion preferences disable animation and snap camera transitions. A user can pause motion independently.

MOCK: ice is a deliberate educational visualization, not an inferred diagnosis. Humidity, liquid water content, and ice sensor measurements are absent; the UI does not invent an icing probability or loss percentage, and does not change the forecast because the illustration is active. The rotor freezes in ice view to make the blades inspectable, not to claim a real turbine shutdown. Mechanical geometry is a generic geared turbine, not the confirmed design of the case assets.

Reference material: [DOE wind turbine components](https://www.energy.gov/cmei/systems/explore-wind-turbine-text-version) and [IEA Wind Task 19 ice detection guidelines](https://iea-wind.org/wp-content/uploads/2022/09/Task-19-Technical-Report-on-Ice-Detection-Guidelines-for-Wind-Energy-Applications.pdf). The procedural geometry is original; no third-party model was imported.

Checks: `npm test` covers scene selection during agent execution, horizon bounds, illustrative motion rules, and the self-contained GLB's blade/drivetrain structure, alongside the forecast tests. Browser QA of the new API integration remains to be performed.
