export type TurbineId = "all" | "t1" | "t2"
export type Horizon = 24 | 48
export type ForecastPoint = {
  timestamp: string
  hour: string
  date: string
  forecast: number
  actual: number | null
  lower: number | null
  upper: number | null
  wind: number | null
  temperature: number | null
}
export type ForecastRun = {
  id: string
  date: string
  horizon: Horizon
  turbine: TurbineId
  revision: number
  completedAt: string
}

export const TURBINES = [
  {
    id: "t1" as const,
    name: "Турбина 01",
    code: "WTG–001",
    location: "Северный участок",
    map: "https://maps.app.goo.gl/iN6svMt69D5qRpFU9",
  },
  {
    id: "t2" as const,
    name: "Турбина 02",
    code: "WTG–002",
    location: "Южный участок",
    map: "https://maps.app.goo.gl/8UQMwsYavY6nLvFY8",
  },
]
export const AGENT_STEPS = [
  { title: "Получение погоды", detail: "Проверка входов и доступности архивного прогноза" },
  {
    title: "Подготовка данных",
    detail: "Проверка пропусков и временных меток",
  },
  { title: "Запуск модели", detail: "Загрузка обученной модели" },
  {
    title: "Почасовой прогноз",
    detail: "Нормализованная мощность на 24–48 часов",
  },
  {
    title: "Анализ результата",
    detail: "Контроль диапазона и качества данных",
  },
  { title: "Публикация", detail: "Обновление графика и выгрузки" },
]
export const TEST_DATES = Array.from(
  { length: 28 },
  (_, i) => `2026-02-${String(i + 1).padStart(2, "0")}`
)
export const clamp = (n: number, min: number, max: number) =>
  Math.min(max, Math.max(min, n))
const round = (n: number) => Math.round(n * 100) / 100
export const number = (n: number | null | undefined, digits = 1) =>
  n == null || !Number.isFinite(n) ? "—" : n.toLocaleString("ru-RU", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })
export const formatDate = (date: string, long = false) =>
  new Intl.DateTimeFormat("ru-RU", {
    day: "2-digit",
    month: long ? "long" : "short",
    timeZone: "Etc/GMT-5",
  }).format(new Date(date.length === 10 ? `${date}T00:00:00+05:00` : date))
export const formatTimestamp = (date: string) =>
  new Intl.DateTimeFormat("ru-RU", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "Etc/GMT-5",
  }).format(new Date(date))

export function getProvenance(date: string) {
  const start = new Date(`${date}T00:00:00+05:00`).getTime()
  return {
    forecastIssuedAt: new Date(start - 60 * 60 * 1000).toISOString(),
    weatherIssuedAt: new Date(start - 6 * 60 * 60 * 1000).toISOString(),
    weatherAvailableAt: new Date(start - 5 * 60 * 60 * 1000).toISOString(),
    trainingCutoff: "2026-01-31T18:00:00.000Z",
  }
}

// Entirely synthetic data. The simulated prediction never consumes the actual values.
export function generateForecast(
  date: string,
  horizon: Horizon,
  turbine: TurbineId,
  revision = 0
): ForecastPoint[] {
  const start = new Date(`${date}T00:00:00+05:00`).getTime()
  const day = Number(date.slice(-2))
  const ids = turbine === "all" ? [1, 2] : [turbine === "t1" ? 1 : 2]
  return Array.from({ length: horizon }, (_, i) => {
    const timestamp = new Date(start + i * 3_600_000).toISOString()
    const localDate = new Date(start + i * 3_600_000 + 5 * 3_600_000)
      .toISOString()
      .slice(0, 10)
    const values = ids.map((id) => {
      const wind =
        9.15 +
        2.4 * Math.sin(i / 5 - 0.75 + day / 9) +
        0.8 * Math.cos(i / 2.3 + id / 3) +
        (id === 1 ? 0.35 : -0.35)
      const weatherRevision =
        Math.sin(revision * 0.8 + i / 8) * 0.15 * Math.min(revision, 3)
      const predictionWind = wind + weatherRevision
      const forecast = clamp(
        7 + Math.pow(Math.max(0, predictionWind - 3) / 10, 1.6) * 90,
        0,
        98
      )
      const observedPower = clamp(
        7 +
          Math.pow(Math.max(0, wind - 3) / 10, 1.6) * 90 +
          Math.sin(i * 0.83 + day + id) * 5.6 +
          Math.cos(i / 3) * 2.8,
        0,
        100
      )
      return { wind: predictionWind, forecast, actual: observedPower }
    })
    const avg = (key: "wind" | "forecast" | "actual") =>
      values.reduce((sum, value) => sum + value[key], 0) / values.length
    const forecast = round(avg("forecast"))
    const spread = 5 + i * 0.13
    return {
      timestamp,
      hour: `${String(i % 24).padStart(2, "0")}:00`,
      date: localDate,
      forecast,
      actual: localDate.startsWith("2026-02") ? round(avg("actual")) : null,
      lower: round(clamp(forecast - spread, 0, 100)),
      upper: round(clamp(forecast + spread, 0, 100)),
      wind: round(avg("wind")),
      temperature: round(-4.8 + 3 * Math.sin(i / 6 - 1.4) + day / 15),
    }
  })
}

export function getMetrics(points: ForecastPoint[]) {
  const measured = points.filter((p) => p.actual !== null)
  const wind = points.filter((p) => p.wind !== null)
  const intervals = measured.filter((p) => p.lower !== null && p.upper !== null)
  return {
    mean: points.length ? points.reduce((sum, p) => sum + p.forecast, 0) / points.length : null,
    peak: points.length ? Math.max(...points.map((p) => p.forecast)) : null,
    wind: wind.length ? wind.reduce((sum, p) => sum + p.wind!, 0) / wind.length : null,
    nmae:
      measured.length ? measured.reduce((sum, p) => sum + Math.abs(p.forecast - p.actual!), 0) /
      measured.length : null,
    rmse: measured.length ? Math.sqrt(
      measured.reduce((sum, p) => sum + (p.forecast - p.actual!) ** 2, 0) /
        (measured.length || 1)
    ) : null,
    coverage:
      intervals.length ? (intervals.filter((p) => p.actual! >= p.lower! && p.actual! <= p.upper!)
        .length /
        intervals.length) *
      100 : null,
    fullLoadHours: points.length ? points.reduce((sum, p) => sum + p.forecast / 100, 0) : null,
  }
}

export function forecastCsv(
  points: ForecastPoint[],
  date: string,
  turbine: TurbineId
) {
  const source = getProvenance(date)
  const rows = points.map((p) =>
    [
      "synthetic_demo",
      turbine,
      p.timestamp,
      source.forecastIssuedAt,
      source.weatherIssuedAt,
      source.weatherAvailableAt,
      p.forecast,
      p.actual ?? "",
      p.lower,
      p.upper,
      p.wind,
      p.temperature,
    ].join(",")
  )
  return (
    "\uFEFFdata_kind,turbine,valid_time_utc,forecast_issued_at_utc,weather_issued_at_utc,weather_available_at_utc,forecast_pct,actual_pct,lower_pct,upper_pct,wind_ms,temperature_c\n" +
    rows.join("\n")
  )
}
