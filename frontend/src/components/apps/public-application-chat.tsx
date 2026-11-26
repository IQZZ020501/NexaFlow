"use client"

import * as React from "react"
import { useRouter } from "next/navigation"
import { LoaderCircleIcon, RotateCcwIcon } from "lucide-react"

import { PublicAgentChat } from "@/components/agents/public-agent-chat"
import { OperationNotification } from "@/components/app/operation-notification"
import { PublicWorkflowChat } from "@/components/workflows/public-workflow-chat"
import { Button } from "@/components/ui/button"
import { useLanguage } from "@/contexts/language-provider"
import { useSession } from "@/contexts/session-context"
import { ApiError } from "@/lib/api-client"
import {
  getPublicAgentProfile,
  type PublicAgentProfile,
} from "@/lib/api/public-agents"
import { getPublicWorkflowProfile } from "@/lib/api/public-workflows"
import { publicChatUrl } from "@/lib/api/public-chat-projects"

/**
 * Loads and renders the public chat for an agent or workflow application.
 *
 * @param applicationId - The application identifier
 * @param initialConversationId - The conversation to open initially, if provided
 */
export function PublicApplicationChat({
  applicationId,
  initialConversationId,
  initialProjectId = null,
}: {
  applicationId: string
  initialConversationId: string | null
  initialProjectId?: string | null
}) {
  const router = useRouter()
  const { t } = useLanguage()
  const { token, isSessionRestored, notification, dismissNotification } =
    useSession()
  const requestKey = `${applicationId}:${initialProjectId ?? ""}`
  const [attempt, setAttempt] = React.useState(0)
  const [resolution, setResolution] = React.useState<{
    key: string
    kind: "agent" | "workflow" | "missing" | "error"
    profile: PublicAgentProfile | null
  } | null>(null)
  const resolved = resolution?.key === `${requestKey}:${attempt}` ? resolution : null
  const kind = resolved?.kind ?? null
  const agentProfile = resolved?.profile ?? null
  const resolvedKeyRef = React.useRef<string | null>(null)

  React.useEffect(() => {
    if (!isSessionRestored || token) return
    const next = publicChatUrl(
      applicationId,
      initialConversationId,
      initialProjectId
    )
    router.replace(`/login?next=${encodeURIComponent(next)}`)
  }, [
    applicationId,
    initialConversationId,
    initialProjectId,
    isSessionRestored,
    router,
    token,
  ])

  React.useEffect(() => {
    if (!token) return
    const activeKey = `${requestKey}:${attempt}`
    if (resolvedKeyRef.current === activeKey) return
    let active = true
    getPublicAgentProfile(applicationId, token)
      .then((nextProfile) => {
        if (!active) return
        resolvedKeyRef.current = activeKey
        setResolution({ key: activeKey, kind: "agent", profile: nextProfile })
      })
      .catch((error: unknown) => {
        if (!(error instanceof ApiError) || error.status !== 404) throw error
        if (initialProjectId) throw error
        return getPublicWorkflowProfile(applicationId, token).then(() => {
          if (!active) return
          resolvedKeyRef.current = activeKey
          setResolution({ key: activeKey, kind: "workflow", profile: null })
        })
      })
      .catch((error: unknown) => {
        if (!active) return
        setResolution({
          key: activeKey,
          kind: error instanceof ApiError && error.status === 404 ? "missing" : "error",
          profile: null,
        })
      })
    return () => {
      active = false
    }
  }, [applicationId, attempt, initialProjectId, requestKey, token])

  if (kind === "agent") {
    return (
      <>
        <PublicAgentChat
          key={applicationId}
          agentId={applicationId}
          initialConversationId={initialConversationId}
          initialProjectId={initialProjectId}
          initialProfile={agentProfile}
        />
        <OperationNotification
          notification={notification}
          onDismiss={dismissNotification}
        />
      </>
    )
  }
  if (kind === "workflow") {
    return (
      <>
        <PublicWorkflowChat
          workflowId={applicationId}
          initialConversationId={initialConversationId}
        />
        <OperationNotification
          notification={notification}
          onDismiss={dismissNotification}
        />
      </>
    )
  }
  return (
    <main className="flex min-h-dvh items-center justify-center p-6 text-sm text-muted-foreground">
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
              resolvedKeyRef.current = null
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
