"use client"

import * as React from "react"
import { useRouter } from "next/navigation"
import { LoaderCircleIcon, RotateCcwIcon } from "lucide-react"

import { PublicAgentChat } from "@/components/agents/public-agent-chat"
import { PublicWorkflowChat } from "@/components/workflows/public-workflow-chat"
import { Button } from "@/components/ui/button"
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
    "agent" | "workflow" | "missing" | "error" | null
  >(null)
  const [attempt, setAttempt] = React.useState(0)

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
      .catch((error: unknown) => {
        if (!active) return
        setKind(error instanceof ApiError && error.status === 404 ? "missing" : "error")
      })
    return () => {
      active = false
    }
  }, [applicationId, attempt, token])

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
        t("未发布")
      ) : kind === "error" ? (
        <span className="flex flex-col items-center gap-3">
          {t("应用加载失败")}
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => {
              setKind(null)
              setAttempt((current) => current + 1)
            }}
          >
            <RotateCcwIcon />
            {t("重试")}
          </Button>
        </span>
      ) : (
        <>
          <LoaderCircleIcon className="mr-2 size-4 animate-spin" />
          {t("正在加载")}
        </>
      )}
    </main>
  )
}
