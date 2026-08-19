import { PublicApplicationChat } from "@/components/apps/public-application-chat"

type PublicAgentChatPageProps = {
  params: Promise<{ id: string }>
  searchParams: Promise<{ conversation_id?: string | string[] }>
}

/**
 * Renders the public application chat page for an application.
 *
 * @returns The chat interface with the initial conversation selected when provided.
 */
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
