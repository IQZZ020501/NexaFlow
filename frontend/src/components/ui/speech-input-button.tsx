"use client"

import * as React from "react"
import { LoaderCircleIcon, MicIcon, SquareIcon } from "lucide-react"

import { useLanguage } from "@/contexts/language-provider"
import { languageLocales } from "@/i18n"
import {
  getBrowserSpeechRecognitionConstructor,
  type BrowserSpeechRecognition,
} from "@/lib/browser-stt"

import { Button } from "./button"

type SpeechInputButtonProps = {
  value: string
  onChange: (value: string) => void
  onError: (message: string) => void
  disabled?: boolean
  maxLength?: number
}

const subscribe = () => () => {}
const getSupported = () => Boolean(getBrowserSpeechRecognitionConstructor())
const getServerSupported = () => false

/** Transcribes microphone input into a draft; sending or editing ends capture. */
export function SpeechInputButton({
  value,
  onChange,
  onError,
  disabled = false,
  maxLength = 4000,
}: SpeechInputButtonProps) {
  const { language, t } = useLanguage()
  const supported = React.useSyncExternalStore(
    subscribe,
    getSupported,
    getServerSupported
  )
  const [status, setStatus] = React.useState<"idle" | "listening" | "stopping">(
    "idle"
  )
  const buttonRef = React.useRef<HTMLButtonElement>(null)
  const recognitionRef = React.useRef<BrowserSpeechRecognition | null>(null)
  const expectedValueRef = React.useRef(value)
  const callbacksRef = React.useRef({ onChange, onError, t })

  React.useLayoutEffect(() => {
    callbacksRef.current = { onChange, onError, t }
  }, [onChange, onError, t])

  const releaseRecognition = React.useCallback(() => {
    const recognition = recognitionRef.current
    recognitionRef.current = null
    if (!recognition) return
    recognition.onresult = null
    recognition.onerror = null
    recognition.onend = null
    recognition.abort()
  }, [])

  const cancelListening = React.useCallback(() => {
    releaseRecognition()
    setStatus("idle")
  }, [releaseRecognition])

  React.useLayoutEffect(() => {
    if (
      recognitionRef.current &&
      (disabled ||
        value !== expectedValueRef.current ||
        recognitionRef.current.lang !== languageLocales[language])
    ) {
      // Stop the external microphone session when the draft changes elsewhere.
      cancelListening()
    }
  }, [disabled, language, value, cancelListening])

  React.useEffect(() => {
    const form = buttonRef.current?.form
    form?.addEventListener("submit", cancelListening)
    return () => {
      form?.removeEventListener("submit", cancelListening)
      releaseRecognition()
    }
  }, [cancelListening, releaseRecognition])

  function handleRecognitionError(error: string) {
    cancelListening()
    if (error === "aborted") return
    const { t, onError } = callbacksRef.current
    onError(
      t(
        error === "not-allowed"
          ? "请允许麦克风权限后重试。"
          : error === "audio-capture"
            ? "无法使用麦克风，请检查设备是否连接或被占用。"
            : error === "network" || error === "service-not-allowed"
              ? "当前浏览器的语音识别服务不可用，请重试或尝试使用 Chrome。"
              : error === "no-speech"
                ? "未检测到语音，请重试。"
                : "语音识别失败，请重试。"
      )
    )
  }

  function toggleListening() {
    if (recognitionRef.current) {
      setStatus("stopping")
      recognitionRef.current.stop()
      return
    }
    const Recognition = getBrowserSpeechRecognitionConstructor()
    if (!Recognition || disabled) return

    const base = value
    let recognition: BrowserSpeechRecognition
    try {
      recognition = new Recognition()
    } catch {
      handleRecognitionError("unknown")
      return
    }
    recognition.lang = languageLocales[language]
    recognition.continuous = true
    recognition.interimResults = true
    recognition.maxAlternatives = 1
    recognitionRef.current = recognition
    expectedValueRef.current = value

    recognition.onresult = (event) => {
      if (recognitionRef.current !== recognition) return
      const transcript = Array.from(
        event.results,
        (result) => result[0].transcript
      )
        .join("")
        .trim()
      const separator = transcript && base && !/\s$/.test(base) ? " " : ""
      const nextValue = `${base}${separator}${transcript}`.slice(0, maxLength)
      expectedValueRef.current = nextValue
      callbacksRef.current.onChange(nextValue)
      if (nextValue.length >= maxLength) cancelListening()
    }
    recognition.onerror = (event) => {
      if (recognitionRef.current === recognition) {
        handleRecognitionError(event.error)
      }
    }
    recognition.onend = () => {
      if (recognitionRef.current !== recognition) return
      recognitionRef.current = null
      setStatus("idle")
    }

    try {
      setStatus("listening")
      recognition.start()
    } catch (error) {
      handleRecognitionError(
        error instanceof DOMException && error.name === "NotAllowedError"
          ? "not-allowed"
          : "unknown"
      )
    }
  }

  const label = status === "idle" ? t("开始语音输入") : t("停止语音输入")
  return (
    <Button
      ref={buttonRef}
      type="button"
      variant={status === "idle" ? "ghost" : "destructive"}
      size={status === "idle" ? "icon-sm" : "sm"}
      className={
        status === "idle"
          ? "rounded-md text-muted-foreground hover:text-foreground"
          : "gap-1.5 rounded-full px-3 disabled:opacity-70 motion-reduce:transition-none"
      }
      aria-label={label}
      aria-pressed={status !== "idle"}
      aria-busy={status === "stopping"}
      title={supported ? label : t("当前浏览器不支持语音转文字")}
      disabled={disabled || !supported || status === "stopping"}
      onClick={toggleListening}
    >
      {status === "stopping" ? (
        <LoaderCircleIcon
          aria-hidden="true"
          className="size-3 animate-spin motion-reduce:animate-none"
        />
      ) : status === "listening" ? (
        <SquareIcon
          aria-hidden="true"
          className="size-2.5 fill-current"
          strokeWidth={0}
        />
      ) : (
        <MicIcon />
      )}
      {status !== "idle" ? (
        <span>{t(status === "stopping" ? "停止中" : "停止")}</span>
      ) : null}
    </Button>
  )
}
