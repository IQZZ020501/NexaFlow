import { PublicAgentChat } from "@/components/agents/public-agent-chat"

type PublicAgentChatPageProps = {
  params: Promise<{ id: string }>
  searchParams: Promise<{ conversation_id?: string | string[] }>
}

export default async function PublicAgentChatPage({
  params,
  searchParams,
}: PublicAgentChatPageProps) {
  const [{ id }, query] = await Promise.all([params, searchParams])
  const value = query.conversation_id
  const conversationId = Array.isArray(value)
    ? (value[0] ?? null)
    : (value ?? null)
  return <PublicAgentChat agentId={id} initialConversationId={conversationId} />
}
