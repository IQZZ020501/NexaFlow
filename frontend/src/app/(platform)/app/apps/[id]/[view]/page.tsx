import { redirect } from "next/navigation"

import { AgentsPage } from "@/components/agents/agents-page"
import { appViewPath, parseAgentDetailView } from "@/lib/agent-views"

/**
 * Renders an agent detail view or redirects overview requests to the canonical app path.
 *
 * @param params - The agent identifier and requested detail view.
 * @param searchParams - Optional conversation identifier from the query string.
 */
export default async function AgentDetailViewPage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string; view: string }>
  searchParams: Promise<{ conversation_id?: string | string[] }>
}) {
  const [{ id, view }, query] = await Promise.all([params, searchParams])
  const initialView = parseAgentDetailView(view)
  const value = query.conversation_id
  const conversationId = Array.isArray(value) ? (value[0] ?? null) : (value ?? null)

  if (initialView === "overview") {
    redirect(appViewPath(id, "agent", "overview", conversationId))
  }

  return (
    <AgentsPage
      initialConversationId={conversationId}
      initialView={initialView}
    />
  )
}
