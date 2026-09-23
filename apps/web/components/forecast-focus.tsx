"use client"

import { useI18n } from "@/components/locale-provider"

import {
  ArrowDownRight,
  ArrowUpRight,
  ChevronLeft,
  ChevronRight,
  Link2,
  Snowflake,
} from "lucide-react"
import { type ForecastPoint } from "@/lib/forecast-data"
import {
  getForecastInsights,
  type ForecastInsight,
} from "@/lib/forecast-insights"

export function ForecastTimeline({
  data,
  index,
  onSelect,
}: {
  data: ForecastPoint[]
  index: number
  onSelect: (index: number) => void
}) {
  const { tr, formatDate } = useI18n()

  const point = data[index]!
  const events = getForecastInsights(data).filter(
    (event) => event.kind !== "low"
  )
  return (
    <section
      className="wc-focus-timeline"
      aria-label={tr("Общее время графика, погоды и турбины")}
    >
      <div className="wc-focus-current">
        <span>
          <Link2 size={13} /> {tr("Выбранный час")}
        </span>
        <strong>
          {point.hour}
          <small>{formatDate(point.date)} · UTC+5</small>
        </strong>
      </div>
      <div className="wc-focus-track">
        <div className="wc-focus-range-row">
          <button
            type="button"
            onClick={() => onSelect(index - 1)}
            disabled={index === 0}
            aria-label={tr("Предыдущий час")}
          >
            <ChevronLeft size={16} />
          </button>
          <div className="wc-focus-range">
            <input
              type="range"
              aria-label={tr("Час 3D-модели")}
              min={0}
              max={data.length - 1}
              value={index}
              onChange={(event) => onSelect(Number(event.target.value))}
              aria-valuetext={`${formatDate(point.date)}, ${point.hour}`}
            />
            <div className="wc-focus-markers" aria-hidden="true">
              {events.map((event) => (
                <i
                  key={event.kind}
                  className={event.kind}
                  style={{
                    left: `${(event.index / (data.length - 1)) * 100}%`,
                  }}
                />
              ))}
            </div>
          </div>
          <button
            type="button"
            onClick={() => onSelect(index + 1)}
            disabled={index === data.length - 1}
            aria-label={tr("Следующий час")}
          >
            <ChevronRight size={16} />
          </button>
        </div>
        <div className="wc-focus-extent">
          <span>
            {formatDate(data[0]!.date)} · {data[0]!.hour}
          </span>
          <span>
            {data.length} {tr(data.length === 24 ? "часа" : "часов")}
          </span>
          <span>
            {formatDate(data.at(-1)!.date)} · {data.at(-1)!.hour}
          </span>
        </div>
      </div>
      <div className="wc-focus-events">
        {events.map((event) => (
          <button
            type="button"
            key={event.kind}
            onClick={() => onSelect(event.index)}
            className={event.kind}
            aria-label={`${event.kind === "peak" ? tr("Перейти к пику выработки") : tr("Перейти к минимуму температуры")}: ${formatDate(event.point.date)}, ${event.point.hour}`}
          >
            {event.kind === "peak" ? (
              <ArrowUpRight size={14} />
            ) : (
              <Snowflake size={14} />
            )}
            <span>
              {event.kind === "peak" ? tr("Пик") : tr("Холод")}
              <b>{event.point.hour}</b>
            </span>
          </button>
        ))}
      </div>
    </section>
  )
}

export function ForecastInsights({
  data,
  index,
  onSelect,
}: {
  data: ForecastPoint[]
  index: number
  onSelect: (insight: ForecastInsight) => void
}) {
  const { tr, number, formatDate } = useI18n()

  const insights = getForecastInsights(data)
  return (
    <section
      className="wc-insights"
      aria-label={tr("Выводы по выбранному прогнозу")}
    >
      {insights.map((insight) => (
        <button
          type="button"
          className={`wc-insight ${insight.kind}`}
          key={insight.kind}
          onClick={() => onSelect(insight)}
          aria-pressed={index === insight.index}
        >
          <span className="wc-insight-icon">
            {insight.kind === "peak" ? (
              <ArrowUpRight size={18} />
            ) : insight.kind === "low" ? (
              <ArrowDownRight size={18} />
            ) : (
              <Snowflake size={18} />
            )}
          </span>
          <span className="wc-insight-body">
            <span>{tr(insight.label)}</span>
            <strong>
              {number(insight.value)}
              <small>{insight.unit}</small>
              <span>
                {tr("в")} {insight.point.hour}
              </span>
            </strong>
            <small>
              {formatDate(insight.point.date)} ·{" "}
              {insight.kind === "cold"
                ? tr("Температура воздуха")
                : tr("Синтетический прогноз")}
            </small>
          </span>
          <ArrowUpRight size={15} className="wc-insight-arrow" />
        </button>
      ))}
    </section>
  )
}
