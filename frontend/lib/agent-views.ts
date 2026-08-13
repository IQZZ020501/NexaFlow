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

export function appViewPath(
  appId: string,
  appType: "agent" | "workflow",
  view: AgentDetailView,
  conversationId?: string | null
) {
  if (appType === "workflow" && view === "settings") {
    return `/workflow/${appId}`
  }
  const query = new URLSearchParams({ view })
  if (conversationId) query.set("conversation_id", conversationId)
  return `/app/apps/${appId}?${query.toString()}`
}
