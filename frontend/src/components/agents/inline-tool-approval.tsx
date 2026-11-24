"use client"

import type { ReactNode } from "react"
import { LoaderCircleIcon } from "lucide-react"
import type { TFunction } from "@/i18n"
import type { AgentToolCall } from "@/lib/api/agents"
import { getErrorMessage } from "@/lib/errors"
import { toolDisplayName, toolSourceDisplayName } from "@/lib/tool-display"
import { Button } from "@/components/ui/button"

export function ToolApprovalCard({
  title,
  toolName,
  serverName,
  input,
  description,
  caption,
  error,
  children,
  t,
}: {
  title: string
  toolName: string
  serverName?: string
  input: Record<string, unknown>
  description?: string
  caption?: string
  error?: string
  children: ReactNode
  t: TFunction
}) {
  return (
    <section className="agent-beautiful bui-approval-card">
      <div className="bui-approval-heading">
        <p className="bui-approval-title">{title}</p>
        <p className="bui-approval-tool">
          {toolName}
          {serverName ? ` @ ${serverName}` : ""}
        </p>
      </div>
      {description ? (
        <p className="px-4 pb-3 text-xs leading-5 text-muted-foreground">
          {description}
        </p>
      ) : null}
      {error ? (
        <p className="px-4 pb-3 text-xs leading-5 text-destructive">{error}</p>
      ) : null}
      <div className="bui-approval-input">
        <p>{t("调用输入")}</p>
        <pre className="font-mono">{JSON.stringify(input, null, 2)}</pre>
      </div>
      <div className="bui-approval-footer">
        <span className="bui-approval-caption">{caption ?? t("等待确认")}</span>
        <div className="bui-approval-actions">{children}</div>
      </div>
    </section>
  )
}

export function InlineToolApproval({
  runId,
  call,
  resolvingCallId,
  onDecision,
  t,
}: {
  runId: string
  call: AgentToolCall
  resolvingCallId: string | null
  onDecision: (callId: string, decision: "approve" | "reject") => void
  t: TFunction
}) {
  const isUncertain = call.status === "uncertain"
  const isResolving = resolvingCallId === `${runId}:${call.call_id}`
  const toolName = toolDisplayName(
    {
      function_name: call.tool_name,
      display_name: call.tool_name,
      description: "",
    },
    t
  )
  const serverName = toolSourceDisplayName(
    { name: call.server_name, kind: call.tool_kind },
    t
  )

  return (
    <ToolApprovalCard
      title={t(isUncertain ? "工具执行结果不确定" : "工具调用需要确认")}
      toolName={toolName}
      serverName={call.server_name ? serverName : undefined}
      input={call.arguments}
      description={
        isUncertain
          ? t(
              "调用可能已在外部服务执行，请先核对结果。选择“不重试并继续”可继续对话。"
            )
          : undefined
      }
      caption={isUncertain ? t("等待核对结果") : undefined}
      error={
        call.last_error
          ? getErrorMessage(new Error(call.last_error), t)
          : undefined
      }
      t={t}
    >
      <Button
        type="button"
        variant="outline"
        size="sm"
        disabled={isResolving}
        onClick={() => onDecision(call.call_id, "reject")}
      >
        {isResolving ? (
          <LoaderCircleIcon className="animate-spin motion-reduce:animate-none" />
        ) : null}
        {t(isUncertain ? "不重试并继续" : "拒绝")}
      </Button>
      {!isUncertain ? (
        <Button
          type="button"
          size="sm"
          disabled={isResolving}
          onClick={() => onDecision(call.call_id, "approve")}
        >
          {isResolving ? (
            <LoaderCircleIcon className="animate-spin motion-reduce:animate-none" />
          ) : null}
          {t("批准并执行")}
        </Button>
      ) : null}
    </ToolApprovalCard>
  )
}
