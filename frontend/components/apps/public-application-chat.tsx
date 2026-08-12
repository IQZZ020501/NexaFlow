"use client"

import * as React from "react"
import { useRouter } from "next/navigation"
import { LoaderCircleIcon } from "lucide-react"

import { PublicAgentChat } from "@/components/agents/public-agent-chat"
import { PublicWorkflowChat } from "@/components/workflows/public-workflow-chat"
import { useLanguage } from "@/contexts/language-provider"
import { useSession } from "@/contexts/session-context"
import { ApiError } from "@/lib/api-client"
import { getPublicAgentProfile } from "@/lib/api/public-agents"
import { getPublicWorkflowProfile } from "@/lib/api/public-workflows"

export function PublicApplicationChat({
  applicationId,
  initialConversationId,
}: {
  applicationId: string
  initialConversationId: string | null
}) {
  const router = useRouter()
  const { t } = useLanguage()
  const { token, isSessionRestored } = useSession()
  const [kind, setKind] = React.useState<
    "agent" | "workflow" | "missing" | null
  >(null)

  React.useEffect(() => {
    if (!isSessionRestored || token) return
    const next = initialConversationId
      ? `/chat/${applicationId}?conversation_id=${encodeURIComponent(initialConversationId)}`
      : `/chat/${applicationId}`
    router.replace(`/login?next=${encodeURIComponent(next)}`)
  }, [applicationId, initialConversationId, isSessionRestored, router, token])

  React.useEffect(() => {
    if (!token) return
    let active = true
    getPublicAgentProfile(applicationId, token)
      .then(() => active && setKind("agent"))
      .catch((error: unknown) => {
        if (!(error instanceof ApiError) || error.status !== 404) throw error
        return getPublicWorkflowProfile(applicationId, token).then(
          () => active && setKind("workflow")
        )
      })
      .catch(() => active && setKind("missing"))
    return () => {
      active = false
    }
  }, [applicationId, token])

  if (kind === "agent") {
    return (
      <PublicAgentChat
        agentId={applicationId}
        initialConversationId={initialConversationId}
      />
    )
  }
  if (kind === "workflow") {
    return (
      <PublicWorkflowChat
        workflowId={applicationId}
        initialConversationId={initialConversationId}
      />
    )
  }
  return (
    <main className="flex min-h-svh items-center justify-center p-6 text-sm text-muted-foreground">
      {kind === "missing" ? (
        t("此应用未发布或不可访问。")
      ) : (
        <>
          <LoaderCircleIcon className="mr-2 size-4 animate-spin" />
          {t("正在加载")}
        </>
      )}
    </main>
  )
}
