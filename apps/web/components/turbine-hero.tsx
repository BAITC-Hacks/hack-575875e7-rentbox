"use client"

import { useI18n } from "@/components/locale-provider"

import { Box, Snowflake, Thermometer, Wind, Zap } from "lucide-react"
import {
  AGENT_STEPS,
  type ForecastPoint,
  type TurbineId,
} from "@/lib/forecast-data"
import {
  SCENE_COPY,
  type DashboardView,
  type SceneFocus,
  type SceneMode,
} from "@/lib/turbine-scene"
import { SimulationHour } from "@/components/simulation-controls"
import { TurbineStage } from "@/components/turbine-stage"

type Props = {
  compact?: boolean
  view: DashboardView
  turbine: TurbineId
  mode: SceneMode
  focus: SceneFocus
  point: ForecastPoint
  hourIndex: number
  data: ForecastPoint[]
  busy: boolean
  step: number
  onMode: (mode: SceneMode) => void
  onFocus: (focus: SceneFocus) => void
  onHour: (index: number) => void
  onStep: (index: number) => void
}
const viewNames: Record<DashboardView, string> = {
  overview: "Обзор станции",
  forecast: "Почасовой прогноз",
  agent: "Цикл AI-агента",
  sources: "Происхождение данных",
  history: "История расчётов",
}
const partNames: { id: SceneFocus; label: string; description: string }[] = [
  {
    id: "rotor",
    label: "Вал",
    description: "Передаёт механическое вращение от ротора.",
  },
  {
    id: "gearbox",
    label: "Редуктор",
    description:
      "Связывает низкооборотный вал и генератор в этой условной конструкции.",
  },
  {
    id: "generator",
    label: "Генератор",
    description: "Преобразует механическую энергию в электрическую.",
  },
]
const sensorNames: { id: SceneFocus; label: string; description: string }[] = [
  {
    id: "wind",
    label: "Ветер",
    description:
      "Скорость ветра — вход прогнозной модели; анемометр показан на гондоле.",
  },
  {
    id: "temperature",
    label: "Температура",
    description:
      "Температура воздуха — погодный вход. Она не подтверждает наличие льда.",
  },
  {
    id: "power",
    label: "Мощность",
    description:
      "Нормализованная активная мощность на стороне линии — целевая величина кейса.",
  },
]
export function TurbineHero({
  compact = false,
  view,
  turbine,
  mode,
  focus,
  point,
  hourIndex,
  data,
  busy,
  step,
  onMode,
  onFocus,
  onHour,
  onStep,
}: Props) {
  const { tr, number, formatDate } = useI18n()

  const copy = SCENE_COPY[mode]
  const details = mode === "cutaway" ? partNames : sensorNames
  const modes: SceneMode[] =
    view === "history"
      ? ["history", "flow", "icing", "cutaway"]
      : ["flow", "icing", "cutaway", "sensors"]
  return (
    <section
      className={`wc-turbine-hero wc-system-twin ${compact ? "is-compact" : ""} ${mode === "icing" ? "is-icing" : ""}`}
      aria-label={tr("Модель турбины, связанная с системой")}
    >
      <div className="wc-twin-toolbar">
        <span className="wc-turbine-eyebrow">
          <Box size={15} />{" "}
          {compact ? tr("Состояние турбины") : tr(viewNames[view])} <b>3D</b>
        </span>
        <div className="wc-twin-modes" aria-label={tr("Сценарий визуализации")}>
          {modes.map((m) => (
            <button
              key={m}
              type="button"
              aria-pressed={mode === m}
              disabled={busy}
              onClick={() => onMode(m)}
            >
              {m === "icing" && <Snowflake size={12} />}{" "}
              {tr(SCENE_COPY[m].label)}
            </button>
          ))}
        </div>
      </div>
      <div className="wc-turbine-hero-copy">
        <span className="wc-twin-object">
          {turbine === "all"
            ? tr("ВЭС · ДВЕ ТУРБИНЫ")
            : turbine === "t1"
              ? tr("WTG–001 · СЕВЕРНЫЙ УЧАСТОК")
              : tr("WTG–002 · ЮЖНЫЙ УЧАСТОК")}{" "}
          <i /> {point.hour} · UTC+5
        </span>
        <h2>
          {tr(copy.title)}
          <br />
          <span>{tr(copy.subtitle)}</span>
        </h2>
        <p>
          {tr(
            point.simulation && mode === "icing"
              ? "Учебный сценарий обледенения: слой на лопастях показывает заданные генератором условия. Потери рассчитаны условно."
              : copy.detail
          )}
        </p>
        <div className="wc-turbine-live-metrics">
          <div>
            <span>
              <Wind size={13} />
              {tr("Ветер")}
            </span>
            <strong>
              {number(point.wind)}
              <small>{tr("м/с")}</small>
            </strong>
          </div>
          <div>
            <span>
              <Zap size={13} />
              {tr("Мощность")}
            </span>
            <strong>
              {number(point.forecast)}
              <small>%</small>
            </strong>
          </div>
          <div>
            <span>
              <Thermometer size={13} />
              {tr("Воздух")}
            </span>
            <strong>
              {number(point.temperature)}
              <small>°C</small>
            </strong>
          </div>
        </div>
        <SimulationHour point={point} />
        {(mode === "cutaway" || mode === "sensors") && (
          <div className="wc-twin-details">
            <div
              aria-label={
                mode === "cutaway"
                  ? tr("Узел турбины")
                  : tr("Показатель источника")
              }
            >
              {details.map((p, i) => (
                <button
                  type="button"
                  key={p.id}
                  aria-pressed={focus === p.id}
                  onClick={() => onFocus(p.id)}
                >
                  <small>0{i + 1}</small>
                  {tr(p.label)}
                </button>
              ))}
            </div>
            <p>
              {tr(
                details.find((p) => p.id === focus)?.description ??
                  details[0]!.description
              )}
            </p>
          </div>
        )}
        {mode === "icing" && (
          <div className="wc-icing-explainer">
            <Snowflake size={18} />
            <div>
              <strong>{tr("Иллюстрация обледенения")}</strong>
              <span>
                {tr(
                  point.simulation
                    ? "Влажность и потери заданы генератором. Реальных измерений льда нет."
                    : "Нет данных о влажности и датчика льда. Потери мощности и вероятность не рассчитаны."
                )}
              </span>
            </div>
          </div>
        )}
        <span className="wc-turbine-disclaimer">
          {tr("Демо-данные · условная конструкция турбины")}
        </span>
      </div>
      <TurbineStage
        mode={mode}
        focus={focus}
        wind={point.wind}
        power={point.forecast}
        temperature={point.temperature}
        operationalStop={Boolean(point.simulation) && point.forecast === 0}
        disabled={busy}
        onFocus={(next) => {
          if (["rotor", "gearbox", "generator"].includes(next))
            onMode("cutaway")
          else onMode("sensors")
          onFocus(next)
        }}
      />
      {!compact && (
        <div className="wc-twin-timeline">
          <div>
            <span>{tr("ВЫБРАННЫЙ ЧАС")}</span>
            <strong>
              {formatDate(point.date)} · {point.hour}
            </strong>
          </div>
          <div className="wc-twin-scrubber">
            <input
              type="range"
              aria-label={tr("Час 3D-модели")}
              min={0}
              max={data.length - 1}
              value={hourIndex}
              onChange={(e) => onHour(Number(e.target.value))}
              aria-valuetext={`${formatDate(point.date)}, ${point.hour}`}
            />
            <div>
              <span>{data[0]!.hour}</span>
              <span>
                {tr("Горизонт")} {data.length} {tr("ч · UTC+5")}
              </span>
              <span>{data.at(-1)!.hour}</span>
            </div>
          </div>
          <span className="wc-twin-sync" role="status">
            {busy
              ? tr("Шаг {v0}: {v1}", {
                  v0: step + 1,
                  v1: tr(AGENT_STEPS[step]!.title),
                })
              : `${tr(copy.label)} · ${tr(viewNames[view])}`}
          </span>
        </div>
      )}
      {view === "agent" && (
        <div
          className="wc-twin-agent-steps"
          aria-label={tr("Этап визуализации агента")}
        >
          {AGENT_STEPS.map((s, i) => (
            <button
              type="button"
              key={s.title}
              disabled={busy}
              aria-pressed={step === i}
              onClick={() => onStep(i)}
            >
              <span>{String(i + 1).padStart(2, "0")}</span>
              {tr(s.title)}
            </button>
          ))}
        </div>
      )}
    </section>
  )
}
