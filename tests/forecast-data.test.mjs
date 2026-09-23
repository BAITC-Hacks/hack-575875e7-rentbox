import test from "node:test"
import assert from "node:assert/strict"
import {
  TEST_DATES,
  generateForecast,
  getProvenance,
  getMetrics,
  forecastCsv,
} from "../apps/web/lib/forecast-data.ts"

test("28 forecast dates and both horizons retain hourly chronology and physical bounds", () => {
  for (const date of TEST_DATES)
    for (const horizon of [24, 48])
      for (const turbine of ["all", "t1", "t2"]) {
        const data = generateForecast(date, horizon, turbine)
        assert.equal(data.length, horizon)
        assert.equal(data[0].date, date)
        data.forEach((p, i) => {
          assert.ok(
            p.lower >= 0 &&
              p.lower <= p.forecast &&
              p.forecast <= p.upper &&
              p.upper <= 100
          )
          assert.ok(Number.isFinite(p.wind) && Number.isFinite(p.temperature))
          if (i)
            assert.equal(
              Date.parse(p.timestamp) - Date.parse(data[i - 1].timestamp),
              3_600_000
            )
        })
      }
})

test("archive availability and training cutoff precede every forecast issuance", () => {
  for (const date of TEST_DATES) {
    const p = getProvenance(date)
    assert.ok(Date.parse(p.weatherIssuedAt) <= Date.parse(p.weatherAvailableAt))
    assert.ok(
      Date.parse(p.weatherAvailableAt) <= Date.parse(p.forecastIssuedAt)
    )
    assert.ok(Date.parse(p.trainingCutoff) <= Date.parse(p.forecastIssuedAt))
    assert.ok(
      Date.parse(p.forecastIssuedAt) <
        Date.parse(generateForecast(date, 24, "all")[0].timestamp)
    )
  }
})

test("synthetic truth is stable across recalculations; forecast changes independently", () => {
  const before = generateForecast("2026-02-04", 48, "t1", 0)
  const after = generateForecast("2026-02-04", 48, "t1", 1)
  assert.deepEqual(
    before.map((p) => p.actual),
    after.map((p) => p.actual)
  )
  assert.notDeepEqual(
    before.map((p) => p.forecast),
    after.map((p) => p.forecast)
  )
  assert.deepEqual(before, generateForecast("2026-02-04", 48, "t1", 0))
})

test("end-of-February horizon has no invented observations in March", () => {
  const data = generateForecast("2026-02-28", 48, "all")
  assert.ok(
    data.slice(0, 24).every((p) => p.date === "2026-02-28" && p.actual !== null)
  )
  assert.ok(
    data.slice(24).every((p) => p.date === "2026-03-01" && p.actual === null)
  )
  assert.equal(getMetrics(data).nmae, getMetrics(data.slice(0, 24)).nmae)
})

test("station values aggregate both normalized turbine forecasts", () => {
  const all = generateForecast("2026-02-01", 24, "all")
  const a = generateForecast("2026-02-01", 24, "t1")
  const b = generateForecast("2026-02-01", 24, "t2")
  assert.notDeepEqual(a, b)
  all.forEach((p, i) =>
    assert.ok(
      Math.abs(p.forecast - (a[i].forecast + b[i].forecast) / 2) < 0.015
    )
  )
})

test("metrics and exported CSV preserve units and source timestamps", () => {
  const base = generateForecast("2026-02-28", 48, "all")
  const fixture = [
    { ...base[0], forecast: 20, actual: 10 },
    { ...base[1], forecast: 80, actual: 90 },
  ]
  const metrics = getMetrics(fixture)
  assert.equal(metrics.mean, 50)
  assert.equal(metrics.nmae, 10)
  assert.equal(metrics.rmse, 10)
  assert.equal(metrics.fullLoadHours, 1)
  const csv = forecastCsv(base, "2026-02-28", "all")
  const rows = csv.trim().split("\n")
  assert.equal(rows.length, 49)
  assert.ok(rows.every((row) => row.split(",").length === 12))
  assert.equal(rows[25].split(",")[7], "")
  assert.equal(rows[1].split(",")[0], "synthetic_demo")
  assert.equal(
    rows[1].split(",")[3],
    getProvenance("2026-02-28").forecastIssuedAt
  )
})
