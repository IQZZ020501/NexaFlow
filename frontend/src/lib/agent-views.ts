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
    return `/workflow/${encodeURIComponent(appId)}`
  }
  const basePath = `/app/apps/${encodeURIComponent(appId)}`
  const path = view === "overview" ? basePath : `${basePath}/${view}`
  if (!conversationId) return path
  return `${path}?${new URLSearchParams({ conversation_id: conversationId })}`
}
