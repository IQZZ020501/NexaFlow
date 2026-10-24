/* @jsxImportSource react */
import { afterEach, describe, expect, test } from "bun:test"
import { useState } from "react"
import { act, fireEvent, screen } from "@testing-library/react"

import { SpeechInputButton } from "@/components/ui/speech-input-button"
import { LanguageProvider, useLanguage } from "@/contexts/language-provider"
import type {
  BrowserSpeechRecognition,
  BrowserSpeechRecognitionErrorEvent,
  BrowserSpeechRecognitionEvent,
} from "@/lib/browser-stt"

import { cleanup, renderPage } from "./helpers/dom"

class FakeSpeechRecognition implements BrowserSpeechRecognition {
  static current: FakeSpeechRecognition
  static startError: DOMException | null = null
  lang = ""
  continuous = false
  interimResults = false
  maxAlternatives = 0
  onresult: ((event: BrowserSpeechRecognitionEvent) => void) | null = null
  onerror: ((event: BrowserSpeechRecognitionErrorEvent) => void) | null = null
  onend: (() => void) | null = null
  started = false
  stopped = false
  aborted = false

  constructor() {
    FakeSpeechRecognition.current = this
  }

  start() {
    if (FakeSpeechRecognition.startError) throw FakeSpeechRecognition.startError
    this.started = true
  }

  stop() {
    this.stopped = true
  }

  abort() {
    this.aborted = true
    this.onend?.()
  }

  emitResult(transcripts: string[], resultIndex = 0) {
    this.onresult?.(
      Object.assign(new Event("result"), {
        resultIndex,
        results: transcripts.map((transcript) => ({
          isFinal: transcripts.length > 1,
          0: { transcript },
        })),
      })
    )
  }
}

const errors: string[] = []

function SpeechHarness({
  disabled = false,
  maxLength = 4000,
}: {
  disabled?: boolean
  maxLength?: number
}) {
  const [value, setValue] = useState("已有问题")
  const { setLanguage } = useLanguage()
  return (
    <form
      onSubmit={(event) => {
        event.preventDefault()
        setValue("")
      }}
    >
      <SpeechInputButton
        value={value}
        onChange={setValue}
        onError={(message) => errors.push(message)}
        disabled={disabled}
        maxLength={maxLength}
      />
      <input
        aria-label="draft"
        value={value}
        onChange={(event) => setValue(event.target.value)}
      />
      <button type="submit">submit</button>
      <button type="button" onClick={() => setLanguage("en")}>
        English
      </button>
    </form>
  )
}

function installRecognition(prefixed = false) {
  Object.defineProperty(
    window,
    prefixed ? "webkitSpeechRecognition" : "SpeechRecognition",
    {
      configurable: true,
      writable: true,
      value: FakeSpeechRecognition,
    }
  )
}

function startRecognition() {
  fireEvent.click(screen.getByRole("button", { name: "开始语音输入" }))
  return FakeSpeechRecognition.current
}

function draftValue() {
  return (screen.getByLabelText("draft") as HTMLInputElement).value
}

afterEach(() => {
  cleanup()
  delete window.SpeechRecognition
  delete window.webkitSpeechRecognition
  FakeSpeechRecognition.startError = null
  errors.length = 0
  localStorage.clear()
})

describe("SpeechInputButton", () => {
  test("replaces interim results without duplicating previous final segments and waits for stop", () => {
    installRecognition()
    renderPage(<SpeechHarness />)
    const recognition = startRecognition()
    expect(recognition.lang).toBe("zh-CN")
    expect(recognition.started).toBe(true)

    act(() => recognition.emitResult(["你"]))
    expect(draftValue()).toBe("已有问题 你")
    act(() => recognition.emitResult(["你好", "，请查"]))
    expect(draftValue()).toBe("已有问题 你好，请查")

    fireEvent.click(screen.getByRole("button", { name: "停止语音输入" }))
    expect(recognition.stopped).toBe(true)
    expect(
      (
        screen.getByRole("button", {
          name: "停止语音输入",
        }) as HTMLButtonElement
      ).disabled
    ).toBe(true)
    act(() => recognition.emitResult(["你好", "，请查询资料"], 1))
    expect(draftValue()).toBe("已有问题 你好，请查询资料")
    act(() => recognition.onend?.())
    expect(screen.getByRole("button", { name: "开始语音输入" })).toBeTruthy()
  })

  test("supports the prefixed API and respects the input limit", () => {
    installRecognition(true)
    renderPage(<SpeechHarness maxLength={8} />)
    const recognition = startRecognition()
    act(() => recognition.emitResult(["一二三四五六七八九"]))
    expect(draftValue().length).toBe(8)
    expect(recognition.aborted).toBe(true)
  })

  test("preserves manual edits and ignores late recognition callbacks", () => {
    installRecognition()
    renderPage(<SpeechHarness />)
    const recognition = startRecognition()
    const lateResult = recognition.onresult!
    fireEvent.change(screen.getByLabelText("draft"), {
      target: { value: "手动修改" },
    })
    expect(recognition.aborted).toBe(true)
    act(() =>
      lateResult(
        Object.assign(new Event("result"), {
          resultIndex: 0,
          results: [{ isFinal: true, 0: { transcript: "迟到结果" } }],
        })
      )
    )
    expect(draftValue()).toBe("手动修改")
  })

  test("submitting ends capture before a result can repopulate the draft", () => {
    installRecognition()
    renderPage(<SpeechHarness />)
    const recognition = startRecognition()
    fireEvent.submit(
      screen.getByRole("button", { name: "submit" }).closest("form")!
    )
    expect(recognition.aborted).toBe(true)
    expect(draftValue()).toBe("")
  })

  test("disabling or unmounting releases the microphone", () => {
    installRecognition()
    const view = renderPage(<SpeechHarness />)
    const recognition = startRecognition()
    view.rerender(
      <LanguageProvider>
        <SpeechHarness disabled />
      </LanguageProvider>
    )
    expect(recognition.aborted).toBe(true)
    cleanup()

    const nextView = renderPage(<SpeechHarness />)
    const nextRecognition = startRecognition()
    nextView.unmount()
    expect(nextRecognition.aborted).toBe(true)
  })

  test("reports permission and network errors in the current language and permits retry", () => {
    installRecognition()
    renderPage(<SpeechHarness />)
    const recognition = startRecognition()
    act(() =>
      recognition.onerror?.(
        Object.assign(new Event("error"), { error: "not-allowed" })
      )
    )
    expect(errors).toEqual(["请允许麦克风权限后重试。"])
    fireEvent.click(screen.getByRole("button", { name: "English" }))
    fireEvent.click(screen.getByRole("button", { name: "Start voice input" }))
    expect(FakeSpeechRecognition.current.lang).toBe("en-US")
    act(() =>
      FakeSpeechRecognition.current.onerror?.(
        Object.assign(new Event("error"), { error: "network" })
      )
    )
    expect(errors.at(-1)).toBe(
      "This browser's speech recognition service is unavailable. Retry or try Chrome."
    )
  })

  test("changing the language ends the current recognition session", () => {
    installRecognition()
    renderPage(<SpeechHarness />)
    const recognition = startRecognition()
    fireEvent.click(screen.getByRole("button", { name: "English" }))
    expect(recognition.aborted).toBe(true)
    fireEvent.click(screen.getByRole("button", { name: "Start voice input" }))
    expect(FakeSpeechRecognition.current.lang).toBe("en-US")
  })

  test("handles synchronous microphone rejection without leaving capture active", () => {
    installRecognition()
    FakeSpeechRecognition.startError = new DOMException(
      "denied",
      "NotAllowedError"
    )
    renderPage(<SpeechHarness />)
    startRecognition()
    expect(errors).toEqual(["请允许麦克风权限后重试。"])
    expect(FakeSpeechRecognition.current.aborted).toBe(true)
    expect(screen.getByRole("button", { name: "开始语音输入" })).toBeTruthy()
  })

  test("disables the control when the browser has no speech recognition", () => {
    renderPage(<SpeechHarness />)
    const button = screen.getByRole("button", {
      name: "开始语音输入",
    }) as HTMLButtonElement
    expect(button.disabled).toBe(true)
    expect(button.title).toBe("当前浏览器不支持语音转文字")
  })
})
