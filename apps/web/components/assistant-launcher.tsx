"use client"

import { useEffect, useState } from "react"
import { MessageCircle, X } from "lucide-react"
import { useI18n } from "@/components/locale-provider"

// Floating entry point for the platform helper: a round button in the bottom
// right corner and a one-time "need help?" prompt that appears a few seconds
// after the dashboard loads. The prompt is remembered per browser session.
const storageKey = "windcast.assistant-prompt"
const promptDelayMs = 4000

export function AssistantLauncher({
  open,
  onOpen,
}: {
  open: boolean
  onOpen: () => void
}) {
  const { tr } = useI18n()
  const [prompt, setPrompt] = useState(false)
  useEffect(() => {
    let seen = false
    try {
      seen = window.sessionStorage.getItem(storageKey) === "1"
    } catch {
      /* Private mode or blocked storage: the prompt simply shows once. */
    }
    if (seen) return
    const timer = window.setTimeout(() => setPrompt(true), promptDelayMs)
    return () => window.clearTimeout(timer)
  }, [])
  function dismiss() {
    setPrompt(false)
    try {
      window.sessionStorage.setItem(storageKey, "1")
    } catch {
      /* Keep the dismissal in memory for this page. */
    }
  }
  function openChat() {
    dismiss()
    onOpen()
  }
  if (open) return null
  return (
    <div className="wc-assistant-launcher">
      {prompt && (
        <div className="wc-assistant-prompt" role="status">
          <button
            type="button"
            className="wc-assistant-prompt-close"
            aria-label={tr("Скрыть подсказку")}
            onClick={dismiss}
          >
            <X size={14} />
          </button>
          <strong>{tr("Нужна помощь?")}</strong>
          <p>
            {tr(
              "Помощник объяснит прогноз, источники погоды и подскажет, что нажать."
            )}
          </p>
          <button
            type="button"
            className="wc-assistant-prompt-open"
            onClick={openChat}
          >
            {tr("Открыть чат")}
          </button>
        </div>
      )}
      <button
        type="button"
        className="wc-assistant-button"
        aria-label={tr("Открыть помощник Windcast")}
        onClick={openChat}
      >
        <MessageCircle size={23} strokeWidth={1.9} />
        <span className="wc-assistant-pulse" aria-hidden="true" />
      </button>
    </div>
  )
}
