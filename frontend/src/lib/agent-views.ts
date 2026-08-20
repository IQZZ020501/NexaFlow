export const AGENT_DETAIL_VIEWS = [
  "overview",
  "settings",
  "logs",
  "monitoring",
  "users",
] as const

export type AgentDetailView = (typeof AGENT_DETAIL_VIEWS)[number]

/**
 * Parses an agent detail view value and falls back to the overview view when invalid or absent.
 *
 * @param value - The view value or an array whose first element contains the view value
 * @returns The matching agent detail view, or `"overview"` when the value is invalid or absent
 */
export function parseAgentDetailView(
  value: string | string[] | undefined
): AgentDetailView {
  const candidate = Array.isArray(value) ? value[0] : value
  return AGENT_DETAIL_VIEWS.includes(candidate as AgentDetailView)
    ? (candidate as AgentDetailView)
    : "overview"
}

/**
 * Builds the URL for an agent or workflow view.
 *
 * @param appId - The application identifier to encode in the URL
 * @param appType - The application type
 * @param view - The detail view to include in the URL
 * @param conversationId - An optional conversation identifier to append as a query parameter
 * @returns The URL for the specified application view
 */
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
