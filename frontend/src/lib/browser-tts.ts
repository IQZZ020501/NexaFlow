import type { Language } from "@/i18n"

const speechLocales: Record<Language, string> = {
  "zh-Hans": "zh-CN",
  "zh-Hant": "zh-TW",
  en: "en-US",
}

/**
 * Converts workflow outputs into text suitable for speech.
 *
 * @param outputs - The workflow output values, preferring `answer`, `result`, and then `text`
 * @returns The selected answer text, or a JSON representation of the selected value or full outputs
 */
export function workflowSpeechText(outputs: Record<string, unknown>) {
  const preferred = [outputs.answer, outputs.result, outputs.text].find(
    (value) => value !== undefined && value !== null && value !== ""
  )
  if (typeof preferred === "string") {
    try {
      const parsed = JSON.parse(preferred)
      if (
        parsed &&
        typeof parsed === "object" &&
        !Array.isArray(parsed) &&
        typeof parsed.answer === "string"
      ) {
        return parsed.answer
      }
    } catch {
      // Preserve ordinary text that is not a JSON envelope.
    }
    return preferred
  }
  if (
    preferred &&
    typeof preferred === "object" &&
    !Array.isArray(preferred) &&
    typeof (preferred as { answer?: unknown }).answer === "string"
  ) {
    return (preferred as { answer: string }).answer
  }
  return JSON.stringify(preferred ?? outputs)
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
