import type { Language } from "@/i18n"

const speechLocales: Record<Language, string> = {
  "zh-Hans": "zh-CN",
  "zh-Hant": "zh-TW",
  en: "en-US",
}

export function workflowSpeechText(outputs: Record<string, unknown>) {
  const preferred = outputs.result ?? outputs.text
  return typeof preferred === "string"
    ? preferred
    : JSON.stringify(preferred ?? outputs)
}

export function speakBrowserText(text: string, language: Language) {
  if (
    !text.trim() ||
    typeof window === "undefined" ||
    !("speechSynthesis" in window)
  ) {
    return
  }
  window.speechSynthesis.cancel()
  const utterance = new SpeechSynthesisUtterance(text)
  utterance.lang = speechLocales[language]
  window.speechSynthesis.speak(utterance)
}
