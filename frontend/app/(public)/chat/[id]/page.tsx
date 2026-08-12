import { PublicApplicationChat } from "@/components/apps/public-application-chat"

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
  return (
    <PublicApplicationChat
      applicationId={id}
      initialConversationId={conversationId}
    />
  )
}
