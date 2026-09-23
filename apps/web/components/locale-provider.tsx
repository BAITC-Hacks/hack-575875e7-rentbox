"use client"

import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useSyncExternalStore,
  type ReactNode,
} from "react"
import { Languages } from "lucide-react"
import { formatDate, formatTimestamp, number } from "@/lib/forecast-data"
import {
  isLocale,
  localeTags,
  translate,
  type Locale,
  type MessageValues,
} from "@/lib/translations"

const storageKey = "windcast.locale"
let currentLocale: Locale = "ru"
const listeners = new Set<() => void>()
function publish(locale: Locale) {
  if (locale === currentLocale) return
  currentLocale = locale
  listeners.forEach((listener) => listener())
}
function subscribe(listener: () => void) {
  listeners.add(listener)
  try {
    const saved = window.localStorage.getItem(storageKey)
    if (isLocale(saved)) publish(saved)
  } catch {
    /* Language switching also works when browser storage is unavailable. */
  }
  const sync = (event: StorageEvent) => {
    if (event.key === storageKey || event.key === null)
      publish(isLocale(event.newValue) ? event.newValue : "ru")
  }
  window.addEventListener("storage", sync)
  return () => {
    listeners.delete(listener)
    window.removeEventListener("storage", sync)
  }
}
function setLocale(locale: Locale) {
  try {
    window.localStorage.setItem(storageKey, locale)
  } catch {
    /* Keep the session preference in memory. */
  }
  publish(locale)
}
function createI18n(locale: Locale) {
  const tag = localeTags[locale]
  return {
    locale,
    setLocale,
    tr: (source: string, values?: MessageValues) =>
      translate(locale, source, values),
    number: (value: number, digits = 1) => number(value, digits, tag),
    formatDate: (date: string, long = false) => formatDate(date, long, tag),
    formatTimestamp: (date: string) => formatTimestamp(date, tag),
  }
}
const LocaleContext = createContext(createI18n("ru"))
export function LocaleProvider({ children }: { children: ReactNode }) {
  const locale = useSyncExternalStore(
    subscribe,
    () => currentLocale,
    () => "ru" as const
  )
  const value = useMemo(() => createI18n(locale), [locale])
  useEffect(() => {
    document.documentElement.lang = locale
  }, [locale])
  return (
    <LocaleContext.Provider value={value}>
      <title>{value.tr("Windcast — прогноз выработки ВЭС")}</title>
      <meta
        name="description"
        content={value.tr(
          "Почасовой прогноз ветровой генерации, погода и AI-агент. Демонстрационный dashboard."
        )}
      />
      {children}
    </LocaleContext.Provider>
  )
}
export function useI18n() {
  return useContext(LocaleContext)
}
export function LanguageSelector() {
  const { locale, setLocale, tr } = useI18n()
  return (
    <label className="wc-language-selector">
      <Languages size={15} aria-hidden="true" />
      <select
        aria-label={tr("Язык интерфейса")}
        value={locale}
        onChange={(event) => {
          if (isLocale(event.target.value)) setLocale(event.target.value)
        }}
      >
        <option value="ru" lang="ru">
          Русский
        </option>
        <option value="en" lang="en">
          English
        </option>
        <option value="kk" lang="kk">
          Қазақша
        </option>
      </select>
    </label>
  )
}
