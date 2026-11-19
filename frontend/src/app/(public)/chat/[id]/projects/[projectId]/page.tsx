import { PublicApplicationChat } from "@/components/apps/public-application-chat"

export default async function PublicChatProjectPage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string; projectId: string }>
  searchParams: Promise<{ conversation_id?: string | string[] }>
}) {
  const [{ id, projectId }, query] = await Promise.all([params, searchParams])
  const conversationId = Array.isArray(query.conversation_id)
    ? query.conversation_id[0]
    : query.conversation_id
  return (
    <PublicApplicationChat
      key={`${id}:${projectId}`}
      applicationId={id}
      initialProjectId={projectId}
      initialConversationId={conversationId ?? null}
    />
  )
}
