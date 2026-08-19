"use client"

import * as React from "react"
import ModelIcon from "@lobehub/icons/es/features/ModelIcon"
import {
  ArrowLeftIcon,
  BotIcon,
  BrainIcon,
  CheckIcon,
  CircleCheckIcon,
  ChevronDownIcon,
  CircleXIcon,
  CopyIcon,
  DatabaseIcon,
  LoaderCircleIcon,
  MessageSquareIcon,
  MessageSquarePlusIcon,
  MoreHorizontalIcon,
  PaperclipIcon,
  ChartNoAxesColumnIcon,
  LayoutDashboardIcon,
  PanelLeftCloseIcon,
  PanelLeftOpenIcon,
  RocketIcon,
  SaveIcon,
  ScrollTextIcon,
  SendIcon,
  SettingsIcon,
  ShieldCheckIcon,
  ShieldAlertIcon,
  SquareIcon,
  Trash2Icon,
  Undo2Icon,
  UsersIcon,
  WrenchIcon,
} from "lucide-react"

import { MarkdownContent } from "@/components/knowledge/markdown-content"
import { RunActionBar } from "@/components/app/run-action-bar"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import type { TFunction } from "@/i18n"
import type { AgentDetailView } from "@/lib/agent-views"
import type { Agent, AgentRun, AgentToolCall } from "@/lib/api/agents"
import type { KnowledgeBase } from "@/lib/api/knowledge"
import type { RegisteredModel } from "@/lib/api/llm"
import type { ToolSummary } from "@/lib/api/tools"
import {
  AGENT_FILE_UPLOAD_SETTING,
  acceptedUploadExtensions,
} from "@/lib/interaction-config"

import { AgentConfigFields } from "./agent-config-fields"
import { AgentAttachmentList } from "./agent-attachment-list"
import {
  AgentConversationUsersPanel,
  AgentLogsPanel,
  AgentMonitoringPanel,
  AgentOverviewPanel,
} from "./agent-management-panels"
import type { AgentFormState } from "./agents-page"

type AgentDetailWorkspaceProps = {
  agent: Agent
  form: AgentFormState
  setForm: React.Dispatch<React.SetStateAction<AgentFormState>>
  models: RegisteredModel[]
  knowledgeBases: KnowledgeBase[]
  tools: ToolSummary[]
  runs: AgentRun[]
  toolCallsByRun: Record<string, AgentToolCall[]>
  resolvingCallId: string | null
  question: string
  setQuestion: React.Dispatch<React.SetStateAction<string>>
  files: File[]
  setFiles: React.Dispatch<React.SetStateAction<File[]>>
  pendingQuestion: string | null
  isDirty: boolean
  isSaving: boolean
  isPublishing: boolean
  isAsking: boolean
  isRunsLoading: boolean
  activeView: AgentDetailView
  token: string
  workspaceId: string
  canManagePublishing: boolean
  onBack: () => void
  onDelete: () => void
  onManagePermissions: () => void
  onSave: (event: React.FormEvent<HTMLFormElement>) => void
  onPublish: () => void
  onViewChange: (view: AgentDetailView) => void
  onAsk: (event: React.FormEvent<HTMLFormElement>) => void
  onCancelAsk: () => void
  onNewConversation: () => void
  onToolCallDecision: (
    runId: string,
    callId: string,
    decision: "approve" | "reject"
  ) => void
  onRegenerateRun?: (runId: string) => void
  onRunFeedback?: (runId: string, value: "positive" | "negative" | null) => void
  regeneratingRunId?: string | null
  feedbackPendingRunId?: string | null
  notify: (kind: "success" | "error", message: string) => void
  t: TFunction
}

const AUTO_FOLLOW_THRESHOLD_PX = 64

export function agentPublicationAction(
  agent: Pick<Agent, "published" | "has_unpublished_changes">
) {
  if (!agent.published) return "publish"
  return agent.has_unpublished_changes ? "republish" : "unpublish"
}

export function isNearScrollBottom(
  element: Pick<HTMLElement, "clientHeight" | "scrollHeight" | "scrollTop">
) {
  return (
    element.scrollHeight - element.scrollTop - element.clientHeight <=
    AUTO_FOLLOW_THRESHOLD_PX
  )
}

function previewScrollHost(element: HTMLElement) {
  if (element.getClientRects().length === 0) return null
  if (element.scrollHeight > element.clientHeight) return element
  return element.ownerDocument.scrollingElement ?? element
}

function processSummary(
  event: AgentRun["events"][number],
  run: AgentRun,
  t: TFunction
) {
  if (event.summary === "agent.analyzing") return t("正在分析问题")
  if (event.summary === "agent.reviewing_tool_results")
    return t("正在整理工具结果")
  if (event.summary === "agent.tools_selected") return t("已完成分析")
  if (event.summary === "agent.grounding_check") return t("正在核验回答依据")
  if (event.summary === "agent.grounding_verified") return t("已完成依据核验")
  if (event.summary === "agent.grounding_revised")
    return t("已根据依据修正回答")
  if (event.summary === "agent.grounding_insufficient")
    return t("依据不足，已停止未经核实的回答")
  if (event.summary === "agent.grounding_unavailable")
    return t("暂时无法完成依据核验")
  if (event.summary === "agent.tool_running")
    return t("正在调用 {name}", { name: event.tool_name })
  if (event.summary === "agent.answer_ready")
    return t(run.status === "running" ? "正在生成回答" : "回答已生成")
  if (event.summary.startsWith("agent.knowledge_chunks_returned:")) {
    const count = Number(event.summary.split(":")[1])
    return t("已检索 {value} 个知识片段", { value: count })
  }
  const legacyKnowledgeMatch = event.summary.match(
    /^(\d+) knowledge chunks returned\.$/
  )
  if (legacyKnowledgeMatch) {
    return t("已检索 {value} 个知识片段", {
      value: Number(legacyKnowledgeMatch[1]),
    })
  }
  return event.summary
}

function ToolEventDetails({
  event,
  run,
  t,
}: {
  event: AgentRun["events"][number]
  run: AgentRun
  t: TFunction
}) {
  const [isOpen, setIsOpen] = React.useState(false)
  const label =
    event.tool_kind === "knowledge"
      ? t("知识库检索")
      : event.tool_label || event.tool_name

  return (
    <div className="overflow-hidden rounded-lg border bg-background/70">
      <button
        type="button"
        className="flex w-full items-center gap-2 px-3 py-2 text-left hover:bg-muted/50"
        aria-expanded={isOpen}
        onClick={() => setIsOpen((current) => !current)}
      >
        <span className="flex size-7 shrink-0 items-center justify-center rounded-md bg-sky-500/10 text-sky-700 dark:text-sky-400">
          {event.tool_kind === "knowledge" ? (
            <DatabaseIcon className="size-3.5" />
          ) : (
            <WrenchIcon className="size-3.5" />
          )}
        </span>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-sm font-medium text-foreground">
            {label}
            {event.server_name ? (
              <span className="ml-1 font-normal text-muted-foreground">
                @ {event.server_name}
              </span>
            ) : null}
          </span>
          <span className="block truncate text-xs text-muted-foreground">
            {processSummary(event, run, t)}
          </span>
        </span>
        {event.status === "running" ? (
          <LoaderCircleIcon className="size-3.5 animate-spin text-sky-600" />
        ) : event.status === "succeeded" ? (
          <CircleCheckIcon className="size-3.5 text-emerald-600" />
        ) : (
          <CircleXIcon className="size-3.5 text-destructive" />
        )}
        <ChevronDownIcon
          className={`size-4 text-muted-foreground transition-transform ${isOpen ? "rotate-180" : ""}`}
        />
      </button>
      {isOpen ? (
        <div className="grid gap-3 border-t bg-muted/20 p-3 text-xs">
          <div>
            <p className="mb-1 font-medium text-muted-foreground">
              {t("调用输入")}
            </p>
            <pre className="max-h-44 overflow-auto rounded-md bg-background p-3 font-mono leading-5 break-words whitespace-pre-wrap">
              {JSON.stringify(event.input, null, 2)}
            </pre>
          </div>
          {event.output !== null && event.output !== undefined ? (
            <div>
              <p className="mb-1 font-medium text-muted-foreground">
                {t("调用结果")}
              </p>
              {event.tool_kind === "knowledge" &&
              typeof event.output === "object" &&
              event.output &&
              "hits" in event.output &&
              Array.isArray(event.output.hits) ? (
                <div className="space-y-2">
                  {event.output.hits.map((hit, index) => {
                    const item = hit as Record<string, unknown>
                    return (
                      <article
                        key={index}
                        className="rounded-md border bg-background p-3"
                      >
                        <div className="flex flex-wrap items-center gap-2 font-medium">
                          <span>{String(item.document ?? t("未知文档"))}</span>
                          <span className="text-muted-foreground">
                            {String(item.knowledge_base ?? "")}
                          </span>
                        </div>
                        <p className="mt-2 leading-5 break-words whitespace-pre-wrap text-muted-foreground">
                          {String(item.content ?? "")}
                        </p>
                      </article>
                    )
                  })}
                </div>
              ) : (
                <pre className="max-h-64 overflow-auto rounded-md bg-background p-3 font-mono leading-5 break-words whitespace-pre-wrap">
                  {typeof event.output === "string"
                    ? event.output
                    : JSON.stringify(event.output, null, 2)}
                </pre>
              )}
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  )
}

export function processTimeline(run: AgentRun) {
  const deduplicated: AgentRun["events"] = []
  for (const event of run.events) {
    const eventIndex = deduplicated.findIndex((current) =>
      event.call_id
        ? current.call_id === event.call_id
        : current.type === event.type &&
          current.turn === event.turn &&
          current.tool_name === event.tool_name
    )
    if (eventIndex === -1) deduplicated.push(event)
    else deduplicated[eventIndex] = event
  }

  const eagerKnowledge = deduplicated.filter(
    (event) =>
      event.type === "tool" &&
      event.turn === 0 &&
      event.tool_kind === "knowledge"
  )
  if (eagerKnowledge.length === 0) {
    return deduplicated.map((event) => ({ event, count: 1 }))
  }

  const events = deduplicated.filter((event) => !eagerKnowledge.includes(event))
  const firstThought = events.findIndex((event) => event.type === "thought")
  if (firstThought === -1) {
    return deduplicated.map((event) => ({ event, count: 1 }))
  }
  events.splice(firstThought + 1, 0, ...eagerKnowledge)
  return events.map((event) => ({ event, count: 1 }))
}

export function unrenderedAgentToolCalls(
  timeline: ReturnType<typeof processTimeline>,
  calls: AgentToolCall[]
) {
  const renderedCallIds = new Set(
    timeline.map(({ event }) => event.call_id).filter(Boolean)
  )
  return calls.filter(
    (call) =>
      [
        "pending",
        "awaiting_approval",
        "approved",
        "running",
        "uncertain",
      ].includes(call.status) && !renderedCallIds.has(call.call_id)
  )
}

export function collapsedProcessStatusKey(
  runStatus: AgentRun["status"],
  hasActiveToolCall: boolean,
  isProcessOpen: boolean
): "等待工具调用确认" | "执行过程" | null {
  if (isProcessOpen) return null
  if (runStatus === "awaiting_approval") return "等待工具调用确认"
  return hasActiveToolCall ? "执行过程" : null
}

function CopyMessageButton({ value, t }: { value: string; t: TFunction }) {
  const [copied, setCopied] = React.useState(false)
  const label = t(copied ? "已复制" : "复制")

  async function handleCopy() {
    try {
      await navigator.clipboard.writeText(value)
      setCopied(true)
    } catch {
      setCopied(false)
    }
  }

  return (
    <Button
      type="button"
      variant="ghost"
      size="icon-xs"
      className="text-muted-foreground"
      aria-label={label}
      title={label}
      onClick={handleCopy}
    >
      {copied ? <CheckIcon /> : <CopyIcon />}
    </Button>
  )
}

function InlineToolApproval({
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
            {call.tool_name}
            {call.server_name ? ` @ ${call.server_name}` : ""}
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
          {call.last_error}
        </p>
      ) : null}
      <pre className="max-h-28 overflow-auto border-t bg-muted/20 px-3 py-2 font-mono text-[11px] leading-4 break-words whitespace-pre-wrap">
        {JSON.stringify(call.arguments, null, 2)}
      </pre>
    </section>
  )
}

function PendingToolEvent({
  call,
  run,
  t,
}: {
  call: AgentToolCall
  run: AgentRun
  t: TFunction
}) {
  return (
    <ToolEventDetails
      event={{
        type: "tool",
        turn: call.turn,
        tool_name: call.tool_name,
        status: "running",
        summary: "agent.tool_running",
        call_id: call.call_id,
        tool_label: call.tool_name,
        tool_kind: call.tool_kind,
        server_name: call.server_name,
        input: call.arguments,
        output: null,
        duration_ms: 0,
      }}
      run={run}
      t={t}
    />
  )
}

function RunExchange({
  run,
  toolCalls,
  resolvingCallId,
  onToolCallDecision,
  onRegenerateRun,
  onRunFeedback,
  regeneratingRunId,
  feedbackPendingRunId,
  regenerateDisabled,
  t,
}: {
  run: AgentRun
  toolCalls: AgentToolCall[]
  resolvingCallId: string | null
  onToolCallDecision: (
    runId: string,
    callId: string,
    decision: "approve" | "reject"
  ) => void
  onRegenerateRun?: (runId: string) => void
  onRunFeedback?: (runId: string, value: "positive" | "negative" | null) => void
  regeneratingRunId?: string | null
  feedbackPendingRunId?: string | null
  regenerateDisabled?: boolean
  t: TFunction
}) {
  const timeline = processTimeline(run)
  const inlineToolCalls = unrenderedAgentToolCalls(timeline, toolCalls)
  const hasProcess = timeline.length > 0 || inlineToolCalls.length > 0
  const hasActiveToolCall =
    inlineToolCalls.length > 0 ||
    timeline.some(
      ({ event }) => event.type === "tool" && event.status === "running"
    )
  const [isProcessOpen, setIsProcessOpen] = React.useState(true)
  const collapsedProcessStatus = collapsedProcessStatusKey(
    run.status,
    hasActiveToolCall,
    isProcessOpen
  )
  const answer = run.result
  return (
    <article className="flex flex-col gap-5">
      <div className="ml-auto flex max-w-[88%] flex-col items-end gap-1">
        <div className="rounded-2xl rounded-br-md bg-foreground px-4 py-3 text-sm leading-6 text-background shadow-sm">
          {run.goal}
        </div>
        <CopyMessageButton value={run.goal} t={t} />
      </div>
      <div className="flex items-start gap-3">
        <span className="mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-lg bg-foreground text-background shadow-sm">
          <BotIcon className="size-4" />
        </span>
        <div className="min-w-0 flex-1">
          <div className="rounded-2xl rounded-tl-md border bg-background p-4 shadow-xs">
            {hasProcess ? (
              <details
                className="group mb-4 rounded-xl bg-muted/50 px-3 py-2.5 text-sm"
                open={isProcessOpen}
                onToggle={(event) => setIsProcessOpen(event.currentTarget.open)}
              >
                <summary className="flex cursor-pointer list-none items-center gap-2 font-medium text-muted-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 [&::-webkit-details-marker]:hidden">
                  <BrainIcon className="size-4" />
                  <span className="flex-1">{t("执行过程")}</span>
                  <ChevronDownIcon className="size-4 transition-transform group-open:rotate-180" />
                </summary>
                <div className="mt-2 space-y-2 border-l pl-4">
                  {timeline.map(({ event }, index) =>
                    event.type === "tool" ? (
                      <ToolEventDetails
                        key={`${event.call_id || `${event.turn}-${event.tool_name}`}-${index}`}
                        event={event}
                        run={run}
                        t={t}
                      />
                    ) : (
                      <div
                        key={`${event.type}-${event.turn}-${index}`}
                        className="relative px-1 text-xs leading-5 text-muted-foreground"
                      >
                        <div className="flex items-start gap-2">
                          {event.status === "running" ? (
                            <LoaderCircleIcon className="mt-0.5 size-3.5 shrink-0 animate-spin" />
                          ) : event.status === "succeeded" ? (
                            <CircleCheckIcon className="mt-0.5 size-3.5 shrink-0 text-emerald-600" />
                          ) : (
                            <CircleXIcon className="mt-0.5 size-3.5 shrink-0 text-destructive" />
                          )}
                          <span>{processSummary(event, run, t)}</span>
                        </div>
                        {event.reasoning ? (
                          <ReasoningContent reasoning={event.reasoning} />
                        ) : null}
                      </div>
                    )
                  )}
                  {inlineToolCalls.map((call) =>
                    ["awaiting_approval", "uncertain"].includes(call.status) ? (
                      <InlineToolApproval
                        key={call.call_id}
                        runId={run.id}
                        call={call}
                        resolvingCallId={resolvingCallId}
                        onDecision={(callId, decision) =>
                          onToolCallDecision(run.id, callId, decision)
                        }
                        t={t}
                      />
                    ) : (
                      <PendingToolEvent
                        key={call.call_id}
                        call={call}
                        run={run}
                        t={t}
                      />
                    )
                  )}
                </div>
              </details>
            ) : null}

            {run.result ? (
              <MarkdownContent content={answer} className="text-sm leading-6" />
            ) : run.status === "failed" ? (
              <p className="rounded-md border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
                {run.last_error ?? t("Agent 未返回结果")}
              </p>
            ) : (run.status === "awaiting_approval" || hasActiveToolCall) &&
              isProcessOpen ? null : collapsedProcessStatus ? (
              <p className="text-sm text-muted-foreground">
                {t(collapsedProcessStatus)}
              </p>
            ) : run.status === "queued" ? (
              <p className="text-sm text-muted-foreground">{t("等待执行")}</p>
            ) : run.status === "cancelled" ? (
              <p className="text-sm text-muted-foreground">{t("运行已取消")}</p>
            ) : (
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <span className="flex gap-1" aria-label={t("正在生成回答")}>
                  <span className="size-1.5 animate-pulse rounded-full bg-current" />
                  <span className="size-1.5 animate-pulse rounded-full bg-current [animation-delay:150ms]" />
                  <span className="size-1.5 animate-pulse rounded-full bg-current [animation-delay:300ms]" />
                </span>
                {t("正在生成回答")}
              </div>
            )}
          </div>
          {run.status === "succeeded" && answer ? (
            <RunActionBar
              result={answer}
              feedback={run.feedback}
              regenerateDisabled={regenerateDisabled}
              regenerating={regeneratingRunId === run.id}
              feedbackPending={feedbackPendingRunId === run.id}
              onRegenerate={() => onRegenerateRun?.(run.id)}
              onFeedback={(value) => onRunFeedback?.(run.id, value)}
              t={t}
            />
          ) : null}
        </div>
      </div>
    </article>
  )
}

function ReasoningContent({ reasoning }: { reasoning: string }) {
  const scrollRef = React.useRef<HTMLDivElement>(null)
  const shouldFollowRef = React.useRef(true)

  React.useLayoutEffect(() => {
    const element = scrollRef.current
    if (!element || !shouldFollowRef.current) return

    const scrollToBottom = () => {
      if (!shouldFollowRef.current) return
      element.scrollTop = element.scrollHeight
    }
    scrollToBottom()
    const frame = requestAnimationFrame(scrollToBottom)
    const resizeObserver = new ResizeObserver(scrollToBottom)
    resizeObserver.observe(element)
    return () => {
      cancelAnimationFrame(frame)
      resizeObserver.disconnect()
    }
  }, [reasoning])

  return (
    <div
      ref={scrollRef}
      className="mt-1 ml-5 max-h-48 overflow-y-auto border-l pl-3 break-words whitespace-pre-wrap text-foreground/80"
      onScroll={(event) => {
        shouldFollowRef.current = isNearScrollBottom(event.currentTarget)
      }}
    >
      {reasoning}
    </div>
  )
}

export function AgentDetailWorkspace({
  agent,
  form,
  setForm,
  models,
  knowledgeBases,
  tools,
  runs,
  toolCallsByRun,
  resolvingCallId,
  question,
  setQuestion,
  files,
  setFiles,
  pendingQuestion,
  isDirty,
  isSaving,
  isPublishing,
  isAsking,
  isRunsLoading,
  activeView,
  token,
  workspaceId,
  canManagePublishing,
  onBack,
  onDelete,
  onManagePermissions,
  onSave,
  onPublish,
  onViewChange,
  onAsk,
  onCancelAsk,
  onNewConversation,
  onToolCallDecision,
  onRegenerateRun,
  onRunFeedback,
  regeneratingRunId,
  feedbackPendingRunId,
  notify,
  t,
}: AgentDetailWorkspaceProps) {
  const [activePanel, setActivePanel] = React.useState<"config" | "preview">(
    "config"
  )
  const [isConfigVisible, setIsConfigVisible] = React.useState(true)
  const previewScrollRef = React.useRef<HTMLDivElement>(null)
  const fileInputRef = React.useRef<HTMLInputElement>(null)
  const shouldFollowPreviewRef = React.useRef(true)

  React.useEffect(() => {
    const scrollContainer = previewScrollRef.current
    const view = scrollContainer?.ownerDocument.defaultView
    if (!scrollContainer || !view) return

    const handlePageScroll = () => {
      const scrollHost = previewScrollHost(scrollContainer)
      if (scrollHost && scrollHost !== scrollContainer) {
        shouldFollowPreviewRef.current = isNearScrollBottom(scrollHost)
      }
    }
    const followContent = () => {
      if (!shouldFollowPreviewRef.current) return
      const scrollHost = previewScrollHost(scrollContainer)
      if (scrollHost) scrollHost.scrollTop = scrollHost.scrollHeight
    }
    const resizeObserver = new ResizeObserver(followContent)
    if (scrollContainer.firstElementChild) {
      resizeObserver.observe(scrollContainer.firstElementChild)
    }
    view.addEventListener("scroll", handlePageScroll, { passive: true })
    return () => {
      view.removeEventListener("scroll", handlePageScroll)
      resizeObserver.disconnect()
    }
  }, [])

  React.useLayoutEffect(() => {
    const scrollContainer = previewScrollRef.current
    if (!scrollContainer || !shouldFollowPreviewRef.current) return

    const scrollToBottom = () => {
      if (!shouldFollowPreviewRef.current) return
      const scrollHost = previewScrollHost(scrollContainer)
      if (scrollHost) scrollHost.scrollTop = scrollHost.scrollHeight
    }
    scrollToBottom()
    const frame = requestAnimationFrame(scrollToBottom)
    return () => cancelAnimationFrame(frame)
  }, [activePanel, isRunsLoading, pendingQuestion, runs])
  const selectedModel = models.find((model) => model.id === form.modelId)
  const visibleRuns = [...runs].reverse()
  const navigationItems = [
    { view: "overview" as const, label: t("概览"), icon: LayoutDashboardIcon },
    { view: "settings" as const, label: t("设置"), icon: SettingsIcon },
    { view: "logs" as const, label: t("对话日志"), icon: ScrollTextIcon },
    {
      view: "monitoring" as const,
      label: t("监控统计"),
      icon: ChartNoAxesColumnIcon,
    },
    { view: "users" as const, label: t("对话用户"), icon: UsersIcon },
  ].filter(
    (item) => agent.can_edit || ["overview", "settings"].includes(item.view)
  )
  const visibleActiveView =
    !agent.can_edit && ["logs", "monitoring", "users"].includes(activeView)
      ? "overview"
      : activeView
  const currentViewLabel =
    navigationItems.find((item) => item.view === visibleActiveView)?.label ??
    t("概览")
  const publicationAction = agentPublicationAction(agent)
  const renderNavItems = (itemClassName: string) =>
    navigationItems.map(({ view, label, icon: Icon }) => (
      <Button
        key={view}
        type="button"
        variant={visibleActiveView === view ? "secondary" : "ghost"}
        className={itemClassName}
        aria-current={visibleActiveView === view ? "page" : undefined}
        onClick={() => onViewChange(view)}
      >
        <Icon data-icon="inline-start" />
        {label}
      </Button>
    ))

  return (
    <div className="-mx-4 -my-6 flex min-h-[calc(100svh-3.5rem)] flex-col overflow-hidden bg-background sm:-mx-6 lg:-mx-8 lg:h-[calc(100svh-3.5rem)] lg:min-h-0">
      <header className="z-10 flex min-h-16 shrink-0 flex-wrap items-center gap-3 border-b bg-background/95 px-4 py-3 backdrop-blur sm:px-6">
        <Button
          type="button"
          variant="ghost"
          size="icon"
          aria-label={t("返回 Agent 列表")}
          title={t("返回 Agent 列表")}
          onClick={onBack}
        >
          <ArrowLeftIcon />
        </Button>
        <span className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-foreground text-background shadow-sm">
          <BotIcon className="size-5" />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="max-w-52 truncate text-base font-semibold sm:max-w-none">
              {form.name || agent.name}
            </h1>
            <Badge
              variant="outline"
              className={
                agent.status === "active"
                  ? "border-emerald-600/20 bg-emerald-500/10 text-emerald-700 dark:text-emerald-400"
                  : "text-muted-foreground"
              }
            >
              <span
                className={`mr-1.5 size-1.5 rounded-full ${agent.status === "active" ? "bg-emerald-500" : "bg-muted-foreground"}`}
              />
              {t(agent.status === "active" ? "已启用" : "已停用")}
            </Badge>
            {agent.published ? (
              <Badge
                variant="outline"
                className="border-blue-600/20 bg-blue-500/10 text-blue-700 dark:text-blue-400"
              >
                <span className="mr-1.5 size-1.5 rounded-full bg-blue-500" />
                {t("已发布")}
              </Badge>
            ) : null}
            {isDirty ? <Badge variant="secondary">{t("未保存")}</Badge> : null}
          </div>
          <p className="mt-0.5 hidden items-center gap-1.5 truncate text-xs text-muted-foreground sm:flex">
            {selectedModel ? (
              <ModelIcon
                model={selectedModel.model_name}
                size={13}
                type="color"
                className="shrink-0"
              />
            ) : null}
            <span className="truncate">
              {selectedModel?.name ?? t("未连接")} · {currentViewLabel}
            </span>
          </p>
        </div>

        {visibleActiveView === "settings" ? (
          <>
            <Button
              type="button"
              variant="ghost"
              size="icon"
              aria-label={t("新建对话")}
              title={t("新建对话")}
              onClick={onNewConversation}
            >
              <MessageSquarePlusIcon />
            </Button>
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="hidden lg:inline-flex"
              aria-label={t(isConfigVisible ? "预览" : "设置")}
              title={t(isConfigVisible ? "预览" : "设置")}
              onClick={() => setIsConfigVisible((current) => !current)}
            >
              {isConfigVisible ? <PanelLeftCloseIcon /> : <PanelLeftOpenIcon />}
            </Button>
          </>
        ) : null}
        {agent.can_edit ? (
          <>
            {canManagePublishing ? (
              <Button
                type="button"
                variant="outline"
                disabled={isSaving || isPublishing || isDirty}
                title={isDirty ? t("请先保存更改后再发布。") : undefined}
                onClick={onPublish}
              >
                {isPublishing ? (
                  <LoaderCircleIcon className="animate-spin" />
                ) : publicationAction === "unpublish" ? (
                  <Undo2Icon />
                ) : (
                  <RocketIcon />
                )}
                <span className="hidden sm:inline">
                  {t(
                    publicationAction === "unpublish"
                      ? "取消发布"
                      : publicationAction === "republish"
                        ? "重新发布"
                        : "发布"
                  )}
                </span>
              </Button>
            ) : null}
            {visibleActiveView === "settings" ? (
              <Button
                type="submit"
                form="agent-settings-form"
                disabled={
                  isSaving || !isDirty || !form.name.trim() || !form.modelId
                }
              >
                {isSaving ? (
                  <LoaderCircleIcon className="animate-spin" />
                ) : (
                  <SaveIcon />
                )}
                <span className="hidden sm:inline">{t("保存")}</span>
              </Button>
            ) : null}
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  aria-label={t("设置")}
                  title={t("设置")}
                >
                  <MoreHorizontalIcon />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent
                side="bottom"
                align="start"
                className="min-w-40"
              >
                <DropdownMenuItem onSelect={onManagePermissions}>
                  <ShieldCheckIcon />
                  {t("资源授权")}
                </DropdownMenuItem>
                <DropdownMenuItem variant="destructive" onSelect={onDelete}>
                  <Trash2Icon />
                  {t("删除 Agent")}
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </>
        ) : null}
      </header>

      <div className="flex min-h-0 flex-1">
        <aside className="hidden w-52 shrink-0 border-r bg-muted/20 p-3 lg:block">
          <nav className="space-y-1" aria-label={t("Agent 详情导航")}>
            {renderNavItems("w-full justify-start")}
          </nav>
        </aside>

        <div className="flex min-w-0 flex-1 flex-col">
          <nav
            className="flex shrink-0 gap-1 overflow-x-auto border-b bg-background p-2 lg:hidden"
            aria-label={t("Agent 详情导航")}
          >
            {renderNavItems("shrink-0")}
          </nav>

          {visibleActiveView === "settings" ? (
            <>
              <nav className="grid shrink-0 grid-cols-2 border-b bg-background p-1 lg:hidden">
                <Button
                  type="button"
                  variant={activePanel === "config" ? "secondary" : "ghost"}
                  onClick={() => setActivePanel("config")}
                >
                  <DatabaseIcon />
                  {t("基本信息")}
                </Button>
                <Button
                  type="button"
                  variant={activePanel === "preview" ? "secondary" : "ghost"}
                  onClick={() => {
                    shouldFollowPreviewRef.current = true
                    setActivePanel("preview")
                  }}
                >
                  <MessageSquareIcon />
                  {t("调试预览")}
                </Button>
              </nav>

              <main className="flex min-h-0 flex-1 bg-muted/20">
                <section
                  className={`${activePanel === "config" ? "flex" : "hidden"} min-h-0 w-full flex-col border-r bg-muted/30 lg:flex ${isConfigVisible ? "lg:w-[46%] lg:max-w-[680px]" : "lg:hidden"}`}
                >
                  <div className="flex items-center justify-between border-b bg-background/70 px-5 py-3">
                    <div>
                      <h2 className="text-sm font-semibold">{t("基本信息")}</h2>
                      <p className="text-xs text-muted-foreground">
                        {t("配置 Agent 使用的模型、知识库和工具。")}
                      </p>
                    </div>
                    <div className="hidden items-center gap-3 text-xs text-muted-foreground sm:flex">
                      <span className="flex items-center gap-1.5">
                        <DatabaseIcon className="size-3.5" />
                        {form.knowledgeBaseIds.length}
                      </span>
                      <span className="flex items-center gap-1.5">
                        <WrenchIcon className="size-3.5" />
                        {form.tools.length}
                      </span>
                    </div>
                  </div>
                  <div className="min-h-0 flex-1 overflow-y-auto p-4 sm:p-5">
                    <form id="agent-settings-form" onSubmit={onSave}>
                      <AgentConfigFields
                        form={form}
                        setForm={setForm}
                        models={models}
                        knowledgeBases={knowledgeBases}
                        tools={tools}
                        token={token}
                        workspaceId={workspaceId}
                        hasLegacyToolBindings={
                          agent.tools === undefined &&
                          Boolean(agent.mcp_tools?.length)
                        }
                        readOnly={!agent.can_edit}
                        t={t}
                      />
                    </form>
                  </div>
                </section>

                <section
                  className={`${activePanel === "preview" ? "flex" : "hidden"} min-h-[680px] min-w-0 flex-1 flex-col bg-background lg:flex lg:min-h-0`}
                >
                  <div className="flex items-center justify-between border-b px-5 py-3">
                    <div>
                      <h2 className="text-sm font-semibold">{t("调试预览")}</h2>
                      <p className="text-xs text-muted-foreground">
                        {t("保存配置后，在这里直接提问。")}
                      </p>
                    </div>
                    <Badge
                      variant="outline"
                      className="font-normal text-muted-foreground"
                    >
                      <span className="mr-1.5 size-1.5 rounded-full bg-emerald-500" />
                      {t("预览")}
                    </Badge>
                  </div>

                  <div
                    ref={previewScrollRef}
                    className="relative min-h-0 flex-1 overflow-y-auto bg-muted/20"
                    onScroll={(event) => {
                      if (
                        previewScrollHost(event.currentTarget) ===
                        event.currentTarget
                      ) {
                        shouldFollowPreviewRef.current = isNearScrollBottom(
                          event.currentTarget
                        )
                      }
                    }}
                  >
                    <div className="mx-auto flex min-h-full w-full max-w-3xl flex-col px-4 py-8 sm:px-8">
                      {isRunsLoading ? (
                        <div className="flex min-h-72 flex-1 items-center justify-center text-muted-foreground">
                          <LoaderCircleIcon className="mr-2 size-4 animate-spin" />
                          {t("正在加载")}
                        </div>
                      ) : visibleRuns.length === 0 && !pendingQuestion ? (
                        <div className="flex min-h-72 flex-1 flex-col items-center justify-center text-center">
                          <span className="relative flex size-16 items-center justify-center rounded-2xl bg-foreground text-background shadow-lg">
                            <BotIcon className="size-7" />
                            <span className="absolute -right-1 -bottom-1 size-4 rounded-full border-2 border-muted bg-emerald-500" />
                          </span>
                          <p className="mt-5 text-base font-semibold">
                            {t("开始和 Agent 对话")}
                          </p>
                          <p className="mt-2 max-w-md text-sm leading-6 text-muted-foreground">
                            {t(
                              "直接提问，Agent 会按需使用已配置的知识库和工具。"
                            )}
                          </p>
                        </div>
                      ) : (
                        <div className="space-y-8">
                          {visibleRuns.map((run) => (
                            <RunExchange
                              key={run.id}
                              run={run}
                              toolCalls={toolCallsByRun[run.id] ?? []}
                              resolvingCallId={resolvingCallId}
                              onToolCallDecision={onToolCallDecision}
                              onRegenerateRun={onRegenerateRun}
                              onRunFeedback={onRunFeedback}
                              regenerateDisabled={isAsking || isRunsLoading}
                              regeneratingRunId={regeneratingRunId}
                              feedbackPendingRunId={feedbackPendingRunId}
                              t={t}
                            />
                          ))}
                        </div>
                      )}
                    </div>
                  </div>

                  <div className="shrink-0 border-t bg-background p-3 sm:p-4">
                    <form
                      className="relative mx-auto max-w-3xl rounded-2xl border bg-background p-2 shadow-sm transition-shadow focus-within:shadow-md"
                      onSubmit={(event) => {
                        shouldFollowPreviewRef.current = true
                        onAsk(event)
                      }}
                    >
                      <input
                        ref={fileInputRef}
                        type="file"
                        className="sr-only"
                        multiple
                        accept={acceptedUploadExtensions(
                          AGENT_FILE_UPLOAD_SETTING.file_upload_type
                        )}
                        disabled={
                          isDirty ||
                          isAsking ||
                          isRunsLoading ||
                          agent.status !== "active"
                        }
                        onChange={(event) => {
                          const selected = Array.from(event.target.files ?? [])
                          setFiles(selected)
                        }}
                      />
                      <textarea
                        value={question}
                        onChange={(event) => setQuestion(event.target.value)}
                        onKeyDown={(event) => {
                          if (
                            event.key === "Enter" &&
                            !event.shiftKey &&
                            !event.nativeEvent.isComposing
                          ) {
                            event.preventDefault()
                            event.currentTarget.form?.requestSubmit()
                          }
                        }}
                        className={`max-h-40 min-h-28 w-full resize-none bg-transparent px-3 pt-2 text-sm leading-6 outline-none placeholder:text-muted-foreground disabled:cursor-not-allowed ${files.length ? "pb-2" : "pb-14"}`}
                        placeholder={
                          isDirty
                            ? t("请先保存配置后再调试")
                            : t("向 Agent 提问...")
                        }
                        aria-label={t("向 Agent 提问")}
                        disabled={
                          isDirty ||
                          isRunsLoading ||
                          isAsking ||
                          agent.status !== "active"
                        }
                        maxLength={4000}
                        rows={2}
                      />
                      <AgentAttachmentList
                        files={files}
                        onRemove={(indexToRemove) =>
                          setFiles((current) =>
                            current.filter(
                              (_, index) => index !== indexToRemove
                            )
                          )
                        }
                        t={t}
                      />
                      <div className="absolute right-2 bottom-2 flex items-center gap-2">
                        <Button
                          type="button"
                          variant="ghost"
                          size="icon-lg"
                          className="rounded-xl"
                          aria-label={t("添加附件")}
                          title={t("添加附件")}
                          disabled={
                            isDirty ||
                            isAsking ||
                            isRunsLoading ||
                            agent.status !== "active"
                          }
                          onClick={() => {
                            if (!fileInputRef.current) return
                            fileInputRef.current.value = ""
                            fileInputRef.current.click()
                          }}
                        >
                          <PaperclipIcon />
                        </Button>
                        <Button
                          type={isAsking ? "button" : "submit"}
                          size="icon-lg"
                          className="rounded-xl"
                          aria-label={t(isAsking ? "停止生成" : "发送问题")}
                          title={t(isAsking ? "停止生成" : "发送问题")}
                          onClick={isAsking ? onCancelAsk : undefined}
                          disabled={
                            !isAsking &&
                            (!question.trim() ||
                              isDirty ||
                              isRunsLoading ||
                              agent.status !== "active")
                          }
                        >
                          {isAsking ? (
                            <SquareIcon className="fill-current" />
                          ) : (
                            <SendIcon />
                          )}
                        </Button>
                      </div>
                    </form>
                  </div>
                </section>
              </main>
            </>
          ) : (
            <main className="min-h-0 flex-1 overflow-y-auto bg-muted/20">
              {visibleActiveView === "overview" ? (
                <AgentOverviewPanel
                  key={`${agent.id}:overview`}
                  agent={agent}
                  token={token}
                  workspaceId={workspaceId}
                  canViewCredentials={agent.can_edit}
                  canManageCredentials={canManagePublishing && agent.can_edit}
                  t={t}
                  notify={notify}
                />
              ) : visibleActiveView === "logs" ? (
                <AgentLogsPanel
                  key={`${agent.id}:logs`}
                  agent={agent}
                  token={token}
                  workspaceId={workspaceId}
                  t={t}
                  notify={notify}
                />
              ) : visibleActiveView === "monitoring" ? (
                <AgentMonitoringPanel
                  key={`${agent.id}:monitoring`}
                  agent={agent}
                  token={token}
                  workspaceId={workspaceId}
                  t={t}
                  notify={notify}
                />
              ) : (
                <AgentConversationUsersPanel
                  key={`${agent.id}:users`}
                  agent={agent}
                  token={token}
                  workspaceId={workspaceId}
                  t={t}
                  notify={notify}
                />
              )}
            </main>
          )}
        </div>
      </div>
    </div>
  )
}
