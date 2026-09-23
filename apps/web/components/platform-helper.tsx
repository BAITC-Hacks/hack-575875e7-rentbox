"use client"

import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react"
import { ArrowUpRight, BookOpen, Download, LoaderCircle, RefreshCw, Send, Sparkles, Square, Trash2 } from "lucide-react"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@workspace/ui/components/dialog"
import { useAppearance } from "@/components/appearance-provider"
import {
  askHelper, getHelperStatus,
  type HelperAction, type HelperContext, type HelperHistory, type HelperReply,
  type HelperRequest, type HelperStatus,
} from "@/lib/helper-api"
import type { DashboardView } from "@/lib/turbine-scene"

const PAGE_NAMES: Record<DashboardView, string> = {
  overview: "Обзор", forecast: "Прогноз", agent: "AI-агент",
  sources: "Источники данных", history: "История запусков",
}
const QUESTIONS = [
  "Как рассчитать прогноз?",
  "Откуда взята погода для этого выпуска?",
  "Что означают предупреждения?",
  "Как скачать прогноз в CSV?",
]
const SIMULATION_QUESTIONS = [
  "Как устроена эта симуляция?",
  "Откуда взята погода в синтетическом сценарии?",
  "Как вернуться к реальным прогнозам?",
  "Что означает условная мощность турбины?",
]

type Message = {
  id: number
  role: "user" | "assistant"
  content: string
  request: HelperRequest
  reply?: HelperReply
}
type Props = {
  open: boolean
  onOpenChange: (open: boolean) => void
  context: HelperContext
  runId: string | null
  downloadableRunId: string | null
  downloading: boolean
  onNavigate: (view: DashboardView) => void
  onDownload: () => Promise<void>
}

function describeContext(context: HelperContext) {
  const date = context.date?.split("-").reverse().join(".") ?? "Дата не выбрана"
  const turbines = context.turbine_ids.length === 2 ? "обе турбины" : `турбина ${context.turbine_ids[0]}`
  const simulation = context.mode === "simulation"
  const hours = simulation ? context.simulation_hours ?? "—" : context.horizon_hours
  return `${simulation ? "Синтетическая симуляция" : "Прогноз"} · начало ${date} · ${hours} ч · ${turbines}`
}

function historyScope(context: HelperContext, runId: string | null) {
  return JSON.stringify([context.mode ?? "forecast", context.locale ?? "ru", runId,
    context.date, context.horizon_hours, context.simulation_hours ?? null, context.turbine_ids])
}

export function PlatformHelper({
  open, onOpenChange, context, runId, downloadableRunId, downloading, onNavigate, onDownload,
}: Props) {
  const simulated = context.mode === "simulation"
  const { highVisibility } = useAppearance()
  const [status, setStatus] = useState<HelperStatus | null>(null)
  const [checking, setChecking] = useState(true)
  const [statusError, setStatusError] = useState<string | null>(null)
  const [statusRevision, setStatusRevision] = useState(0)
  const [messages, setMessages] = useState<Message[]>([])
  const [draft, setDraft] = useState("")
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [retry, setRetry] = useState<HelperRequest | null>(null)
  const history = useRef<HelperHistory[]>([])
  const completedScope = useRef<string | null>(null)
  const sequence = useRef(0)
  const active = useRef<{ controller: AbortController; request: HelperRequest } | null>(null)
  const transcript = useRef<HTMLDivElement>(null)
  const input = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    if (!open) return
    const controller = new AbortController()
    async function load() {
      setChecking(true)
      setStatusError(null)
      try {
        const result = await getHelperStatus(controller.signal)
        if (!controller.signal.aborted) setStatus(result)
      } catch (cause) {
        if (!controller.signal.aborted) {
          setStatus(null)
          setStatusError(cause instanceof Error ? cause.message : "Не удалось проверить подключение.")
        }
      } finally {
        if (!controller.signal.aborted) setChecking(false)
      }
    }
    void load()
    return () => controller.abort()
  }, [open, statusRevision])

  useEffect(() => () => {
    active.current?.controller.abort()
    active.current = null
  }, [])
  useEffect(() => {
    if (open && transcript.current) transcript.current.scrollTop = transcript.current.scrollHeight
  }, [messages, busy, error, open])

  function stop() {
    const pending = active.current
    if (!pending) return
    active.current = null
    pending.controller.abort()
    setBusy(false)
    setRetry(pending.request)
    setError("Ожидание ответа остановлено. Вопрос можно отправить повторно.")
  }
  function changeOpen(next: boolean) {
    if (!next) stop()
    onOpenChange(next)
  }
  function navigate(next: DashboardView) {
    changeOpen(false)
    onNavigate(next)
  }

  async function send(request: HelperRequest, append: boolean) {
    // A ref locks immediately, including multiple clicks before the next render.
    if (active.current) return
    if (historyScope(request.context, request.run_id) !== historyScope(context, simulated ? null : runId)) {
      setError("Выбранный контекст изменился. Отправьте вопрос заново для текущего режима и даты.")
      setRetry(null)
      return
    }
    const controller = new AbortController()
    active.current = { controller, request }
    setBusy(true)
    setError(null)
    setRetry(null)
    if (append) {
      const item: Message = { id: ++sequence.current, role: "user", content: request.message, request }
      setMessages((items) => [...items, item].slice(-31))
      setDraft("")
    }
    try {
      const reply = await askHelper(request, controller.signal)
      if (controller.signal.aborted || active.current?.controller !== controller) return
      const item: Message = { id: ++sequence.current, role: "assistant", content: reply.text, request, reply }
      setMessages((items) => [...items, item].slice(-32))
      history.current = [
        ...request.history,
        { role: "user", content: request.message },
        { role: "assistant", content: reply.text.slice(0, 3000) },
      ].slice(-8) as HelperHistory[]
      completedScope.current = historyScope(request.context, request.run_id)
    } catch (cause) {
      if (controller.signal.aborted || active.current?.controller !== controller) return
      setError(cause instanceof Error ? cause.message : "Не удалось получить ответ.")
      setRetry(request)
    } finally {
      if (active.current?.controller === controller) {
        active.current = null
        setBusy(false)
        input.current?.focus()
      }
    }
  }
  function ask(value: string) {
    const message = value.trim()
    if (!message || message.length > 2000 || active.current) return
    if (simulated && (!Number.isInteger(context.simulation_hours)
      || (context.simulation_hours ?? 0) < 1 || (context.simulation_hours ?? 0) > 10000)) {
      setError("Помощник поддерживает синтетические сценарии длительностью от 1 до 10 000 часов.")
      setRetry(null)
      return
    }
    const preparedContext = {
      ...context, mode: context.mode ?? "forecast", locale: context.locale ?? "ru",
      simulation_hours: simulated ? context.simulation_hours ?? null : null,
    }
    const selectedRunId = simulated ? null : runId
    const previous = completedScope.current === historyScope(preparedContext, selectedRunId) ? history.current.slice(-8) : []
    void send({ message, history: previous, run_id: selectedRunId, context: preparedContext }, true)
  }
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    ask(draft)
  }
  function keyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault()
      ask(draft)
    }
  }
  function actionEnabled(action: HelperAction) {
    if (busy) return false
    if (action.type === "navigate") return action.view !== null
    return !simulated && !downloading && action.run_id !== null && action.run_id === downloadableRunId
  }
  function act(action: HelperAction) {
    if (!actionEnabled(action)) return
    if (action.type === "navigate" && action.view) navigate(action.view)
    else if (action.type === "download_csv") {
      changeOpen(false)
      void onDownload()
    }
  }
  const ready = status?.provider === "openai" && status.available && status.enabled && status.configured

  return (
    <Dialog open={open} onOpenChange={changeOpen}>
      <DialogContent
        className={`wc-helper ${highVisibility ? "wc-helper-high" : ""}`}
        lang="ru"
        closeLabel="Закрыть помощник"
        initialFocus={(interaction) => interaction === "touch" ? true : input.current}
        style={{ top: 0, right: 0, bottom: 0, left: "auto", transform: "none", width: "min(500px, 100vw)", maxWidth: "100vw", height: "100dvh", maxHeight: "100dvh", borderRadius: 0, margin: 0 }}
      >
        <DialogHeader className="wc-helper-header">
          <div className="wc-helper-heading">
            <span className="wc-helper-avatar"><BookOpen className="size-5" /></span>
            <div>
              <DialogTitle className="wc-helper-title">Помощник Windcast</DialogTitle>
              <DialogDescription className="wc-helper-subtitle">Прогнозы, источники данных и история запусков.</DialogDescription>
            </div>
          </div>
          <div className="wc-helper-toolbar">
            <span
              className={`wc-helper-status ${ready ? "is-ready" : ""}`}
              aria-live="polite"
              title={checking ? "Проверяем доступный режим ответов."
                : statusError ? `${statusError} Подключение ASTRA не подтверждено.`
                  : ready ? "Доступ к модели проверяется при отправке вопроса."
                    : "ASTRA не подключена. Доступны подсказки и справка платформы."}
            >
              {checking ? <LoaderCircle className="size-3.5 animate-spin" /> : ready ? <Sparkles className="size-3.5" /> : <BookOpen className="size-3.5" />}
              {checking ? "Проверяем подключение" : ready ? "ASTRA · OpenAI" : "Справка платформы"}
            </span>
            <button type="button" className="wc-helper-icon-button" disabled={checking} onClick={() => setStatusRevision((value) => value + 1)} aria-label="Обновить состояние помощника">
              <RefreshCw className="size-3.5" />
            </button>
            <button type="button" className="wc-helper-icon-button" disabled={busy || !messages.length} aria-label="Очистить диалог" onClick={() => {
              setMessages([]); history.current = []; completedScope.current = null; setError(null); setRetry(null); input.current?.focus()
            }}>
              <Trash2 className="size-3.5" />
            </button>
          </div>
          <p className="wc-helper-context">{PAGE_NAMES[context.view]} · {describeContext(context)}</p>
        </DialogHeader>

        <div ref={transcript} className="wc-helper-transcript" role="log" aria-label="Диалог с помощником" aria-live="polite" aria-relevant="additions text" aria-busy={busy}>
          {simulated && <p className="wc-helper-warning" role="status">
            Синтетическая симуляция на {context.simulation_hours ?? "—"} ч. Значения созданы в браузере и не являются результатом модели ВЭС. Выпуск реального прогноза и его CSV здесь не используются.
          </p>}
          {!messages.length && (
            <article className="wc-helper-message is-assistant">
              <div className="wc-helper-message-meta"><BookOpen className="size-3.5" /> Помощник</div>
              <p className="wc-helper-message-text">Здравствуйте! Задайте вопрос или выберите подсказку ниже. Я учитываю выбранный раздел, язык и {simulated ? "параметры синтетической симуляции" : "дату начала прогноза и выбранный выпуск"}.</p>
              <p className="wc-helper-message-hint">{simulated
                ? "Мощность в МВт в симуляции опирается на условный параметр сценария. Он не подтверждает номинальную мощность турбин из кейса."
                : "Мощность имеет нормализованную шкалу 0–1 и отображается в процентах. База нормализации не подтверждена."}</p>
              <div className="wc-helper-actions">
                <button type="button" className="wc-helper-chip" onClick={() => navigate("forecast")}>К прогнозу <ArrowUpRight className="size-3.5" /></button>
                <button type="button" className="wc-helper-chip" onClick={() => navigate("history")}>История запусков <ArrowUpRight className="size-3.5" /></button>
              </div>
            </article>
          )}
          {messages.map((message) => (
            <article key={message.id} className={`wc-helper-message ${message.role === "user" ? "is-user" : "is-assistant"}`}>
              <div className="wc-helper-message-meta">
                {message.role === "user" ? "Вы"
                  : message.reply?.provider === "openai" ? <><Sparkles className="size-3.5" /> ASTRA · OpenAI</>
                    : <><BookOpen className="size-3.5" /> Справка платформы</>}
              </div>
              <p lang={message.reply?.provider === "openai" ? message.request.context.locale ?? "ru" : undefined} className="wc-helper-message-text">{message.content}</p>
              {message.role === "user" && <p className="wc-helper-message-hint">{describeContext(message.request.context)}</p>}
              {message.reply?.provider === "local_help" && <p className="wc-helper-message-hint">Ответ подготовлен справкой платформы, ASTRA не использовалась.</p>}
              {message.reply?.warning && <p className="wc-helper-warning">{message.reply.warning}</p>}
              {!!message.reply?.sources.length && (
                <div className="wc-helper-sources">
                  <span>Источники ответа</span>
                  {message.reply.sources.map((source, index) => source.view ? (
                    <button key={`${source.id}-${index}`} type="button" disabled={busy} className="wc-helper-link" onClick={() => source.view && navigate(source.view)}>
                      {source.title} <ArrowUpRight className="size-3" />
                    </button>
                  ) : <span key={`${source.id}-${index}`} className="wc-helper-source">{source.title}</span>)}
                </div>
              )}
              {!!message.reply?.actions.length && <div className="wc-helper-actions">
                {message.reply.actions.filter((action) => !simulated || action.type !== "download_csv").map((action, index) => (
                  <button key={`${action.type}-${index}`} type="button" className="wc-helper-chip is-action" disabled={!actionEnabled(action)} title={action.type === "download_csv" && action.run_id !== downloadableRunId ? "Откройте выпуск, к которому относится этот ответ, чтобы скачать его CSV." : undefined} onClick={() => act(action)}>
                    {action.type === "download_csv" ? <Download className="size-3.5" /> : <ArrowUpRight className="size-3.5" />} {action.label}
                  </button>
                ))}
              </div>}
            </article>
          ))}
          {busy && <div className="wc-helper-typing" role="status"><LoaderCircle className="size-4 animate-spin" /> Готовим ответ…</div>}
          {error && <div className="wc-helper-warning is-error" role="alert">
            <p>{error}</p>
            {retry && <button type="button" className="wc-helper-chip" disabled={busy} onClick={() => void send(retry, false)}><RefreshCw className="size-3.5" /> Повторить вопрос</button>}
          </div>}
        </div>

        <div className="wc-helper-composer">
          <div className="wc-helper-suggestions" aria-label="Быстрые вопросы">
            {(simulated ? SIMULATION_QUESTIONS : QUESTIONS).map((question) => <button key={question} type="button" className="wc-helper-chip" disabled={busy} onClick={() => ask(question)}>{question}</button>)}
          </div>
          <form className="wc-helper-form" onSubmit={submit}>
            <label className="sr-only" htmlFor="platform-helper-message">Вопрос помощнику платформы</label>
            <textarea
              ref={input} id="platform-helper-message" value={draft} onChange={(event) => setDraft(event.target.value)}
              onKeyDown={keyDown} maxLength={2000} rows={1} disabled={busy}
              placeholder="Напишите вопрос…"
              className="wc-helper-input"
            />
            {busy
              ? <button type="button" className="wc-helper-send" onClick={stop} aria-label="Остановить"><Square className="size-4" /></button>
              : <button type="submit" className="wc-helper-send" disabled={!draft.trim()} aria-label="Отправить"><Send className="size-4" /></button>}
          </form>
          <p className="wc-helper-footnote">Enter — отправить · Shift+Enter — новая строка · {draft.length}/2000 · диалог хранится до обновления страницы</p>
        </div>
      </DialogContent>
    </Dialog>
  )
}
