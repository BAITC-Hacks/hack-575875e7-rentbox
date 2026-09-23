"use client"

import Image from "next/image"
import { useEffect, useRef, useState, useSyncExternalStore } from "react"
import { LockKeyhole, Pause, Play } from "lucide-react"
import {
  SCENE_COPY,
  type SceneFocus,
  type SceneMode,
} from "@/lib/turbine-scene"
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
}: {
  mode: SceneMode
  focus: SceneFocus
  wind: number
  power: number
  temperature: number
}) {
  const hostRef = useRef<HTMLDivElement>(null)
  const [status, setStatus] = useState<"loading" | "ready" | "fallback">(
    "loading"
  )
  const [motionRequested, setMotionRequested] = useState<boolean | null>(null)
  const reducedMotion = useSyncExternalStore(
    subscribeMotion,
    () => window.matchMedia(motionQuery).matches,
    () => true
  )
  const playing = motionRequested ?? !reducedMotion
  const settingsRef = useRef<TurbineSceneSettings>({
    mode,
    focus,
    wind,
    power,
    temperature,
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
      playing,
      reducedMotion,
    }
  }, [mode, focus, wind, power, temperature, playing, reducedMotion])
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
          alt="Общий вид ветряной турбины"
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
        aria-label={`Турбина: ${SCENE_COPY[mode].label}. Ракурс автоматически связан с разделом. ${mode === "icing" ? "Голубой лёд — демонстрационный сценарий, не показание датчика." : ""}`}
      />
      <div className="wc-turbine-scene-label">
        <span />
        {status === "loading"
          ? "Загрузка модели…"
          : status === "fallback"
            ? "3D недоступно · общий вид"
            : mode === "icing"
              ? "СЦЕНАРИЙ · НЕ ДИАГНОЗ"
              : mode === "cutaway"
                ? "РАЗРЕЗ ГОНДОЛЫ"
                : mode === "history"
                  ? "АРХИВНЫЙ СНИМОК"
                  : "СВЯЗАНО С СИСТЕМОЙ"}
      </div>
      {status === "ready" && (
        <div className="wc-scene-caption">
          <span>
            <LockKeyhole size={12} />
            {mode === "icing"
              ? "Лёд на профиле лопасти · иллюстрация"
              : mode === "cutaway"
                ? "Вал → редуктор → генератор"
                : mode === "sensors"
                  ? "Условные точки измерений"
                  : "Ракурс выбирает система"}
          </span>
          {mode !== "icing" && mode !== "history" && (
            <button
              type="button"
              aria-label={
                playing ? "Приостановить анимацию" : "Включить анимацию"
              }
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
