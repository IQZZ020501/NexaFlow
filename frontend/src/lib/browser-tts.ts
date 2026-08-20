import type { Language } from "@/i18n"

const speechLocales: Record<Language, string> = {
  "zh-Hans": "zh-CN",
  "zh-Hant": "zh-TW",
  en: "en-US",
}

/**
 * Converts workflow outputs into text suitable for speech.
 *
 * @param outputs - The workflow output values, preferring `result` and then `text`
 * @returns The selected string value, or a JSON representation of the selected value or full outputs
 */
export function workflowSpeechText(outputs: Record<string, unknown>) {
  const preferred = outputs.result ?? outputs.text
  return typeof preferred === "string"
    ? preferred
    : JSON.stringify(preferred ?? outputs)
}

/**
 * Speaks text using the browser's speech synthesis service.
 *
 * @param text - The text to speak
 * @param language - The language used for speech synthesis
 */
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
