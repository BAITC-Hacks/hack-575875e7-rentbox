import test from "node:test"
import assert from "node:assert/strict"
import {
  generateSimulation,
  simulationPower,
  simulationHours,
  simulationError,
  simulationSummary,
  simulationCsv,
  SCENARIOS,
} from "../apps/web/lib/wind-simulation.ts"
import { illustrativeRotorSpeed } from "../apps/web/lib/turbine-scene.ts"
const base = {
  startDate: "2026-02-28",
  endDate: "2026-03-02",
  scenario: "mixed",
  capacityMW: 5,
  seed: 42,
}

test("period validation rejects invalid dates, excessive durations and invalid physical inputs", () => {
  assert.equal(simulationHours("2028-02-28", "2028-03-01"), 72)
  assert.equal(simulationHours("2026-12-31", "2027-01-01"), 48)
  assert.equal(simulationError(base), null)
  for (const patch of [
    { startDate: "2026-02-30" },
    { endDate: "2026-02-27" },
    { endDate: "2026-04-01" },
    { startDate: "" },
    { capacityMW: NaN },
    { capacityMW: 0 },
    { capacityMW: 21 },
    { seed: -1 },
    { seed: 2.5 },
    { scenario: "unknown" },
  ]) {
    assert.ok(simulationError({ ...base, ...patch }))
    assert.throws(() => generateSimulation({ ...base, ...patch }), RangeError)
  }
})
test("all scenarios preserve hourly chronology, physical bounds, and absent observations across a month", () => {
  for (const scenario of SCENARIOS.map((s) => s.id))
    for (const seed of [0, 42, 0xffffffff]) {
      const config = {
        ...base,
        startDate: "2026-12-15",
        endDate: "2027-01-14",
        scenario,
        seed,
      }
      const result = generateSimulation(config)
      for (const data of Object.values(result)) {
        assert.equal(data.length, 744)
        assert.equal(data[0].date, config.startDate)
        assert.equal(data.at(-1).date, config.endDate)
        for (const [i, p] of data.entries()) {
          assert.equal(p.actual, null)
          if (p.forecast === 0)
            assert.notEqual(p.simulation.state, "generating")
          assert.ok(
            p.lower >= 0 &&
              p.lower <= p.forecast &&
              p.forecast <= p.upper &&
              p.upper <= 100
          )
          assert.ok(p.wind >= 0 && p.wind <= 40)
          assert.ok(p.simulation.gust >= p.wind)
          assert.ok(p.temperature >= -30 && p.temperature <= 40)
          assert.ok(p.simulation.humidity >= 0 && p.simulation.humidity <= 100)
          assert.ok(p.simulation.icingLoss >= 0 && p.simulation.icingLoss <= 48)
          if (i)
            assert.equal(
              Date.parse(p.timestamp) - Date.parse(data[i - 1].timestamp),
              3_600_000
            )
        }
      }
    }
})
test("same configuration replays exactly; another seed changes weather, and both turbines aggregate consistently", () => {
  const first = generateSimulation(base)
  assert.deepEqual(first, generateSimulation({ ...base }))
  assert.notDeepEqual(first, generateSimulation({ ...base, seed: 43 }))
  first.all.forEach((p, i) => {
    assert.ok(
      Math.abs(
        p.forecast - (first.t1[i].forecast + first.t2[i].forecast) / 2
      ) <= 0.006
    )
    assert.equal(
      p.simulation.stoppedTurbines,
      first.t1[i].simulation.stoppedTurbines +
        first.t2[i].simulation.stoppedTurbines
    )
  })
})
test("power curve starts, saturates, and cuts out; storm protections stop the rotor and recover after safe wind", () => {
  assert.equal(simulationPower(2.99), 0)
  assert.equal(simulationPower(3), 0)
  assert.ok(simulationPower(8) > simulationPower(5))
  assert.equal(simulationPower(11.4), 100)
  assert.equal(simulationPower(24), 100)
  assert.equal(simulationPower(25), 0)
  for (const seed of [0, 1, 42, 1500]) {
    const points = generateSimulation({
      ...base,
      endDate: base.startDate,
      scenario: "storm",
      seed,
    }).t1
    assert.ok(points.some((p) => p.simulation.state === "storm"))
    assert.ok(points.some((p) => p.simulation.state === "recovering"))
    const firstStorm = points.findIndex((p) => p.simulation.state === "storm")
    assert.ok(
      points
        .slice(firstStorm + 1)
        .some((p) => p.simulation.state === "generating")
    )
    points.forEach((p, i) => {
      if (["storm", "recovering"].includes(p.simulation.state)) {
        assert.equal(p.forecast, 0)
        assert.equal(illustrativeRotorSpeed(p.wind, "flow", true), 0)
      }
      if (
        i &&
        points[i - 1].simulation.state === "recovering" &&
        p.simulation.state === "generating"
      ) {
        for (const safe of [p, points[i - 1]]) {
          assert.ok(safe.wind < 20)
          assert.ok(safe.simulation.gust < 27)
        }
      }
    })
  }
})
test("calm produces idle hours; icing imposes cold humid weather and bounded accumulating loss", () => {
  const calm = generateSimulation({ ...base, scenario: "calm" }).t1
  assert.ok(calm.some((p) => p.forecast === 0))
  assert.ok(calm.every((p) => p.forecast < 10 && p.simulation.icingLoss === 0))
  const icing = generateSimulation({ ...base, scenario: "icing" }).t1
  assert.ok(
    icing.every((p) => p.temperature < 0 && p.simulation.humidity >= 80)
  )
  assert.ok(icing.at(-1).simulation.icingLoss > icing[0].simulation.icingLoss)
  assert.ok(icing.at(-1).simulation.icingLoss <= 48)
})
test("energy scales with assumed capacity and turbine count; CSV preserves scenario and omits fictitious observations", () => {
  const data = generateSimulation(base)
  const summary = simulationSummary(data.all, base, "all")
  const individual =
    simulationSummary(data.t1, base, "t1").energyMWh +
    simulationSummary(data.t2, base, "t2").energyMWh
  assert.ok(Math.abs(summary.energyMWh - individual) < 0.06)
  assert.equal(
    simulationSummary(data.all, { ...base, capacityMW: 10 }, "all").energyMWh,
    summary.energyMWh * 2
  )
  assert.deepEqual(generateSimulation({ ...base, capacityMW: 10 }), data)
  const lines = simulationCsv(data.all, base, "all").trim().split("\n")
  assert.equal(lines.length, 73)
  assert.equal(lines[0].split(",").length, 20)
  assert.ok(!lines[0].includes("actual") && !lines[0].includes("issued"))
  for (const line of lines.slice(1)) {
    const row = line.split(",")
    assert.equal(row.length, 20)
    assert.equal(row[0], "synthetic_simulation")
    assert.equal(row[1], base.scenario)
    assert.equal(Number(row[2]), base.seed)
    assert.equal(Number(row[6]), 10)
  }
  const exported = lines
    .slice(1)
    .reduce((sum, row) => sum + Number(row.split(",")[10]), 0)
  assert.ok(Math.abs(exported - summary.energyMWh) < 0.0001)
})

test("live simulation rotates through icing while preserving actual shutdowns and still inspection", () => {
  for (const scenario of SCENARIOS.map((s) => s.id)) {
    const points = generateSimulation({ ...base, scenario }).t1
    for (const point of points) {
      const stopped = point.forecast === 0
      for (const mode of ["flow", "icing", "cutaway", "sensors"]) {
        const speed = illustrativeRotorSpeed(point.wind, mode, stopped, true)
        if (stopped) assert.equal(speed, 0)
        else
          assert.ok(
            speed > 0,
            `${scenario}/${mode}: positive power must animate`
          )
      }
      assert.equal(
        illustrativeRotorSpeed(point.wind, "history", stopped, true),
        0
      )
      assert.equal(illustrativeRotorSpeed(point.wind, "icing", false, false), 0)
    }
  }
})
