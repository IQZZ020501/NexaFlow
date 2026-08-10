import { AgentsPage } from "@/components/agents/agents-page"

type AgentDetailPageProps = {
  searchParams: Promise<{ conversation_id?: string | string[] }>
}

export default async function AgentDetailPage({
  searchParams,
}: AgentDetailPageProps) {
  const params = await searchParams
  const value = params.conversation_id
  const conversationId = Array.isArray(value) ? value[0] ?? null : value ?? null
  return <AgentsPage initialConversationId={conversationId} />
}
