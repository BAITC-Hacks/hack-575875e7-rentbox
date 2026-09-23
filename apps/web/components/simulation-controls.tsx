"use client"

import { useState } from "react"
import {
  FlaskConical,
  Play,
  RotateCcw,
  Wind,
  Snowflake,
  CloudSun,
  Waves,
  CloudLightning,
} from "lucide-react"
import { Button } from "@workspace/ui/components/button"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@workspace/ui/components/dialog"
import { useI18n } from "@/components/locale-provider"
import type { ForecastPoint, TurbineId } from "@/lib/forecast-data"
import {
  SCENARIOS,
  OPERATING_LABELS,
  simulationError,
  simulationHours,
  simulationSummary,
  type SimulationConfig,
} from "@/lib/wind-simulation"

export function newSimulationSeed() {
  return crypto.getRandomValues(new Uint32Array(1))[0]!
}
const icons = {
  mixed: CloudSun,
  steady: Wind,
  calm: Waves,
  storm: CloudLightning,
  icing: Snowflake,
}
export function SimulationControl({
  active,
  date,
  disabled,
  onRun,
}: {
  active: SimulationConfig | null
  date: string
  disabled: boolean
  onRun: (config: SimulationConfig) => void
}) {
  const { tr, number } = useI18n()
  const [open, setOpen] = useState(false)
  const [draft, setDraft] = useState<SimulationConfig>({
    startDate: date,
    endDate: date,
    scenario: "mixed",
    capacityMW: 5,
    seed: 0,
  })
  const [error, setError] = useState<string | null>(null)
  const hours = simulationHours(draft.startDate, draft.endDate)
  return (
    <>
      <Button
        variant="outline"
        className="wc-simulation-trigger"
        disabled={disabled}
        onClick={() => {
          setDraft(
            active ?? {
              startDate: date,
              endDate: date,
              scenario: "mixed",
              capacityMW: 5,
              seed: 0,
            }
          )
          setError(null)
          setOpen(true)
        }}
      >
        <FlaskConical size={16} />
        {tr(active ? "Настроить симуляцию" : "Симуляция")}
      </Button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent
          className="wc-dialog wc-simulation-dialog"
          closeLabel={tr("Закрыть")}
        >
          <DialogHeader>
            <DialogTitle>{tr("Симуляция на период")}</DialogTitle>
            <DialogDescription>
              {tr(
                "Задайте погоду и даты. Сравните выработку и поведение турбин в разных условиях."
              )}
            </DialogDescription>
          </DialogHeader>
          <form
            onSubmit={(event) => {
              event.preventDefault()
              const config = { ...draft, seed: newSimulationSeed() }
              const problem = simulationError(config)
              setError(problem)
              if (!problem) {
                onRun(config)
                setOpen(false)
              }
            }}
          >
            <fieldset className="wc-simulation-scenarios">
              <legend>{tr("Погодный сценарий")}</legend>
              {SCENARIOS.map((s) => {
                const Icon = icons[s.id]
                return (
                  <label
                    key={s.id}
                    className={draft.scenario === s.id ? "selected" : ""}
                  >
                    <input
                      type="radio"
                      name="scenario"
                      value={s.id}
                      checked={draft.scenario === s.id}
                      onChange={() => setDraft({ ...draft, scenario: s.id })}
                    />
                    <Icon size={20} />
                    <span>
                      <strong>{tr(s.label)}</strong>
                      <small>{tr(s.detail)}</small>
                    </span>
                  </label>
                )
              })}
            </fieldset>
            <div className="wc-simulation-fields">
              <label>
                {tr("Начало периода")}
                <input
                  type="date"
                  required
                  min="2020-01-01"
                  max="2100-12-31"
                  value={draft.startDate}
                  onChange={(e) =>
                    setDraft({ ...draft, startDate: e.target.value })
                  }
                />
              </label>
              <label>
                {tr("Конец периода")}
                <input
                  type="date"
                  required
                  min="2020-01-01"
                  max="2100-12-31"
                  value={draft.endDate}
                  onChange={(e) =>
                    setDraft({ ...draft, endDate: e.target.value })
                  }
                />
              </label>
              <label>
                {tr("Мощность одной турбины, МВт")}
                <input
                  type="number"
                  required
                  min="0.1"
                  max="20"
                  step="0.1"
                  value={Number.isNaN(draft.capacityMW) ? "" : draft.capacityMW}
                  onChange={(e) =>
                    setDraft({ ...draft, capacityMW: e.target.valueAsNumber })
                  }
                />
              </label>
            </div>
            <p className="wc-simulation-footnote">
              {tr("Обе даты включены · шаг 1 час · UTC+5 · максимум 31 день.")}
              {Number.isFinite(hours) && hours >= 24 && hours <= 744 && (
                <strong>
                  {" "}
                  {tr("Будет рассчитано: {v0} ч", { v0: hours })}
                </strong>
              )}
            </p>
            <div className="wc-simulation-assumption">
              <FlaskConical size={19} />
              <p>
                {tr(
                  "Это синтетический эксперимент, а не прогноз погоды. Мощность — ваше допущение; по умолчанию 2 турбины по {v0} МВт.",
                  { v0: number(draft.capacityMW || 5) }
                )}
              </p>
            </div>
            {error && (
              <p role="alert" className="wc-simulation-error">
                {tr(error)}
              </p>
            )}
            <div className="wc-simulation-form-actions">
              <Button
                type="button"
                variant="outline"
                onClick={() => setOpen(false)}
              >
                {tr("Отмена")}
              </Button>
              <Button
                type="submit"
                className="wc-primary-button"
                disabled={disabled}
              >
                <Play size={15} />
                {tr("Сгенерировать период")}
              </Button>
            </div>
          </form>
        </DialogContent>
      </Dialog>
    </>
  )
}
export function SimulationSummary({
  config,
  data,
  turbine,
  onRun,
  onReset,
  onInspect,
}: {
  config: SimulationConfig
  data: ForecastPoint[]
  turbine: TurbineId
  onRun: (config: SimulationConfig) => void
  onReset: () => void
  onInspect: (index: number) => void
}) {
  const { tr, number, formatDate } = useI18n()
  const result = simulationSummary(data, config, turbine)
  const scenario = SCENARIOS.find((s) => s.id === config.scenario)!
  const gustIndex = data.reduce(
    (best, p, i) =>
      p.simulation!.gust > data[best]!.simulation!.gust ? i : best,
    0
  )
  const iceIndex = data.reduce(
    (best, p, i) =>
      p.simulation!.icingLoss > data[best]!.simulation!.icingLoss ? i : best,
    0
  )
  const stopIndex = data.findIndex((p) => p.simulation!.stoppedTurbines > 0)
  return (
    <section
      className="wc-simulation-summary"
      aria-label={tr("Результат симуляции")}
    >
      <div className="wc-simulation-summary-heading">
        <div>
          <span className="wc-simulation-kicker">
            <FlaskConical size={15} />
            {tr("СИМУЛЯЦИЯ")}
          </span>
          <h2>
            {tr(scenario.label)}{" "}
            <span>
              {formatDate(config.startDate)} — {formatDate(config.endDate)} ·{" "}
              {config.startDate.slice(0, 4)}
              {config.startDate.slice(0, 4) !== config.endDate.slice(0, 4)
                ? ` / ${config.endDate.slice(0, 4)}`
                : ""}
            </span>
          </h2>
          <p>
            {tr("{v0} ч · условная мощность {v1} МВт · синтетические данные", {
              v0: data.length,
              v1: number(result.capacityMW),
            })}
          </p>
        </div>
        <div className="wc-simulation-summary-actions">
          <button
            type="button"
            onClick={() => onRun({ ...config, seed: newSimulationSeed() })}
          >
            <RotateCcw size={14} />
            {tr("Новая реализация")}
          </button>
          <button type="button" onClick={onReset}>
            {tr("Вернуться к прогнозу")}
          </button>
        </div>
      </div>
      <div className="wc-simulation-results">
        <div>
          <span>{tr("Энергия за период")}</span>
          <strong>
            {number(result.energyMWh)} <small>{tr("МВт·ч")}</small>
          </strong>
        </div>
        <button type="button" onClick={() => onInspect(gustIndex)}>
          <span>{tr("Пик порывов")}</span>
          <strong>
            {number(result.maxGust)} <small>{tr("м/с")}</small>
          </strong>
          <small>{tr("Показать на графике")}</small>
        </button>
        <button
          type="button"
          disabled={stopIndex < 0}
          onClick={() => onInspect(stopIndex)}
        >
          <span>{tr("Часы с остановками")}</span>
          <strong>
            {result.affectedHours} <small>{tr("ч")}</small>
          </strong>
          <small>{tr("Хотя бы одна турбина")}</small>
        </button>
        {config.scenario === "icing" && (
          <button type="button" onClick={() => onInspect(iceIndex)}>
            <span>{tr("Макс. потери от льда")}</span>
            <strong>
              {number(result.maxIceLoss)} <small>%</small>
            </strong>
            <small>{tr("Условие сценария")}</small>
          </button>
        )}
      </div>
    </section>
  )
}
export function SimulationHour({ point }: { point: ForecastPoint }) {
  const { tr, number } = useI18n()
  if (!point.simulation) return null
  const s = point.simulation
  return (
    <div className="wc-simulation-hour" data-operating-state={s.state}>
      <strong>
        {tr(
          s.stoppedTurbines > 0 && point.forecast > 0
            ? "Частичная остановка"
            : OPERATING_LABELS[s.state]
        )}
      </strong>
      <span>
        {tr("Порывы: {v0} м/с · влажность: {v1}%", {
          v0: number(s.gust),
          v1: number(s.humidity, 0),
        })}
      </span>
      {s.icingLoss > 0 && (
        <span>
          {tr("Потери от льда в сценарии: {v0}%", { v0: number(s.icingLoss) })}
        </span>
      )}
    </div>
  )
}
export function SimulationMethod() {
  const { tr } = useI18n()
  return (
    <section className="wc-simulation-method">
      <h2>{tr("Как устроена симуляция")}</h2>
      <p>
        {tr(
          "Ветер, порывы, температура и влажность генерируются с плавными изменениями. Обе турбины используют общую погоду с небольшими локальными различиями."
        )}
      </p>
      <p>
        {tr(
          "Условная кривая мощности: старт при 3 м/с, номинальная мощность при 11,4 м/с, остановка при 25 м/с или порывах от 32 м/с. Возврат — после двух безопасных часов: ветер ниже 20 м/с и порывы ниже 27 м/с."
        )}
      </p>
      <p>
        {tr(
          "В сценарии обледенения задана высокая влажность и мороз. Условная потеря мощности накапливается до 48%. Это допущение генератора, а не измерение льда."
        )}
      </p>
      <p>
        {tr(
          "Фактические наблюдения, погодные API и ML-модель не используются. Энергия рассчитывается по заданной мощности; ошибки прогноза для симуляции не оцениваются."
        )}
      </p>
      <a
        href="https://www.nrel.gov/docs/fy09osti/38060.pdf"
        target="_blank"
        rel="noreferrer"
      >
        {tr("Ориентир для порогов: эталонная турбина NREL 5 МВт")}
      </a>
    </section>
  )
}
