import { compareLiveStreamIds } from "@/lib/api/agents"

export type AgentProcessPosition = {
  sequence?: number
  live_sequence?: string
  stream_epoch?: string
}

type ProcessState = AgentProcessPosition & {
  turn: number
  status: string
  reasoning?: string
  input?: Record<string, unknown>
}

/** A process snapshot already includes every live event through its watermark. */
export function includesAgentProcessDelta(
  current: AgentProcessPosition,
  incoming: AgentProcessPosition
) {
  return Boolean(
    current.live_sequence &&
    incoming.live_sequence &&
    compareLiveStreamIds(incoming.live_sequence, current.live_sequence) <= 0
  )
}

export function mergeAgentProcessEvent<T extends ProcessState>(
  current: T,
  incoming: T
): T {
  if (
    typeof current.sequence === "number" &&
    typeof incoming.sequence === "number" &&
    incoming.sequence <= current.sequence
  ) {
    return current
  }
  // Legacy snapshots have no version. Never let their old start event reopen a
  // completed step; new versioned events can still describe a worker takeover.
  if (
    (incoming.sequence === undefined || current.sequence === undefined) &&
    current.status !== "running" &&
    incoming.status === "running"
  ) {
    return current
  }
  if (
    current.stream_epoch === incoming.stream_epoch &&
    current.live_sequence &&
    incoming.live_sequence &&
    compareLiveStreamIds(incoming.live_sequence, current.live_sequence) < 0
  ) {
    return {
      ...incoming,
      reasoning: current.reasoning,
      input: { ...incoming.input, ...current.input },
      live_sequence: current.live_sequence,
    }
  }
  if (!incoming.live_sequence && current.live_sequence) {
    return {
      ...incoming,
      reasoning: current.reasoning?.startsWith(incoming.reasoning ?? "")
        ? current.reasoning
        : incoming.reasoning,
      live_sequence: current.live_sequence,
      stream_epoch: current.stream_epoch,
    }
  }
  return incoming
}

/** Reconnect snapshots may omit a step whose live text is already on screen. */
export function mergeAgentProcessSnapshot<T extends ProcessState>(
  current: T[],
  incoming: T[],
  key: (event: T) => string
): T[] {
  const previous = new Map(current.map((event) => [key(event), event]))
  const merged = incoming.map((event) => {
    const existing = previous.get(key(event))
    previous.delete(key(event))
    return existing ? mergeAgentProcessEvent(existing, event) : event
  })
  return [...merged, ...previous.values()].sort(
    (left, right) => left.turn - right.turn
  )
}
