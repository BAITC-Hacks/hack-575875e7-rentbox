"use client"

import {
  createContext,
  useContext,
  useEffect,
  useSyncExternalStore,
  type ReactNode,
} from "react"
import { Eye, Moon, Sun } from "lucide-react"
import { useTheme } from "next-themes"
import { useI18n } from "@/components/locale-provider"

const storageKey = "windcast.vision"
let vision = false
const listeners = new Set<() => void>()
function publish(value: boolean) {
  if (vision === value) return
  vision = value
  listeners.forEach((listener) => listener())
}
function subscribe(listener: () => void) {
  listeners.add(listener)
  try {
    publish(window.localStorage.getItem(storageKey) === "high")
  } catch {
    /* Use session preference if storage is blocked. */
  }
  const sync = (event: StorageEvent) => {
    if (event.key === storageKey || event.key === null)
      publish(event.newValue === "high")
  }
  window.addEventListener("storage", sync)
  return () => {
    listeners.delete(listener)
    window.removeEventListener("storage", sync)
  }
}
function setVision(value: boolean) {
  try {
    window.localStorage.setItem(storageKey, value ? "high" : "standard")
  } catch {
    /* Still works for this page. */
  }
  publish(value)
}
const AppearanceContext = createContext({
  highVisibility: false,
  setHighVisibility: setVision,
})
// Apply the saved type size before hydration to avoid a distracting layout flash.
const bootstrap = `try{document.documentElement.dataset.vision=localStorage.getItem("windcast.vision")==="high"?"high":"standard"}catch{}`
export function AppearanceProvider({ children }: { children: ReactNode }) {
  const highVisibility = useSyncExternalStore(
    subscribe,
    () => vision,
    () => false
  )
  useEffect(() => {
    document.documentElement.dataset.vision = highVisibility
      ? "high"
      : "standard"
  }, [highVisibility])
  return (
    <AppearanceContext.Provider
      value={{ highVisibility, setHighVisibility: setVision }}
    >
      <script
        suppressHydrationWarning
        dangerouslySetInnerHTML={{ __html: bootstrap }}
      />
      {children}
    </AppearanceContext.Provider>
  )
}
export function useAppearance() {
  return useContext(AppearanceContext)
}
const subscribeHydration = () => () => {}
export function AppearanceControls() {
  const { tr } = useI18n()
  const { highVisibility, setHighVisibility } = useAppearance()
  const { resolvedTheme, setTheme } = useTheme()
  const hydrated = useSyncExternalStore(
    subscribeHydration,
    () => true,
    () => false
  )
  const dark = hydrated && resolvedTheme === "dark"
  return (
    <div
      className="wc-appearance-controls"
      role="group"
      aria-label={tr("Внешний вид")}
    >
      <button
        type="button"
        className="wc-appearance-button wc-vision-button"
        aria-label={tr("Версия для слабовидящих")}
        title={tr("Версия для слабовидящих")}
        aria-pressed={highVisibility}
        onClick={() => setHighVisibility(!highVisibility)}
      >
        <Eye size={19} aria-hidden="true" />
        <span>{tr("Для слабовидящих")}</span>
      </button>
      <button
        type="button"
        className="wc-appearance-button wc-theme-button"
        aria-label={tr("Тёмная тема")}
        title={tr(dark ? "Включить светлую тему" : "Включить тёмную тему")}
        aria-pressed={dark}
        onClick={() => setTheme(dark ? "light" : "dark")}
      >
        {dark ? (
          <Sun size={18} aria-hidden="true" />
        ) : (
          <Moon size={18} aria-hidden="true" />
        )}
      </button>
    </div>
  )
}
