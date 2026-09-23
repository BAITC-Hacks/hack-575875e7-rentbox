export type DashboardView =
  "overview" | "forecast" | "agent" | "sources" | "history"
export type SceneMode = "flow" | "icing" | "cutaway" | "sensors" | "history"
export type SceneFocus =
  "rotor" | "gearbox" | "generator" | "wind" | "temperature" | "power"

const stepModes: SceneMode[] = [
  "sensors",
  "sensors",
  "cutaway",
  "flow",
  "icing",
  "flow",
]
export function resolveSceneMode(
  view: DashboardView,
  override: SceneMode | null,
  busy: boolean,
  step: number
): SceneMode {
  if (busy) return stepModes[Math.max(0, Math.min(5, step))]!
  if (override) return override
  return {
    overview: "flow",
    forecast: "flow",
    agent: "cutaway",
    sources: "sensors",
    history: "history",
  }[view] as SceneMode
}

export function resolveHour(index: number, length: number) {
  return Math.max(0, Math.min(Math.trunc(index), Math.max(0, length - 1)))
}

export const SCENE_COPY: Record<
  SceneMode,
  { label: string; title: string; subtitle: string; detail: string }
> = {
  flow: {
    label: "Выработка",
    title: "От ветра",
    subtitle: "к энергии.",
    detail:
      "Поток проходит через ротор. Выберите час — скорость движения и показатели подстроятся под прогноз.",
  },
  icing: {
    label: "Обледенение",
    title: "Холод меняет",
    subtitle: "профиль лопасти.",
    detail:
      "Учебный сценарий: голубой слой показывает лёд на лопастях. Температура взята из выбранного часа; наличие льда не измерено.",
  },
  cutaway: {
    label: "В разрезе",
    title: "Энергия",
    subtitle: "изнутри.",
    detail:
      "Открытый разрез гондолы: вал передаёт вращение через редуктор к генератору. Выберите узел, чтобы рассмотреть его.",
  },
  sensors: {
    label: "Источники",
    title: "Каждый прогноз",
    subtitle: "начинается с данных.",
    detail:
      "Выберите входной показатель — модель покажет связанную с ним часть турбины. Точки измерений показаны условно.",
  },
  history: {
    label: "Снимок",
    title: "Состояние",
    subtitle: "на момент расчёта.",
    detail:
      "Остановленная модель помогает изучить выбранный прогноз. Откройте запуск ниже — восстановятся дата, турбина и горизонт.",
  },
}

export function illustrativeRotorSpeed(wind: number, mode: SceneMode) {
  // MOCK: animation only. Neither measured RPM nor an icing loss estimate.
  if (mode === "history" || mode === "icing" || wind <= 0) return 0
  return Math.min(wind * 0.075, 1.4) * (mode === "cutaway" ? 0.35 : 1)
}
