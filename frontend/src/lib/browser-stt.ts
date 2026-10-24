export type BrowserSpeechRecognitionResult = {
  isFinal: boolean
  0: { transcript: string }
}

export type BrowserSpeechRecognitionEvent = Event & {
  resultIndex: number
  results: ArrayLike<BrowserSpeechRecognitionResult>
}

export type BrowserSpeechRecognitionErrorEvent = Event & {
  error: string
}

export type BrowserSpeechRecognition = {
  lang: string
  continuous: boolean
  interimResults: boolean
  maxAlternatives: number
  onresult: ((event: BrowserSpeechRecognitionEvent) => void) | null
  onerror: ((event: BrowserSpeechRecognitionErrorEvent) => void) | null
  onend: (() => void) | null
  start: () => void
  stop: () => void
  abort: () => void
}

export type BrowserSpeechRecognitionConstructor =
  new () => BrowserSpeechRecognition

declare global {
  interface Window {
    SpeechRecognition?: BrowserSpeechRecognitionConstructor
    webkitSpeechRecognition?: BrowserSpeechRecognitionConstructor
  }
}

/** Returns the browser speech recognition constructor when available. */
export function getBrowserSpeechRecognitionConstructor() {
  if (typeof window === "undefined") return null
  return window.SpeechRecognition ?? window.webkitSpeechRecognition ?? null
}
