import type { ForecastPoint } from "./forecast-data"

export type ForecastInsight = {
  kind: "peak" | "low" | "cold"
  label: string
  index: number
  point: ForecastPoint
  value: number
  unit: "%" | "°C"
}

/** Summarizes forecast inputs only; never reads retrospective actual power. */
export function getForecastInsights(data: ForecastPoint[]): ForecastInsight[] {
  if (!data.length) return []
  let peak = 0,
    low = 0,
    cold = 0
  data.forEach((point, index) => {
    if (point.forecast > data[peak]!.forecast) peak = index
    if (point.forecast < data[low]!.forecast) low = index
    if (point.temperature < data[cold]!.temperature) cold = index
  })
  return [
    {
      kind: "peak",
      label: "Пик выработки",
      index: peak,
      point: data[peak]!,
      value: data[peak]!.forecast,
      unit: "%",
    },
    {
      kind: "low",
      label: "Минимум выработки",
      index: low,
      point: data[low]!,
      value: data[low]!.forecast,
      unit: "%",
    },
    {
      kind: "cold",
      label: "Самый холодный час",
      index: cold,
      point: data[cold]!,
      value: data[cold]!.temperature,
      unit: "°C",
    },
  ]
}
