import { redirect } from "next/navigation"

import { AgentsPage } from "@/components/agents/agents-page"
import { appViewPath, parseAgentDetailView } from "@/lib/agent-views"

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
