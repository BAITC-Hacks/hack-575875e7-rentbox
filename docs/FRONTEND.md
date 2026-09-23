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

The root page implements a Russian, English, and Kazakh dashboard for the [wind farm forecasting case](https://docs.google.com/document/d/1Fn5IJoj87Fx7IAknG26zkfX8c0eq7feCujd0m66PCgY/preview).

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

The browser uses [Three.js](https://threejs.org/) (MIT), installed through npm. Blender and MCP are authoring tools only; they are not needed to run the dashboard. WebGL failure falls back to the still render. Animation respects reduced-motion preferences, pauses offscreen, and releases its GPU resources when the viewer unmounts.

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

MOCK: ice is a deliberate educational visualization, not an inferred diagnosis. Humidity, liquid water content, and ice sensor measurements are absent; the UI does not invent an icing probability or loss percentage, and does not change the forecast because the illustration is active. In the retrospective forecast, the rotor freezes in ice view to make the blades inspectable, not to claim a real turbine shutdown. In a live generation simulation, the ice layer does not itself freeze the rotor: positive simulated output keeps it rotating, while zero output stops it. Mechanical geometry is a generic geared turbine, not the confirmed design of the case assets.

Reference material: [DOE wind turbine components](https://www.energy.gov/cmei/systems/explore-wind-turbine-text-version) and [IEA Wind Task 19 ice detection guidelines](https://iea-wind.org/wp-content/uploads/2022/09/Task-19-Technical-Report-on-Ice-Detection-Guidelines-for-Wind-Energy-Applications.pdf). The procedural geometry is original; no third-party model was imported.

Checks: `npm test` covers scene selection during agent execution, horizon bounds, illustrative motion rules, and the self-contained GLB's blade/drivetrain structure, alongside the forecast tests. Browser QA covers navigation, component selection, timeline synchronization, and responsive layout.


## Dashboard v2 and languages

This version is isolated on `design/dashboard-v2`. The previous frontend is preserved at tag `dashboard-before-v2` (commit `1428a97`); `main` is not merged with v2. With a clean working tree, `git switch main` returns to the previous branch. To inspect the exact baseline, use `git switch --detach dashboard-before-v2`; `git switch design/dashboard-v2` restores v2. Keep any unrelated local changes saved before switching.

- Overview and forecast put the four KPIs first, followed by a chart and compact turbine panel. Smaller screens stack the panels. Text and chart contrast have been increased.
- One selected hour drives the chart, weather readout, turbine metrics, and scene. The shared timeline includes dates for 48-hour forecasts, arrow-key controls, and peak/cold shortcuts.
- Three insight cards jump to the highest/lowest forecast power and lowest air temperature. The cold card selects the educational icing scene below freezing, otherwise the temperature source. These summaries never read retrospective actual power and do not diagnose ice.
- Labels attach to projected model locations and can select the shaft, gearbox, generator, or weather source. Inactive drivetrain parts are dimmed; the camera remains controlled by the system.
- The header language selector offers **Русский / English / Қазақша** without reloading or resetting forecast settings. It translates navigation, tooltips, dialogs, notices, sources, agent stages, and 3D labels. The document language/title and displayed dates/numbers follow the selection.
- The preference is saved in `localStorage` under `windcast.locale` and synchronized across tabs. If storage is unavailable, switching still works for the current page. Russian is the default. Kazakh month names are explicit to support embedded browsers with incomplete ICU data; all three languages keep Kazakhstan time (UTC+5).
- CSV column names, decimal serialization, UTC timestamps, model object IDs, and run IDs are stable across languages. Language changes affect presentation only. Existing mock limitations still apply.

Implementation: `locale-provider.tsx` holds the language preference and locale-bound formatters; `lib/translations.ts` is the RU/EN/KK message catalog. Add translations there when adding visible UI text. `forecast-focus.tsx` and `forecast-insights.ts` implement synchronized timeline and insight cards; `dashboard-v2.css` scopes the new visual treatment.

Validation: `npm test` includes translation/placeholder coverage, localized formatting and unchanged CSV output, plus forecast extrema, tie-breaking, and the February/March boundary. Browser checks cover desktop/mobile layouts, language persistence, preserved hour/scene on language changes, localized dialogs, navigation, and system-driven model scenes.

## Display preferences

The header includes separate **Dark theme** and **Low-vision mode** toggles, with translated labels in Russian, English, and Kazakh. They can be combined. The default is the existing light theme; settings do not change the forecast, selected hour, language, or run history.

- `next-themes` persists light/dark under `windcast.theme`; `AppearanceProvider` persists `high`/`standard` under `windcast.vision`. Both synchronize across tabs. Low-vision mode remains usable in memory when storage is blocked.
- `appearance.css` defines semantic colors for panels, text, controls, chart series, and 3D labels. The existing light colors remain fallbacks. Dialogs use the same root-scoped palette even when portaled outside the dashboard.
- Low-vision mode raises interface text to at least 18 px, expands control targets, uses a more spacious responsive layout, strengthens focus outlines and borders, and removes decorative transitions. The chart reserves more space for large axis labels and reduces time-label density on narrow screens. Wide tables retain horizontal scrolling.
- Forecast and actual series remain distinguishable by solid/dashed strokes as well as color. Values are also available in the hourly table and detail dialog.
- The turbine stays visible but rotor/wind animation stops and camera changes snap to their targets in low-vision mode. Dashboard interactions, component inspection, and educational icing scenes remain functional. Exiting the mode restores the prior animation preference and respects the OS reduced-motion setting.
- A keyboard-visible “Skip to content” link focuses the main region. The former single-letter theme shortcut has been removed to avoid conflict with assistive navigation commands.

Checks: `tests/appearance.test.mjs` verifies the defined text/background pairs at 4.5:1 in dark mode and 7:1 in both low-vision palettes, and checks chart line/focus visibility. This is a focused palette regression check, not a claim of a complete accessibility certification. Browser QA covers combined modes, saved preferences, keyboard skip navigation, translated controls, and mobile dialogs.

## Period generation simulation

Use **Simulation** in the heading to generate an inclusive 1–31-day period (24–744 hourly points, fixed UTC+5). Choose typical weather, steady wind, calm, storm, or icing, and an **assumed** capacity per turbine (0.1–20 MW, default 5 MW). Dates from 2020–2100 are supported. This assumption is independent of the real case assets, whose rated capacity is not established.

- Weather is seeded and temporally correlated: seasonal/daily temperature, varying wind, gusts, humidity, and small local differences for the two turbines. **Generate again** draws a new seed. Switching turbines uses the same generated weather. There is no weather API or calibrated statistical match to site observations.
- A simplified cubic power curve uses 3 m/s cut-in, 11.4 m/s rated wind, and 25 m/s cut-out as reference thresholds from the [NREL 5-MW reference turbine report](https://www.nrel.gov/docs/fy09osti/38060.pdf). These do not describe the case turbines. The shape, air-density approximation, gust threshold of 32 m/s, and restart after two consecutive hours below 20 m/s wind / 27 m/s gusts are **illustrative generator assumptions**, not a certified controller.
- Storm fronts produce protective shutdowns and recovery. The icing preset imposes subzero temperature and high humidity with gradual assumed losses capped at 48%; this differs from the original forecast's educational ice view, which never changes forecast power. Normal presets do not infer ice from temperature alone.
- A single generated dataset drives KPIs, chart, hourly table, weather, turbine cards/details, insights and 3D. The table exposes gusts and operating state instead of unavailable actuals/error columns. Scenario events jump to the associated hour. The rotor stops at zero simulated output; wind animation remains visible. Both display preferences and all three languages apply.
- Station power averages two equal-capacity turbines; energy sums hourly normalized power times assumed total MW. Individual turbine views use one turbine's capacity. Energy is shown in MWh. Simulated actual observations are absent; nMAE/RMSE are not presented as simulation accuracy.
- History stores the configuration and seed in the current browser session. Opening it regenerates the identical result. Reloading clears the simulation and history. **Back to forecast** restores the retrospective data controls without losing the existing historical forecast settings.
- Simulation CSV has a separate schema marked `synthetic_simulation`, including scenario, seed, inclusive period, assumed capacity, hourly power/energy, weather, assumed icing losses and operating state. It does not fabricate observation or weather-issue timestamps. Existing forecast CSV remains unchanged.

Implementation: `apps/web/lib/wind-simulation.ts` is the pure generator, validation, metrics and serializer; `simulation-controls.tsx` provides the accessible configuration dialog, result summary and assumptions; `simulation.css` uses the shared theme palette. The configuration is a reproducibility aid, not server persistence.

Checks: `tests/wind-simulation.test.mjs` covers invalid periods/capacities, leap days/year boundaries, all scenarios over 31 days, bounds, reproducibility, station aggregation, power-curve thresholds, storm stop/restart behavior, icing losses, capacity scaling and CSV units. Translation coverage includes scenario/error/status messages. Browser QA covers form validation, a February/March period, reruns/history replay, turbine switching, selected-hour/3D synchronization, dark/low-vision/mobile layouts, and return to the retrospective forecast.


### Simulation motion

The shared timeline, arrows, slider and event shortcuts move the selected hour; graph, weather and turbine follow the same hour. Automatic period playback was prototyped on a side branch and is not part of `main`.

