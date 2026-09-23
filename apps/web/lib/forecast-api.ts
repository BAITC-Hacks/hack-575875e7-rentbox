import type { ForecastPoint, Horizon, TurbineId } from "./forecast-data"

export type Stage = "validate" | "weather" | "prepare" | "model" | "predict" | "review" | "save"
export type RunStatus = "queued" | "running" | "completed" | "failed"
export type ApiErrorDetail = { code: string; message: string; retryable: boolean }
export type AgentEvent = {
  id: string
  timestamp: string
  stage: Stage
  level: "info" | "warning" | "error"
  message: string
  tool: string | null
  attempt: number
}
export type ApiRun = {
  run_id: string
  status: RunStatus
  stage: Stage
  progress: number
  agent_mode: "policy" | "llm"
  as_of: string
  horizon_hours: Horizon
  turbine_ids: number[]
  revision: number
  supersedes_run_id: string | null
  reused_run_id: string | null
  events: AgentEvent[]
  warnings: string[]
  error: ApiErrorDetail | null
}
export type WeatherSource = {
  source_id: string
  provider: string
  model: string
  product: "single_run" | "previous_runs"
  initialization_time: string | null
  available_at: string | null
  retrieved_at: string
  sha256: string
  availability_basis: string
}
export type WeatherInput = {
  source_id: string
  forecast_offset_days: number | null
  available_at_estimate: string | null
}
export type ApiForecast = {
  run_id: string
  as_of: string
  horizon_hours: Horizon
  unit: "normalized_power"
  model_version: string
  training_data_available_until: string
  series: {
    turbine_id: number
    storage_run_id: number
    points: {
      valid_time: string
      lead_hour: number
      predicted_power: number
      wind_speed_100m: number | null
      wind_speed_10m: number | null
      temperature_2m: number | null
      weather_inputs: WeatherInput[]
    }[]
    weather: { sources: WeatherSource[] }
  }[]
  analysis: { summary: string; warnings: string[] }
}
export type Health = {
  status: "ok"
  agent_configured: boolean
  time_configuration_ready: boolean
  time_configuration_confirmed: boolean
  research_mode: boolean
  turbines_count: number
}
export type ApiTurbine = { id: number; name: string; latitude: number; longitude: number }
export type DashboardTurbine = {
  id: Exclude<TurbineId, "all">
  name: string
  code: string
  location: string
  map: string
}
export type DataSummary = {
  time_configuration: {
    source_timezone: string | null
    timestamp_meaning: string | null
    confirmed: boolean
    missing_fields: string[]
  }
  turbines: {
    turbine_id: number
    rows: number
    start_local: string
    end_local: string
    missing_percent: number
    source_matches_audit: boolean
  }[]
  february_actuals_available: boolean
  warnings: string[]
}

export const statusLabel: Record<RunStatus, string> = {
  queued: "В очереди", running: "В работе", completed: "Завершён", failed: "Ошибка",
}
export const stageIndex: Record<Stage, number> = {
  validate: 0, weather: 0, prepare: 1, model: 2, predict: 3, review: 4, save: 5,
}
export class ForecastApiError extends Error {
  constructor(public code: string, message: string) {
    super(message)
    this.name = "ForecastApiError"
  }
}

// Next.js proxies this same-origin path to FastAPI, including CSV downloads.
async function response(path: string, options: RequestInit = {}) {
  try {
    const timeout = AbortSignal.timeout(20_000)
    const signal = options.signal ? AbortSignal.any([options.signal, timeout]) : timeout
    const result = await fetch(`/api${path}`, { ...options, cache: "no-store", signal })
    if (!result.ok) {
      const body = await result.json().catch(() => null)
      throw new ForecastApiError(
        body?.error?.code ?? `HTTP_${result.status}`,
        body?.error?.message ?? "Сервер недоступен. Повторите попытку позже.",
      )
    }
    return result
  } catch (error) {
    if (options.signal?.aborted || error instanceof ForecastApiError) throw error
    throw new ForecastApiError("CONNECTION_ERROR", "Не удалось связаться с сервером. Проверьте подключение и повторите попытку.")
  }
}

export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  return (await response(path, options)).json() as Promise<T>
}
export async function downloadForecast(runId: string) {
  const result = await response(`/agent/runs/${encodeURIComponent(runId)}/forecast.csv`)
  const url = URL.createObjectURL(await result.blob())
  const anchor = document.createElement("a")
  anchor.href = url
  anchor.download = `forecast-${runId}.csv`
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}

// The picker is the first forecast day in display time UTC+5. The NOAA
// archive issues at 18:00 UTC on the preceding day (23:00 display time).
export function issueForDate(date: string) {
  return new Date(new Date(`${date}T00:00:00+05:00`).getTime() - 3_600_000).toISOString()
}
export function forecastDate(asOf: string) {
  return new Date(new Date(asOf).getTime() + 6 * 3_600_000).toISOString().slice(0, 10)
}
export function turbineSelection(ids: number[]): TurbineId {
  return ids.length === 2 ? "all" : ids[0] === 1 ? "t1" : "t2"
}
export function turbineIds(id: TurbineId) {
  return id === "all" ? [1, 2] : [id === "t1" ? 1 : 2]
}
export function dashboardTurbines(items: ApiTurbine[]): DashboardTurbine[] {
  return items.map((item) => ({
    id: item.id === 1 ? "t1" : "t2",
    name: item.name,
    code: `WTG–00${item.id}`,
    location: `${item.latitude.toFixed(6)}, ${item.longitude.toFixed(6)}`,
    map: `https://www.google.com/maps/search/?api=1&query=${item.latitude},${item.longitude}`,
  }))
}
export function forecastPoints(result: ApiForecast | null, turbine: TurbineId): ForecastPoint[] {
  if (!result) return []
  const ids = turbineIds(turbine)
  const series = result.series.filter((item) => ids.includes(item.turbine_id))
  if (series.length !== ids.length || !series[0]) return []
  return series[0].points.map((point, index) => {
    const local = new Date(new Date(point.valid_time).getTime() + 5 * 3_600_000).toISOString()
    return {
      timestamp: point.valid_time, date: local.slice(0, 10), hour: local.slice(11, 16),
      forecast: series.reduce((sum, item) => sum + item.points[index]!.predicted_power, 0) / series.length * 100,
      actual: null, lower: null, upper: null,
      wind: average(series.map((item) => item.points[index]!.wind_speed_100m ?? null)),
      temperature: average(series.map((item) => item.points[index]!.temperature_2m ?? null)),
    }
  })
}
// Weather readouts are per turbine; the station view shows their mean. Runs
// stored before the backend exported weather have no values and stay "—".
function average(values: (number | null | undefined)[]) {
  const known = values.filter((value): value is number => typeof value === "number" && Number.isFinite(value))
  return known.length === values.length && known.length ? known.reduce((sum, value) => sum + value, 0) / known.length : null
}
export function forecastSources(result: ApiForecast | null) {
  const sources = new Map<string, WeatherSource>()
  result?.series.forEach((series) => series.weather.sources.forEach((source) => {
    sources.set(`${source.provider}:${source.model}:${source.sha256}`, source)
  }))
  return [...sources.values()]
}

export function pointSources(result: ApiForecast | null, turbine: TurbineId, timestamp: string) {
  return (result?.series ?? []).filter((series) => turbineIds(turbine).includes(series.turbine_id))
    .flatMap((series) => {
      const point = series.points.find((item) => item.valid_time === timestamp)
      return (point?.weather_inputs ?? []).flatMap((input) => {
        const source = series.weather.sources.find((item) => item.source_id === input.source_id)
        return source ? [{ ...source, ...input, turbine_id: series.turbine_id }] : []
      })
    })
}
