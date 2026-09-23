import type { DashboardView } from "./turbine-scene"
import type { Horizon } from "./forecast-data"

export type HelperContext = {
  view: DashboardView
  date: string | null
  horizon_hours: Horizon
  turbine_ids: (1 | 2)[]
}
export type HelperHistory = { role: "user" | "assistant"; content: string }
export type HelperRequest = {
  message: string
  history: HelperHistory[]
  run_id: string | null
  context: HelperContext
}
export type HelperStatus = {
  provider: "openai"
  model: "gpt-6-astra"
  enabled: boolean
  configured: boolean
  available: boolean
  prompt_version: string
}
export type HelperSource = { id: string; title: string; view: DashboardView | null }
export type HelperAction = {
  type: "navigate" | "download_csv"
  label: string
  view: DashboardView | null
  run_id: string | null
}
export type HelperReply = {
  provider: "openai" | "local_help"
  model: string | null
  text: string
  sources: HelperSource[]
  actions: HelperAction[]
  warning: string | null
  prompt_version: string
}

const VIEWS: readonly string[] = ["overview", "forecast", "agent", "sources", "history"]
const object = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value)
const view = (value: unknown): value is DashboardView | null =>
  value === null || (typeof value === "string" && VIEWS.includes(value))
const nullableString = (value: unknown): value is string | null =>
  value === null || typeof value === "string"

async function request(path: string, signal: AbortSignal, body?: HelperRequest): Promise<unknown> {
  // The browser uses the same Next.js /api proxy as forecast-api.ts.
  // Credentials and calls to OpenAI belong to the backend.
  const timeout = AbortSignal.timeout(body ? 55_000 : 10_000)
  try {
    const response = await fetch(`/api/help/${path}`, {
      method: body ? "POST" : "GET",
      cache: "no-store",
      signal: AbortSignal.any([signal, timeout]),
      ...(body ? {
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      } : {}),
    })
    const data: unknown = await response.json().catch(() => null)
    if (!response.ok) {
      const detail = object(data) && object(data.error) ? data.error : null
      throw new Error(detail && typeof detail.message === "string"
        ? detail.message
        : "Справка временно недоступна. Попробуйте ещё раз.")
    }
    return data
  } catch (error) {
    if (signal.aborted) throw error
    if (timeout.aborted) throw new Error("Помощник не ответил вовремя. Можно повторить вопрос.")
    if (error instanceof TypeError) throw new Error("Не удалось связаться с помощником. Проверьте подключение.")
    throw error
  }
}

export async function getHelperStatus(signal: AbortSignal): Promise<HelperStatus> {
  const data = await request("status", signal)
  if (!object(data) || data.provider !== "openai" || data.model !== "gpt-6-astra"
    || typeof data.enabled !== "boolean" || typeof data.configured !== "boolean"
    || typeof data.available !== "boolean" || typeof data.prompt_version !== "string") {
    throw new Error("Не удалось прочитать состояние помощника.")
  }
  return data as HelperStatus
}

export async function askHelper(body: HelperRequest, signal: AbortSignal): Promise<HelperReply> {
  const data = await request("chat", signal, body)
  if (!object(data) || !["openai", "local_help"].includes(String(data.provider))
    || !nullableString(data.model) || (data.provider === "openai"
      && (typeof data.model !== "string"
        || (data.model !== "gpt-6-astra" && !data.model.startsWith("gpt-6-astra-"))))
    || typeof data.text !== "string" || !data.text.trim()
    || !nullableString(data.warning) || typeof data.prompt_version !== "string"
    || !Array.isArray(data.sources) || !Array.isArray(data.actions)
    || !data.sources.every((item: unknown) => object(item) && typeof item.id === "string"
      && typeof item.title === "string" && view(item.view))
    || !data.actions.every((item: unknown) => object(item)
      && (item.type === "navigate" || item.type === "download_csv")
      && typeof item.label === "string" && view(item.view) && nullableString(item.run_id))) {
    throw new Error("Помощник вернул неполный ответ. Повторите вопрос.")
  }
  return data as HelperReply
}
