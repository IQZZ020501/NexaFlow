/**
 * Batches high-frequency streaming events (such as token deltas and reasoning
 * chunks) into at most one state flush per animation frame while ensuring
 * structural/lifecycle events flush pending chunks immediately in order.
 */
export type StreamEventBatcher<E> = {
  push: (event: E) => void
  flushNow: () => void
  cancel: () => void
}

export function createStreamEventBatcher<E>(
  isBatchable: (event: E) => boolean,
  onFlush: (events: E[]) => void
): StreamEventBatcher<E> {
  let queue: E[] = []
  let rafId: number | null = null
  let microtaskPending = false

  function cancelScheduled() {
    if (
      rafId !== null &&
      typeof cancelAnimationFrame === "function"
    ) {
      cancelAnimationFrame(rafId)
    }
    rafId = null
    microtaskPending = false
  }

  function flushNow() {
    cancelScheduled()
    if (queue.length === 0) return
    const batch = queue
    queue = []
    onFlush(batch)
  }

  function scheduleFlush() {
    if (rafId !== null || microtaskPending) return
    if (typeof requestAnimationFrame === "function") {
      rafId = requestAnimationFrame(() => {
        rafId = null
        flushNow()
      })
      return
    }
    microtaskPending = true
    queueMicrotask(() => {
      if (!microtaskPending) return
      flushNow()
    })
  }

  return {
    push(event: E) {
      if (isBatchable(event)) {
        queue.push(event)
        scheduleFlush()
        return
      }
      flushNow()
      onFlush([event])
    },
    flushNow,
    cancel() {
      cancelScheduled()
      queue = []
    },
  }
}
