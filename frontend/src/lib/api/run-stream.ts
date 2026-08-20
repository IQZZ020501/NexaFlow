export type NdjsonCursorEvent = {
  type: string
  sequence?: number
  live_sequence?: string
}

type StreamResponseFactory = (
  cursor: number,
  liveCursor: string,
  signal?: AbortSignal
) => Promise<Response>

type ObserveNdjsonStreamOptions = {
  signal?: AbortSignal
  after?: number
  liveAfter?: string
  errorLabel: string
  isTerminal?: (event: NdjsonCursorEvent) => boolean
}

const INITIAL_RECONNECT_DELAY_MS = 250
const MAX_RECONNECT_DELAY_MS = 5_000

/**
 * Waits for the reconnect delay, allowing the wait to be cancelled.
 *
 * @param delayMs - The delay in milliseconds.
 * @param signal - An optional signal that cancels the wait and rejects with its abort reason.
 */
function waitForReconnect(delayMs: number, signal?: AbortSignal) {
  return new Promise<void>((resolve, reject) => {
    if (signal?.aborted) {
      reject(signal.reason ?? new DOMException("Aborted", "AbortError"))
      return
    }
    const onAbort = () => {
      clearTimeout(timeout)
      reject(signal?.reason ?? new DOMException("Aborted", "AbortError"))
    }
    const timeout = setTimeout(() => {
      signal?.removeEventListener("abort", onAbort)
      resolve()
    }, delayMs)
    signal?.addEventListener("abort", onAbort, { once: true })
  })
}

/**
 * Consumes an NDJSON response stream and processes each parsed event.
 *
 * @param cursor - The initial numeric cursor used to track stream progress
 * @param liveCursor - The initial live cursor used to track stream progress
 * @param isTerminal - Determines whether an event marks the end of observation
 * @returns The latest numeric and live cursors and whether a terminal event was received
 * @throws Error If the response has no body
 */
async function consumeNdjsonStream<TEvent extends NdjsonCursorEvent>(
  response: Response,
  onEvent: (event: TEvent) => void,
  cursor: number,
  liveCursor: string,
  isTerminal: (event: TEvent) => boolean
) {
  if (!response.body) {
    throw new Error("Stream did not return a response body.")
  }
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ""
  let terminal = false

  const consumeLine = (line: string, tolerateIncomplete = false) => {
    if (!line.trim()) return
    let event: TEvent
    try {
      event = JSON.parse(line) as TEvent
    } catch (error) {
      if (tolerateIncomplete) return
      throw error
    }
    if (typeof event.sequence === "number") {
      cursor = Math.max(cursor, event.sequence)
    }
    if (typeof event.live_sequence === "string") {
      liveCursor = event.live_sequence
    }
    terminal = terminal || isTerminal(event)
    onEvent(event)
  }

  while (true) {
    const { done, value } = await reader.read()
    buffer += decoder.decode(value, { stream: !done })
    const lines = buffer.split("\n")
    buffer = lines.pop() ?? ""
    lines.forEach((line) => consumeLine(line))
    if (done) break
  }
  consumeLine(buffer, true)
  return { cursor, liveCursor, terminal }
}

/**
 * Observes an NDJSON stream until a terminal event is received or observation is aborted.
 *
 * Reconnects after caught stream-processing failures other than non-retryable HTTP responses,
 * resuming from the latest event cursors and increasing the delay between attempts up to five seconds.
 *
 * @param getResponse - Creates a stream response using the current numeric and live cursors.
 * @param onEvent - Handles each event received from the stream.
 * @throws An error for non-retryable HTTP responses or the abort reason when observation is aborted.
 */
export async function observeNdjsonStream<TEvent extends NdjsonCursorEvent>(
  getResponse: StreamResponseFactory,
  onEvent: (event: TEvent) => void,
  {
    signal,
    after = 0,
    liveAfter = "0-0",
    errorLabel,
    isTerminal = (event) => event.type === "complete" || event.type === "error",
  }: ObserveNdjsonStreamOptions
) {
  let cursor = after
  let liveCursor = liveAfter
  let reconnectDelayMs = INITIAL_RECONNECT_DELAY_MS

  while (!signal?.aborted) {
    try {
      const response = await getResponse(cursor, liveCursor, signal)
      if (!response.ok) {
        if (response.status < 500 && response.status !== 429) {
          throw new Error(
            `${errorLabel} failed with status ${response.status}.`
          )
        }
        await waitForReconnect(reconnectDelayMs, signal)
        reconnectDelayMs = Math.min(
          reconnectDelayMs * 2,
          MAX_RECONNECT_DELAY_MS
        )
        continue
      }
      const consumed = await consumeNdjsonStream(
        response,
        onEvent,
        cursor,
        liveCursor,
        isTerminal as (event: TEvent) => boolean
      )
      if (
        consumed.cursor !== cursor ||
        consumed.liveCursor !== liveCursor ||
        consumed.terminal
      ) {
        reconnectDelayMs = INITIAL_RECONNECT_DELAY_MS
      }
      cursor = consumed.cursor
      liveCursor = consumed.liveCursor
      if (consumed.terminal) return
    } catch (error) {
      if (signal?.aborted) throw signal.reason ?? error
      if (
        error instanceof Error &&
        error.message.startsWith(`${errorLabel} failed with status`)
      ) {
        throw error
      }
    }
    await waitForReconnect(reconnectDelayMs, signal)
    reconnectDelayMs = Math.min(reconnectDelayMs * 2, MAX_RECONNECT_DELAY_MS)
  }
}
