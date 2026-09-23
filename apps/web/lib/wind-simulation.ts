import type { ForecastPoint, TurbineId } from "./forecast-data"

export const SCENARIOS = [
  {
    id: "mixed",
    label: "Обычная погода",
    detail: "Смена ветра и температуры, без экстремальных событий.",
  },
  {
    id: "steady",
    label: "Устойчивый ветер",
    detail: "Ровный сильный ветер и высокая загрузка турбин.",
  },
  {
    id: "calm",
    label: "Штиль",
    detail: "Слабый ветер, периоды простоя и небольшой выработки.",
  },
  {
    id: "storm",
    label: "Шторм",
    detail: "Усиление ветра, защитная остановка и постепенное восстановление.",
  },
  {
    id: "icing",
    label: "Обледенение",
    detail: "Мороз и высокая влажность, условные потери на лопастях.",
  },
] as const
export type Scenario = (typeof SCENARIOS)[number]["id"]
export type SimulationConfig = {
  startDate: string
  endDate: string
  scenario: Scenario
  capacityMW: number
  seed: number
}
export type SimulationReading = {
  gust: number
  humidity: number
  icingLoss: number
  state: "generating" | "calm" | "storm" | "recovering"
  stoppedTurbines: number
}
export const OPERATING_LABELS = {
  generating: "Генерация",
  calm: "Недостаточно ветра",
  storm: "Штормовая защита",
  recovering: "Ожидание безопасного ветра",
} as const
const HOUR = 3_600_000
const bound = (n: number, a: number, b: number) => Math.min(b, Math.max(a, n))
const round = (n: number) => Math.round(n * 100) / 100
function parseDate(value: string) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return NaN
  const ms = Date.parse(`${value}T00:00:00Z`)
  return Number.isFinite(ms) &&
    new Date(ms).toISOString().slice(0, 10) === value
    ? ms
    : NaN
}
export function simulationHours(start: string, end: string) {
  return (parseDate(end) - parseDate(start)) / HOUR + 24
}
export function simulationError(config: SimulationConfig): string | null {
  const hours = simulationHours(config.startDate, config.endDate)
  if (
    !Number.isFinite(hours) ||
    config.startDate < "2020-01-01" ||
    config.endDate > "2100-12-31"
  )
    return "Укажите корректные даты с 2020 по 2100 год."
  if (hours < 24 || hours > 31 * 24)
    return "Выберите период от 1 до 31 дня включительно."
  if (
    !Number.isFinite(config.capacityMW) ||
    config.capacityMW < 0.1 ||
    config.capacityMW > 20
  )
    return "Мощность одной турбины должна быть от 0,1 до 20 МВт."
  if (!SCENARIOS.some((s) => s.id === config.scenario))
    return "Выберите погодный сценарий."
  if (
    !Number.isInteger(config.seed) ||
    config.seed < 0 ||
    config.seed > 0xffffffff
  )
    return "Некорректный номер реализации."
  return null
}
// MOCK: correlated synthetic weather, not site observations or a calibrated forecast.
function random(seed: number) {
  let state = seed >>> 0
  return () => {
    state += 0x6d2b79f5
    let t = Math.imul(state ^ (state >>> 15), 1 | state)
    t ^= t + Math.imul(t ^ (t >>> 7), 61 | t)
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}
// Illustrative cubic curve. Thresholds reference NREL's generic 5-MW turbine:
// https://www.nrel.gov/docs/fy09osti/38060.pdf (3 / 11.4 / 25 m/s).
// This is not the power curve or control system of the case turbines.
export function simulationPower(wind: number) {
  if (wind < 3 || wind >= 25) return 0
  return 100 * bound((wind ** 3 - 3 ** 3) / (11.4 ** 3 - 3 ** 3), 0, 1)
}
export function generateSimulation(
  config: SimulationConfig
): Record<TurbineId, ForecastPoint[]> {
  const error = simulationError(config)
  if (error) throw new RangeError(error)
  const count = simulationHours(config.startDate, config.endDate)
  const start = parseDate(config.startDate) - 5 * HOUR
  const rand = random(config.seed)
  const phase = rand() * Math.PI * 2
  const center = count <= 48 ? count * (0.4 + rand() * 0.2) : 30 + rand() * 10
  let noise = 0
  const weather = Array.from({ length: count }, (_, i) => {
    noise = noise * 0.82 + (rand() - 0.5) * 1.5
    const local = new Date(start + (i + 5) * HOUR)
    const dayOfYear =
      (Date.UTC(
        local.getUTCFullYear(),
        local.getUTCMonth(),
        local.getUTCDate()
      ) -
        Date.UTC(local.getUTCFullYear(), 0, 0)) /
      (24 * HOUR)
    const seasonal =
      8 + 16 * Math.cos(((dayOfYear - 200) * Math.PI * 2) / 365.25)
    const daily = Math.sin((((i % 24) - 8) * Math.PI) / 12)
    const front = Math.exp(
      -Math.pow(((i % 72) - center) / (count <= 48 ? count * 0.14 : 10), 2)
    )
    const base =
      config.scenario === "steady" ? 11 : config.scenario === "calm" ? 1.9 : 8.4
    let wind =
      base +
      Math.sin(i / 9 + phase) *
        (config.scenario === "steady"
          ? 0.6
          : config.scenario === "calm"
            ? 1.1
            : 2) +
      noise * (config.scenario === "calm" ? 0.4 : 1) +
      daily * 0.5
    if (config.scenario === "storm") wind += front * 22
    wind = bound(wind, 0.2, 35)
    const temperature =
      config.scenario === "icing"
        ? -5.5 + daily * 2 + noise * 0.4
        : seasonal +
          daily * 3 +
          noise -
          front * (config.scenario === "storm" ? 4 : 0)
    const humidity = bound(
      (config.scenario === "icing" ? 93 : 62) -
        daily * 5 +
        noise * 3 +
        (config.scenario === "storm" ? front * 22 : 0),
      25,
      100
    )
    const gust = Math.max(
      wind,
      wind * (1.12 + rand() * 0.13) +
        (config.scenario === "storm" ? front * 3 : 0)
    )
    return { wind, temperature, humidity, gust }
  })
  const turbineData = [1, 2].map((id) => {
    const local = random(config.seed ^ (id * 0x9e3779b9))
    let stopped = false,
      safeHours = 0,
      ice = 0,
      variation = 0
    return weather.map((weatherPoint, i): ForecastPoint => {
      variation = variation * 0.7 + (local() - 0.5) * 0.5
      const wind = round(
        Math.max(0, weatherPoint.wind * (id === 1 ? 1.02 : 0.98) + variation)
      )
      const gust = round(
        Math.max(wind, weatherPoint.gust * (id === 1 ? 1.02 : 0.98) + variation)
      )
      const dangerous = wind >= 25 || gust >= 32
      if (dangerous) {
        stopped = true
        safeHours = 0
      } else if (stopped) {
        safeHours = wind < 20 && gust < 27 ? safeHours + 1 : 0
        if (safeHours >= 2) stopped = false
      }
      // MOCK: icing is imposed by the scenario, with synthetic humidity and loss.
      // Growth/decay and storm restart thresholds are illustrative assumptions.
      const icing =
        config.scenario === "icing" &&
        weatherPoint.temperature < 0 &&
        weatherPoint.temperature > -15 &&
        weatherPoint.humidity >= 80
      ice = bound(icing ? ice + 0.018 + local() * 0.025 : ice * 0.75, 0, 0.48)
      const density = bound(
        288.15 / (273.15 + weatherPoint.temperature),
        0.92,
        1.08
      )
      const forecast = stopped
        ? 0
        : round(bound(simulationPower(wind) * density, 0, 100) * (1 - ice))
      const spread =
        forecast === 0
          ? 0
          : 4 + Math.min(10, (gust - wind) * 0.8) + Math.min(4, i / 48)
      const timestamp = new Date(start + i * HOUR).toISOString()
      return {
        timestamp,
        date: new Date(start + (i + 5) * HOUR).toISOString().slice(0, 10),
        hour: `${String(i % 24).padStart(2, "0")}:00`,
        forecast,
        actual: null,
        lower: round(bound(forecast - spread, 0, 100)),
        upper: round(bound(forecast + spread, 0, 100)),
        wind,
        temperature: round(weatherPoint.temperature),
        simulation: {
          gust,
          humidity: round(weatherPoint.humidity),
          icingLoss: round(ice * 100),
          state: stopped
            ? dangerous
              ? "storm"
              : "recovering"
            : wind <= 3
              ? "calm"
              : "generating",
          stoppedTurbines: forecast === 0 ? 1 : 0,
        },
      }
    })
  })
  const t1 = turbineData[0]!,
    t2 = turbineData[1]!
  const all = t1.map((a, i): ForecastPoint => {
    const b = t2[i]!
    const sa = a.simulation!,
      sb = b.simulation!
    const state = [sa.state, sb.state].includes("storm")
      ? "storm"
      : [sa.state, sb.state].includes("recovering")
        ? "recovering"
        : sa.state === "calm" && sb.state === "calm"
          ? "calm"
          : "generating"
    return {
      ...a,
      forecast: round((a.forecast + b.forecast) / 2),
      lower: round((a.lower! + b.lower!) / 2),
      upper: round((a.upper! + b.upper!) / 2),
      wind: round((a.wind! + b.wind!) / 2),
      simulation: {
        ...sa,
        gust: Math.max(sa.gust, sb.gust),
        icingLoss: round((sa.icingLoss + sb.icingLoss) / 2),
        state,
        stoppedTurbines: sa.stoppedTurbines + sb.stoppedTurbines,
      },
    }
  })
  return { t1, t2, all }
}
export function simulationSummary(
  data: ForecastPoint[],
  config: SimulationConfig,
  turbine: TurbineId
) {
  const capacity = config.capacityMW * (turbine === "all" ? 2 : 1)
  return {
    energyMWh: data.reduce((s, p) => s + (p.forecast / 100) * capacity, 0),
    capacityMW: capacity,
    maxGust: Math.max(...data.map((p) => p.simulation?.gust ?? 0)),
    affectedHours: data.filter((p) => (p.simulation?.stoppedTurbines ?? 0) > 0)
      .length,
    maxIceLoss: Math.max(...data.map((p) => p.simulation?.icingLoss ?? 0)),
  }
}
export function simulationCsv(
  data: ForecastPoint[],
  config: SimulationConfig,
  turbine: TurbineId
) {
  const capacity = config.capacityMW * (turbine === "all" ? 2 : 1)
  return (
    "\uFEFFdata_kind,scenario,seed,period_start,period_end,turbine,assumed_capacity_mw,valid_time_utc,power_pct,power_mw,energy_mwh,lower_pct,upper_pct,wind_ms,gust_ms,temperature_c,humidity_pct,icing_loss_pct,operating_state,stopped_turbines\n" +
    data
      .map((p) =>
        [
          "synthetic_simulation",
          config.scenario,
          config.seed,
          config.startDate,
          config.endDate,
          turbine,
          capacity,
          p.timestamp,
          p.forecast,
          Number(((p.forecast / 100) * capacity).toFixed(6)),
          Number(((p.forecast / 100) * capacity).toFixed(6)),
          p.lower,
          p.upper,
          p.wind,
          p.simulation!.gust,
          p.temperature,
          p.simulation!.humidity,
          p.simulation!.icingLoss,
          p.simulation!.state,
          p.simulation!.stoppedTurbines,
        ].join(",")
      )
      .join("\n")
  )
}
