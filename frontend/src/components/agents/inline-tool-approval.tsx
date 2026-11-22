"use client"

import { LoaderCircleIcon, ShieldAlertIcon } from "lucide-react"
import type { TFunction } from "@/i18n"
import type { AgentToolCall } from "@/lib/api/agents"
import { getErrorMessage } from "@/lib/errors"
import { toolDisplayName, toolSourceDisplayName } from "@/lib/tool-display"
import { Button } from "@/components/ui/button"

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
    <section className="overflow-hidden rounded-lg border border-amber-600/30 bg-background/80">
      <div className="flex flex-wrap items-center gap-2 px-3 py-2">
        <span className="flex size-7 shrink-0 items-center justify-center rounded-md bg-amber-500/10 text-amber-700 dark:text-amber-400">
          <ShieldAlertIcon className="size-3.5" />
        </span>
        <div className="min-w-0 flex-1">
          <p className="truncate text-xs font-medium text-foreground">
            {t(isUncertain ? "工具执行结果不确定" : "工具调用需要确认")}
          </p>
          <p className="truncate text-[11px] text-muted-foreground">
            {toolName}
            {call.server_name ? ` @ ${serverName}` : ""}
          </p>
        </div>
        <div className="ml-auto flex shrink-0 gap-1.5">
          <Button
            type="button"
            variant="outline"
            size="xs"
            disabled={isResolving}
            onClick={() => onDecision(call.call_id, "reject")}
          >
            {isResolving ? <LoaderCircleIcon className="animate-spin" /> : null}
            {t(isUncertain ? "不重试并继续" : "拒绝")}
          </Button>
          {!isUncertain ? (
            <Button
              type="button"
              size="xs"
              disabled={isResolving}
              onClick={() => onDecision(call.call_id, "approve")}
            >
              {isResolving ? (
                <LoaderCircleIcon className="animate-spin" />
              ) : null}
              {t("批准并执行")}
            </Button>
          ) : null}
        </div>
      </div>
      {call.last_error ? (
        <p className="border-t px-3 py-2 text-xs leading-5 text-muted-foreground">
          {getErrorMessage(new Error(call.last_error), t)}
        </p>
      ) : null}
      <pre className="max-h-28 overflow-auto border-t bg-muted/20 px-3 py-2 font-mono text-[11px] leading-4 break-words whitespace-pre-wrap">
        {JSON.stringify(call.arguments, null, 2)}
      </pre>
    </section>
  )
}
