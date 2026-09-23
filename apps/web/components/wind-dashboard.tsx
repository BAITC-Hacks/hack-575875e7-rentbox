"use client"

import { LanguageSelector, useI18n } from "@/components/locale-provider"

import { useEffect, useMemo, useRef, useState, type ReactNode } from "react"
import {
  ArrowRight,
  ArrowUpRight,
  Bell,
  CalendarDays,
  Check,
  CheckCheck,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  CircleHelp,
  CloudDownload,
  CloudSun,
  Database,
  Download,
  ExternalLink,
  FileClock,
  Gauge,
  History,
  Info,
  LayoutDashboard,
  LoaderCircle,
  MapPin,
  Menu,
  MoreHorizontal,
  RefreshCw,
  Search,
  ShieldCheck,
  Sparkles,
  TrendingUp,
  Waves,
  Wind,
  X,
  Zap,
  type LucideIcon,
} from "lucide-react"
import { TurbineHero } from "@/components/turbine-hero"
import { ForecastInsights, ForecastTimeline } from "@/components/forecast-focus"
import type { ForecastInsight } from "@/lib/forecast-insights"
import { Button } from "@workspace/ui/components/button"
import { Card } from "@workspace/ui/components/card"
import { Badge } from "@workspace/ui/components/badge"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@workspace/ui/components/dialog"
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@workspace/ui/components/tooltip"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@workspace/ui/components/table"
import {
  AGENT_STEPS,
  TEST_DATES,
  TURBINES,
  clamp,
  forecastCsv,
  generateForecast,
  getMetrics,
  getProvenance,
  type ForecastPoint,
  type ForecastRun,
  type Horizon,
  type TurbineId,
} from "@/lib/forecast-data"

import {
  resolveHour,
  resolveSceneMode,
  type DashboardView,
  type SceneFocus,
  type SceneMode,
} from "@/lib/turbine-scene"

type View = DashboardView
const NAV: { id: View; label: string; icon: LucideIcon }[] = [
  { id: "overview", label: "Обзор", icon: LayoutDashboard },
  { id: "forecast", label: "Прогноз выработки", icon: TrendingUp },
  { id: "agent", label: "AI-агент", icon: Sparkles },
  { id: "sources", label: "Источники данных", icon: Database },
  { id: "history", label: "История запусков", icon: History },
]
const PAGE_TITLES: Record<View, string> = {
  overview: "Обзор выработки",
  forecast: "Прогноз выработки",
  agent: "Центр управления агентом",
  sources: "Источники данных",
  history: "История запусков",
}
function Hint({ children }: { children: ReactNode }) {
  const { tr } = useI18n()

  return (
    <Tooltip>
      <TooltipTrigger
        className="wc-hint"
        aria-label={tr("Подробнее о показателе")}
      >
        <Info size={14} />
      </TooltipTrigger>
      <TooltipContent>{children}</TooltipContent>
    </Tooltip>
  )
}
function Sparkline({
  values,
  color = "#437c54",
}: {
  values: number[]
  color?: string
}) {
  const min = Math.min(...values),
    max = Math.max(...values)
  const line = values
    .map(
      (v, i) =>
        `${(i * 92) / (values.length - 1)},${32 - ((v - min) / (max - min || 1)) * 26}`
    )
    .join(" ")
  return (
    <svg className="wc-sparkline" viewBox="0 0 94 38" aria-hidden="true">
      <polyline points={`0,38 ${line} 92,38`} fill={color} opacity=".07" />
      <polyline
        points={line}
        stroke={color}
        strokeWidth="1.7"
        fill="none"
        strokeLinejoin="round"
        strokeLinecap="round"
      />
    </svg>
  )
}
function TurbineArt({ compact = false }: { compact?: boolean }) {
  return (
    <svg
      viewBox="0 0 420 170"
      className={compact ? "wc-turbine-art compact" : "wc-turbine-art"}
      aria-hidden="true"
    >
      <circle cx="328" cy="46" r="26" fill="#e5edcf" />
      <path d="M0 136Q73 91 171 137T420 125V170H0Z" fill="#e7eeda" />
      <path d="M0 158Q146 115 275 150T420 137V170H0Z" fill="#dce7c9" />
      <g stroke="#526c54" strokeWidth="2" fill="#fafbf4" strokeLinejoin="round">
        <path d="M130 143L134 57H138L142 143Z" />
        <circle cx="136" cy="57" r="5" />
        <path d="M136 55L131 6Q139 7 141 14L139 54Z" />
        <path d="M140 59L181 83Q177 91 170 87L137 63Z" />
        <path d="M133 61L95 88Q91 81 97 76L132 56Z" />
        <path d="M277 148L280 83H283L286 148Z" />
        <circle cx="282" cy="83" r="4" />
        <path d="M282 80L278 41Q285 42 286 48L285 81Z" />
        <path d="M285 85L319 103Q316 109 311 106L281 88Z" />
        <path d="M279 87L248 110Q245 104 249 100L279 81Z" />
      </g>
      <path
        d="M26 66H78M46 76H90M328 98H368M344 108H385"
        stroke="#b3c2a5"
        strokeWidth="1.4"
        strokeLinecap="round"
      />
    </svg>
  )
}
function StatCard({
  title,
  value,
  unit,
  icon: Icon,
  note,
  values,
  hint,
  positive = true,
}: {
  title: string
  value: string
  unit: string
  icon: LucideIcon
  note: string
  values: number[]
  hint: string
  positive?: boolean
}) {
  return (
    <Card className="wc-card wc-stat">
      <div className="wc-stat-label">
        <span>{title}</span>
        <Hint>{hint}</Hint>
      </div>
      <div className="wc-stat-main">
        <div className="wc-stat-number">
          {value}
          <span>{unit}</span>
        </div>
        <span className="wc-stat-icon">
          <Icon size={21} strokeWidth={1.6} />
        </span>
      </div>
      <div className="wc-stat-footer">
        <span className={positive ? "wc-positive" : "wc-muted"}>
          {positive ? <ArrowUpRight size={14} /> : <Check size={14} />}
          {note}
        </span>
        <Sparkline values={values} />
      </div>
    </Card>
  )
}
function ForecastChart({
  data,
  horizon,
  setHorizon,
  busy,
  onInspect,
  inspectedHour,
}: {
  data: ForecastPoint[]
  horizon: Horizon
  setHorizon: (h: Horizon) => void
  busy: boolean
  onInspect: (index: number) => void
  inspectedHour: number
}) {
  const { tr, number, formatDate } = useI18n()

  const [active, setActive] = useState<number | null>(null)
  const [showActual, setShowActual] = useState(true)
  const [showRange, setShowRange] = useState(true)
  const [plotWidth, setPlotWidth] = useState(700)
  const chartRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const element = chartRef.current
    if (!element) return
    const observer = new ResizeObserver(([entry]) => {
      if (entry) setPlotWidth(Math.max(300, entry.contentRect.width))
    })
    observer.observe(element)
    return () => observer.disconnect()
  }, [])
  const x = (i: number) => 45 + (i / (data.length - 1)) * (plotWidth - 61)
  const y = (v: number) => 222 - v * 1.95
  const path = (key: "forecast" | "actual" | "lower" | "upper") =>
    data
      .filter((p) => p[key] !== null)
      .map(
        (p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(p[key]!).toFixed(1)}`
      )
      .join(" ")
  const area = `${path("upper")} ${[...data]
    .reverse()
    .map((p, i) => `L${x(data.length - i - 1)},${y(p.lower)}`)
    .join(" ")} Z`
  const displayIndex = active ?? inspectedHour
  const selected = data[displayIndex]
  function inspect(index: number) {
    setActive(index)
    onInspect(index)
  }
  return (
    <Card className="wc-card wc-forecast-card">
      <div className="wc-panel-heading">
        <div>
          <h2>
            {tr("Почасовой прогноз")}
            <span className="wc-tag">
              {horizon} {tr("ч")}
            </span>
          </h2>
          <p>{tr("Нормализованная мощность · % от номинальной")}</p>
        </div>
        <div className="wc-segment" aria-label={tr("Горизонт прогноза")}>
          {([24, 48] as const).map((h) => (
            <button
              key={h}
              disabled={busy}
              aria-pressed={horizon === h}
              onClick={() => {
                setActive(null)
                setHorizon(h)
              }}
            >
              {h} {h === 24 ? tr("часа") : tr("часов")}
            </button>
          ))}
        </div>
      </div>
      <div
        className="wc-chart-selected"
        aria-label={tr("Выбранный час прогноза")}
      >
        <span>
          {formatDate(data[inspectedHour]!.date)} ·{" "}
          <b>{data[inspectedHour]!.hour}</b>
        </span>
        <strong>
          {number(data[inspectedHour]!.forecast)}
          <small>{tr("% мощности")}</small>
        </strong>
        <span>
          <Wind size={13} />
          {number(data[inspectedHour]!.wind)} {tr("м/с")}
        </span>
      </div>
      <div className="wc-chart-legend">
        <span>
          <i className="wc-legend-line green" />
          {tr("Прогноз")}
        </span>
        <button
          onClick={() => setShowActual(!showActual)}
          aria-pressed={showActual}
          className={!showActual ? "off" : ""}
        >
          <i className="wc-legend-line dashed" />
          {tr("Факт")}
        </button>
        <button
          onClick={() => setShowRange(!showRange)}
          aria-pressed={showRange}
          className={!showRange ? "off" : ""}
        >
          <i className="wc-legend-range" />
          {tr("Диапазон прогноза")}
        </button>
        <span className="wc-chart-zone">UTC+5</span>
      </div>
      <div
        className="wc-chart"
        ref={chartRef}
        role="group"
        aria-label={tr(
          "Интерактивный график прогноза. Используйте стрелки для выбора часа."
        )}
        tabIndex={0}
        onKeyDown={(e) => {
          if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
            e.preventDefault()
            inspect(
              clamp(
                (active ?? inspectedHour) + (e.key === "ArrowRight" ? 1 : -1),
                0,
                data.length - 1
              )
            )
          }
        }}
        onPointerMove={(e) => {
          const rect = e.currentTarget.getBoundingClientRect()
          inspect(
            clamp(
              Math.round(
                ((((e.clientX - rect.left) / rect.width) * plotWidth - 45) /
                  (plotWidth - 61)) *
                  (data.length - 1)
              ),
              0,
              data.length - 1
            )
          )
        }}
        onPointerLeave={() => setActive(null)}
        onBlur={() => setActive(null)}
      >
        <svg
          viewBox={`0 0 ${plotWidth} 264`}
          role="img"
          aria-label={tr("Почасовой прогноз выработки на {v0} ч", {
            v0: horizon,
          })}
        >
          <defs>
            <linearGradient id="forecast-fill" x1="0" y1="0" x2="0" y2="1">
              <stop stopColor="#8caf6a" stopOpacity=".18" />
              <stop offset="1" stopColor="#8caf6a" stopOpacity="0" />
            </linearGradient>
          </defs>
          {[0, 25, 50, 75, 100].map((tick) => (
            <g key={tick}>
              <line
                x1="45"
                x2={plotWidth - 16}
                y1={y(tick)}
                y2={y(tick)}
                stroke="#e9ece7"
                strokeDasharray="3 5"
              />
              <text x="30" y={y(tick) + 4} textAnchor="end" className="wc-axis">
                {tick}%
              </text>
            </g>
          ))}
          {[0, 0.25, 0.5, 0.75, 1].map((part) => {
            const i = Math.round(part * (data.length - 1))
            return (
              <text
                key={part}
                x={x(i)}
                y="245"
                textAnchor={
                  part === 0 ? "start" : part === 1 ? "end" : "middle"
                }
                className="wc-axis"
              >
                {data[i]!.hour}
                {i % 24 === 0 && (
                  <tspan x={x(i)} dy="13">
                    {formatDate(data[i]!.date)}
                  </tspan>
                )}
              </text>
            )
          })}
          <path
            d={`${path("forecast")} L${plotWidth - 16},222 L45,222 Z`}
            fill="url(#forecast-fill)"
          />
          {showRange && <path d={area} fill="#9abb7c" opacity=".17" />}
          {showActual && (
            <path
              d={path("actual")}
              fill="none"
              stroke="#9fa59c"
              strokeWidth="1.8"
              strokeDasharray="5 5"
              strokeLinecap="round"
            />
          )}
          <path
            d={path("forecast")}
            fill="none"
            stroke="#48794d"
            strokeWidth="2.7"
            strokeLinejoin="round"
            strokeLinecap="round"
          />
          {selected && (
            <g>
              <rect
                x={
                  x(displayIndex) -
                  Math.max(5, (plotWidth - 61) / data.length / 2)
                }
                y="20"
                width={Math.max(10, (plotWidth - 61) / data.length)}
                height="203"
                fill="#e0ebd5"
                opacity=".65"
              />

              <line
                x1={x(displayIndex)}
                x2={x(displayIndex)}
                y1="20"
                y2="223"
                stroke="#718d62"
                strokeDasharray="3 4"
              />
              <circle
                cx={x(displayIndex)}
                cy={y(selected.forecast)}
                r="5"
                fill="#48794d"
                stroke="white"
                strokeWidth="3"
              />
            </g>
          )}
        </svg>
        {selected && active !== null && (
          <div
            className="wc-chart-tooltip"
            style={{ left: `${clamp((x(active) / plotWidth) * 100, 16, 82)}%` }}
          >
            <b>
              {formatDate(selected.date)} · {selected.hour}
            </b>
            <span>
              {tr("Прогноз")}
              <strong>{number(selected.forecast)}%</strong>
            </span>
            {showActual && (
              <span>
                {tr("Факт")}
                <strong>
                  {selected.actual === null
                    ? tr("Нет данных")
                    : `${number(selected.actual)}%`}
                </strong>
              </span>
            )}
            <span>
              {tr("Ветер")}
              <strong>
                {number(selected.wind)} {tr("м/с")}
              </strong>
            </span>
          </div>
        )}
      </div>
      <div className="wc-chart-bottom">
        <span>
          <ShieldCheck size={14} />{" "}
          {tr("Архивный прогноз без данных из будущего")}
        </span>
        <span>{tr("Выбранный час связан с 3D-моделью")}</span>
      </div>
    </Card>
  )
}
function AgentPanel({
  busy,
  step,
  onOpen,
  expanded = false,
  onInspect,
}: {
  busy: boolean
  step: number
  onOpen: () => void
  expanded?: boolean
  onInspect?: (index: number) => void
}) {
  const { tr } = useI18n()

  return (
    <Card className={`wc-card wc-agent-card ${expanded ? "expanded" : ""}`}>
      <div className="wc-panel-heading">
        <div>
          <h2>
            <Sparkles size={17} /> {tr("AI-агент")}
          </h2>
          <p>{tr("От данных до решения")}</p>
        </div>
        <span className={`wc-status ${busy ? "processing" : ""}`}>
          <i />
          {busy ? tr("В работе") : tr("Готов")}
        </span>
      </div>
      <div className="wc-agent-steps">
        {AGENT_STEPS.map((item, i) => {
          const current = busy && i === step
          const done = !busy || i < step
          return (
            <div
              key={item.title}
              className={`wc-agent-step ${done ? "done" : ""} ${current ? "current" : ""}`}
            >
              <span className="wc-step-dot">
                {current ? (
                  <LoaderCircle size={12} className="wc-spin" />
                ) : done ? (
                  <Check size={12} />
                ) : (
                  <span>{i + 1}</span>
                )}
              </span>
              <div>
                <h3>
                  {onInspect ? (
                    <button
                      type="button"
                      className="wc-step-inspect"
                      disabled={busy}
                      onClick={() => onInspect(i)}
                    >
                      {tr(item.title)}
                    </button>
                  ) : (
                    tr(item.title)
                  )}
                </h3>
                {expanded && <p>{tr(item.detail)}</p>}
              </div>
              <span className="wc-step-result">
                {current
                  ? tr("Выполняется")
                  : done
                    ? tr("Готово")
                    : tr("В очереди")}
              </span>
            </div>
          )
        })}
      </div>
      <div className="wc-agent-footer">
        <span>
          <span className="wc-live-dot" />
          {busy ? tr("Выполняется демо-цикл") : tr("6 из 6 этапов выполнено")}
        </span>
        <button
          className="wc-text-button"
          onClick={onOpen}
          aria-label={tr("Открыть журнал агента")}
        >
          <ArrowUpRight size={17} />
        </button>
      </div>
    </Card>
  )
}
function WeatherPanel({
  data,
  onInspect,
  inspectedHour,
}: {
  inspectedHour: number
  data: ForecastPoint[]
  onInspect: (index: number) => void
}) {
  const { tr, number, formatDate } = useI18n()

  const point = data[inspectedHour]!
  const selected = [0, 6, 12, 18].map((i) => data[i]!)
  return (
    <Card className="wc-card wc-weather-card">
      <div className="wc-panel-heading">
        <div>
          <h2>{tr("Погодные условия")}</h2>
          <p>
            {tr("Архивный прогноз ·")} {formatDate(data[0]!.date)}
          </p>
        </div>
        <CloudSun size={21} className="wc-muted" />
      </div>
      <button
        type="button"
        className="wc-weather-selected"
        onClick={() => onInspect(inspectedHour)}
        aria-label={tr("Показать погодный сценарий выбранного часа {v0}", {
          v0: point.hour,
        })}
      >
        <span>
          <small>
            {formatDate(point.date)} · {point.hour}
          </small>
          <strong>
            {number(point.temperature)}
            <small>°C</small>
          </strong>
        </span>
        <span>
          <Wind size={18} />
          <strong>
            {number(point.wind)} {tr("м/с")}
          </strong>
          <small>{tr("Выбранный час")}</small>
        </span>
      </button>
      <div className="wc-weather-hours">
        {selected.map((p, i) => (
          <button
            type="button"
            key={p.timestamp}
            aria-pressed={inspectedHour === i * 6}
            onClick={() => onInspect(i * 6)}
            aria-label={tr("Показать погодный сценарий на {v0}", {
              v0: p.hour,
            })}
          >
            <span>{p.hour}</span>
            {i === 0 ? (
              <CloudSun className="wc-weather-icon" />
            ) : i === 1 ? (
              <Wind className="wc-weather-icon" />
            ) : i === 2 ? (
              <CloudSun className="wc-weather-icon sunny" />
            ) : (
              <Waves className="wc-weather-icon" />
            )}
            <strong>{number(p.temperature, 0)}°</strong>
            <small>
              <Wind size={12} />
              {number(p.wind)} {tr("м/с")}
            </small>
          </button>
        ))}
      </div>
      <div className="wc-weather-note">
        <ArrowUpRight size={15} />
        <span>{tr("Ветер благоприятен для генерации")}</span>
        <Hint>
          {tr(
            "Демонстрационная оценка по синтетическому прогнозу скорости ветра."
          )}
        </Hint>
      </div>
    </Card>
  )
}
function TurbinePanel({
  date,
  horizon,
  revision,
  onOpen,
}: {
  date: string
  horizon: Horizon
  revision: number
  onOpen: (id: TurbineId) => void
}) {
  const { tr, number } = useI18n()

  return (
    <Card className="wc-card wc-turbines-card">
      <div className="wc-panel-heading">
        <div>
          <h2>
            {tr("Турбины станции")} <span className="wc-count">2</span>
          </h2>
          <p>{tr("Средняя выработка на выбранном горизонте")}</p>
        </div>
        <span className="wc-status">
          <i />
          {tr("Доступны")}
        </span>
      </div>
      <div className="wc-turbine-list">
        {TURBINES.map((t) => {
          const m = getMetrics(generateForecast(date, horizon, t.id, revision))
          return (
            <button
              className="wc-turbine-row"
              onClick={() => onOpen(t.id)}
              key={t.id}
            >
              <span className="wc-turbine-icon">
                <Wind size={25} strokeWidth={1.3} />
              </span>
              <span className="wc-turbine-name">
                <strong>{tr(t.name)}</strong>
                <small>
                  {t.code} · {tr(t.location)}
                </small>
              </span>
              <span className="wc-turbine-value">
                <strong>
                  {number(m.mean)}
                  <small>%</small>
                </strong>
                <span>
                  <i style={{ width: `${m.mean}%` }} />
                </span>
              </span>
              <ChevronRight size={16} />
            </button>
          )
        })}
      </div>
      <div className="wc-subtle-note">
        <Info size={13} />{" "}
        {tr("Мощность нормализована относительно номинальной.")}
      </div>
    </Card>
  )
}
function SourcesPanel({
  date,
  detailed = false,
}: {
  date: string
  detailed?: boolean
}) {
  const { tr, formatTimestamp } = useI18n()

  const times = getProvenance(date)
  return (
    <Card className="wc-card wc-source-card">
      <div className="wc-panel-heading">
        <div>
          <h2>{tr("Данные, которым можно доверять")}</h2>
          <p>{tr("Контроль доступности на момент прогнозирования")}</p>
        </div>
        <ShieldCheck size={22} className="wc-green" />
      </div>
      <div className="wc-source-grid">
        {[
          {
            name: "ECMWF IFS",
            sub: tr("Смоделированный архив погоды"),
            icon: CloudDownload,
          },
          {
            name: "GFS",
            sub: tr("Смоделированный архив погоды"),
            icon: CloudSun,
          },
          {
            name: tr("SCADA · 2 турбины"),
            sub: tr("Синтетические исторические данные"),
            icon: Database,
          },
        ].map(({ name, sub, icon: Icon }) => (
          <div className="wc-source-item" key={name}>
            <span className="wc-source-icon">
              <Icon size={19} />
            </span>
            <div>
              <strong>{name}</strong>
              <small>{sub}</small>
            </div>
            <CheckCheck size={16} className="wc-green" />
          </div>
        ))}
      </div>
      {detailed && (
        <div className="wc-provenance">
          <div>
            <span>{tr("Выпуск прогноза погоды")}</span>
            <strong>{formatTimestamp(times.weatherIssuedAt)}</strong>
          </div>
          <div>
            <span>{tr("Погодный прогноз стал доступен")}</span>
            <strong>{formatTimestamp(times.weatherAvailableAt)}</strong>
          </div>
          <div>
            <span>{tr("Момент расчёта выработки")}</span>
            <strong>{formatTimestamp(times.forecastIssuedAt)}</strong>
          </div>
          <div>
            <span>{tr("Конец обучающего периода")}</span>
            <strong>{tr("31 янв. 2026 · 23:00")}</strong>
          </div>
          <div>
            <span>{tr("Тестовый период")}</span>
            <strong>{tr("01–28 февраля 2026")}</strong>
          </div>
          <p>
            <ShieldCheck size={16} />{" "}
            {tr(
              "Доступность погоды ≤ момент расчёта. Фактическая выработка отображается только для ретроспективной оценки."
            )}
          </p>
        </div>
      )}
    </Card>
  )
}
function HourlyTable({
  data,
  onExport,
  onPoint,
  compact = false,
}: {
  data: ForecastPoint[]
  onExport: () => void
  onPoint: (p: ForecastPoint) => void
  compact?: boolean
}) {
  const { tr, number, formatDate } = useI18n()

  const [page, setPage] = useState(0)
  const [query, setQuery] = useState("")
  const [sort, setSort] = useState<"time" | "high" | "low">("time")
  const filtered = useMemo(() => {
    const points = data.filter((p) =>
      `${p.hour} ${p.date} ${formatDate(p.date)}`.includes(
        query.trim().toLowerCase()
      )
    )
    return sort === "time"
      ? points
      : [...points].sort((a, b) =>
          sort === "high" ? b.forecast - a.forecast : a.forecast - b.forecast
        )
  }, [data, query, sort, formatDate])
  const size = compact ? 6 : 12
  const pages = Math.max(1, Math.ceil(filtered.length / size))
  const currentPage = Math.min(page, pages - 1)
  const visible = filtered.slice(currentPage * size, (currentPage + 1) * size)
  return (
    <Card className="wc-card wc-table-card">
      <div className="wc-panel-heading">
        <div>
          <h2>{tr("Почасовая детализация")}</h2>
          <p>{tr("Прогноз и ретроспективный факт · UTC+5")}</p>
        </div>
        <div className="wc-table-actions">
          <label className="wc-search">
            <Search size={15} />
            <input
              aria-label={tr("Найти час")}
              placeholder={tr("Найти час…")}
              value={query}
              onChange={(e) => {
                setQuery(e.target.value)
                setPage(0)
              }}
            />
          </label>
          <Button variant="outline" size="sm" onClick={onExport}>
            <Download size={14} /> CSV
          </Button>
        </div>
      </div>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>{tr("Дата и время")}</TableHead>
            <TableHead>
              <button
                className="wc-sort"
                onClick={() => {
                  setSort(sort === "high" ? "low" : "high")
                  setPage(0)
                }}
              >
                {tr("Прогноз, %")}{" "}
                <ChevronDown
                  size={13}
                  className={sort === "low" ? "wc-rotate" : ""}
                />
              </button>
            </TableHead>
            <TableHead>{tr("Факт, %")}</TableHead>
            <TableHead>{tr("Отклонение, п.п.")}</TableHead>
            <TableHead>{tr("Ветер, м/с")}</TableHead>
            <TableHead>{tr("Температура")}</TableHead>
            <TableHead>
              <span className="sr-only">{tr("Подробности")}</span>
            </TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {visible.map((p) => (
            <TableRow key={p.timestamp}>
              <TableCell>
                <div className="wc-table-time">
                  <span>{p.hour}</span>
                  <small>{formatDate(p.date)}</small>
                </div>
              </TableCell>
              <TableCell>
                <span className="wc-table-forecast">
                  {number(p.forecast)}
                  <span className="wc-mini-bar">
                    <i style={{ width: `${p.forecast}%` }} />
                  </span>
                </span>
              </TableCell>
              <TableCell>
                {p.actual === null ? "—" : number(p.actual)}
              </TableCell>
              <TableCell>
                {p.actual === null ? (
                  "—"
                ) : (
                  <span
                    className={`wc-delta ${Math.abs(p.forecast - p.actual) > 5 ? "warning" : ""}`}
                  >
                    {p.forecast - p.actual > 0 ? "+" : ""}
                    {number(p.forecast - p.actual)}
                  </span>
                )}
              </TableCell>
              <TableCell>
                <span className="wc-cell-weather">
                  <Wind size={13} />
                  {number(p.wind)}
                </span>
              </TableCell>
              <TableCell>{number(p.temperature)} °C</TableCell>
              <TableCell>
                <button
                  className="wc-icon-button"
                  onClick={() => onPoint(p)}
                  aria-label={tr("Подробнее за {v0}, {v1}", {
                    v0: p.hour,
                    v1: formatDate(p.date),
                  })}
                >
                  <MoreHorizontal size={17} />
                </button>
              </TableCell>
            </TableRow>
          ))}
          {!visible.length && (
            <TableRow>
              <TableCell colSpan={7}>
                <div className="wc-empty">
                  <Search size={24} />
                  <strong>{tr("Ничего не найдено")}</strong>
                  <span>{tr("Попробуйте время в формате 09:00.")}</span>
                  <button onClick={() => setQuery("")}>
                    {tr("Сбросить поиск")}
                  </button>
                </div>
              </TableCell>
            </TableRow>
          )}
        </TableBody>
      </Table>
      <div className="wc-pagination">
        <span>
          {filtered.length ? currentPage * size + 1 : 0}–
          {Math.min((currentPage + 1) * size, filtered.length)} {tr("из")}{" "}
          {filtered.length} {tr("часов")}
        </span>
        <div>
          <button
            className="wc-icon-button"
            disabled={currentPage === 0}
            onClick={() => setPage(currentPage - 1)}
            aria-label={tr("Предыдущая страница")}
          >
            <ChevronLeft size={15} />
          </button>
          <span>
            {currentPage + 1} / {pages}
          </span>
          <button
            className="wc-icon-button"
            disabled={currentPage === pages - 1}
            onClick={() => setPage(currentPage + 1)}
            aria-label={tr("Следующая страница")}
          >
            <ChevronRight size={15} />
          </button>
        </div>
      </div>
    </Card>
  )
}
export function WindDashboard() {
  const { tr, number, formatDate, formatTimestamp } = useI18n()

  const [view, setView] = useState<View>("overview")
  const [sceneOverride, setSceneOverride] = useState<SceneMode | null>(null)
  const [sceneFocus, setSceneFocus] = useState<SceneFocus>("gearbox")
  const [sceneHour, setSceneHour] = useState(0)
  const [inspectedStep, setInspectedStep] = useState(2)
  const [date, setDate] = useState("2026-02-01")
  const [horizon, setHorizon] = useState<Horizon>(24)
  const [turbine, setTurbine] = useState<TurbineId>("all")
  const [revision, setRevision] = useState(0)
  const [busy, setBusy] = useState(false)
  const [step, setStep] = useState(0)
  const [mobileMenu, setMobileMenu] = useState(false)
  const sidebarRef = useRef<HTMLElement>(null)
  const menuButtonRef = useRef<HTMLButtonElement>(null)
  useEffect(() => {
    if (!mobileMenu) return
    const menuButton = menuButtonRef.current
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = "hidden"
    sidebarRef.current
      ?.querySelector<HTMLButtonElement>('[aria-current="page"]')
      ?.focus()
    function handleMenuKey(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setMobileMenu(false)
        return
      }
      if (event.key !== "Tab") return
      const elements = Array.from(
        sidebarRef.current?.querySelectorAll<HTMLElement>(
          "a[href], button:not([disabled])"
        ) ?? []
      )
      const first = elements[0],
        last = elements[elements.length - 1]
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault()
        last?.focus()
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault()
        first?.focus()
      }
    }
    document.addEventListener("keydown", handleMenuKey)
    return () => {
      document.body.style.overflow = previousOverflow
      document.removeEventListener("keydown", handleMenuKey)
      menuButton?.focus()
    }
  }, [mobileMenu])
  const [toast, setToast] = useState<{
    key: string
    values?: Record<string, string | number>
  } | null>(null)
  const [dialog, setDialog] = useState<
    "help" | "notifications" | TurbineId | null
  >(null)
  const [selectedPoint, setSelectedPoint] = useState<ForecastPoint | null>(null)
  const [runs, setRuns] = useState<ForecastRun[]>([
    {
      id: "FC-0201-001",
      date: "2026-02-01",
      horizon: 24,
      turbine: "all",
      revision: 0,
      completedAt: "2026-01-31T18:00:00.000Z",
    },
  ])
  const data = useMemo(
    () => generateForecast(date, horizon, turbine, revision),
    [date, horizon, turbine, revision]
  )
  const metrics = useMemo(() => getMetrics(data), [data])
  const inspectedHour = resolveHour(sceneHour, data.length)
  const sceneMode = resolveSceneMode(view, sceneOverride, busy, step)
  function chooseScene(mode: SceneMode) {
    setSceneOverride(mode)
    if (mode === "cutaway") setSceneFocus("gearbox")
    if (mode === "sensors") setSceneFocus("wind")
  }
  function inspectWeather(index: number) {
    setSceneHour(index)
    chooseScene(data[index]!.temperature <= 0 ? "icing" : "sensors")
    if (data[index]!.temperature > 0) setSceneFocus("temperature")
    document
      .getElementById("turbine-system-view")
      ?.scrollIntoView({ behavior: "smooth", block: "start" })
  }
  function inspectSource(focus: SceneFocus) {
    chooseScene("sensors")
    setSceneFocus(focus)
    document
      .getElementById("turbine-system-view")
      ?.scrollIntoView({ behavior: "smooth", block: "start" })
  }
  function inspectAgentStep(index: number) {
    setInspectedStep(index)
    chooseScene(resolveSceneMode("agent", null, true, index))
  }
  const provenance = getProvenance(date)
  const peak = data.reduce(
    (best, p) => (p.forecast > best.forecast ? p : best),
    data[0]!
  )
  const currentNav = NAV.find((item) => item.id === view)!
  const selectedTurbine = TURBINES.find((t) => t.id === dialog)
  const turbineMetrics = selectedTurbine
    ? getMetrics(generateForecast(date, horizon, selectedTurbine.id, revision))
    : null
  useEffect(() => {
    if (!busy) return
    const timer = window.setTimeout(() => {
      if (step < AGENT_STEPS.length - 1) setStep(step + 1)
      else {
        setRevision((r) => r + 1)
        setRuns((previous) => [
          {
            id: `FC-${date.slice(5).replace("-", "")}-${String(previous.length + 1).padStart(3, "0")}`,
            date,
            horizon,
            turbine,
            revision: revision + 1,
            completedAt: new Date().toISOString(),
          },
          ...previous,
        ])
        setBusy(false)
        setToast({
          key: "Демо-прогноз обновлён. Новый запуск сохранён в журнале.",
        })
      }
    }, 650)
    return () => window.clearTimeout(timer)
  }, [busy, step, date, horizon, turbine, revision])
  useEffect(() => {
    if (!toast) return
    const timer = window.setTimeout(() => setToast(null), 4500)
    return () => window.clearTimeout(timer)
  }, [toast])
  function navigate(next: View) {
    setView(next)
    setSceneOverride(null)
    setSceneFocus(next === "sources" ? "wind" : "gearbox")
    setMobileMenu(false)
    window.scrollTo({ top: 0, behavior: "smooth" })
  }
  function refresh() {
    if (busy) return
    setStep(0)
    setBusy(true)
  }
  const analytical = view === "overview" || view === "forecast"
  function selectHour(index: number) {
    setSceneHour(resolveHour(index, data.length))
  }
  function inspectInsight(insight: ForecastInsight) {
    selectHour(insight.index)
    if (insight.kind === "cold") {
      chooseScene(insight.point.temperature <= 0 ? "icing" : "sensors")
      setSceneFocus("temperature")
    } else chooseScene("flow")
    const target =
      insight.kind === "cold"
        ? document.querySelector(".wc-turbine-hero")
        : document.getElementById("turbine-system-view")
    target?.scrollIntoView({ behavior: "smooth", block: "nearest" })
  }
  const turbineScene = (
    <TurbineHero
      compact={analytical}
      view={view}
      turbine={turbine}
      mode={sceneMode}
      focus={sceneFocus}
      point={data[inspectedHour]!}
      hourIndex={inspectedHour}
      data={data}
      busy={busy}
      step={busy ? step : inspectedStep}
      onMode={chooseScene}
      onFocus={setSceneFocus}
      onHour={setSceneHour}
      onStep={inspectAgentStep}
    />
  )
  function exportCsv() {
    const url = URL.createObjectURL(
      new Blob([forecastCsv(data, date, turbine)], {
        type: "text/csv;charset=utf-8;",
      })
    )
    const anchor = document.createElement("a")
    anchor.href = url
    anchor.download = `windcast-demo-${date}-${turbine}-${horizon}h.csv`
    document.body.appendChild(anchor)
    anchor.click()
    anchor.remove()
    window.setTimeout(() => URL.revokeObjectURL(url), 1000)
    setToast({
      key: "CSV с прогнозом на {v0} ч готов.",
      values: { v0: horizon },
    })
  }
  return (
    <TooltipProvider delay={200}>
      <div className="wc-app wc-design-v2">
        {mobileMenu && (
          <button
            className="wc-mobile-backdrop"
            aria-label={tr("Закрыть меню")}
            onClick={() => setMobileMenu(false)}
          />
        )}
        <aside
          id="wc-sidebar"
          ref={sidebarRef}
          role={mobileMenu ? "dialog" : undefined}
          aria-modal={mobileMenu || undefined}
          aria-label={mobileMenu ? tr("Меню навигации") : undefined}
          className={`wc-sidebar ${mobileMenu ? "open" : ""}`}
        >
          <a
            href="#"
            className="wc-brand"
            onClick={(e) => {
              e.preventDefault()
              navigate("overview")
            }}
          >
            <span className="wc-brand-icon">
              <Wind size={23} />
            </span>
            windcast<span className="wc-brand-period">.</span>
          </a>
          <button
            className="wc-station-switch"
            onClick={() => setDialog("all")}
          >
            <span className="wc-station-symbol">
              <Wind size={18} />
            </span>
            <span>
              <strong>{tr("Ветровая станция")}</strong>
              <small>{tr("Казахстан · 2 турбины")}</small>
            </span>
            <ChevronDown size={15} />
          </button>
          <span className="wc-nav-label">{tr("РАБОЧЕЕ ПРОСТРАНСТВО")}</span>
          <nav aria-label={tr("Основная навигация")}>
            {NAV.map(({ id, label, icon: Icon }) => (
              <button
                key={id}
                className={`wc-nav-item ${view === id ? "active" : ""}`}
                aria-current={view === id ? "page" : undefined}
                onClick={() => navigate(id)}
              >
                <Icon size={18} strokeWidth={1.6} />
                <span>{tr(label)}</span>
                {id === "agent" && <span className="wc-nav-ai">AI</span>}
                {view === id && <span className="wc-nav-active-dot" />}
              </button>
            ))}
          </nav>
          <div className="wc-sidebar-bottom">
            <div className="wc-sidebar-note">
              <span className="wc-note-kicker">
                <Sparkles size={13} /> {tr("АГЕНТНЫЙ ПРОГНОЗ")}
              </span>
              <p>
                {tr("Увидеть энергию.")}
                <br />
                {tr("Раньше, чем она появится.")}
              </p>
              <TurbineArt compact />
            </div>
            <button className="wc-nav-item" onClick={() => setDialog("help")}>
              <CircleHelp size={18} strokeWidth={1.6} />
              {tr("О проекте")}
              <ArrowUpRight size={14} />
            </button>
            <div className="wc-sidebar-version">
              <span>
                <i className="wc-live-dot" /> {tr("Демо-стенд")}
              </span>
              <span>v2</span>
            </div>
          </div>
        </aside>
        <div className="wc-workspace" inert={mobileMenu}>
          <header className="wc-topbar">
            <div className="wc-breadcrumb">
              <button
                className="wc-mobile-toggle wc-icon-button"
                ref={menuButtonRef}
                aria-expanded={mobileMenu}
                aria-controls="wc-sidebar"
                onClick={() => setMobileMenu(true)}
                aria-label={tr("Открыть меню")}
              >
                <Menu size={21} />
              </button>
              <LayoutDashboard size={16} />
              <span>{tr("Рабочее пространство")}</span>
              <ChevronRight size={13} />
              <strong>{tr(currentNav.label)}</strong>
            </div>
            <div className="wc-topbar-right">
              <LanguageSelector />
              <Badge className="wc-demo-badge">
                <span />
                {tr("Демо-данные")}
              </Badge>
              <span className="wc-topbar-divider" />
              <button
                className="wc-icon-button wc-bell"
                onClick={() => setDialog("notifications")}
                aria-label={tr("Уведомления")}
              >
                <Bell size={18} />
                <i />
              </button>
              <button
                className="wc-avatar"
                aria-label={tr("О демонстрационном проекте")}
                onClick={() => setDialog("help")}
              >
                WC
              </button>
            </div>
          </header>
          <main className="wc-main">
            <div className="wc-page-title">
              <div>
                <div className="wc-eyebrow">{tr("ЭНЕРГИЯ ПОД КОНТРОЛЕМ")}</div>
                <h1>{tr(PAGE_TITLES[view])}</h1>
                <p>
                  {tr("Прогноз, погода и работа AI-агента — в одном месте.")}
                </p>
              </div>
              <div className="wc-heading-actions">
                <Button
                  variant="outline"
                  className="wc-export-button"
                  onClick={exportCsv}
                >
                  <Download size={15} />
                  {tr("Экспорт")}
                </Button>
                <Button
                  className="wc-primary-button"
                  onClick={refresh}
                  disabled={busy}
                >
                  {busy ? (
                    <LoaderCircle size={15} className="wc-spin" />
                  ) : (
                    <RefreshCw size={15} />
                  )}
                  {busy ? tr("Выполняется расчёт…") : tr("Обновить прогноз")}
                </Button>
              </div>
            </div>
            <div className="wc-filters">
              <div className="wc-filter-left">
                <label className="wc-select-label">
                  <Wind size={15} />
                  <select
                    aria-label={tr("Выбор турбины")}
                    value={turbine}
                    disabled={busy}
                    onChange={(e) => {
                      setTurbine(e.target.value as TurbineId)
                      setRevision(0)
                    }}
                  >
                    <option value="all">{tr("Все турбины")}</option>
                    <option value="t1">{tr("Турбина 01")}</option>
                    <option value="t2">{tr("Турбина 02")}</option>
                  </select>
                  <ChevronDown size={13} />
                </label>
                <label className="wc-select-label date">
                  <CalendarDays size={15} />
                  <select
                    aria-label={tr("Дата прогноза")}
                    value={date}
                    disabled={busy}
                    onChange={(e) => {
                      setDate(e.target.value)
                      setRevision(0)
                    }}
                  >
                    {TEST_DATES.map((d) => (
                      <option key={d} value={d}>
                        {formatDate(d, true)} 2026
                      </option>
                    ))}
                  </select>
                  <ChevronDown size={13} />
                </label>
                <span className="wc-archive-label">
                  <History size={13} /> {tr("Ретроспективный режим")}
                </span>
              </div>
              <span className="wc-issued">
                {tr("Расчёт на")}{" "}
                <strong>{formatTimestamp(provenance.forecastIssuedAt)}</strong>
                <Hint>
                  {tr(
                    "Момент исторического прогноза, UTC+5. Все погодные входные данные доступны до этого времени."
                  )}
                </Hint>
              </span>
            </div>
            {!analytical && <div id="turbine-system-view">{turbineScene}</div>}
            {(view === "overview" || view === "forecast") && (
              <>
                <section
                  className="wc-stats"
                  aria-label={tr("Ключевые показатели")}
                >
                  <StatCard
                    title={tr("Средняя выработка")}
                    value={number(metrics.mean)}
                    unit="%"
                    icon={Zap}
                    note={tr("{v0} ч полной нагрузки", {
                      v0: number(metrics.fullLoadHours),
                    })}
                    values={data.map((p) => p.forecast)}
                    hint={tr(
                      "Средняя прогнозная мощность в процентах от номинальной. Для двух турбин используется среднее нормализованных значений."
                    )}
                  />
                  <StatCard
                    title={tr("Пиковая выработка")}
                    value={number(metrics.peak)}
                    unit="%"
                    icon={TrendingUp}
                    note={tr("Ожидается в {v0}", { v0: peak.hour })}
                    values={data.slice(0, 12).map((p) => p.upper)}
                    hint={tr(
                      "Максимальная прогнозная мощность на выбранном горизонте."
                    )}
                  />
                  <StatCard
                    title={tr("Скорость ветра")}
                    value={number(metrics.wind)}
                    unit={tr("м/с")}
                    icon={Wind}
                    note={tr("Среднее на горизонте")}
                    values={data.map((p) => p.wind)}
                    hint={tr(
                      "Средняя скорость ветра из синтетического архивного прогноза."
                    )}
                    positive={false}
                  />
                  <StatCard
                    title={tr("Ошибка прогноза")}
                    value={number(metrics.nmae)}
                    unit="%"
                    icon={Gauge}
                    note={tr("nMAE · ретроспектива")}
                    values={data
                      .filter((p) => p.actual !== null)
                      .map((p) => Math.abs(p.forecast - p.actual!))}
                    hint={tr(
                      "Средняя абсолютная ошибка, нормализованная на номинальную мощность. Рассчитана на моковых данных; это не качество обученной модели."
                    )}
                    positive={false}
                  />
                </section>
                <div className="wc-analysis-grid" id="turbine-system-view">
                  <ForecastChart
                    key={`${date}-${turbine}`}
                    data={data}
                    horizon={horizon}
                    setHorizon={(next) => {
                      setHorizon(next)
                      setSceneHour((hour) => resolveHour(hour, next))
                    }}
                    busy={busy}
                    onInspect={setSceneHour}
                    inspectedHour={inspectedHour}
                  />
                  {turbineScene}
                </div>
                <ForecastTimeline
                  data={data}
                  index={inspectedHour}
                  onSelect={selectHour}
                />
                <ForecastInsights
                  data={data}
                  index={inspectedHour}
                  onSelect={inspectInsight}
                />
                {view === "overview" && (
                  <div className="wc-overview-support">
                    <AgentPanel
                      busy={busy}
                      step={step}
                      onOpen={() => navigate("agent")}
                      onInspect={(index) => {
                        navigate("agent")
                        inspectAgentStep(index)
                      }}
                    />
                    <WeatherPanel
                      data={data}
                      inspectedHour={inspectedHour}
                      onInspect={inspectWeather}
                    />
                    <TurbinePanel
                      date={date}
                      horizon={horizon}
                      revision={revision}
                      onOpen={setDialog}
                    />
                  </div>
                )}
                {view === "forecast" && (
                  <div className="wc-evaluation-note">
                    <ShieldCheck size={20} />
                    <div>
                      <strong>{tr("Честная ретроспективная оценка")}</strong>
                      <p>
                        {tr(
                          "Факт за февраль показан только для сравнения и не используется в прогнозе. Данные за март отсутствуют. Диапазон неопределённости — демонстрационный, без статистической калибровки."
                        )}
                      </p>
                    </div>
                    <span>
                      RMSE <b>{number(metrics.rmse)}%</b>
                    </span>
                  </div>
                )}
                <HourlyTable
                  key={`${date}-${horizon}-${turbine}`}
                  data={data}
                  onExport={exportCsv}
                  onPoint={(point) => {
                    setSceneHour(
                      data.findIndex((p) => p.timestamp === point.timestamp)
                    )
                    setSelectedPoint(point)
                  }}
                  compact={view === "overview"}
                />
              </>
            )}
            {view === "agent" && (
              <>
                <div className="wc-agent-page-grid">
                  <AgentPanel
                    busy={busy}
                    step={step}
                    onOpen={() => navigate("history")}
                    onInspect={(index) => {
                      inspectAgentStep(index)
                      document
                        .getElementById("turbine-system-view")
                        ?.scrollIntoView({ behavior: "smooth", block: "start" })
                    }}
                    expanded
                  />
                  <Card className="wc-card wc-agent-log">
                    <div className="wc-panel-heading">
                      <div>
                        <h2>{tr("Журнал событий")}</h2>
                        <p>{tr("Прозрачность на каждом этапе")}</p>
                      </div>
                      <span className="wc-terminal-label">{tr("ДЕМО")}</span>
                    </div>
                    <div className="wc-log-lines">
                      {AGENT_STEPS.filter((_, i) => !busy || i <= step).map(
                        (item, i) => (
                          <div key={item.title}>
                            <span>
                              +{number(i * 0.65, 2)} {tr("с")}
                            </span>
                            {busy && i === step ? (
                              <LoaderCircle size={13} className="wc-spin" />
                            ) : (
                              <Check size={13} />
                            )}
                            <p>{tr(item.detail)}</p>
                          </div>
                        )
                      )}
                    </div>
                    <div className="wc-log-explainer">
                      <Info size={15} />
                      {tr(
                        "Это симуляция оркестрации. Внешние API и ML-модель пока не подключены."
                      )}
                    </div>
                  </Card>
                </div>
              </>
            )}
            {view === "sources" && (
              <>
                <div className="wc-info-banner">
                  <ShieldCheck size={21} />
                  <div>
                    <strong>
                      {tr("Только то, что было известно на момент прогноза")}
                    </strong>
                    <p>
                      {tr(
                        "В рабочей системе используются архивные прогнозы, а не погода, наблюдавшаяся позднее. Здесь это правило воспроизведено на синтетических данных."
                      )}
                    </p>
                  </div>
                </div>
                <SourcesPanel date={date} detailed />
                <div className="wc-secondary-grid">
                  <Card className="wc-card wc-dataset-card">
                    <Database size={26} />
                    <h2>{tr("История работы ВЭС")}</h2>
                    <p>{tr("Март 2023 — январь 2026")}</p>
                    <div className="wc-data-fields">
                      <span>{tr("Временная метка")}</span>
                      <button
                        type="button"
                        onClick={() => {
                          inspectSource("wind")
                        }}
                      >
                        {tr("Скорость ветра, м/с")}
                      </button>
                      <button
                        type="button"
                        onClick={() => {
                          inspectSource("power")
                        }}
                      >
                        {tr("Нормализованная мощность")}
                      </button>
                      <button
                        type="button"
                        onClick={() => {
                          inspectSource("temperature")
                        }}
                      >
                        {tr("Температура, °C")}
                      </button>
                    </div>
                    <small>
                      {tr(
                        "Схема соответствует кейсу. Исходный датасет не загружен."
                      )}
                    </small>
                  </Card>
                  <Card className="wc-card wc-dataset-card">
                    <MapPin size={26} />
                    <h2>{tr("Две точки наблюдения")}</h2>
                    <p>{tr("Площадки из описания кейса")}</p>
                    {TURBINES.map((t) => (
                      <a
                        className="wc-map-link"
                        key={t.id}
                        href={t.map}
                        target="_blank"
                        rel="noreferrer"
                      >
                        {tr(t.name)}
                        <ExternalLink size={14} />
                      </a>
                    ))}
                    <small>
                      {tr("Числовые координаты не подменяются вымышленными.")}
                    </small>
                  </Card>
                </div>
              </>
            )}
            {view === "history" && (
              <Card className="wc-card wc-history-card">
                <div className="wc-panel-heading">
                  <div>
                    <h2>
                      {tr("Запуски прогнозирования")}{" "}
                      <span className="wc-count">{runs.length}</span>
                    </h2>
                    <p>
                      {tr(
                        "Демо-история текущей сессии · сбрасывается при перезагрузке"
                      )}
                    </p>
                  </div>
                  <Badge variant="outline">{tr("Февраль 2026")}</Badge>
                </div>
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>{tr("Запуск")}</TableHead>
                      <TableHead>{tr("Дата прогноза")}</TableHead>
                      <TableHead>{tr("Объект")}</TableHead>
                      <TableHead>{tr("Горизонт")}</TableHead>
                      <TableHead>{tr("Статус")}</TableHead>
                      <TableHead />
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {runs.map((run) => (
                      <TableRow key={run.id}>
                        <TableCell>
                          <span className="wc-run-id">
                            <FileClock size={15} />
                            {run.id}
                          </span>
                        </TableCell>
                        <TableCell>{formatDate(run.date, true)}</TableCell>
                        <TableCell>
                          {run.turbine === "all"
                            ? tr("Все турбины")
                            : run.turbine === "t1"
                              ? tr("Турбина 01")
                              : tr("Турбина 02")}
                        </TableCell>
                        <TableCell>
                          {run.horizon}{" "}
                          {run.horizon === 24 ? tr("часа") : tr("часов")}
                        </TableCell>
                        <TableCell>
                          <span className="wc-status">
                            <i />
                            {tr("Завершён")}
                          </span>
                        </TableCell>
                        <TableCell>
                          <button
                            className="wc-text-button"
                            onClick={() => {
                              setDate(run.date)
                              setHorizon(run.horizon)
                              setTurbine(run.turbine)
                              setRevision(run.revision)
                              setSceneHour(0)
                              navigate("forecast")
                            }}
                            disabled={busy}
                          >
                            {tr("Открыть")}
                            <ArrowUpRight size={14} />
                          </button>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </Card>
            )}
            <footer className="wc-footer">
              <span>
                <Wind size={14} />
                Windcast · Agentic Wind Intelligence
              </span>
              <span>
                {tr("Синтетические данные · Тестовый период: февраль 2026")}
              </span>
            </footer>
          </main>
        </div>
        {toast && (
          <div className="wc-toast" role="status">
            <span>
              <Check size={15} />
            </span>
            {tr(toast.key, toast.values)}
            <button
              aria-label={tr("Закрыть уведомление")}
              onClick={() => setToast(null)}
            >
              <X size={15} />
            </button>
          </div>
        )}
        <Dialog
          open={dialog !== null}
          onOpenChange={(open) => {
            if (!open) setDialog(null)
          }}
        >
          <DialogContent className="wc-dialog" closeLabel={tr("Закрыть")}>
            <DialogHeader>
              <DialogTitle>
                {dialog === "help"
                  ? tr("Windcast — энергия данных")
                  : dialog === "notifications"
                    ? tr("Уведомления")
                    : tr(selectedTurbine?.name ?? "Ветровая станция")}
              </DialogTitle>
              <DialogDescription>
                {dialog === "help"
                  ? tr(
                      "Демонстрационный dashboard по кейсу прогнозирования почасовой выработки ВЭС."
                    )
                  : dialog === "notifications"
                    ? tr("События демонстрационного рабочего пространства.")
                    : tr("Карточка объекта · демонстрационные данные")}
              </DialogDescription>
            </DialogHeader>
            {dialog === "help" ? (
              <div className="wc-dialog-copy">
                <p>
                  {tr(
                    "Выберите турбину, дату в феврале 2026 и горизонт 24/48 часов. График и показатели пересчитаются. «Обновить прогноз» показывает полный цикл AI-агента, а «Экспорт» сохраняет CSV."
                  )}
                </p>
                <p>
                  {tr(
                    "Все значения синтетические. Реальные погодные API, модель машинного обучения и серверное хранение не подключены. Номинальная мощность не задана в кейсе, поэтому выработка показана в процентах."
                  )}
                </p>
                <a
                  href="https://docs.google.com/document/d/1Fn5IJoj87Fx7IAknG26zkfX8c0eq7feCujd0m66PCgY/preview"
                  target="_blank"
                  rel="noreferrer"
                >
                  {tr("Открыть описание кейса")} <ExternalLink size={14} />
                </a>
              </div>
            ) : dialog === "notifications" ? (
              <div className="wc-notifications">
                <div>
                  <CheckCheck size={20} />
                  <span>
                    <strong>{tr("Демо-стенд готов")}</strong>
                    <p>{tr("Доступны 2 турбины и 28 прогнозных дат.")}</p>
                  </span>
                </div>
                <div>
                  <History size={20} />
                  <span>
                    <strong>
                      {tr("Запусков в текущей сессии:")} {runs.length}
                    </strong>
                    <p>
                      {tr("Последний:")} {runs[0]!.id}
                    </p>
                  </span>
                </div>
                <Button
                  variant="outline"
                  onClick={() => {
                    setDialog(null)
                    navigate("history")
                  }}
                >
                  {tr("Открыть историю")} <ArrowRight size={14} />
                </Button>
              </div>
            ) : (
              <div className="wc-object-details">
                <TurbineArt />
                {selectedTurbine && turbineMetrics ? (
                  <>
                    <div>
                      <span>{tr("Идентификатор")}</span>
                      <strong>{selectedTurbine.code}</strong>
                    </div>
                    <div>
                      <span>{tr("Средняя выработка")}</span>
                      <strong>{number(turbineMetrics.mean)}%</strong>
                    </div>
                    <div>
                      <span>{tr("Скорость ветра")}</span>
                      <strong>
                        {number(turbineMetrics.wind)} {tr("м/с")}
                      </strong>
                    </div>
                    <a
                      href={selectedTurbine.map}
                      target="_blank"
                      rel="noreferrer"
                    >
                      {tr("Координаты из кейса")}
                      <ExternalLink size={14} />
                    </a>
                    <Button
                      className="wc-primary-button"
                      disabled={busy}
                      onClick={() => {
                        setTurbine(selectedTurbine.id)
                        setDialog(null)
                        navigate("forecast")
                      }}
                    >
                      {tr("Открыть прогноз")} <ArrowRight size={14} />
                    </Button>
                  </>
                ) : (
                  <>
                    <p>
                      {tr(
                        "Две турбины из кейса. Общие показатели рассчитаны как среднее нормализованной мощности."
                      )}
                    </p>
                    <Button
                      onClick={() => {
                        setTurbine("all")
                        setDialog(null)
                      }}
                      disabled={busy}
                    >
                      {tr("Показать всю станцию")}
                    </Button>
                  </>
                )}
              </div>
            )}
          </DialogContent>
        </Dialog>
        <Dialog
          open={selectedPoint !== null}
          onOpenChange={(open) => {
            if (!open) setSelectedPoint(null)
          }}
        >
          <DialogContent className="wc-dialog" closeLabel={tr("Закрыть")}>
            <DialogHeader>
              <DialogTitle>
                {tr("Прогноз на")} {selectedPoint?.hour}
              </DialogTitle>
              <DialogDescription>
                {selectedPoint && formatDate(selectedPoint.date, true)}{" "}
                {tr("2026 · UTC+5 · синтетические данные")}
              </DialogDescription>
            </DialogHeader>
            {selectedPoint && (
              <div className="wc-provenance">
                <div>
                  <span>{tr("Прогноз мощности")}</span>
                  <strong>{number(selectedPoint.forecast)}%</strong>
                </div>
                <div>
                  <span>{tr("Диапазон")}</span>
                  <strong>
                    {number(selectedPoint.lower)}–{number(selectedPoint.upper)}%
                  </strong>
                </div>
                <div>
                  <span>{tr("Фактическое значение")}</span>
                  <strong>
                    {selectedPoint.actual === null
                      ? tr("Нет данных за тестовый период")
                      : `${number(selectedPoint.actual)}%`}
                  </strong>
                </div>
                <div>
                  <span>{tr("Скорость ветра")}</span>
                  <strong>
                    {number(selectedPoint.wind)} {tr("м/с")}
                  </strong>
                </div>
                <div>
                  <span>{tr("Температура")}</span>
                  <strong>{number(selectedPoint.temperature)} °C</strong>
                </div>
                <p>
                  {tr(
                    "Диапазон показывает демонстрационную неопределённость и расширяется с горизонтом прогноза."
                  )}
                </p>
              </div>
            )}
          </DialogContent>
        </Dialog>
      </div>
    </TooltipProvider>
  )
}
