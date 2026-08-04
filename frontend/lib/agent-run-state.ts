import type { AgentRun, AgentRunStreamEvent } from "@/lib/api/agents"

export function mergeAgentRunStreamEvent(
  runs: AgentRun[],
  event: AgentRunStreamEvent,
  activeRunId: string | null
) {
  if ("run" in event) {
    const index = runs.findIndex((run) => run.id === event.run.id)
    if (index === -1) return [event.run, ...runs]
    return runs.map((run) => (run.id === event.run.id ? event.run : run))
  }
  if (!activeRunId) return runs
  if (event.type === "answer_delta") {
    return runs.map((run) =>
      run.id === activeRunId
        ? { ...run, result: run.result + event.delta }
        : run
    )
  }
  return runs.map((run) => {
    if (run.id !== activeRunId) return run
    const index = run.events.findIndex((item) =>
      event.event.call_id
        ? item.type === event.event.type && item.call_id === event.event.call_id
        : item.event_id === event.event.event_id
    )
    if (index === -1) return { ...run, events: [...run.events, event.event] }
    return {
      ...run,
      events: run.events.map((item, itemIndex) =>
        itemIndex === index ? event.event : item
      ),
    }
  })
}
