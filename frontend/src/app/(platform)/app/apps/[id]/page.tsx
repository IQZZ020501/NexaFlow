import { AgentsPage } from "@/components/agents/agents-page"
import { parseAgentDetailView } from "@/lib/agent-views"

type AgentDetailPageProps = {
  searchParams: Promise<{
    conversation_id?: string | string[]
    view?: string | string[]
  }>
}

/**
 * Renders the agent detail page for the requested conversation and view.
 *
 * @param searchParams - Query parameters containing the conversation ID and optional view.
 * @returns The agent page configured with the requested conversation and detail view.
 */
export default async function AgentDetailPage({
  searchParams,
}: AgentDetailPageProps) {
  const params = await searchParams
  const value = params.conversation_id
  const conversationId = Array.isArray(value)
    ? (value[0] ?? null)
    : (value ?? null)
  return (
    <AgentsPage
      hasLegacyView={params.view !== undefined}
      initialConversationId={conversationId}
      initialView={parseAgentDetailView(params.view)}
    />
  )
}
