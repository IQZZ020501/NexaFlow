export const AGENT_DETAIL_VIEWS = [
  "overview",
  "settings",
  "logs",
  "monitoring",
  "users",
] as const

export type AgentDetailView = (typeof AGENT_DETAIL_VIEWS)[number]

export function parseAgentDetailView(
  value: string | string[] | undefined
): AgentDetailView {
  const candidate = Array.isArray(value) ? value[0] : value
  return AGENT_DETAIL_VIEWS.includes(candidate as AgentDetailView)
    ? (candidate as AgentDetailView)
    : "overview"
}
