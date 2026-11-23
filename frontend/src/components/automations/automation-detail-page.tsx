"use client"

import * as React from "react"
import Link from "next/link"
import { useParams, useRouter, useSearchParams } from "next/navigation"
import {
  ArrowLeftIcon,
  DownloadIcon,
  KeyRoundIcon,
  LoaderCircleIcon,
  PauseIcon,
  PencilIcon,
  PlayIcon,
  RefreshCwIcon,
  SquareIcon,
} from "lucide-react"

import { InlineToolApproval } from "@/components/agents/inline-tool-approval"
import { useConfirmDialog } from "@/components/app/confirm-dialog"
import {
  SystemPagination,
  type SystemPageSize,
} from "@/components/system/pagination-footer"
import { TopLoadingBar } from "@/components/app/top-progress"
import {
  AutomationStatusBadge,
  DispatchStatusBadge,
  ExecutionRunStatusBadge,
  isAutomationExecutionActive,
  triggerSourceLabelKey,
  triggerTypeLabelKey,
  WebhookSecretDialog,
  type WebhookSecretDisclosure,
} from "@/components/automations/automation-badges"
import { AutomationFormDialog } from "@/components/automations/automation-form-dialog"
import { MarkdownContent } from "@/components/knowledge/markdown-content"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { CopyButton } from "@/components/ui/copy-button"
import { WorkflowRuntimeForm } from "@/components/workflows/workflow-runtime-form"
import { useLanguage } from "@/contexts/language-provider"
import { useOptionalMessageCenter } from "@/contexts/message-center-context"
import { useSession } from "@/contexts/session-context"
import { languageLocales } from "@/i18n"
import { apiUrl } from "@/lib/api-client"
import {
  automationWebhookUrl,
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
import { formatDateTime } from "@/lib/display"
import { getErrorMessage } from "@/lib/errors"
import { cn } from "@/lib/utils"

function formatFileSize(bytes: number) {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function resolveResultMarkdown(detail: AutomationExecutionDetail) {
  if (detail.agent_run?.result) {
    return detail.agent_run.result
  }
  const outputs = detail.workflow_run?.outputs
  if (outputs) {
    if (typeof outputs.result === "string" && outputs.result.trim()) {
      return outputs.result
    }
    if (typeof outputs.answer === "string" && outputs.answer.trim()) {
      return outputs.answer
    }
    if (typeof outputs.text === "string" && outputs.text.trim()) {
      return outputs.text
    }
    if (Object.keys(outputs).length > 0) {
      return `\`\`\`json\n${JSON.stringify(outputs, null, 2)}\n\`\`\``
    }
  }
  return ""
}

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

  const pendingToolCalls = React.useMemo(
    () =>
      (visibleExecutionDetail?.tool_calls ?? []).filter(
        (call) =>
          call.status === "awaiting_approval" || call.status === "uncertain"
      ),
    [visibleExecutionDetail?.tool_calls]
  )

  const startedAt =
    visibleExecutionDetail?.agent_run?.started_at ??
    visibleExecutionDetail?.workflow_run?.started_at ??
    null
  const finishedAt =
    visibleExecutionDetail?.agent_run?.finished_at ??
    visibleExecutionDetail?.workflow_run?.finished_at ??
    null
  const runErrorMessage =
    visibleExecutionDetail?.agent_run?.last_error ??
    visibleExecutionDetail?.workflow_run?.last_error ??
    null
  const resultMarkdown = visibleExecutionDetail
    ? resolveResultMarkdown(visibleExecutionDetail)
    : ""

  return (
    <div className="flex min-h-full flex-col lg:h-[calc(100svh-3.5rem-var(--theme-page-padding)-1.5rem-1px)] lg:min-h-0">
      {isLoading || isLoadingDetail ? <TopLoadingBar /> : null}
      <div className="mx-auto flex min-h-0 w-full max-w-6xl flex-1 flex-col gap-6 px-4 py-6 sm:px-6">
        <div className="flex shrink-0 flex-wrap items-center justify-between gap-3">
          <div className="min-w-0 space-y-2">
            <Button variant="ghost" size="sm" className="-ml-2" asChild>
              <Link href="/app/automations">
                <ArrowLeftIcon />
                <span>{t("返回自动化列表")}</span>
              </Link>
            </Button>
            {automation ? (
              <>
                <div className="flex flex-wrap items-center gap-2">
                  <h1 className="text-xl font-semibold tracking-tight">
                    {automation.name}
                  </h1>
                  <AutomationStatusBadge status={automation.status} t={t} />
                  <Badge variant="outline">
                    {automation.target_app_type === "workflow"
                      ? "Workflow"
                      : "Agent"}
                    : {automation.target_app_name} v
                    {automation.target_version_number}
                  </Badge>
                  <Badge variant="secondary">
                    {t(triggerTypeLabelKey(automation.trigger_type))}
                  </Badge>
                </div>
                {automation.description ? (
                  <p className="text-sm text-muted-foreground">
                    {automation.description}
                  </p>
                ) : null}
                <div className="flex flex-wrap gap-4 text-xs text-muted-foreground">
                  <span>
                    {t("下次执行时间")}:{" "}
                    {automation.next_run_at
                      ? formatDateTime(automation.next_run_at, locale)
                      : "—"}
                  </span>
                  <span>
                    {t("绑定版本")}: v{automation.target_version_number}
                  </span>
                </div>
              </>
            ) : (
              <h1 className="text-xl font-semibold tracking-tight">
                {t("自动化详情")}
              </h1>
            )}
          </div>

          {automation ? (
            <div className="flex flex-wrap items-center gap-2">
              <Button
                type="button"
                variant="outline"
                size="sm"
                disabled={isActionBusy}
                onClick={() => {
                  void loadHeaderAndExecutions()
                  if (selectedExecutionId) {
                    void loadExecutionDetail(selectedExecutionId)
                  }
                }}
              >
                <RefreshCwIcon />
                <span>{t("刷新")}</span>
              </Button>
              <Button
                type="button"
                variant="outline"
                size="sm"
                disabled={isActionBusy}
                onClick={() => setEditOpen(true)}
              >
                <PencilIcon />
                <span>{t("编辑")}</span>
              </Button>
              {automation.status !== "completed" ? (
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  disabled={isActionBusy}
                  onClick={() => void handlePauseResume()}
                >
                  {automation.status === "paused" ? (
                    <PlayIcon />
                  ) : (
                    <PauseIcon />
                  )}
                  <span>
                    {t(automation.status === "paused" ? "恢复运行" : "暂停")}
                  </span>
                </Button>
              ) : null}
              <Button
                type="button"
                size="sm"
                disabled={isActionBusy}
                onClick={() => void handleExecuteNow()}
              >
                <PlayIcon />
                <span>{t("立即执行")}</span>
              </Button>
            </div>
          ) : null}
        </div>

        {error ? (
          <div
            role="alert"
            className="shrink-0 rounded-lg border border-destructive/40 bg-destructive/5 px-4 py-3 text-sm text-destructive"
          >
            {error}
          </div>
        ) : null}

        {automation?.trigger_type === "webhook" ? (
          <Card className="shrink-0">
            <CardHeader className="flex flex-row flex-wrap items-center justify-between gap-3">
              <div>
                <CardTitle className="text-base">
                  {t("Webhook 地址与签名密钥")}
                </CardTitle>
                <CardDescription>
                  {t(
                    "请填写请求头 X-NexaFlow-Timestamp、X-NexaFlow-Event-Id 与 X-NexaFlow-Signature (HMAC-SHA256)。"
                  )}
                </CardDescription>
              </div>
              <Button
                type="button"
                variant="outline"
                size="sm"
                disabled={isActionBusy}
                onClick={() => void handleRotateSecret()}
              >
                <KeyRoundIcon />
                <span>{t("轮换密钥")}</span>
              </Button>
            </CardHeader>
            <CardContent className="grid gap-3 text-xs sm:grid-cols-2">
              {automation.webhook_url ? (
                <div className="space-y-1">
                  <p className="text-muted-foreground">{t("Webhook URL")}</p>
                  <div className="flex items-center gap-2 rounded-md border bg-muted/20 px-2.5 py-1.5 font-mono break-all">
                    <span className="min-w-0 flex-1">
                      {automationWebhookUrl(automation.webhook_url)}
                    </span>
                    <CopyButton
                      value={automationWebhookUrl(automation.webhook_url)}
                      t={t}
                    />
                  </div>
                </div>
              ) : null}
              <div className="space-y-1">
                <p className="text-muted-foreground">{t("密钥提示")}</p>
                <div className="rounded-md border bg-muted/20 px-2.5 py-2 font-mono">
                  {automation.webhook_secret_hint ?? "—"}
                </div>
              </div>
            </CardContent>
          </Card>
        ) : null}

        <div className="grid min-h-0 flex-1 gap-6 lg:grid-cols-[320px_minmax(0,1fr)] lg:grid-rows-[minmax(0,1fr)]">
          <Card className="flex min-h-0 flex-col lg:overflow-hidden">
            <CardHeader className="shrink-0">
              <CardTitle className="text-base">{t("执行历史")}</CardTitle>
            </CardHeader>
            <CardContent className="grid min-h-0 gap-2 lg:content-start lg:overflow-y-auto lg:overscroll-contain">
              {executions.length === 0 ? (
                <p className="py-6 text-center text-sm text-muted-foreground">
                  {t("暂无执行记录")}
                </p>
              ) : (
                executions.map((item) => {
                  const selected = item.id === selectedExecutionId
                  return (
                    <button
                      key={item.id}
                      type="button"
                      onClick={() => selectExecution(item.id)}
                      className={cn(
                        "grid gap-1.5 rounded-lg border p-3 text-left transition-colors hover:bg-muted/40",
                        selected && "border-primary bg-primary/5"
                      )}
                    >
                      <div className="flex items-center justify-between gap-2">
                        <Badge variant="outline">
                          {t(triggerSourceLabelKey(item.trigger_source))}
                        </Badge>
                        <ExecutionRunStatusBadge
                          runStatus={item.run_status}
                          dispatchStatus={item.dispatch_status}
                          t={t}
                        />
                      </div>
                      <p className="text-xs text-muted-foreground tabular-nums">
                        {formatDateTime(
                          item.scheduled_at ?? item.received_at,
                          locale
                        )}
                      </p>
                      {item.skip_reason ? (
                        <p className="line-clamp-2 text-[11px] text-destructive">
                          {getErrorMessage(new Error(item.skip_reason), t)}
                        </p>
                      ) : null}
                    </button>
                  )
                })
              )}
              <SystemPagination
                page={page}
                pageSize={pageSize}
                itemCount={executions.length}
                total={total}
                hasNext={page * pageSize < total}
                onPageChange={setPage}
                onPageSizeChange={(size) => {
                  setPageSize(size)
                  setPage(1)
                }}
              />
            </CardContent>
          </Card>

          <Card className="min-h-0 min-w-0 lg:overflow-y-auto lg:overscroll-contain">
            {!visibleExecutionDetail ? (
              <CardContent className="flex min-h-64 items-center justify-center text-sm text-muted-foreground">
                {t("请选择一条执行记录查看详情")}
              </CardContent>
            ) : (
              <>
                <CardHeader className="gap-3 border-b">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="flex flex-wrap items-center gap-2">
                      <DispatchStatusBadge
                        status={visibleExecutionDetail.dispatch_status}
                        t={t}
                      />
                      <ExecutionRunStatusBadge
                        runStatus={visibleExecutionDetail.run_status}
                        dispatchStatus={visibleExecutionDetail.dispatch_status}
                        t={t}
                      />
                      <Badge variant="outline">
                        {t(
                          triggerSourceLabelKey(
                            visibleExecutionDetail.trigger_source
                          )
                        )}
                      </Badge>
                    </div>
                    {isAutomationExecutionActive(
                      visibleExecutionDetail.dispatch_status,
                      visibleExecutionDetail.run_status
                    ) ? (
                      <Button
                        type="button"
                        variant="destructive"
                        size="xs"
                        disabled={isActionBusy}
                        onClick={() => void handleCancelExecution()}
                      >
                        <SquareIcon />
                        <span>{t("取消运行")}</span>
                      </Button>
                    ) : null}
                  </div>
                  {visibleExecutionDetail.run_id ? (
                    <p className="font-mono text-xs text-muted-foreground">
                      Run ID: {visibleExecutionDetail.run_id}
                    </p>
                  ) : null}
                </CardHeader>

                <CardContent className="grid gap-5 pt-5">
                  {visibleExecutionDetail.missed_count_before > 0 ? (
                    <div className="rounded-lg border bg-muted/30 px-3 py-2 text-xs text-muted-foreground">
                      <span className="font-medium text-foreground">
                        {t("补跑说明")}:{" "}
                      </span>
                      {t("停机恢复跳过 {value} 次过期调度", {
                        value: visibleExecutionDetail.missed_count_before,
                      })}
                    </div>
                  ) : null}

                  {visibleExecutionDetail.skip_reason ? (
                    <div className="rounded-lg border border-destructive/30 bg-destructive/5 px-3 py-2 text-xs text-destructive">
                      <span className="font-medium">
                        {t("跳过或拒绝原因")}:{" "}
                      </span>
                      {visibleExecutionDetail.skip_reason}
                    </div>
                  ) : null}

                  <dl className="grid gap-3 rounded-lg border bg-muted/20 p-3 text-xs sm:grid-cols-2 lg:grid-cols-3">
                    <div>
                      <dt className="text-muted-foreground">{t("计划时间")}</dt>
                      <dd className="mt-0.5 font-medium tabular-nums">
                        {visibleExecutionDetail.scheduled_at
                          ? formatDateTime(
                              visibleExecutionDetail.scheduled_at,
                              locale
                            )
                          : "—"}
                      </dd>
                    </div>
                    <div>
                      <dt className="text-muted-foreground">{t("接收时间")}</dt>
                      <dd className="mt-0.5 font-medium tabular-nums">
                        {formatDateTime(
                          visibleExecutionDetail.received_at,
                          locale
                        )}
                      </dd>
                    </div>
                    <div>
                      <dt className="text-muted-foreground">{t("派发时间")}</dt>
                      <dd className="mt-0.5 font-medium tabular-nums">
                        {visibleExecutionDetail.dispatched_at
                          ? formatDateTime(
                              visibleExecutionDetail.dispatched_at,
                              locale
                            )
                          : "—"}
                      </dd>
                    </div>
                    <div>
                      <dt className="text-muted-foreground">
                        {t("实际启动时间")}
                      </dt>
                      <dd className="mt-0.5 font-medium tabular-nums">
                        {startedAt ? formatDateTime(startedAt, locale) : "—"}
                      </dd>
                    </div>
                    <div>
                      <dt className="text-muted-foreground">{t("完成时间")}</dt>
                      <dd className="mt-0.5 font-medium tabular-nums">
                        {finishedAt ? formatDateTime(finishedAt, locale) : "—"}
                      </dd>
                    </div>
                    <div>
                      <dt className="text-muted-foreground">{t("派发状态")}</dt>
                      <dd className="mt-0.5 font-medium">
                        {visibleExecutionDetail.dispatch_status}
                      </dd>
                    </div>
                  </dl>

                  {pendingToolCalls.length > 0 &&
                  visibleExecutionDetail.run_id ? (
                    <section className="grid gap-2">
                      <h2 className="text-sm font-medium">{t("待审批操作")}</h2>
                      {pendingToolCalls.map((call) => (
                        <InlineToolApproval
                          key={call.call_id}
                          runId={visibleExecutionDetail.run_id!}
                          call={call}
                          resolvingCallId={resolvingCallId}
                          onDecision={(callId, decision) =>
                            void handleToolApproval(callId, decision)
                          }
                          t={t}
                        />
                      ))}
                    </section>
                  ) : null}

                  {visibleExecutionDetail.workflow_run?.pending_form ? (
                    <section className="grid gap-2">
                      <h2 className="text-sm font-medium">{t("待填写表单")}</h2>
                      <WorkflowRuntimeForm
                        form={visibleExecutionDetail.workflow_run.pending_form}
                        submitting={isSubmittingForm}
                        onSubmit={handleWorkflowFormSubmit}
                      />
                    </section>
                  ) : null}

                  {runErrorMessage ? (
                    <div
                      role="alert"
                      className="rounded-lg border border-destructive/40 bg-destructive/5 px-3 py-2 text-xs text-destructive"
                    >
                      {getErrorMessage(new Error(runErrorMessage), t)}
                    </div>
                  ) : null}

                  <section className="grid gap-2">
                    <h2 className="text-sm font-medium">{t("执行结果")}</h2>
                    {resultMarkdown ? (
                      <div className="rounded-lg border bg-background p-4">
                        <MarkdownContent content={resultMarkdown} />
                      </div>
                    ) : (
                      <p className="rounded-lg border border-dashed px-4 py-6 text-center text-xs text-muted-foreground">
                        {t("暂无数据")}
                      </p>
                    )}
                  </section>

                  {visibleExecutionDetail.tool_calls.length > 0 ? (
                    <section className="grid gap-2">
                      <h2 className="text-sm font-medium">{t("工具调用")}</h2>
                      <div className="grid gap-2">
                        {visibleExecutionDetail.tool_calls.map((call) => (
                          <div
                            key={call.call_id}
                            className="flex flex-wrap items-center justify-between gap-2 rounded-lg border px-3 py-2 text-xs"
                          >
                            <span className="font-medium">
                              {call.tool_name}
                              {call.server_name ? ` @ ${call.server_name}` : ""}
                            </span>
                            <Badge variant="outline">{call.status}</Badge>
                          </div>
                        ))}
                      </div>
                    </section>
                  ) : null}

                  {visibleExecutionDetail.artifacts.length > 0 ? (
                    <section className="grid gap-2">
                      <h2 className="text-sm font-medium">{t("生成产物")}</h2>
                      <div className="grid gap-2">
                        {visibleExecutionDetail.artifacts.map((artifact) => {
                          const busyDownload =
                            downloadingArtifactId === artifact.artifact_id
                          return (
                            <div
                              key={artifact.artifact_id}
                              className="flex flex-wrap items-center justify-between gap-3 rounded-lg border px-3 py-2 text-xs"
                            >
                              <div className="min-w-0 space-y-0.5">
                                <p className="truncate font-medium">
                                  {artifact.filename}
                                </p>
                                <p className="text-muted-foreground">
                                  {artifact.format.toUpperCase()} ·{" "}
                                  {formatFileSize(artifact.size_bytes)}
                                  {artifact.relative_path
                                    ? ` · ${artifact.relative_path}`
                                    : ""}
                                </p>
                              </div>
                              <Button
                                type="button"
                                size="xs"
                                variant="outline"
                                disabled={busyDownload}
                                onClick={() =>
                                  void handleDownloadArtifact(artifact)
                                }
                              >
                                {busyDownload ? (
                                  <LoaderCircleIcon className="animate-spin" />
                                ) : (
                                  <DownloadIcon />
                                )}
                                <span>{t("下载产物")}</span>
                              </Button>
                            </div>
                          )
                        })}
                      </div>
                    </section>
                  ) : null}

                  <section className="grid gap-2">
                    <h2 className="text-sm font-medium">{t("冻结输入")}</h2>
                    <pre className="max-h-60 overflow-auto rounded-lg border bg-muted/20 p-3 font-mono text-xs break-words whitespace-pre-wrap">
                      {JSON.stringify(
                        visibleExecutionDetail.frozen_input,
                        null,
                        2
                      )}
                    </pre>
                  </section>
                </CardContent>
              </>
            )}
          </Card>
        </div>
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
