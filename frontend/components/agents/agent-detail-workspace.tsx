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
  MoreHorizontalIcon,
  PanelLeftCloseIcon,
  PanelLeftOpenIcon,
  RocketIcon,
  SaveIcon,
  SendIcon,
  ShieldAlertIcon,
  Trash2Icon,
  Undo2Icon,
  WrenchIcon,
} from "lucide-react"

import { MarkdownContent } from "@/components/knowledge/markdown-content"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import type { TFunction } from "@/i18n"
import type { Agent, AgentRun, AgentToolCall } from "@/lib/api/agents"
import type { KnowledgeBase } from "@/lib/api/knowledge"
import type { RegisteredModel } from "@/lib/api/llm"
import type { McpServer } from "@/lib/api/mcp"

import { AgentConfigFields } from "./agent-config-fields"
import type { AgentFormState } from "./agents-page"

type AgentDetailWorkspaceProps = {
  agent: Agent
  form: AgentFormState
  setForm: React.Dispatch<React.SetStateAction<AgentFormState>>
  models: RegisteredModel[]
  knowledgeBases: KnowledgeBase[]
  mcpServers: McpServer[]
  runs: AgentRun[]
  toolCallsByRun: Record<string, AgentToolCall[]>
  resolvingCallId: string | null
  question: string
  setQuestion: React.Dispatch<React.SetStateAction<string>>
  pendingQuestion: string | null
  isDirty: boolean
  isSaving: boolean
  isAsking: boolean
  isRunsLoading: boolean
  onBack: () => void
  onDelete: () => void
  onSave: (event: React.FormEvent<HTMLFormElement>) => void
  onPublish: () => void
  onAsk: (event: React.FormEvent<HTMLFormElement>) => void
  onCancelAsk: () => void
  onToolCallDecision: (
    runId: string,
    callId: string,
    decision: "approve" | "reject"
  ) => void
  t: TFunction
}

const AUTO_FOLLOW_THRESHOLD_PX = 64

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
  const label = event.tool_label || event.tool_name

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

  const events = deduplicated.filter(
    (event) => !eagerKnowledge.includes(event)
  )
  const firstThought = events.findIndex((event) => event.type === "thought")
  if (firstThought === -1) {
    return deduplicated.map((event) => ({ event, count: 1 }))
  }
  events.splice(firstThought + 1, 0, ...eagerKnowledge)
  return events.map((event) => ({ event, count: 1 }))
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

function ToolApprovalPanel({
  run,
  calls,
  resolvingCallId,
  onDecision,
  t,
}: {
  run: AgentRun
  calls: AgentToolCall[]
  resolvingCallId: string | null
  onDecision: (callId: string, decision: "approve" | "reject") => void
  t: TFunction
}) {
  const pendingCalls = calls.filter((call) =>
    ["awaiting_approval", "uncertain"].includes(call.status)
  )
  if (pendingCalls.length === 0) return null

  return (
    <div className="mb-4 space-y-3">
      {pendingCalls.map((call) => {
        const isUncertain = call.status === "uncertain"
        const isResolving = resolvingCallId === `${run.id}:${call.call_id}`
        return (
          <section
            key={`${call.turn}:${call.call_id}`}
            className="rounded-lg border border-amber-600/30 bg-amber-500/5 p-3"
          >
            <div className="flex items-start gap-2">
              <ShieldAlertIcon className="mt-0.5 size-4 shrink-0 text-amber-700 dark:text-amber-400" />
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium">
                  {t(isUncertain ? "工具执行结果不确定" : "工具调用需要确认")}
                </p>
                <p className="mt-0.5 truncate text-xs text-muted-foreground">
                  {call.tool_name}
                  {call.server_name ? ` @ ${call.server_name}` : ""}
                </p>
              </div>
            </div>
            {call.last_error ? (
              <p className="mt-3 text-xs leading-5 text-muted-foreground">
                {call.last_error}
              </p>
            ) : null}
            <pre className="mt-3 max-h-40 overflow-auto rounded-md border bg-background p-3 text-xs leading-5 break-words whitespace-pre-wrap">
              {JSON.stringify(call.arguments, null, 2)}
            </pre>
            <div className="mt-3 flex justify-end gap-2">
              <Button
                type="button"
                variant="outline"
                size="sm"
                disabled={isResolving}
                onClick={() => onDecision(call.call_id, "reject")}
              >
                {isResolving ? (
                  <LoaderCircleIcon className="animate-spin" />
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
                    <LoaderCircleIcon className="animate-spin" />
                  ) : null}
                  {t("批准并执行")}
                </Button>
              ) : null}
            </div>
          </section>
        )
      })}
    </div>
  )
}

function RunExchange({
  run,
  toolCalls,
  resolvingCallId,
  onToolCallDecision,
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
  t: TFunction
}) {
  const timeline = processTimeline(run)
  const hasProcess = timeline.length > 0
  const answer = run.result
  const [isProcessOpen, setIsProcessOpen] = React.useState(true)
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
            <ToolApprovalPanel
              run={run}
              calls={toolCalls}
              resolvingCallId={resolvingCallId}
              onDecision={(callId, decision) =>
                onToolCallDecision(run.id, callId, decision)
              }
              t={t}
            />
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
                </div>
              </details>
            ) : null}

            {run.result ? (
              <MarkdownContent content={answer} className="text-sm leading-6" />
            ) : run.status === "failed" ? (
              <p className="rounded-md border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
                {run.last_error ?? t("Agent 未返回结果")}
              </p>
            ) : run.status === "awaiting_approval" ? (
              <p className="text-sm text-muted-foreground">
                {t("等待工具调用确认")}
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
          {run.status !== "running" && answer ? (
            <div className="mt-1 flex">
              <CopyMessageButton value={answer} t={t} />
            </div>
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
  mcpServers,
  runs,
  toolCallsByRun,
  resolvingCallId,
  question,
  setQuestion,
  pendingQuestion,
  isDirty,
  isSaving,
  isAsking,
  isRunsLoading,
  onBack,
  onDelete,
  onSave,
  onPublish,
  onAsk,
  onCancelAsk,
  onToolCallDecision,
  t,
}: AgentDetailWorkspaceProps) {
  const [activePanel, setActivePanel] = React.useState<"config" | "preview">(
    "config"
  )
  const [isConfigVisible, setIsConfigVisible] = React.useState(true)
  const previewScrollRef = React.useRef<HTMLDivElement>(null)
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
              {selectedModel?.name ?? t("未连接")} · {t("设置")}
            </span>
          </p>
        </div>

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
        {agent.can_edit ? (
          <>
            <Button
              type="button"
              variant="outline"
              disabled={isSaving}
              onClick={onPublish}
            >
              {agent.published ? <Undo2Icon /> : <RocketIcon />}
              <span className="hidden sm:inline">
                {t(agent.published ? "取消发布" : "发布")}
              </span>
            </Button>
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
              <DropdownMenuContent align="end">
                <DropdownMenuItem variant="destructive" onSelect={onDelete}>
                  <Trash2Icon />
                  {t("删除 Agent")}
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </>
        ) : null}
      </header>

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
                {t("配置 Agent 使用的模型、知识库和 MCP 工具。")}
              </p>
            </div>
            <div className="hidden items-center gap-3 text-xs text-muted-foreground sm:flex">
              <span className="flex items-center gap-1.5">
                <DatabaseIcon className="size-3.5" />
                {form.knowledgeBaseIds.length}
              </span>
              <span className="flex items-center gap-1.5">
                <WrenchIcon className="size-3.5" />
                {form.mcpTools.length}
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
                mcpServers={mcpServers}
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
              if (previewScrollHost(event.currentTarget) === event.currentTarget) {
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
                    {t("直接提问，Agent 会按需使用已配置的知识库和 MCP 工具。")}
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
                      t={t}
                    />
                  ))}
                </div>
              )}
            </div>
          </div>

          <div className="shrink-0 border-t bg-background p-3 sm:p-4">
            <form
              className="mx-auto max-w-3xl rounded-2xl border bg-background p-2 shadow-sm transition-shadow focus-within:shadow-md"
              onSubmit={(event) => {
                shouldFollowPreviewRef.current = true
                onAsk(event)
              }}
            >
              <div className="flex items-end gap-2">
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
                  className="max-h-40 min-h-14 min-w-0 flex-1 resize-none bg-transparent px-3 py-2 text-sm leading-6 outline-none placeholder:text-muted-foreground disabled:cursor-not-allowed"
                  placeholder={
                    isDirty ? t("请先保存配置后再调试") : t("向 Agent 提问...")
                  }
                  aria-label={t("向 Agent 提问")}
                  disabled={isDirty || isAsking || agent.status !== "active"}
                  maxLength={4000}
                  rows={2}
                />
                {isAsking ? (
                  <Button
                    type="button"
                    variant="outline"
                    className="rounded-xl"
                    aria-label={t("停止查看")}
                    title={t("停止查看")}
                    onClick={onCancelAsk}
                  >
                    <CircleXIcon />
                    {t("停止查看")}
                  </Button>
                ) : null}
                <Button
                  type="submit"
                  size="icon-lg"
                  className="rounded-xl"
                  aria-label={t("发送问题")}
                  title={t("发送问题")}
                  disabled={
                    !question.trim() ||
                    isDirty ||
                    isAsking ||
                    agent.status !== "active"
                  }
                >
                  {isAsking ? (
                    <LoaderCircleIcon className="animate-spin" />
                  ) : (
                    <SendIcon />
                  )}
                </Button>
              </div>
            </form>
          </div>
        </section>
      </main>
    </div>
  )
}
