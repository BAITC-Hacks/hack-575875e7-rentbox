"use client"

import { useSystemReducedMotion } from "@/components/motion-preference"
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
  CloudSun,
  Database,
  Download,
  ExternalLink,
  FileClock,
  FlaskConical,
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
  Wind,
  X,
  Zap,
  type LucideIcon,
} from "lucide-react"
import {
  AppearanceControls,
  useAppearance,
} from "@/components/appearance-provider"
import { TurbineHero } from "@/components/turbine-hero"
import { PlatformHelper } from "@/components/platform-helper"
import { AssistantLauncher } from "@/components/assistant-launcher"
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
  clamp,
  getMetrics,
  type ForecastPoint,
  type Horizon,
  type TurbineId,
} from "@/lib/forecast-data"
import {
  downloadForecast, forecastDate, forecastPoints, forecastSources, issueForDate, pointSources,
  stageIndex, statusLabel, turbineIds, turbineSelection,
  type ApiForecast, type ApiRun, type DashboardTurbine,
} from "@/lib/forecast-api"
import { useForecastDashboard } from "@/lib/use-forecast-dashboard"

import {
  resolveHour,
  resolveSceneMode,
  type DashboardView,
  type SceneFocus,
  type SceneMode,
} from "@/lib/turbine-scene"

import {
  SimulationControl,
  SimulationSummary,
  SimulationMethod,
  SimulationHour,
  newSimulationSeed,
} from "@/components/simulation-controls"
import {
  generateSimulation,
  simulationCsv,
  simulationSummary,
  OPERATING_LABELS,
  type SimulationConfig,
} from "@/lib/wind-simulation"

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
  const { tr } = useI18n()
  if (!values.length)
    return <span className="wc-muted">{tr("Нет данных")}</span>
  const min = Math.min(...values),
    max = Math.max(...values)
  const line = values
    .map(
      (v, i) =>
        `${(i * 92) / Math.max(1, values.length - 1)},${32 - ((v - min) / (max - min || 1)) * 26}`
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
  values: (number | null)[]
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
        <Sparkline values={values.filter((value): value is number => value !== null)} />
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
  horizon: number
  setHorizon: (h: Horizon) => void
  busy: boolean
  onInspect: (index: number) => void
  inspectedHour: number
}) {
  const { tr, number, formatDate } = useI18n()
  const { highVisibility } = useAppearance()
  const simulated = Boolean(data[0]?.simulation)
  const chartLeft = highVisibility ? 66 : 45

  const [active, setActive] = useState<number | null>(null)
  const [showActual, setShowActual] = useState(true)
  const [showRange, setShowRange] = useState(true)
  const hasActual = data.some((point) => point.actual !== null)
  const hasRange = data.every((point) => point.lower !== null && point.upper !== null)
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
  const x = (i: number) =>
    chartLeft + (i / (data.length - 1)) * (plotWidth - chartLeft - 16)
  const y = (v: number) => 222 - v * 1.95
  const path = (key: "forecast" | "actual" | "lower" | "upper") =>
    data
      .filter((p) => p[key] !== null)
      .map(
        (p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(p[key]!).toFixed(1)}`
      )
      .join(" ")
  const area = hasRange ? `${path("upper")} ${[...data]
    .reverse()
    .map((p, i) => `L${x(data.length - i - 1)},${y(p.lower!)}`)
    .join(" ")} Z` : ""
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
            {tr(simulated ? "Симуляция выработки" : "Почасовой прогноз")}
            <span className="wc-tag">
              {horizon} {tr("ч")}
            </span>
          </h2>
          <p>{tr("Нормализованная мощность · %")}</p>
        </div>
        {!simulated && (
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
        )}
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
        {!simulated && (
          <button
            onClick={() => setShowActual(!showActual)}
            disabled={!hasActual}
            aria-pressed={hasActual && showActual}
            className={!showActual ? "off" : ""}
          >
            <i className="wc-legend-line dashed" />
            {hasActual ? tr("Факт") : tr("Факт отсутствует")}
          </button>
        )}
        <button
          onClick={() => setShowRange(!showRange)}
          disabled={!hasRange}
          aria-pressed={hasRange && showRange}
          className={!showRange ? "off" : ""}
        >
          <i className="wc-legend-range" />
          {hasRange ? tr("Диапазон прогноза") : tr("Диапазон не рассчитан")}
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
                ((((e.clientX - rect.left) / rect.width) * plotWidth -
                  chartLeft) /
                  (plotWidth - chartLeft - 16)) *
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
          viewBox={`0 0 ${plotWidth} ${highVisibility ? 290 : 264}`}
          role="img"
          aria-label={tr("Почасовой прогноз выработки на {v0} ч", {
            v0: horizon,
          })}
        >
          <defs>
            <linearGradient id="forecast-fill" x1="0" y1="0" x2="0" y2="1">
              <stop
                stopColor="var(--wc-chart-forecast, #8caf6a)"
                stopOpacity=".18"
              />
              <stop
                offset="1"
                stopColor="var(--wc-chart-forecast, #8caf6a)"
                stopOpacity="0"
              />
            </linearGradient>
          </defs>
          {[0, 25, 50, 75, 100].map((tick) => (
            <g key={tick}>
              <line
                x1={chartLeft}
                x2={plotWidth - 16}
                y1={y(tick)}
                y2={y(tick)}
                stroke="var(--wc-chart-grid, #e9ece7)"
                strokeDasharray="3 5"
              />
              <text
                x={chartLeft - 12}
                y={y(tick) + 4}
                textAnchor="end"
                className="wc-axis"
              >
                {tick}%
              </text>
            </g>
          ))}
          {(highVisibility && plotWidth < 460
            ? [0, 0.5, 1]
            : [0, 0.25, 0.5, 0.75, 1]
          ).map((part) => {
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
                {(simulated || i % 24 === 0) && (
                  <tspan x={x(i)} dy={highVisibility ? 22 : 13}>
                    {formatDate(data[i]!.date)}
                  </tspan>
                )}
              </text>
            )
          })}
          <path
            d={`${path("forecast")} L${plotWidth - 16},222 L${chartLeft},222 Z`}
            fill="url(#forecast-fill)"
          />
          {hasRange && showRange && (
            <path
              d={area}
              fill="var(--wc-chart-range, #9abb7c)"
              opacity=".17"
            />
          )}
          {hasActual && showActual && !simulated && (
            <path
              d={path("actual")}
              fill="none"
              stroke="var(--wc-chart-actual, #9fa59c)"
              strokeWidth="1.8"
              strokeDasharray="5 5"
              strokeLinecap="round"
            />
          )}
          <path
            d={path("forecast")}
            fill="none"
            stroke="var(--wc-chart-forecast, #48794d)"
            strokeWidth="2.7"
            strokeLinejoin="round"
            strokeLinecap="round"
          />
          {selected && (
            <g>
              <rect
                x={
                  x(displayIndex) -
                  Math.max(5, (plotWidth - chartLeft - 16) / data.length / 2)
                }
                y="20"
                width={Math.max(10, (plotWidth - chartLeft - 16) / data.length)}
                height="203"
                fill="var(--wc-chart-selection, #e0ebd5)"
                opacity=".65"
              />

              <line
                x1={x(displayIndex)}
                x2={x(displayIndex)}
                y1="20"
                y2="223"
                stroke="var(--wc-chart-forecast, #718d62)"
                strokeDasharray="3 4"
              />
              <circle
                cx={x(displayIndex)}
                cy={y(selected.forecast)}
                r="5"
                fill="var(--wc-chart-forecast, #48794d)"
                stroke="var(--wc-chart-dot-outline, white)"
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
            {showActual && !simulated && (
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
          {tr(
            simulated
              ? "Синтетическая симуляция · не прогноз погоды"
              : "Архивный прогноз без данных из будущего"
          )}
        </span>
        <span>{tr("Выбранный час связан с 3D-моделью")}</span>
      </div>
    </Card>
  )
}
function AgentPanel({
  busy,
  step,
  run,
  onOpen,
  expanded = false,
  onInspect,
}: {
  busy: boolean
  step: number
  run: ApiRun | null
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
          <p>
            {run
              ? tr("Режим {v0} · {v1}%", {
                  v0: run.agent_mode,
                  v1: Math.round(run.progress * 100),
                })
              : tr("Ожидает запуска")}
          </p>
        </div>
        <span className={`wc-status ${busy ? "processing" : ""}`}>
          <i />
          {run ? tr(statusLabel[run.status]) : tr("Нет запуска")}
        </span>
      </div>
      <div className="wc-agent-steps">
        {AGENT_STEPS.map((item, i) => {
          const current = busy && i === step
          const done = run?.status === "completed" || (!!run && i < step)
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
                    : run?.status === "failed"
                      ? tr("Не выполнено")
                      : run
                        ? tr("В очереди")
                        : tr("Ожидает запуска")}
              </span>
            </div>
          )
        })}
      </div>
      <div className="wc-agent-footer">
        <span>
          <span className="wc-live-dot" />
          {run?.status === "completed"
            ? tr("6 из 6 этапов выполнено")
            : run?.status === "failed"
              ? tr("Расчёт завершился ошибкой")
              : busy
                ? tr("Выполняется расчёт")
                : tr("Запустите прогноз")}
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
  const dayOffset = Math.floor(inspectedHour / 24) * 24
  const selected = [0, 6, 12, 18]
    .map((i) => data[dayOffset + i]!)
    .filter(Boolean)
  return (
    <Card className="wc-card wc-weather-card">
      <div className="wc-panel-heading">
        <div>
          <h2>{tr("Погодные условия")}</h2>
          <p>
            {tr(point.simulation ? "Симуляция" : "Прогнозные часы ·")}{" "}
            {formatDate(point.date)}
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
            aria-pressed={inspectedHour === dayOffset + i * 6}
            onClick={() => onInspect(dayOffset + i * 6)}
            aria-label={tr("Показать погодный сценарий на {v0}", {
              v0: p.hour,
            })}
          >
            <span>{p.hour}</span>
            <Info className="wc-weather-icon" />
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
        <span>
          {tr(
            point.simulation
              ? "Состояние погоды задано сценарием"
              : "Ветер и температура — из прогноза погоды, использованного моделью"
          )}
        </span>
        <Hint>
          {tr(
            point.simulation
              ? "Ветер и температура сгенерированы сценарием симуляции. Это не прогноз погоды."
              : "Скорость ветра на 100 м и температура на 2 м берутся из того же выпуска NOAA GFS, по которому рассчитана мощность. Для станции показано среднее двух турбин."
          )}
        </Hint>
      </div>
    </Card>
  )
}
function TurbinePanel({
  forecast,
  turbines,
  simulationData,
  onOpen,
}: {
  forecast: ApiForecast | null
  turbines: DashboardTurbine[]
  simulationData?: Record<TurbineId, ForecastPoint[]> | null
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
        {turbines.map((t) => {
          const m = getMetrics(
            simulationData?.[t.id] ?? forecastPoints(forecast, t.id)
          )
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
                    <i style={{ width: `${m.mean ?? 0}%` }} />
                </span>
              </span>
              <ChevronRight size={16} />
            </button>
          )
        })}
      </div>
      <div className="wc-subtle-note">
        <Info size={13} />{" "}
        {tr("Мощность показана в шкале 0–1; база нормализации не подтверждена.")}
      </div>
    </Card>
  )
}
function SourcesPanel({
  forecast,
  detailed = false,
}: {
  forecast: ApiForecast | null
  detailed?: boolean
}) {
  const { tr, formatTimestamp } = useI18n()
  const sources = forecastSources(forecast)
  return (
    <Card className="wc-card wc-source-card">
      <div className="wc-panel-heading">
        <div>
          <h2>{tr("Источники прогноза")}</h2>
          <p>{tr("Метаданные выбранного расчёта · время UTC+5")}</p>
        </div>
        <ShieldCheck size={22} className="wc-green" />
      </div>
      {!forecast && (
        <p className="wc-subtle-note">
          {tr(
            "Откройте сохранённый расчёт или запустите прогноз, чтобы увидеть его источники."
          )}
        </p>
      )}
      {sources.map((source) => (
        <div
          className="wc-provenance"
          key={`${source.source_id}:${source.sha256}`}
        >
          <div>
            <span>{tr("Погодный источник")}</span>
            <strong>
              {source.provider} · {source.model}
            </strong>
          </div>
          <div>
            <span>{tr("Выпуск погоды")}</span>
            <strong>
              {source.initialization_time
                ? formatTimestamp(source.initialization_time)
                : tr("Точное время неизвестно")}
            </strong>
          </div>
          <div>
            <span>{tr("Публикация погоды")}</span>
            <strong>
              {source.available_at
                ? formatTimestamp(source.available_at)
                : tr("Оценка доступности по каждому часу")}
            </strong>
          </div>
          {detailed && (
            <>
              <div>
                <span>{tr("Архив скачан")}</span>
                <strong>{formatTimestamp(source.retrieved_at)}</strong>
              </div>
              <div>
                <span>SHA-256</span>
                <code className="wc-hash">{source.sha256}</code>
              </div>
              <p>{source.availability_basis}</p>
            </>
          )}
        </div>
      ))}
      {forecast && (
        <div className="wc-provenance">
          <div>
            <span>{tr("Момент решения")}</span>
            <strong>{formatTimestamp(forecast.as_of)}</strong>
          </div>
          <div>
            <span>{tr("Обучающие данные доступны до")}</span>
            <strong>
              {formatTimestamp(forecast.training_data_available_until)}
            </strong>
          </div>
          <div>
            <span>{tr("Версия модели")}</span>
            <code className="wc-hash">{forecast.model_version}</code>
          </div>
          <p>
            {tr(
              "Дата скачивания архива отличается от исторического времени публикации. Для Previous Runs доступность остаётся оценочной."
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
          <p>
            {tr(
              data[0]?.simulation
                ? "Синтетическая симуляция · шаг 1 час · UTC+5"
                : "Прогноз мощности · факт февраля отсутствует · UTC+5"
            )}
          </p>
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
            <Download size={14} />{" "}
            {tr(data[0]?.simulation ? "Экспорт" : "CSV выпуска")}
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
                {tr(data[0]?.simulation ? "Мощность, %" : "Прогноз, %")}{" "}
                <ChevronDown
                  size={13}
                  className={sort === "low" ? "wc-rotate" : ""}
                />
              </button>
            </TableHead>
            <TableHead>
              {tr(data[0]?.simulation ? "Порывы, м/с" : "Факт, %")}
            </TableHead>
            <TableHead>
              {tr(data[0]?.simulation ? "Состояние" : "Отклонение, п.п.")}
            </TableHead>
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
                {p.simulation
                  ? number(p.simulation.gust)
                  : p.actual === null
                    ? "—"
                    : number(p.actual)}
              </TableCell>
              <TableCell>
                {p.simulation ? (
                  tr(
                    p.simulation.stoppedTurbines > 0 && p.forecast > 0
                      ? "Частичная остановка"
                      : OPERATING_LABELS[p.simulation.state]
                  )
                ) : p.actual === null ? (
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
  const systemReducedMotion = useSystemReducedMotion()
  const { locale, tr, number, formatDate, formatTimestamp } = useI18n()
  const { highVisibility } = useAppearance()

  const [view, setView] = useState<View>("overview")
  const [sceneOverride, setSceneOverride] = useState<SceneMode | null>(null)
  const [sceneFocus, setSceneFocus] = useState<SceneFocus>("gearbox")
  const [sceneHour, setSceneHour] = useState(0)
  const [inspectedStep, setInspectedStep] = useState(2)
  const [date, setDate] = useState("2026-02-01")
  const [horizon, setHorizon] = useState<Horizon>(48)
  const [turbine, setTurbine] = useState<TurbineId>("all")
  const dashboard = useForecastDashboard()
  const { run, runs, health, summary, turbines } = dashboard
  const busy = dashboard.busy
  const step = run ? stageIndex[run.stage] : 0
  const [refreshWeather, setRefreshWeather] = useState(false)
  const [downloadError, setDownloadError] = useState<string | null>(null)
  const [downloading, setDownloading] = useState(false)
  const [simulation, setSimulation] = useState<SimulationConfig | null>(null)
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
  const forecast = dashboard.forecast
  const result =
    forecast &&
    forecastDate(forecast.as_of) === date &&
    forecast.horizon_hours === horizon
      ? forecast
      : null
  const simulationData = useMemo(
    () => (simulation ? generateSimulation(simulation) : null),
    [simulation]
  )
  const data = useMemo(
    () => simulationData?.[turbine] ?? forecastPoints(result, turbine),
    [simulationData, result, turbine]
  )
  const simulatedMetrics = simulation
    ? simulationSummary(data, simulation, turbine)
    : null
  const helperRun = !simulation && run && forecastDate(run.as_of) === date && run.horizon_hours === horizon
    && turbineIds(turbine).every((id) => run.turbine_ids.includes(id)) ? run : null
  const metrics = useMemo(() => getMetrics(data), [data])
  const inspectedHour = resolveHour(sceneHour, data.length)
  const automaticScene =
    simulation && (view === "overview" || view === "forecast")
      ? (data[inspectedHour]?.simulation?.icingLoss ?? 0) > 1
        ? "icing"
        : "flow"
      : null
  const sceneMode = resolveSceneMode(
    view,
    sceneOverride ?? automaticScene,
    busy,
    step
  )
  function chooseScene(mode: SceneMode) {
    setSceneOverride(mode)
    if (mode === "cutaway") setSceneFocus("gearbox")
    if (mode === "sensors") setSceneFocus("wind")
  }
  function inspectWeather(index: number) {
    setSceneHour(index)
    const temperature = data[index]?.temperature
    chooseScene(temperature != null && temperature <= 0 ? "icing" : "sensors")
    if (temperature != null && temperature > 0) setSceneFocus("temperature")
    document.getElementById("turbine-system-view")?.scrollIntoView({
      behavior: highVisibility ? "auto" : "smooth",
      block: "start",
    })
  }
  function inspectSource(focus: SceneFocus) {
    chooseScene("sensors")
    setSceneFocus(focus)
    document.getElementById("turbine-system-view")?.scrollIntoView({
      behavior: highVisibility ? "auto" : "smooth",
      block: "start",
    })
  }
  function inspectAgentStep(index: number) {
    setInspectedStep(index)
    chooseScene(resolveSceneMode("agent", null, true, index))
  }
  const issuedAt = result?.as_of ?? issueForDate(date)
  const peak = data.reduce<ForecastPoint | null>(
    (best, point) => !best || point.forecast > best.forecast ? point : best, null,
  )
  const currentNav = NAV.find((item) => item.id === view)!
  const selectedTurbine = turbines.find((item) => item.id === dialog)
  const turbineMetrics = selectedTurbine
    ? getMetrics(
        simulationData?.[selectedTurbine.id] ??
          forecastPoints(result, selectedTurbine.id)
      )
    : null
  const warnings = [
    ...new Set([
      ...(summary?.warnings ?? []),
      ...(run?.warnings ?? []),
      ...(result?.analysis.warnings ?? []),
    ]),
  ]
  const dates = TEST_DATES.includes(date)
    ? TEST_DATES
    : [...TEST_DATES, date].sort()
  const error = dashboard.error ?? downloadError
  const selectedWeather = selectedPoint
    ? pointSources(result, turbine, selectedPoint.timestamp)
    : []
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
    window.scrollTo({ top: 0, behavior: highVisibility ? "auto" : "smooth" })
  }
  function runSimulation(config: SimulationConfig) {
    if (busy) return
    setSimulation(config)
    setSceneHour(0)
    setSelectedPoint(null)
    navigate("overview")
    setToast({
      key: "Симуляция готова. Это синтетический сценарий, он не сохраняется в истории сервера.",
    })
  }
  function resetSimulation() {
    setSimulation(null)
    setSceneHour(0)
    setSelectedPoint(null)
    setSceneOverride(null)
  }
  function refresh() {
    if (busy || dashboard.loading) return
    if (simulation) {
      runSimulation({ ...simulation, seed: newSimulationSeed() })
      return
    }
    setDownloadError(null)
    setSelectedPoint(null)
    setSceneHour(0)
    if (run && (run.status === "running" || run.status === "queued")) {
      openRun(run)
      return
    }
    void dashboard.start({
      as_of: issueForDate(date),
      horizon_hours: horizon,
      turbine_ids: turbineIds(turbine),
      refresh_weather: refreshWeather,
    })
  }
  function openRun(item: ApiRun) {
    if (busy) return
    setSimulation(null)
    setDate(forecastDate(item.as_of))
    setHorizon(item.horizon_hours)
    setTurbine(turbineSelection(item.turbine_ids))
    setSceneHour(0)
    setSelectedPoint(null)
    navigate(item.status === "completed" ? "forecast" : "agent")
    void dashboard.open(item.run_id)
  }
  const analytical = view === "overview" || view === "forecast"
  function selectHour(index: number) {
    setSceneHour(resolveHour(index, data.length))
    if (simulation) setSceneOverride(null)
  }
  function inspectInsight(insight: ForecastInsight) {
    selectHour(insight.index)
    if (insight.kind === "cold") {
      const temperature = insight.point.temperature
      chooseScene(temperature != null && temperature <= 0 ? "icing" : "sensors")
      setSceneFocus("temperature")
    } else chooseScene("flow")
    const target =
      insight.kind === "cold"
        ? document.querySelector(".wc-turbine-hero")
        : document.getElementById("turbine-system-view")
    target?.scrollIntoView({
      behavior: highVisibility ? "auto" : "smooth",
      block: "nearest",
    })
  }
  const turbineScene = (
    <TurbineHero
      compact={analytical}
      view={view}
      turbine={turbine}
      mode={sceneMode}
      focus={sceneFocus}
      point={data[inspectedHour] ?? null}
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
  async function exportCsv() {
    if (simulation) {
      // Synthetic scenario: built in the browser, never stored on the server.
      const url = URL.createObjectURL(
        new Blob([simulationCsv(data, simulation, turbine)], {
          type: "text/csv;charset=utf-8;",
        })
      )
      const anchor = document.createElement("a")
      anchor.href = url
      anchor.download = `windcast-simulation-${simulation.scenario}-${simulation.startDate}-${simulation.endDate}-${turbine}-${simulation.seed}.csv`
      document.body.appendChild(anchor)
      anchor.click()
      anchor.remove()
      window.setTimeout(() => URL.revokeObjectURL(url), 1000)
      setToast({
        key: "CSV с прогнозом на {v0} ч готов.",
        values: { v0: data.length },
      })
      return
    }
    if (!result || !run || downloading) return
    setDownloading(true)
    setDownloadError(null)
    try {
      await downloadForecast(run.run_id)
      setToast({ key: "CSV выбранного выпуска скачан." })
    } catch (cause) {
      setDownloadError(
        cause instanceof Error ? cause.message : tr("Не удалось скачать CSV.")
      )
    } finally {
      setDownloading(false)
    }
  }
  return (
    <TooltipProvider delay={200}>
      <div className="wc-app wc-design-v2">
        <a className="wc-skip-link" href="#main-content">
          {tr("Перейти к содержимому")}
        </a>
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
              {tr("Помощник")}
              <ArrowUpRight size={14} />
            </button>
            <div className="wc-sidebar-version">
              <span>
                <i className="wc-live-dot" />{" "}
                {health ? tr("API подключён") : tr("Нет подключения")}
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
              <AppearanceControls />
              <LanguageSelector />
              <Badge className="wc-demo-badge">
                <span />
                {tr(
                  health?.research_mode
                    ? "Исследовательский режим"
                    : health
                      ? "Реальные прогнозы"
                      : "Ожидание API"
                )}
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
                aria-label={tr("Открыть помощник Windcast")}
                onClick={() => setDialog("help")}
              >
                WC
              </button>
            </div>
          </header>
          <main className="wc-main" id="main-content" tabIndex={-1}>
            <div className="wc-page-title">
              <div>
                <div className="wc-eyebrow">{tr("ЭНЕРГИЯ ПОД КОНТРОЛЕМ")}</div>
                <h1>{tr(PAGE_TITLES[view])}</h1>
                <p>
                  {tr(
                    view === "forecast"
                      ? "Почасовые значения выбранного выпуска, детализация по часам и выгрузка CSV."
                      : "Прогноз, погода и работа AI-агента — в одном месте."
                  )}
                </p>
              </div>
              <div className="wc-heading-actions">
                <SimulationControl
                  active={simulation}
                  date={date}
                  disabled={busy}
                  onRun={runSimulation}
                />
                <Button
                  variant="outline"
                  className="wc-export-button"
                  onClick={exportCsv}
                  disabled={!data.length || busy || downloading}
                >
                  <Download size={15} />
                  {tr(simulation ? "Экспорт" : "CSV выпуска")}
                </Button>
                <Button
                  className="wc-primary-button"
                  onClick={refresh}
                  disabled={
                    busy ||
                    (!simulation &&
                      (dashboard.loading ||
                        !health?.agent_configured ||
                        !health.time_configuration_ready))
                  }
                >
                  {busy ? (
                    <LoaderCircle size={15} className="wc-spin" />
                  ) : (
                    <RefreshCw size={15} />
                  )}
                  {busy
                    ? tr("Выполняется расчёт…")
                    : simulation
                      ? tr("Новая реализация")
                      : run && ["running", "queued"].includes(run.status)
                        ? tr("Проверить запуск")
                        : tr("Рассчитать прогноз")}
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
                      setSelectedPoint(null)
                    }}
                  >
                    <option value="all">{tr("Все турбины")}</option>
                    {turbines.map((item) => (
                      <option key={item.id} value={item.id}>
                        {tr(item.name)}
                      </option>
                    ))}
                  </select>
                  <ChevronDown size={13} />
                </label>
                {!simulation && (
                  <>
                    <label className="wc-select-label date">
                      <CalendarDays size={15} />
                      <select
                        aria-label={tr("Дата прогноза")}
                        value={date}
                        disabled={busy}
                        onChange={(e) => {
                          setDate(e.target.value)
                          setSelectedPoint(null)
                        }}
                      >
                        {dates.map((d) => (
                          <option key={d} value={d}>
                            {formatDate(d, true)} 2026
                          </option>
                        ))}
                      </select>
                      <ChevronDown size={13} />
                    </label>
                    <div
                      className="wc-segment"
                      aria-label={tr("Горизонт расчёта")}
                    >
                      {([24, 48] as const).map((hours) => (
                        <button
                          key={hours}
                          disabled={busy}
                          aria-pressed={horizon === hours}
                          onClick={() => {
                            setHorizon(hours)
                            setSelectedPoint(null)
                          }}
                        >
                          {hours} {tr("ч")}
                        </button>
                      ))}
                    </div>
                    <label className="wc-refresh-weather">
                      <input
                        type="checkbox"
                        checked={refreshWeather}
                        disabled={busy}
                        onChange={(event) =>
                          setRefreshWeather(event.target.checked)
                        }
                      />
                      {tr("Обновить архив погоды")}
                    </label>
                  </>
                )}
                <span className="wc-archive-label">
                  <History size={13} />{" "}
                  {tr(simulation ? "Режим симуляции" : "Ретроспективный режим")}
                </span>
              </div>
              {!simulation && (
                <span className="wc-issued">
                  {tr("Расчёт на")}{" "}
                  <strong>{formatTimestamp(issuedAt)}</strong>
                  <Hint>
                    {tr(
                      "Момент исторического прогноза, UTC+5. Все погодные входные данные доступны до этого времени."
                    )}
                  </Hint>
                </span>
              )}
            </div>
            {dashboard.loading && (
              <div className="wc-info-banner" role="status">
                <LoaderCircle className="wc-spin" size={18} />
                {tr("Подключение к серверу…")}
              </div>
            )}
            {error && (
              <div className="wc-info-banner wc-error-banner" role="alert">
                <Info size={20} />
                <div>
                  <strong>{tr("Не удалось выполнить действие")}</strong>
                  <p>{error}</p>
                </div>
                <Button
                  variant="outline"
                  disabled={busy}
                  onClick={() => {
                    setDownloadError(null)
                    void dashboard.reload()
                  }}
                >
                  {tr("Обновить состояние")}
                </Button>
              </div>
            )}
            {health && !health.time_configuration_ready && (
              <div className="wc-info-banner">
                <Info size={20} />
                <p>
                  {tr(
                    "Время исходных измерений не настроено. Расчёт недоступен до настройки сервера."
                  )}
                </p>
              </div>
            )}
            {health && !health.agent_configured && (
              <div className="wc-info-banner">
                <Info size={20} />
                <p>{tr("Модуль прогнозирования не подключён к серверу.")}</p>
              </div>
            )}
            {health?.research_mode && !simulation && (
              <div className="wc-info-banner">
                <Info size={20} />
                <p>
                  <strong>{tr("Исследовательский режим.")}</strong>{" "}
                  {tr(
                    "UTC+5 и начало интервала исходных CSV пока не подтверждены организаторами."
                  )}
                </p>
              </div>
            )}
            {warnings.length > 0 && !simulation && (
              <details className="wc-api-warnings">
                <summary>
                  {tr("Предупреждения о данных и расчёте")} · {warnings.length}
                </summary>
                <ul>
                  {warnings.map((warning) => (
                    <li key={warning}>{warning}</li>
                  ))}
                </ul>
              </details>
            )}
            {busy && (
              <div
                className="wc-run-progress"
                role="progressbar"
                aria-label={tr("Расчёт прогноза")}
                aria-valuemin={0}
                aria-valuemax={100}
                aria-valuenow={Math.round((run?.progress ?? 0) * 100)}
              >
                <span style={{ width: `${(run?.progress ?? 0) * 100}%` }} />
              </div>
            )}
            {!data.length && analytical && (
              <Card className="wc-card wc-api-empty">
                <TurbineArt compact />
                <h2>
                  {busy ? tr("Выполняется расчёт") : tr("Прогноз ещё не выбран")}
                </h2>
                <p>
                  {busy
                    ? tr("События и прогресс поступают от агента.")
                    : tr(
                        "Выберите дату и горизонт, затем нажмите «Рассчитать прогноз» или откройте сохранённый выпуск в истории."
                      )}
                </p>
                <Button
                  variant="outline"
                  onClick={() => navigate(busy ? "agent" : "history")}
                >
                  {busy ? tr("Открыть журнал") : tr("Открыть историю")}
                </Button>
              </Card>
            )}
            {simulation && (
              <SimulationSummary
                config={simulation}
                data={data}
                turbine={turbine}
                onRun={runSimulation}
                onReset={resetSimulation}
                onInspect={(index) => {
                  selectHour(index)
                  if (!analytical) setView("overview")
                  document
                    .getElementById("turbine-system-view")
                    ?.scrollIntoView({
                      behavior: highVisibility ? "auto" : "smooth",
                      block: "start",
                    })
                }}
              />
            )}
            {(!analytical || !data.length) && (
              <div id="turbine-system-view">{turbineScene}</div>
            )}
            {analytical && data.length > 0 && (
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
                      "Средняя нормализованная мощность в процентах. Для двух турбин используется среднее нормализованных значений."
                    )}
                  />
                  <StatCard
                    title={tr("Пиковая выработка")}
                    value={number(metrics.peak)}
                    unit="%"
                    icon={TrendingUp}
                    note={
                      peak
                        ? tr("Ожидается в {v0}", {
                            v0: simulation
                              ? `${formatDate(peak.date)} · ${peak.hour}`
                              : peak.hour,
                          })
                        : tr("Нет прогноза")
                    }
                    values={data.slice(0, 12).map((p) => p.forecast)}
                    hint={tr(
                      "Максимальная прогнозная мощность на выбранном горизонте."
                    )}
                  />
                  <StatCard
                    title={tr("Скорость ветра")}
                    value={number(metrics.wind)}
                    unit={tr("м/с")}
                    icon={Wind}
                    note={tr(
                      metrics.wind === null
                        ? "Нет в этом выпуске"
                        : simulation
                          ? "Среднее за период"
                          : "Среднее на 100 м"
                    )}
                    values={data.map((p) => p.wind)}
                    hint={tr(
                      simulation
                        ? "Средний ветер за весь период симуляции."
                        : "Средняя прогнозная скорость ветра на высоте 100 м из выпуска погоды, использованного моделью. Выпуски, сохранённые до добавления погоды в ответ, показывают «—»."
                    )}
                    positive={false}
                  />
                  {simulatedMetrics ? (
                    <StatCard
                      title={tr("Энергия за период")}
                      value={number(simulatedMetrics.energyMWh)}
                      unit={tr("МВт·ч")}
                      icon={Gauge}
                      note={tr("Условная мощность: {v0} МВт", {
                        v0: number(simulatedMetrics.capacityMW),
                      })}
                      values={data.map((p) => p.forecast)}
                      hint={tr(
                        "Сумма почасовой выработки при заданной номинальной мощности. Фактических наблюдений в симуляции нет."
                      )}
                      positive={false}
                    />
                  ) : (
                    <StatCard
                      title={tr("Ошибка прогноза")}
                      value={number(metrics.nmae)}
                      unit="%"
                      icon={Gauge}
                      note={tr("Факт февраля отсутствует")}
                      values={data
                        .filter((p) => p.actual !== null)
                        .map((p) => Math.abs(p.forecast - p.actual!))}
                      hint={tr(
                        "Ошибка выбранного прогноза не вычисляется без фактической выработки. Январские метрики относятся к другой выборке."
                      )}
                      positive={false}
                    />
                  )}
                </section>
                <div className="wc-analysis-grid" id="turbine-system-view">
                  <ForecastChart
                    key={`${date}-${turbine}-${simulation?.seed ?? "forecast"}`}
                    data={data}
                    horizon={data.length}
                    setHorizon={(next) => {
                      setHorizon(next)
                      setSceneHour((hour) => resolveHour(hour, next))
                    }}
                    busy={busy}
                    onInspect={selectHour}
                    inspectedHour={inspectedHour}
                  />
                  {turbineScene}
                </div>
                <ForecastTimeline
                  key={`${simulation?.seed ?? "forecast"}-${highVisibility}-${systemReducedMotion}`}
                  allowPlayback={Boolean(simulation)}
                  playbackDisabled={highVisibility || systemReducedMotion}
                  data={data}
                  index={inspectedHour}
                  onSelect={selectHour}
                />
                {view === "overview" && (
                  <ForecastInsights
                    data={data}
                    index={inspectedHour}
                    onSelect={inspectInsight}
                  />
                )}
                {view === "overview" && (
                  <div className="wc-overview-support">
                    {simulation ? (
                      <Card className="wc-card wc-simulation-guide">
                        <FlaskConical size={22} />
                        <h2>{tr("Модель генерации")}</h2>
                        <p>
                          {tr(
                            "Ветер, температура и влажность связаны во времени. Порывы и обледенение меняют выработку и состояние 3D-модели."
                          )}
                        </p>
                        <button
                          type="button"
                          className="wc-text-button"
                          onClick={() => navigate("sources")}
                        >
                          {tr("Условия и допущения")}
                          <ArrowRight size={15} />
                        </button>
                      </Card>
                    ) : (
                      <AgentPanel
                        run={run}
                        busy={busy}
                        step={step}
                        onOpen={() => navigate("agent")}
                        onInspect={(index) => {
                          navigate("agent")
                          inspectAgentStep(index)
                        }}
                      />
                    )}
                    <WeatherPanel
                      data={data}
                      inspectedHour={inspectedHour}
                      onInspect={inspectWeather}
                    />
                    <TurbinePanel
                      forecast={result}
                      turbines={turbines}
                      simulationData={simulationData}
                      onOpen={setDialog}
                    />
                  </div>
                )}
                {view === "forecast" && !simulation && (
                  <div className="wc-evaluation-note">
                    <ShieldCheck size={20} />
                    <div>
                      <strong>{tr("Честная ретроспективная оценка")}</strong>
                      <p>
                        {tr(
                          "Фактическая выработка февраля отсутствует. Ошибка и интервал неопределённости не рассчитаны. На графике показан прогноз обученной модели; мартовский хвост сохраняется."
                        )}
                      </p>
                    </div>
                    <span>
                      RMSE <b>{number(metrics.rmse)}%</b>
                    </span>
                  </div>
                )}
                {view === "forecast" && (
                  <HourlyTable
                    key={`${date}-${horizon}-${turbine}-${simulation?.seed ?? "forecast"}`}
                    data={data}
                    onExport={exportCsv}
                    onPoint={(point) => {
                      setSceneHour(
                        data.findIndex((p) => p.timestamp === point.timestamp)
                      )
                      setSelectedPoint(point)
                    }}
                  />
                )}
              </>
            )}
            {view === "agent" && !simulation && (
              <>
                <div className="wc-agent-page-grid">
                  <AgentPanel
                    run={run}
                    busy={busy}
                    step={step}
                    onOpen={() => navigate("history")}
                    onInspect={(index) => {
                      inspectAgentStep(index)
                      document
                        .getElementById("turbine-system-view")
                        ?.scrollIntoView({
                          behavior: highVisibility ? "auto" : "smooth",
                          block: "start",
                        })
                    }}
                    expanded
                  />
                  <Card className="wc-card wc-agent-log">
                    <div className="wc-panel-heading">
                      <div>
                        <h2>{tr("Журнал событий")}</h2>
                        <p>
                          {run
                            ? `${tr("Запуск на")} ${formatTimestamp(run.as_of)} · ${run.horizon_hours} ${tr("ч")}`
                            : tr("События выбранного запуска")}
                        </p>
                      </div>
                      <span className="wc-terminal-label">
                        {run?.agent_mode.toUpperCase() ?? tr("ОЖИДАНИЕ")}
                      </span>
                    </div>
                    <div className="wc-log-lines">
                      {run?.events.map((event) => (
                        <div key={event.id} data-level={event.level}>
                          <span>{formatTimestamp(event.timestamp)}</span>
                          {event.level === "info" ? (
                            <Check size={13} />
                          ) : (
                            <Info size={13} />
                          )}
                          <p>{event.message}</p>
                        </div>
                      ))}
                      {!run?.events.length && (
                        <p>{tr("События появятся после запуска расчёта.")}</p>
                      )}
                    </div>
                    <div className="wc-log-explainer">
                      <Info size={15} />
                      {run
                        ? `${tr("Ревизия")} ${run.revision}${run.reused_run_id ? ` · ${tr("предыдущий результат переиспользован")}` : ""}`
                        : tr("Журнал поступает с сервера.")}
                    </div>
                  </Card>
                </div>
              </>
            )}
            {(view === "sources" || view === "agent") && simulation && (
              <SimulationMethod />
            )}
            {view === "sources" && !simulation && (
              <>
                <div className="wc-info-banner">
                  <ShieldCheck size={21} />
                  <div>
                    <strong>
                      {tr("Только то, что было известно на момент прогноза")}
                    </strong>
                    <p>
                      {tr(
                        "Модель использует архивные прогнозы погоды. Для выбранного выпуска ниже показаны сохранённые метаданные источников."
                      )}
                    </p>
                  </div>
                </div>
                <SourcesPanel forecast={result} detailed />
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
                      {summary
                        ? tr("{v0} исходных записей.", {
                            v0: number(
                              summary.turbines.reduce(
                                (total, item) => total + item.rows,
                                0
                              ),
                              0
                            ),
                          })
                        : tr("Сводка ещё не загружена.")}{" "}
                      {summary?.turbines.every(
                        (item) => item.source_matches_audit
                      )
                        ? tr("Контрольные суммы совпадают с аудитом.")
                        : tr("Проверьте предупреждения о данных.")}
                    </small>
                  </Card>
                  <Card className="wc-card wc-dataset-card">
                    <MapPin size={26} />
                    <h2>{tr("Две точки наблюдения")}</h2>
                    <p>{tr("Площадки из описания кейса")}</p>
                    {turbines.map((t) => (
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
                      {tr("Последние 100 запусков · сохранены на сервере")}
                    </p>
                  </div>
                  <Button
                    variant="outline"
                    disabled={busy || dashboard.loading}
                    onClick={() => void dashboard.reload()}
                  >
                    {tr("Обновить историю")}
                  </Button>
                </div>
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>{tr("Запуск")}</TableHead>
                      <TableHead>{tr("Момент решения · UTC+5")}</TableHead>
                      <TableHead>{tr("Объект")}</TableHead>
                      <TableHead>{tr("Горизонт")}</TableHead>
                      <TableHead>{tr("Статус")}</TableHead>
                      <TableHead />
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {!runs.length && (
                      <TableRow>
                        <TableCell colSpan={6}>
                          <p className="wc-empty">
                            {tr("Сохранённых запусков пока нет.")}
                          </p>
                        </TableCell>
                      </TableRow>
                    )}
                    {runs.map((run) => (
                      <TableRow key={run.run_id}>
                        <TableCell>
                          <span className="wc-run-id">
                            <FileClock size={15} />
                            <span title={run.run_id}>{run.run_id.slice(0, 16)}…</span>
                          </span>
                        </TableCell>
                        <TableCell>{formatTimestamp(run.as_of)}</TableCell>
                        <TableCell>
                          {run.turbine_ids.length === 2
                            ? tr("Все турбины")
                            : run.turbine_ids[0] === 1
                              ? tr("Турбина 01")
                              : tr("Турбина 02")}
                        </TableCell>
                        <TableCell>
                          {run.horizon_hours}{" "}
                          {run.horizon_hours === 24 ? tr("часа") : tr("часов")}
                        </TableCell>
                        <TableCell>
                          <span className="wc-status">
                            <i />
                            {tr(statusLabel[run.status])}
                          </span>
                        </TableCell>
                        <TableCell>
                          <button
                            className="wc-text-button"
                            onClick={() => openRun(run)}
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
                {tr(
                  simulation
                    ? "Синтетическая симуляция · не прогноз погоды"
                    : "Прогноз модели · Тестовый период: февраль 2026"
                )}
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
        {!mobileMenu && (
          <AssistantLauncher open={dialog === "help"} onOpen={() => setDialog("help")} />
        )}
        <PlatformHelper
          open={dialog === "help"}
          onOpenChange={(open) => setDialog(open ? "help" : null)}
          context={{ view, date: simulation?.startDate ?? date, horizon_hours: horizon,
            mode: simulation ? "simulation" : "forecast", locale,
            simulation_hours: simulation ? data.length : null,
            turbine_ids: turbine === "all" ? [1, 2] : turbine === "t1" ? [1] : [2] }}
          runId={helperRun?.run_id ?? null}
          downloadableRunId={!simulation && result && helperRun?.status === "completed" ? result.run_id : null}
          downloading={downloading}
          onNavigate={navigate}
          onDownload={exportCsv}
        />
        <Dialog
          open={dialog !== null && dialog !== "help"}
          onOpenChange={(open) => {
            if (!open) setDialog(null)
          }}
        >
          <DialogContent className="wc-dialog" closeLabel={tr("Закрыть")}>
            <DialogHeader>
              <DialogTitle>
                {dialog === "notifications"
                  ? tr("Уведомления")
                  : tr(selectedTurbine?.name ?? "Ветровая станция")}
              </DialogTitle>
              <DialogDescription>
                {dialog === "notifications"
                  ? tr("Состояние сервера и предупреждения выбранного расчёта.")
                  : tr("Карточка объекта из каталога сервера")}
              </DialogDescription>
            </DialogHeader>
            {dialog === "notifications" ? (
              <div className="wc-notifications">
                <div>
                  <CheckCheck size={20} />
                  <span>
                    <strong>
                      {health ? tr("Сервер доступен") : tr("Сервер недоступен")}
                    </strong>
                    <p>
                      {tr("Турбин в каталоге: {v0}.", { v0: turbines.length })}{" "}
                      {health?.research_mode
                        ? tr("Настройки времени исследовательские.")
                        : ""}
                    </p>
                  </span>
                </div>
                <div>
                  <History size={20} />
                  <span>
                    <strong>
                      {tr("Запусков в истории:")} {runs.length}
                    </strong>
                    <p>
                      {tr("Последний:")}{" "}
                      {runs[0]?.run_id ?? tr("запусков ещё нет")}
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
                {selectedPoint?.date.slice(0, 4)} · UTC+5 ·{" "}
                {tr(
                  selectedPoint?.simulation
                    ? "синтетические данные"
                    : "прогноз модели"
                )}
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
                    {selectedPoint.lower == null || selectedPoint.upper == null
                      ? tr("Не рассчитан")
                      : `${number(selectedPoint.lower)}–${number(selectedPoint.upper)}%`}
                  </strong>
                </div>
                <div>
                  <span>{tr("Фактическое значение")}</span>
                  <strong>
                    {selectedPoint.actual === null
                      ? tr(
                          selectedPoint.simulation
                            ? "Нет наблюдений: симуляция"
                            : "Нет данных за тестовый период"
                        )
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
                {selectedWeather.map((source) => (
                  <div
                    className="wc-point-source"
                    key={`${source.turbine_id}:${source.source_id}`}
                  >
                    <span>
                      {tr("Турбина")} {source.turbine_id} · {source.provider} ·{" "}
                      {source.model}
                    </span>
                    <strong>
                      {source.available_at
                        ? `${tr("Доступен:")} ${formatTimestamp(source.available_at)}`
                        : source.available_at_estimate
                          ? `${tr("Оценка доступности:")} ${formatTimestamp(source.available_at_estimate)} · offset ${source.forecast_offset_days} ${tr("сут.")}`
                          : tr("Доступность не указана")}
                    </strong>
                  </div>
                ))}
                <SimulationHour point={selectedPoint} />
                <p>
                  {tr(
                    selectedPoint.simulation
                      ? "Диапазон и факт в симуляции не рассчитываются: это синтетический сценарий."
                      : "Отсутствующие фактические значения и погодные показатели не заменяются нулями. Мощность — прогноз для выбранного часа."
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
