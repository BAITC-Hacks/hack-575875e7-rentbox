"use client"

import { useI18n } from "@/components/locale-provider"

import Image from "next/image"
import { useEffect, useRef, useState, useSyncExternalStore } from "react"
import { LockKeyhole, Pause, Play } from "lucide-react"
import {
  SCENE_COPY,
  type SceneFocus,
  type SceneMode,
} from "@/lib/turbine-scene"
import { useAppearance } from "@/components/appearance-provider"
import type { TurbineSceneSettings } from "@/lib/turbine-renderer"

const motionQuery = "(prefers-reduced-motion: reduce)"
function subscribeMotion(callback: () => void) {
  const media = window.matchMedia(motionQuery)
  media.addEventListener("change", callback)
  return () => media.removeEventListener("change", callback)
}

export function TurbineStage({
  mode,
  focus,
  wind,
  power,
  temperature,
  onFocus,
  disabled = false,
  operationalStop = false,
}: {
  mode: SceneMode
  focus: SceneFocus
  wind: number
  power: number
  temperature: number
  onFocus: (focus: SceneFocus) => void
  operationalStop?: boolean
  disabled?: boolean
}) {
  const { tr, number } = useI18n()

  const hostRef = useRef<HTMLDivElement>(null)
  const [status, setStatus] = useState<"loading" | "ready" | "fallback">(
    "loading"
  )
  const [motionRequested, setMotionRequested] = useState<boolean | null>(null)
  const { highVisibility } = useAppearance()
  const systemReducedMotion = useSyncExternalStore(
    subscribeMotion,
    () => window.matchMedia(motionQuery).matches,
    () => true
  )
  const reducedMotion = systemReducedMotion || highVisibility
  const playing = !highVisibility && (motionRequested ?? !systemReducedMotion)
  const settingsRef = useRef<TurbineSceneSettings>({
    mode,
    focus,
    wind,
    power,
    temperature,
    operationalStop,
    playing: false,
    reducedMotion: true,
  })
  useEffect(() => {
    settingsRef.current = {
      mode,
      focus,
      wind,
      power,
      temperature,
      operationalStop,
      playing,
      reducedMotion,
    }
  }, [
    mode,
    focus,
    wind,
    power,
    temperature,
    playing,
    reducedMotion,
    operationalStop,
  ])
  useEffect(() => {
    const host = hostRef.current
    if (!host) return
    const aborter = new AbortController()
    let cleanup: (() => void) | undefined
    import("@/lib/turbine-renderer")
      .then(async ({ mountTurbineScene }) => {
        if (aborter.signal.aborted) return
        cleanup = await mountTurbineScene(
          host,
          () => settingsRef.current,
          aborter.signal,
          () => setStatus("fallback")
        )
        if (!aborter.signal.aborted) setStatus("ready")
      })
      .catch(() => {
        if (!aborter.signal.aborted) setStatus("fallback")
      })
    return () => {
      aborter.abort()
      cleanup?.()
    }
  }, [])
  const cutaway =
    mode === "cutaway" || (mode === "sensors" && focus === "power")
  const callouts: { id: SceneFocus; title: string; value: string }[] = cutaway
    ? [
        {
          id: "rotor",
          title: tr("Главный вал"),
          value: tr("Передача вращения"),
        },
        {
          id: "gearbox",
          title: tr("Редуктор"),
          value: tr("Передаточный узел"),
        },
        {
          id: "generator",
          title: tr("Генератор"),
          value: tr("{v0}% · прогноз", { v0: number(power) }),
        },
      ]
    : [
        {
          id: "wind",
          title: tr("Анемометр"),
          value: tr("{v0} м/с", { v0: number(wind) }),
        },
        {
          id: "temperature",
          title: tr("Воздух"),
          value: `${number(temperature)} °C`,
        },
        {
          id: "power",
          title: tr("Выработка"),
          value: tr("{v0}% · прогноз", { v0: number(power) }),
        },
      ]
  return (
    <div
      className="wc-turbine-stage"
      data-scene-status={status}
      data-scene-mode={mode}
    >
      <div className="wc-turbine-halo" aria-hidden="true" />
      <div
        className={`wc-turbine-poster ${status === "ready" ? "loaded" : ""}`}
        aria-hidden={status === "ready"}
      >
        <Image
          src="/models/windcast-turbine.png"
          alt={tr("Общий вид ветряной турбины")}
          fill
          sizes="(max-width: 760px) 100vw, 650px"
          loading="eager"
          unoptimized
        />
      </div>
      <div
        className="wc-turbine-canvas"
        ref={hostRef}
        role="img"
        aria-hidden={status !== "ready"}
        aria-label={tr(
          "Турбина: {v0}. Ракурс автоматически связан с разделом. {v1}",
          {
            v0: tr(SCENE_COPY[mode].label),
            v1:
              mode === "icing"
                ? tr(
                    "Голубой лёд — демонстрационный сценарий, не показание датчика."
                  )
                : "",
          }
        )}
      />
      <div className="wc-turbine-scene-label">
        <span />
        {status === "loading"
          ? tr("Загрузка модели…")
          : status === "fallback"
            ? tr("3D недоступно · общий вид")
            : mode === "icing"
              ? tr("СЦЕНАРИЙ · НЕ ДИАГНОЗ")
              : mode === "cutaway"
                ? tr("РАЗРЕЗ ГОНДОЛЫ")
                : mode === "history"
                  ? tr("АРХИВНЫЙ СНИМОК")
                  : tr("СВЯЗАНО С СИСТЕМОЙ")}
      </div>
      {status === "ready" && mode !== "icing" && (
        <div
          className="wc-scene-callouts"
          aria-label={tr("Узлы и показатели на модели")}
          data-cutaway={cutaway}
        >
          <svg className="wc-callout-lines" aria-hidden="true">
            {callouts.map((item) => (
              <g key={item.id}>
                <line data-anchor-line={item.id} />
                <circle data-anchor-dot={item.id} r="3" />
              </g>
            ))}
          </svg>
          {callouts.map((item, index) => (
            <button
              type="button"
              key={item.id}
              className={`wc-scene-callout callout-${index}`}
              data-scene-anchor={item.id}
              aria-pressed={
                focus === item.id ||
                (focus === "power" && item.id === "generator")
              }
              disabled={disabled}
              onClick={() => onFocus(item.id)}
            >
              <span>{item.title}</span>
              <strong>{item.value}</strong>
            </button>
          ))}
        </div>
      )}
      {status === "ready" && (
        <div className="wc-scene-caption">
          <span>
            <LockKeyhole size={12} />
            {mode === "icing"
              ? tr("Лёд на профиле лопасти · иллюстрация")
              : mode === "cutaway"
                ? tr("Вал → редуктор → генератор")
                : mode === "sensors"
                  ? tr("Условные точки измерений")
                  : tr("Ракурс выбирает система")}
          </span>
          {mode !== "icing" && mode !== "history" && (
            <button
              type="button"
              aria-label={
                highVisibility
                  ? tr("Анимация отключена в версии для слабовидящих")
                  : playing
                    ? tr("Приостановить анимацию")
                    : tr("Включить анимацию")
              }
              disabled={highVisibility}
              aria-pressed={playing}
              onClick={() => setMotionRequested(!playing)}
            >
              {playing ? <Pause size={13} /> : <Play size={13} />}
            </button>
          )}
        </div>
      )}
    </div>
  )
}
