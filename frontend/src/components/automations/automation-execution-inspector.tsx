"use client"

import * as React from "react"
import {
  AlertTriangleIcon,
  CircleCheckIcon,
  CircleXIcon,
  InfoIcon,
  LoaderCircleIcon,
  SparklesIcon,
  SquareIcon,
} from "lucide-react"

import { AgentReasoningStep } from "@/components/agents/agent-reasoning-step"
import { AgentToolCallRow } from "@/components/agents/agent-tool-call-row"
import {
  AgentArtifactPreviewContext,
  useAgentArtifactPreview,
} from "@/components/agents/artifacts/agent-artifact-preview-context"
import { AgentArtifactPreviewPanel } from "@/components/agents/artifacts/agent-artifact-previews"
import { InlineToolApproval } from "@/components/agents/inline-tool-approval"
import { ToolInputPreview } from "@/components/agents/tool-input-preview"
import {
  DispatchStatusBadge,
  ExecutionRunStatusBadge,
  formatExecutionDuration,
  isAutomationExecutionActive,
  toolCallStatusMeta,
  triggerSourceLabelKey,
} from "@/components/automations/automation-badges"
import { AutomationOutputView } from "@/components/automations/automation-output-view"
import { BuiltinToolIcon } from "@/components/tools/builtin-tool-icon"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { CopyButton } from "@/components/ui/copy-button"
import { WorkflowRuntimeForm } from "@/components/workflows/workflow-runtime-form"
import type { TFunction } from "@/i18n"
import {
  artifactContentUrl,
  MAX_PREVIEW_BYTES,
  type PreviewArtifact,
  type PreviewFormat,
} from "@/lib/agent-artifacts"
import type { AgentRunEvent, AgentToolCall } from "@/lib/api/agents"
import type {
  AutomationArtifactLink,
  AutomationExecutionDetail,
} from "@/lib/api/automations"
import { formatDateTime, formatTokenCount } from "@/lib/display"
import { getErrorMessage } from "@/lib/errors"
import { toolActivityName, toolSourceDisplayName } from "@/lib/tool-display"
import { cn } from "@/lib/utils"

type InspectorSubTab = "output" | "process"

const PREVIEWABLE_FORMATS = new Set<PreviewFormat>([
  "html",
  "pdf",
  "docx",
  "xlsx",
  "pptx",
])

function toPreviewArtifact(
  artifact: AutomationArtifactLink
): PreviewArtifact | null {
  const rawFormat = artifact.format.toLowerCase()
  const normalized = rawFormat === "htm" ? "html" : rawFormat
  if (
    !PREVIEWABLE_FORMATS.has(normalized as PreviewFormat) ||
    artifact.size_bytes > MAX_PREVIEW_BYTES
  ) {
    return null
  }
  const downloadUrl =
    artifactContentUrl({ artifact_id: artifact.artifact_id }) ??
    artifact.download_url
  return {
    artifactId: artifact.artifact_id,
    ...(artifact.relative_path ? { relativePath: artifact.relative_path } : {}),
    filename: artifact.filename,
    downloadUrl,
    format: normalized as PreviewFormat,
  }
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

function formatToolOutput(output: unknown) {
  if (output === null || output === undefined) return ""
  if (typeof output === "string") return output
  try {
    return JSON.stringify(output, null, 2)
  } catch {
    return String(output)
  }
}

function EventStatusIcon({ status }: { status: AgentRunEvent["status"] }) {
  if (status === "running") {
    return (
      <LoaderCircleIcon className="size-3.5 animate-spin text-sky-500 motion-reduce:animate-none" />
    )
  }
  if (status === "failed") {
    return <CircleXIcon className="size-3.5 text-destructive" />
  }
  return <CircleCheckIcon className="size-3.5 text-emerald-500" />
}

function ToolCallRowItem({
  call,
  t,
}: {
  call: AgentToolCall
  t: TFunction
}) {
  const statusMeta = toolCallStatusMeta(call.status, t)
  const duration = formatExecutionDuration(call.started_at, call.finished_at)
  return (
    <AgentToolCallRow
      title={toolActivityName(
        { tool_name: call.tool_name, tool_kind: call.tool_kind },
        t
      )}
      functionName={call.tool_name}
      sourceName={
        call.server_name
          ? toolSourceDisplayName(
              { name: call.server_name, kind: call.tool_kind },
              t
            )
          : undefined
      }
      icon={
        <BuiltinToolIcon
          functionName={call.tool_name}
          toolKind={call.tool_kind}
          className="size-3.5"
        />
      }
      statusIcon={
        <Badge
          variant="outline"
          className={cn("rounded-full text-[11px]", statusMeta.className)}
        >
          {statusMeta.label}
        </Badge>
      }
      detail={duration}
      input={call.arguments}
    >
      {() => (
        <div className="space-y-2.5 text-xs">
          {call.last_error ? (
            <div className="rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-destructive">
              <span className="font-medium">{t("错误信息")}: </span>
              {getErrorMessage(new Error(call.last_error), t)}
            </div>
          ) : null}
          {Object.keys(call.arguments ?? {}).length > 0 ? (
            <div className="space-y-1">
              <p className="text-[11px] font-medium text-muted-foreground">
                {t("输入参数")}
              </p>
              <ToolInputPreview input={call.arguments} streaming={false} />
            </div>
          ) : null}
        </div>
      )}
    </AgentToolCallRow>
  )
}

export function AutomationExecutionInspector({
  automationId,
  detail,
  locale,
  isActionBusy,
  resolvingCallId,
  isSubmittingForm,
  downloadingArtifactId,
  onCancelExecution,
  onToolApproval,
  onWorkflowFormSubmit,
  onDownloadArtifact,
  t,
}: {
  automationId: string
  detail: AutomationExecutionDetail | null
  locale: string
  isActionBusy: boolean
  resolvingCallId: string | null
  isSubmittingForm: boolean
  downloadingArtifactId: string | null
  onCancelExecution: () => void
  onToolApproval: (callId: string, decision: "approve" | "reject") => void
  onWorkflowFormSubmit: (data: Record<string, unknown>) => Promise<void>
  onDownloadArtifact: (artifact: AutomationArtifactLink) => void
  t: TFunction
}) {
  const preview = useAgentArtifactPreview(
    `${automationId}:${detail?.id ?? "none"}`
  )
  const ownerId = React.useId()
  const [subTab, setSubTab] = React.useState<InspectorSubTab>("output")

  const previewableEntries = React.useMemo(
    () =>
      (detail?.artifacts ?? []).map((artifact) => ({
        artifact,
        preview: toPreviewArtifact(artifact),
      })),
    [detail?.artifacts]
  )

  const updateSource = preview.updateSource
  React.useEffect(() => {
    const urls = previewableEntries
      .map((entry) => entry.preview?.downloadUrl)
      .filter((url): url is string => Boolean(url))
    updateSource(ownerId, urls)
  }, [ownerId, previewableEntries, updateSource])
  React.useEffect(() => () => updateSource(ownerId), [ownerId, updateSource])

  const pendingToolCalls = React.useMemo(
    () =>
      (detail?.tool_calls ?? []).filter(
        (call) =>
          call.status === "awaiting_approval" || call.status === "uncertain"
      ),
    [detail?.tool_calls]
  )

  if (!detail) {
    return (
      <div className="flex min-h-72 flex-1 flex-col items-center justify-center gap-2 p-8 text-center text-sm text-muted-foreground">
        <SparklesIcon className="size-8 text-muted-foreground/50" />
        <p>{t("请选择一条执行记录查看详情")}</p>
      </div>
    )
  }

  const startedAt =
    detail.agent_run?.started_at ?? detail.workflow_run?.started_at ?? null
  const finishedAt =
    detail.agent_run?.finished_at ?? detail.workflow_run?.finished_at ?? null
  const runErrorMessage =
    detail.agent_run?.last_error ?? detail.workflow_run?.last_error ?? null
  const resultMarkdown = resolveResultMarkdown(detail)
  const isActive = isAutomationExecutionActive(
    detail.dispatch_status,
    detail.run_status
  )
  const durationLabel = formatExecutionDuration(
    startedAt,
    finishedAt,
    detail.dispatched_at ?? detail.received_at,
    finishedAt
  )

  const agentEvents = detail.agent_run?.events ?? []
  const eventCallIds = new Set(
    agentEvents
      .filter((event) => event.type === "tool" && event.call_id)
      .map((event) => event.call_id)
  )
  const toolCallsByCallId = new Map(
    detail.tool_calls.map((call) => [call.call_id, call])
  )
  const extraToolCalls = detail.tool_calls.filter(
    (call) => !eventCallIds.has(call.call_id)
  )
  const processStepCount = agentEvents.length + extraToolCalls.length

  const totalModelTokens =
    typeof detail.agent_run?.model_usage?.total_tokens === "number"
      ? detail.agent_run.model_usage.total_tokens
      : detail.workflow_run?.token_usage

  return (
    <AgentArtifactPreviewContext.Provider value={preview}>
      <div className="flex min-h-0 min-w-0 flex-1 overflow-hidden">
        <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
          <div className="shrink-0 border-b bg-card">
            <div className="flex flex-wrap items-center justify-between gap-2 px-6 pt-3.5 pb-2.5">
              <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                <ExecutionRunStatusBadge
                  runStatus={detail.run_status}
                  dispatchStatus={detail.dispatch_status}
                  t={t}
                />
                {detail.dispatch_status !== "dispatched" ? (
                  <DispatchStatusBadge
                    status={detail.dispatch_status}
                    t={t}
                  />
                ) : null}
                <span>
                  {t(triggerSourceLabelKey(detail.trigger_source))}
                </span>
                <span aria-hidden="true">·</span>
                <span className="tabular-nums">
                  {formatDateTime(
                    startedAt ?? detail.scheduled_at ?? detail.received_at,
                    locale
                  )}
                </span>
                {durationLabel ? (
                  <>
                    <span aria-hidden="true">·</span>
                    <span className="tabular-nums">
                      {t("耗时")} {durationLabel}
                    </span>
                  </>
                ) : null}
              </div>

              <div className="flex flex-wrap items-center gap-2">
                {detail.run_id ? (
                  <div className="inline-flex items-center gap-1 rounded-md border bg-muted/30 px-2 py-0.5 font-mono text-[11px] text-muted-foreground">
                    <span>Run: {detail.run_id.slice(0, 8)}</span>
                    <CopyButton value={detail.run_id} t={t} />
                  </div>
                ) : null}
                {isActive ? (
                  <Button
                    type="button"
                    variant="destructive"
                    size="xs"
                    disabled={isActionBusy}
                    onClick={onCancelExecution}
                  >
                    <SquareIcon />
                    <span>{t("取消运行")}</span>
                  </Button>
                ) : null}
              </div>
            </div>

            <div className="flex flex-wrap items-center justify-between gap-2 px-6">
              <div
                role="tablist"
                aria-label={t("执行详情")}
                className="-mb-px flex items-center gap-5"
              >
                <button
                  type="button"
                  role="tab"
                  aria-selected={subTab === "output"}
                  onClick={() => setSubTab("output")}
                  className={cn(
                    "border-b-2 py-2.5 text-xs font-medium transition-colors",
                    subTab === "output"
                      ? "border-primary text-foreground"
                      : "border-transparent text-muted-foreground hover:text-foreground"
                  )}
                >
                  {t("结果与产物")}
                </button>
                <button
                  type="button"
                  role="tab"
                  aria-selected={subTab === "process"}
                  onClick={() => setSubTab("process")}
                  className={cn(
                    "inline-flex items-center gap-1.5 border-b-2 py-2.5 text-xs font-medium transition-colors",
                    subTab === "process"
                      ? "border-primary text-foreground"
                      : "border-transparent text-muted-foreground hover:text-foreground"
                  )}
                >
                  <span>{t("执行过程")}</span>
                  {processStepCount > 0 ? (
                    <span className="rounded-full bg-muted px-1.5 text-[10px] text-muted-foreground tabular-nums">
                      {processStepCount}
                    </span>
                  ) : null}
                </button>
              </div>

              {subTab === "output" && resultMarkdown ? (
                <div className="pb-1">
                  <CopyButton value={resultMarkdown} showLabel t={t} />
                </div>
              ) : null}
            </div>
          </div>

          <div className="min-h-0 flex-1 space-y-5 overflow-y-auto overscroll-contain px-6 py-5">
            {detail.missed_count_before > 0 ? (
              <div className="flex items-start gap-2.5 rounded-lg border bg-muted/30 px-3.5 py-2.5 text-xs text-muted-foreground">
                <InfoIcon className="mt-0.5 size-4 shrink-0 text-foreground" />
                <div>
                  <span className="font-medium text-foreground">
                    {t("补跑说明")}:{" "}
                  </span>
                  <span>
                    {t("停机恢复跳过 {value} 次过期调度", {
                      value: detail.missed_count_before,
                    })}
                  </span>
                </div>
              </div>
            ) : null}

            {detail.skip_reason ? (
              <div className="flex items-start gap-2.5 rounded-lg border border-destructive/30 bg-destructive/5 px-3.5 py-2.5 text-xs text-destructive">
                <AlertTriangleIcon className="mt-0.5 size-4 shrink-0" />
                <div>
                  <span className="font-medium">{t("跳过或拒绝原因")}: </span>
                  <span>
                    {getErrorMessage(new Error(detail.skip_reason), t)}
                  </span>
                </div>
              </div>
            ) : null}

            {runErrorMessage ? (
              <div
                role="alert"
                className="flex items-start gap-2.5 rounded-lg border border-destructive/40 bg-destructive/5 px-3.5 py-2.5 text-xs text-destructive"
              >
                <CircleXIcon className="mt-0.5 size-4 shrink-0" />
                <span>{getErrorMessage(new Error(runErrorMessage), t)}</span>
              </div>
            ) : null}

            {pendingToolCalls.length > 0 && detail.run_id ? (
              <section className="space-y-3 rounded-xl border border-amber-500/30 bg-amber-500/[0.04] p-4">
                <h2 className="text-sm font-medium">{t("待审批操作")}</h2>
                <div className="grid gap-3">
                  {pendingToolCalls.map((call) => (
                    <InlineToolApproval
                      key={call.call_id}
                      runId={detail.run_id!}
                      call={call}
                      resolvingCallId={resolvingCallId}
                      onDecision={onToolApproval}
                      t={t}
                    />
                  ))}
                </div>
              </section>
            ) : null}

            {detail.workflow_run?.pending_form ? (
              <section className="space-y-3 rounded-xl border border-amber-500/30 bg-amber-500/[0.04] p-4">
                <h2 className="text-sm font-medium">{t("待填写表单")}</h2>
                <WorkflowRuntimeForm
                  form={detail.workflow_run.pending_form}
                  submitting={isSubmittingForm}
                  onSubmit={onWorkflowFormSubmit}
                />
              </section>
            ) : null}

            {subTab === "output" ? (
              <AutomationOutputView
                detail={detail}
                resultMarkdown={resultMarkdown}
                isActive={isActive}
                previewableEntries={previewableEntries}
                preview={preview}
                downloadingArtifactId={downloadingArtifactId}
                onDownloadArtifact={onDownloadArtifact}
                t={t}
              />
            ) : null}

            {subTab === "process" ? (
              <div className="space-y-4">
                {detail.agent_run?.model_name ||
                detail.workflow_run?.step_count !== undefined ||
                typeof totalModelTokens === "number" ? (
                  <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                    {detail.agent_run?.model_name ? (
                      <Badge variant="outline">
                        {detail.agent_run.model_name}
                      </Badge>
                    ) : null}
                    {typeof detail.workflow_run?.step_count === "number" ? (
                      <Badge variant="outline">
                        {detail.workflow_run.step_count} steps
                      </Badge>
                    ) : null}
                    {typeof totalModelTokens === "number" &&
                    totalModelTokens > 0 ? (
                      <Badge variant="outline">
                        {formatTokenCount(totalModelTokens)} tokens
                      </Badge>
                    ) : null}
                  </div>
                ) : null}

                {processStepCount === 0 ? (
                  <p className="rounded-xl border border-dashed px-4 py-8 text-center text-xs text-muted-foreground">
                    {t("暂无执行步骤")}
                  </p>
                ) : (
                  <div className="space-y-2.5">
                    {agentEvents.map((event, index) => {
                      const key =
                        event.call_id ||
                        `${event.type}-${event.turn}-${index}`
                      if (event.type === "thought") {
                        return (
                          <AgentReasoningStep
                            key={key}
                            title={event.summary || t("思考过程")}
                            status={
                              event.status === "failed"
                                ? "failed"
                                : event.status === "running"
                                  ? "running"
                                  : "succeeded"
                            }
                            reasoning={event.reasoning}
                          />
                        )
                      }
                      if (event.type === "tool") {
                        const matchedCall = event.call_id
                          ? toolCallsByCallId.get(event.call_id)
                          : undefined
                        const outputText = formatToolOutput(event.output)
                        return (
                          <AgentToolCallRow
                            key={key}
                            title={toolActivityName(event, t)}
                            functionName={event.tool_name}
                            sourceName={
                              event.server_name
                                ? toolSourceDisplayName(
                                    {
                                      name: event.server_name,
                                      kind: event.tool_kind,
                                    },
                                    t
                                  )
                                : undefined
                            }
                            icon={
                              <BuiltinToolIcon
                                functionName={event.tool_name}
                                toolKind={event.tool_kind}
                                className="size-3.5"
                              />
                            }
                            statusIcon={
                              <EventStatusIcon status={event.status} />
                            }
                            detail={
                              event.duration_ms > 0
                                ? `${event.duration_ms}ms`
                                : undefined
                            }
                            input={event.input}
                          >
                            {() => (
                              <div className="space-y-2.5 text-xs">
                                {matchedCall?.last_error ? (
                                  <div className="rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-destructive">
                                    <span className="font-medium">
                                      {t("错误信息")}:{" "}
                                    </span>
                                    {getErrorMessage(
                                      new Error(matchedCall.last_error),
                                      t
                                    )}
                                  </div>
                                ) : null}
                                {Object.keys(event.input ?? {}).length > 0 ? (
                                  <div className="space-y-1">
                                    <p className="text-[11px] font-medium text-muted-foreground">
                                      {t("输入参数")}
                                    </p>
                                    <ToolInputPreview
                                      input={event.input}
                                      streaming={event.status === "running"}
                                    />
                                  </div>
                                ) : null}
                                {outputText ? (
                                  <div className="space-y-1">
                                    <p className="text-[11px] font-medium text-muted-foreground">
                                      {t("输出结果")}
                                    </p>
                                    <pre className="max-h-56 overflow-auto rounded-md bg-background p-3 font-mono text-[11px] leading-5 [overflow-wrap:anywhere] whitespace-pre-wrap">
                                      {outputText}
                                    </pre>
                                  </div>
                                ) : null}
                              </div>
                            )}
                          </AgentToolCallRow>
                        )
                      }
                      return null
                    })}

                    {extraToolCalls.map((call) => (
                      <ToolCallRowItem key={call.call_id} call={call} t={t} />
                    ))}
                  </div>
                )}
              </div>
            ) : null}
          </div>
        </div>

        <AgentArtifactPreviewPanel />
      </div>
    </AgentArtifactPreviewContext.Provider>
  )
}
