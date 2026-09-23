import test from "node:test"
import assert from "node:assert/strict"
import { getForecastInsights } from "../apps/web/lib/forecast-insights.ts"
import { generateForecast } from "../apps/web/lib/forecast-data.ts"

test("insights select forecast extrema and preserve the date on a 48-hour horizon", () => {
  const points = generateForecast("2026-02-28", 48, "all").map((p, i) => ({
    ...p,
    forecast: i === 30 ? 99 : i === 47 ? 0 : 50,
    temperature: i === 27 ? -20 : -2,
  }))
  const insights = getForecastInsights(points)
  assert.deepEqual(
    insights.map((i) => [i.kind, i.index, i.value]),
    [
      ["peak", 30, 99],
      ["low", 47, 0],
      ["cold", 27, -20],
    ]
  )
  assert.equal(insights[0].point.date, "2026-03-01")
  assert.equal(insights[0].point.hour, "06:00")
  assert.equal(insights[2].unit, "°C")
})
test("insights ignore retrospective actuals, select earliest tied hour, and handle empty input", () => {
  assert.deepEqual(getForecastInsights([]), [])
  const points = generateForecast("2026-02-01", 24, "all").map((p) => ({
    ...p,
    forecast: 50,
    temperature: -3,
  }))
  assert.deepEqual(
    getForecastInsights(points).map((i) => i.index),
    [0, 0, 0]
  )
  const original = getForecastInsights(points).map(
    ({ kind, index, value }) => ({ kind, index, value })
  )
  const changed = points.map((p, i) => ({ ...p, actual: i % 2 ? 100 : null }))
  assert.deepEqual(
    getForecastInsights(changed).map(({ kind, index, value }) => ({
      kind,
      index,
      value,
    })),
    original
  )
})
