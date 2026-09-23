"use client"

import { useCallback, useEffect, useRef, useState } from "react"
import {
  api, dashboardTurbines, ForecastApiError,
  type ApiForecast, type ApiRun, type ApiTurbine, type DashboardTurbine,
  type DataSummary, type Health,
} from "./forecast-api"
import type { Horizon } from "./forecast-data"

function wait(signal: AbortSignal) {
  return new Promise<void>((resolve, reject) => {
    const abort = () => { window.clearTimeout(timer); reject(signal.reason) }
    const timer = window.setTimeout(() => {
      signal.removeEventListener("abort", abort)
      resolve()
    }, 1500)
    if (signal.aborted) abort()
    else signal.addEventListener("abort", abort, { once: true })
  })
}

export function useForecastDashboard() {
  const [health, setHealth] = useState<Health | null>(null)
  const [turbines, setTurbines] = useState<DashboardTurbine[]>([])
  const [summary, setSummary] = useState<DataSummary | null>(null)
  const [runs, setRuns] = useState<ApiRun[]>([])
  const [run, setRun] = useState<ApiRun | null>(null)
  const [forecast, setForecast] = useState<ApiForecast | null>(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const active = useRef<AbortController | null>(null)
  const bootstrap = useRef<AbortController | null>(null)

  const reload = useCallback(() => {
    bootstrap.current?.abort()
    const controller = new AbortController()
    bootstrap.current = controller
    const options = { signal: controller.signal }
    return Promise.all([
      api<Health>("/health", options),
      api<{ items: ApiTurbine[] }>("/turbines", options),
      api<DataSummary>("/data/summary", options),
      api<{ items: ApiRun[] }>("/agent/runs?limit=100", options),
    ]).then(([service, catalog, data, history]) => {
      if (controller.signal.aborted) return
      setError(null)
      setHealth(service)
      setTurbines(dashboardTurbines(catalog.items))
      setSummary(data)
      setRuns(history.items)
    }).catch((cause: unknown) => {
      if (controller.signal.aborted) return
      setHealth(null)
      setError(cause instanceof Error ? cause.message : "Не удалось загрузить данные.")
    }).finally(() => {
      if (!controller.signal.aborted) setLoading(false)
    })
  }, [])

  useEffect(() => {
    void reload()
    return () => {
      bootstrap.current?.abort()
      active.current?.abort()
    }
  }, [reload])

  function record(state: ApiRun) {
    setRun(state)
    setRuns((items) => [state, ...items.filter((item) => item.run_id !== state.run_id)].slice(0, 100))
  }

  async function monitor(runId: string, signal: AbortSignal) {
    const path = `/agent/runs/${encodeURIComponent(runId)}`
    let state = await api<ApiRun>(path, { signal })
    record(state)
    while (state.status === "queued" || state.status === "running") {
      await wait(signal)
      state = await api<ApiRun>(path, { signal })
      record(state)
    }
    if (state.status === "failed") throw new Error(state.error?.message ?? "Расчёт завершился ошибкой.")
    const result = await api<ApiForecast>(`${path}/forecast`, { signal })
    if (!signal.aborted) setForecast(result)
    return state
  }

  async function operation(action: (signal: AbortSignal) => Promise<unknown>) {
    // Lock immediately: two clicks before React renders must not submit twice.
    if (active.current) return
    const controller = new AbortController()
    active.current = controller
    setBusy(true)
    setError(null)
    setForecast(null)
    try {
      await action(controller.signal)
    } catch (cause) {
      if (!controller.signal.aborted) {
        if (cause instanceof ForecastApiError && ["CONNECTION_ERROR", "HTTP_502", "HTTP_504"].includes(cause.code)) setHealth(null)
        setError(cause instanceof Error ? cause.message : "Не удалось получить прогноз.")
      }
    } finally {
      if (!controller.signal.aborted) setBusy(false)
      if (active.current === controller) active.current = null
    }
  }

  function start(payload: { as_of: string; horizon_hours: Horizon; turbine_ids: number[]; refresh_weather: boolean }) {
    return operation(async (signal) => {
      setRun(null)
      const accepted = await api<{ run_id: string }>("/agent/runs", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload), signal,
      })
      // Keep the accepted ID even if the first status request loses connection.
      record({ ...payload, run_id: accepted.run_id, status: "queued", stage: "validate",
        progress: 0, agent_mode: "policy", revision: 1, supersedes_run_id: null,
        reused_run_id: null, events: [], warnings: [], error: null })
      await monitor(accepted.run_id, signal)
    })
  }
  function open(runId: string) {
    return operation((signal) => monitor(runId, signal))
  }

  function refreshConnection() {
    setLoading(true)
    setError(null)
    return reload()
  }

  return { health, turbines, summary, runs, run, forecast, loading, busy, error, reload: refreshConnection, start, open }
}
