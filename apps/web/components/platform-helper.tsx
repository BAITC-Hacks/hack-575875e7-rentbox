"use client"

import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react"
import { ArrowUpRight, BookOpen, Download, LoaderCircle, RefreshCw, Send, Sparkles, Square, Trash2 } from "lucide-react"
import { Button } from "@workspace/ui/components/button"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@workspace/ui/components/dialog"
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
  return `${date} · ${context.horizon_hours} ч · ${turbines}`
}

export function PlatformHelper({
  open, onOpenChange, context, runId, downloadableRunId, downloading, onNavigate, onDownload,
}: Props) {
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
    void send({ message, history: history.current.slice(-8), run_id: runId, context }, true)
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
    return !downloading && action.run_id !== null && action.run_id === downloadableRunId
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
        className="flex flex-col gap-4 border border-[#e1ead6] bg-[#fefffc] text-[#3c5131]"
        initialFocus={(interaction) => interaction === "touch" ? true : input.current}
        style={{ width: "min(720px, calc(100vw - 2rem))", maxWidth: "calc(100vw - 2rem)", maxHeight: "min(820px, calc(100dvh - 2rem))", overflowY: "auto" }}
      >
        <DialogHeader className="shrink-0 pr-8">
          <DialogTitle className="flex items-center gap-2 text-xl font-semibold">
            <BookOpen className="size-5 text-[#4e7c39]" /> Помощник Windcast
          </DialogTitle>
          <DialogDescription className="text-xs leading-relaxed text-[#687b5d]">
            Прогнозы, источники данных и история — помогу найти нужное и разобраться в показателях.
          </DialogDescription>
        </DialogHeader>

        <div className="shrink-0 rounded-xl border border-[#e1ead6] bg-[#f3f7ed] p-3" aria-live="polite">
          <div className="flex items-center justify-between gap-3">
            <span className="flex items-center gap-2 text-xs font-semibold">
              {checking ? <LoaderCircle className="size-4 animate-spin" /> : ready ? <Sparkles className="size-4" /> : <BookOpen className="size-4" />}
              {checking ? "Проверяем подключение" : ready ? "OpenAI · GPT-6 Astra" : "Справка платформы"}
            </span>
            <Button variant="ghost" size="icon-xs" disabled={checking} onClick={() => setStatusRevision((value) => value + 1)} aria-label="Обновить состояние помощника">
              <RefreshCw className="size-3" />
            </Button>
          </div>
          <p className="mt-1 text-xs leading-relaxed text-[#687b5d]">
            {checking ? "Проверяем доступный режим ответов."
              : statusError ? `${statusError} Подключение ASTRA не подтверждено.`
                : ready ? "Доступ к модели проверяется при отправке вопроса."
                  : "ASTRA не подключена. Доступны подсказки и справка платформы."}
          </p>
        </div>

        <div className="flex shrink-0 items-center justify-between gap-3 text-xs text-[#687b5d]">
          <span>{PAGE_NAMES[context.view]} · {describeContext(context)}</span>
          <Button variant="ghost" size="icon-xs" disabled={busy || !messages.length} aria-label="Очистить диалог" onClick={() => {
            setMessages([]); history.current = []; setError(null); setRetry(null); input.current?.focus()
          }}><Trash2 className="size-3" /></Button>
        </div>

        <div ref={transcript} className="min-h-24 flex-1 space-y-4 overflow-y-auto overscroll-contain pr-1" role="log" aria-label="Диалог с помощником" aria-live="polite" aria-relevant="additions text" aria-busy={busy}>
          {!messages.length && (
            <div className="rounded-xl border border-dashed border-[#d6e1cc] p-4 text-sm leading-relaxed">
              <p>Задайте вопрос или выберите подсказку ниже. Помощник учитывает выбранный раздел, дату и выпуск прогноза.</p>
              <p className="mt-2 text-xs text-[#687b5d]">Мощность имеет нормализованную шкалу 0–1 и отображается в процентах. База нормализации не подтверждена.</p>
              <div className="mt-3 flex flex-wrap gap-2">
                <Button size="xs" variant="outline" onClick={() => navigate("forecast")}>К прогнозу <ArrowUpRight /></Button>
                <Button size="xs" variant="outline" onClick={() => navigate("history")}>История запусков <ArrowUpRight /></Button>
              </div>
            </div>
          )}
          {messages.map((message) => (
            <article key={message.id} className={message.role === "user"
              ? "ml-6 rounded-xl border border-[#d9e5cf] bg-[#eef4e7] p-3 sm:ml-12"
              : "mr-3 rounded-xl border border-[#e5eadf] bg-white p-3 sm:mr-6"}>
              <div className="mb-2 flex items-center gap-2 text-xs font-semibold text-[#4e7c39]">
                {message.role === "user" ? "Вы"
                  : message.reply?.provider === "openai" ? <><Sparkles className="size-3.5" /> ASTRA · OpenAI · GPT-6 Astra</>
                    : <><BookOpen className="size-3.5" /> Справка платформы</>}
              </div>
              <p className="whitespace-pre-wrap break-words text-sm leading-relaxed">{message.content}</p>
              {message.role === "user" && <p className="mt-2 text-[11px] text-[#687b5d]">{describeContext(message.request.context)}</p>}
              {message.reply?.provider === "local_help" && <p className="mt-2 text-xs text-[#687b5d]">Этот ответ подготовлен справкой платформы. ASTRA не использовалась.</p>}
              {message.reply?.warning && <p className="mt-3 rounded-lg border border-[#e7d6ae] bg-[#fff9e9] p-2 text-xs leading-relaxed text-[#795e26]">{message.reply.warning}</p>}
              {!!message.reply?.sources.length && (
                <div className="mt-3 border-t border-[#e5eadf] pt-2">
                  <p className="mb-1 text-[11px] font-medium text-[#687b5d]">Источники ответа</p>
                  <div className="flex flex-wrap gap-x-3 gap-y-1">
                    {message.reply.sources.map((source, index) => source.view ? (
                      <button key={`${source.id}-${index}`} type="button" disabled={busy} className="inline-flex items-center gap-1 text-xs text-[#4e7c39] underline underline-offset-2 disabled:opacity-50" onClick={() => source.view && navigate(source.view)}>
                        {source.title} <ArrowUpRight className="size-3" />
                      </button>
                    ) : <span key={`${source.id}-${index}`} className="text-xs text-[#687b5d]">{source.title}</span>)}
                  </div>
                </div>
              )}
              {!!message.reply?.actions.length && <div className="mt-3 flex flex-wrap gap-2">
                {message.reply.actions.map((action, index) => (
                  <Button key={`${action.type}-${index}`} size="sm" variant="outline" className="h-auto min-h-8 whitespace-normal text-left text-xs" disabled={!actionEnabled(action)} title={action.type === "download_csv" && action.run_id !== downloadableRunId ? "Откройте выпуск, к которому относится этот ответ, чтобы скачать его CSV." : undefined} onClick={() => act(action)}>
                    {action.type === "download_csv" ? <Download /> : <ArrowUpRight />} {action.label}
                  </Button>
                ))}
              </div>}
            </article>
          ))}
          {busy && <div className="flex items-center gap-2 py-2 text-xs text-[#687b5d]" role="status"><LoaderCircle className="size-4 animate-spin" /> Готовим ответ…</div>}
          {error && <div className="rounded-xl border border-[#e7d6ae] bg-[#fff9e9] p-3 text-xs text-[#795e26]" role="alert">
            <p>{error}</p>
            {retry && <Button className="mt-2" size="sm" variant="outline" disabled={busy} onClick={() => void send(retry, false)}><RefreshCw /> Повторить вопрос</Button>}
          </div>}
        </div>

        <div className="flex shrink-0 flex-wrap gap-2" aria-label="Быстрые вопросы">
          {QUESTIONS.map((question) => <Button key={question} variant="outline" size="xs" className="h-auto min-h-7 whitespace-normal py-1 text-left" disabled={busy} onClick={() => ask(question)}>{question}</Button>)}
        </div>
        <form className="shrink-0 space-y-2 border-t border-[#e1ead6] pt-3" onSubmit={submit}>
          <label className="sr-only" htmlFor="platform-helper-message">Вопрос помощнику платформы</label>
          <textarea
            ref={input} id="platform-helper-message" value={draft} onChange={(event) => setDraft(event.target.value)}
            onKeyDown={keyDown} maxLength={2000} rows={2} disabled={busy}
            placeholder="Например: почему нет фактической мощности за февраль?"
            className="w-full resize-none rounded-xl border border-[#d6e1cc] bg-white px-3 py-2 text-sm text-[#3c5131] outline-none placeholder:text-[#849575] focus:border-[#749c5e] focus:ring-2 focus:ring-[#dce8d2] disabled:opacity-60"
          />
          <div className="flex items-center justify-between gap-2">
            <span className="text-[11px] text-[#687b5d]">Enter — отправить · Shift+Enter — новая строка · {draft.length}/2000</span>
            {busy ? <Button type="button" size="sm" variant="outline" onClick={stop}><Square /> Остановить</Button>
              : <Button type="submit" size="sm" className="bg-[#3b6545] text-white hover:bg-[#2f5539]" disabled={!draft.trim()}><Send /> Отправить</Button>}
          </div>
          <p className="text-[11px] text-[#687b5d]">Диалог хранится до обновления страницы. Последние сообщения передаются помощнику вместе с выбранным контекстом.</p>
        </form>
      </DialogContent>
    </Dialog>
  )
}
