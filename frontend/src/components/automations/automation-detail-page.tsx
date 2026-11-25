"use client"

import * as React from "react"
import { useParams, useRouter, useSearchParams } from "next/navigation"

import { useConfirmDialog } from "@/components/app/confirm-dialog"
import { TopLoadingBar } from "@/components/app/top-progress"
import {
  isAutomationExecutionActive,
  isExecutionNeedsAction,
  WebhookSecretDialog,
  type WebhookSecretDisclosure,
} from "@/components/automations/automation-badges"
import { AutomationConfigPanel } from "@/components/automations/automation-config-panel"
import {
  AutomationDetailHeader,
  type AutomationDetailTab,
} from "@/components/automations/automation-detail-header"
import { AutomationExecutionInspector } from "@/components/automations/automation-execution-inspector"
import { AutomationExecutionList } from "@/components/automations/automation-execution-list"
import { AutomationFormDialog } from "@/components/automations/automation-form-dialog"
import { type SystemPageSize } from "@/components/system/pagination-footer"
import { useLanguage } from "@/contexts/language-provider"
import { useOptionalMessageCenter } from "@/contexts/message-center-context"
import { useSession } from "@/contexts/session-context"
import { languageLocales } from "@/i18n"
import { apiUrl } from "@/lib/api-client"
import {
  approveAutomationToolCall,
  cancelAutomationExecution,
  executeAutomationNow,
  getAutomation,
  getAutomationExecution,
  listAutomationExecutions,
  pauseAutomation,
  resumeAutomation,
  rotateAutomationWebhookSecret,
  submitAutomationWorkflowForm,
  type Automation,
  type AutomationArtifactLink,
  type AutomationExecutionDetail,
  type AutomationExecutionSummary,
} from "@/lib/api/automations"
import { getErrorMessage } from "@/lib/errors"

export function AutomationDetailPage(props: {
  automationId?: string
  initialExecutionId?: string | null
}) {
  const { selectedWorkspaceId } = useSession()
  const params = useParams<{ id?: string }>()
  return (
    <AutomationDetailContent
      key={`${selectedWorkspaceId}:${props.automationId ?? params?.id}`}
      {...props}
    />
  )
}

function AutomationDetailContent({
  automationId: propAutomationId,
  initialExecutionId,
}: {
  automationId?: string
  initialExecutionId?: string | null
}) {
  const params = useParams<{ id?: string }>()
  const router = useRouter()
  const searchParams = useSearchParams()
  const { token, selectedWorkspaceId, notify } = useSession()
  const { language, t } = useLanguage()
  const messageCenter = useOptionalMessageCenter()
  const [confirm, confirmDialog] = useConfirmDialog()
  const locale = languageLocales[language]

  const automationId = propAutomationId ?? params?.id ?? ""
  const urlExecutionId =
    searchParams.get("execution") ?? initialExecutionId ?? null

  const [activeTab, setActiveTab] = React.useState<AutomationDetailTab>(
    searchParams.get("tab") === "config" ? "config" : "executions"
  )
  const [page, setPage] = React.useState(1)
  const [pageSize, setPageSize] = React.useState<SystemPageSize>(50)
  const [total, setTotal] = React.useState(0)
  const executeKey = React.useRef<string | null>(null)
  const [automation, setAutomation] = React.useState<Automation | null>(null)
  const [executions, setExecutions] = React.useState<
    AutomationExecutionSummary[]
  >([])
  const [pickedExecution, setPickedExecution] = React.useState<{
    forUrl: string | null
    id: string
  } | null>(null)
  const [executionDetail, setExecutionDetail] =
    React.useState<AutomationExecutionDetail | null>(null)

  const selectedExecutionId =
    (pickedExecution?.forUrl === urlExecutionId ? pickedExecution.id : null) ??
    urlExecutionId ??
    executions[0]?.id ??
    null
  const visibleExecutionDetail =
    selectedExecutionId && executionDetail?.id === selectedExecutionId
      ? executionDetail
      : null

  const [isLoading, setIsLoading] = React.useState(true)
  const [isLoadingDetail, setIsLoadingDetail] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)
  const [isActionBusy, setIsActionBusy] = React.useState(false)
  const [resolvingCallId, setResolvingCallId] = React.useState<string | null>(
    null
  )
  const [isSubmittingForm, setIsSubmittingForm] = React.useState(false)
  const [downloadingArtifactId, setDownloadingArtifactId] = React.useState<
    string | null
  >(null)

  const [editOpen, setEditOpen] = React.useState(false)
  const [secretDisclosure, setSecretDisclosure] =
    React.useState<WebhookSecretDisclosure | null>(null)

  const loadHeaderAndExecutions = React.useCallback(async () => {
    if (!token || !selectedWorkspaceId || !automationId) {
      setIsLoading(false)
      return
    }
    setError(null)
    try {
      const [autoData, listData] = await Promise.all([
        getAutomation(token, selectedWorkspaceId, automationId),
        listAutomationExecutions(token, selectedWorkspaceId, automationId, {
          limit: pageSize,
          offset: (page - 1) * pageSize,
        }),
      ])
      setAutomation(autoData)
      setExecutions(listData.items)
      setTotal(listData.total)
    } catch (nextError) {
      setError(getErrorMessage(nextError, t))
    } finally {
      setIsLoading(false)
    }
  }, [automationId, selectedWorkspaceId, t, token, page, pageSize])

  const loadExecutionDetail = React.useCallback(
    async (executionId: string) => {
      if (!token || !selectedWorkspaceId || !automationId) return
      setIsLoadingDetail(true)
      try {
        const detail = await getAutomationExecution(
          token,
          selectedWorkspaceId,
          automationId,
          executionId
        )
        setExecutionDetail(detail)
      } catch (nextError) {
        setError(getErrorMessage(nextError, t))
      } finally {
        setIsLoadingDetail(false)
      }
    },
    [automationId, selectedWorkspaceId, t, token]
  )

  React.useEffect(() => {
    const timer = window.setTimeout(() => {
      void loadHeaderAndExecutions()
    }, 0)
    return () => window.clearTimeout(timer)
  }, [loadHeaderAndExecutions, messageCenter?.refreshVersion])

  React.useEffect(() => {
    if (!selectedExecutionId) {
      return
    }
    const timer = window.setTimeout(() => {
      void loadExecutionDetail(selectedExecutionId)
    }, 0)
    return () => window.clearTimeout(timer)
  }, [loadExecutionDetail, messageCenter?.refreshVersion, selectedExecutionId])

  const shouldPoll = Boolean(
    (visibleExecutionDetail &&
      isAutomationExecutionActive(
        visibleExecutionDetail.dispatch_status,
        visibleExecutionDetail.run_status
      )) ||
    executions.some((item) =>
      isAutomationExecutionActive(item.dispatch_status, item.run_status)
    )
  )

  React.useEffect(() => {
    if (!shouldPoll) return
    const timer = setInterval(() => {
      void loadHeaderAndExecutions()
      if (selectedExecutionId) {
        void loadExecutionDetail(selectedExecutionId)
      }
    }, 4000)
    return () => clearInterval(timer)
  }, [
    loadExecutionDetail,
    loadHeaderAndExecutions,
    selectedExecutionId,
    shouldPoll,
  ])

  function selectExecution(executionId: string) {
    setPickedExecution({ forUrl: urlExecutionId, id: executionId })
    router.replace(`/app/automations/${automationId}?execution=${executionId}`)
  }

  async function handlePauseResume() {
    if (!token || !selectedWorkspaceId || !automation || isActionBusy) return
    setIsActionBusy(true)
    try {
      const updated =
        automation.status === "paused"
          ? await resumeAutomation(token, selectedWorkspaceId, automation.id)
          : await pauseAutomation(token, selectedWorkspaceId, automation.id)
      setAutomation(updated)
      notify(
        "success",
        t(automation.status === "paused" ? "自动化已恢复" : "自动化已暂停")
      )
    } catch (nextError) {
      notify("error", getErrorMessage(nextError, t))
    } finally {
      setIsActionBusy(false)
    }
  }

  async function handleExecuteNow() {
    if (!token || !selectedWorkspaceId || !automation || isActionBusy) return
    setIsActionBusy(true)
    try {
      const created = await executeAutomationNow(
        token,
        selectedWorkspaceId,
        automation.id,
        (executeKey.current ??= crypto.randomUUID())
      )
      executeKey.current = null
      setExecutionDetail(created)
      setPickedExecution({ forUrl: urlExecutionId, id: created.id })
      setActiveTab("executions")
      router.replace(
        `/app/automations/${automation.id}?execution=${created.id}`
      )
      notify("success", t("已触发立即执行"))
      void loadHeaderAndExecutions()
    } catch (nextError) {
      notify("error", getErrorMessage(nextError, t))
    } finally {
      setIsActionBusy(false)
    }
  }

  async function handleRotateSecret() {
    if (!token || !selectedWorkspaceId || !automation || isActionBusy) return
    const ok = await confirm({
      title: t("轮换密钥"),
      description: t("Webhook 密钥仅展示一次，请妥善保存。"),
      confirmLabel: t("确认"),
    })
    if (!ok) return
    setIsActionBusy(true)
    try {
      const rotated = await rotateAutomationWebhookSecret(
        token,
        selectedWorkspaceId,
        automation.id
      )
      setSecretDisclosure({
        name: automation.name,
        webhookUrl: rotated.webhook_url,
        secret: rotated.webhook_secret,
      })
      notify("success", t("Webhook密钥已轮换"))
      void loadHeaderAndExecutions()
    } catch (nextError) {
      notify("error", getErrorMessage(nextError, t))
    } finally {
      setIsActionBusy(false)
    }
  }

  async function handleCancelExecution() {
    if (
      !token ||
      !selectedWorkspaceId ||
      !automation ||
      !visibleExecutionDetail ||
      isActionBusy
    ) {
      return
    }
    setIsActionBusy(true)
    try {
      const updated = await cancelAutomationExecution(
        token,
        selectedWorkspaceId,
        automation.id,
        visibleExecutionDetail.id
      )
      setExecutionDetail(updated)
      notify("success", t("已取消本次运行"))
      void loadHeaderAndExecutions()
    } catch (nextError) {
      notify("error", getErrorMessage(nextError, t))
    } finally {
      setIsActionBusy(false)
    }
  }

  async function handleToolApproval(
    callId: string,
    decision: "approve" | "reject"
  ) {
    if (
      !token ||
      !selectedWorkspaceId ||
      !automation ||
      !visibleExecutionDetail ||
      !visibleExecutionDetail.run_id
    ) {
      return
    }
    setResolvingCallId(`${visibleExecutionDetail.run_id}:${callId}`)
    try {
      const updated = await approveAutomationToolCall(
        token,
        selectedWorkspaceId,
        automation.id,
        visibleExecutionDetail.id,
        callId,
        decision === "approve"
      )
      setExecutionDetail(updated)
      notify("success", t(decision === "approve" ? "批准执行" : "拒绝执行"))
      void loadHeaderAndExecutions()
    } catch (nextError) {
      notify("error", getErrorMessage(nextError, t))
    } finally {
      setResolvingCallId(null)
    }
  }

  async function handleWorkflowFormSubmit(data: Record<string, unknown>) {
    if (
      !token ||
      !selectedWorkspaceId ||
      !automation ||
      !visibleExecutionDetail?.workflow_run?.pending_form
    ) {
      return
    }
    setIsSubmittingForm(true)
    try {
      const updated = await submitAutomationWorkflowForm(
        token,
        selectedWorkspaceId,
        automation.id,
        visibleExecutionDetail.id,
        {
          runtime_node_id:
            visibleExecutionDetail.workflow_run.pending_form.runtime_node_id,
          data,
        }
      )
      setExecutionDetail(updated)
      notify("success", t("提交表单继续"))
      void loadHeaderAndExecutions()
    } catch (nextError) {
      notify("error", getErrorMessage(nextError, t))
    } finally {
      setIsSubmittingForm(false)
    }
  }

  async function handleDownloadArtifact(artifact: AutomationArtifactLink) {
    if (!token || downloadingArtifactId) return
    setDownloadingArtifactId(artifact.artifact_id)
    try {
      const response = await fetch(apiUrl(artifact.download_url), {
        headers: { Authorization: `Bearer ${token}` },
      })
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`)
      }
      const blob = await response.blob()
      const objectUrl = URL.createObjectURL(blob)
      const anchor = document.createElement("a")
      anchor.href = objectUrl
      anchor.download = artifact.filename
      document.body.appendChild(anchor)
      anchor.click()
      anchor.remove()
      URL.revokeObjectURL(objectUrl)
    } catch (nextError) {
      notify("error", getErrorMessage(nextError, t))
    } finally {
      setDownloadingArtifactId(null)
    }
  }

  const needsActionCount = React.useMemo(
    () =>
      executions.filter((item) =>
        isExecutionNeedsAction(item.dispatch_status, item.run_status)
      ).length,
    [executions]
  )

  return (
    <div className="flex min-h-full flex-col lg:h-[calc(100svh-3.5rem-var(--theme-page-padding)-1.5rem-1px)] lg:min-h-0">
      {isLoading || isLoadingDetail ? <TopLoadingBar /> : null}

      <div className="mx-auto flex min-h-0 w-full max-w-6xl flex-1 flex-col gap-3">
        <AutomationDetailHeader
          automation={automation}
          activeTab={activeTab}
          totalExecutions={total}
          needsActionCount={needsActionCount}
          isBusy={isActionBusy}
          onTabChange={setActiveTab}
          onRefresh={() => {
            void loadHeaderAndExecutions()
            if (selectedExecutionId) {
              void loadExecutionDetail(selectedExecutionId)
            }
          }}
          onEdit={() => setEditOpen(true)}
          onTogglePause={() => void handlePauseResume()}
          onExecuteNow={() => void handleExecuteNow()}
          onRotateSecret={() => void handleRotateSecret()}
          t={t}
        />

        {error ? (
          <div
            role="alert"
            className="shrink-0 rounded-lg border border-destructive/40 bg-destructive/5 px-4 py-3 text-sm text-destructive"
          >
            {error}
          </div>
        ) : null}

        {activeTab === "executions" ? (
          <div className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-xl border bg-card shadow-xs lg:flex-row">
            <AutomationExecutionList
              executions={executions}
              selectedExecutionId={selectedExecutionId}
              page={page}
              pageSize={pageSize}
              total={total}
              locale={locale}
              onSelectExecution={selectExecution}
              onPageChange={setPage}
              onPageSizeChange={(size) => {
                setPageSize(size)
                setPage(1)
              }}
              t={t}
            />

            <AutomationExecutionInspector
              key={visibleExecutionDetail?.id ?? "empty"}
              automationId={automationId}
              detail={visibleExecutionDetail}
              locale={locale}
              isActionBusy={isActionBusy}
              resolvingCallId={resolvingCallId}
              isSubmittingForm={isSubmittingForm}
              downloadingArtifactId={downloadingArtifactId}
              onCancelExecution={() => void handleCancelExecution()}
              onToolApproval={(callId, decision) =>
                void handleToolApproval(callId, decision)
              }
              onWorkflowFormSubmit={handleWorkflowFormSubmit}
              onDownloadArtifact={(artifact) =>
                void handleDownloadArtifact(artifact)
              }
              t={t}
            />
          </div>
        ) : (
          <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain pb-2">
            {automation ? (
              <AutomationConfigPanel
                automation={automation}
                locale={locale}
                isActionBusy={isActionBusy}
                onEdit={() => setEditOpen(true)}
                onRotateSecret={() => void handleRotateSecret()}
                t={t}
              />
            ) : null}
          </div>
        )}
      </div>

      {automation ? (
        <AutomationFormDialog
          open={editOpen}
          onOpenChange={setEditOpen}
          automation={automation}
          onSaved={() => {
            void loadHeaderAndExecutions()
          }}
        />
      ) : null}
      <WebhookSecretDialog
        disclosure={secretDisclosure}
        onClose={() => setSecretDisclosure(null)}
        t={t}
      />
      {confirmDialog}
    </div>
  )
}
