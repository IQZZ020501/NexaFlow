"use client"

import * as React from "react"
import { useRouter } from "next/navigation"
import {
  BotIcon,
  BrainIcon,
  CheckIcon,
  ChevronDownIcon,
  CircleCheckIcon,
  CircleAlertIcon,
  CircleXIcon,
  CopyIcon,
  DatabaseIcon,
  DownloadIcon,
  EllipsisIcon,
  HistoryIcon,
  LoaderCircleIcon,
  MenuIcon,
  MessageSquarePlusIcon,
  PaperclipIcon,
  SendIcon,
  ShieldAlertIcon,
  SquareIcon,
  SearchIcon,
  UserIcon,
  WrenchIcon,
} from "lucide-react"

import { MarkdownContent } from "@/components/knowledge/markdown-content"
import { RunActionBar } from "@/components/app/run-action-bar"
import { useConfirmDialog } from "@/components/app/confirm-dialog"
import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { AgentAttachmentList } from "@/components/agents/agent-attachment-list"
import { ToolInputPreview } from "@/components/agents/tool-input-preview"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { useLanguage } from "@/contexts/language-provider"
import { useSession } from "@/contexts/session-context"
import type { TFunction } from "@/i18n"
import { compareLiveStreamIds } from "@/lib/api/agents"
import type { AgentToolCall } from "@/lib/api/agents"
import {
  initializePublicAgent,
  deletePublicAgentConversation,
  listPublicAgentConversations,
  listPublicAgentRuns,
  listPublicAgentRunToolCalls,
  observePublicAgentRun,
  regeneratePublicAgentRun,
  resolvePublicAgentRunToolCall,
  setPublicAgentRunFeedback,
  streamPublicAgentRun,
  uploadPublicAgentFiles,
  type ExternalAgentProgressEvent,
  type ExternalAgentRun,
  type PublicAgentConversation,
  type PublicAgentProfile,
  type PublicAgentRunStreamEvent,
} from "@/lib/api/public-agents"
import { getErrorMessage } from "@/lib/errors"
import {
  downloadConversationMarkdown,
  type ConversationExportMessage,
} from "@/lib/conversation-export"
import { latestRunVersions } from "@/lib/run-versions"
import {
  AGENT_FILE_UPLOAD_SETTING,
  acceptedUploadExtensions,
} from "@/lib/interaction-config"
import {
  builtinToolDisplayName,
  withArtifactDownloadLinks,
} from "@/lib/tool-display"

type PublicAgentChatProps = {
  agentId: string
  initialConversationId?: string | null
}

function CopyMessageButton({ value }: { value: string }) {
  const { t } = useLanguage()
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

function ReasoningBlock({ reasoning }: { reasoning: string }) {
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
        const element = event.currentTarget
        shouldFollowRef.current =
          element.scrollHeight - element.scrollTop - element.clientHeight < 32
      }}
    >
      {reasoning}
    </div>
  )
}

export function publicToolName(
  event: ExternalAgentProgressEvent,
  t?: TFunction
) {
  const fallback = event.tool_label || event.tool_name || ""
  return t
    ? (builtinToolDisplayName(event.tool_name || "", t) ?? fallback)
    : fallback
}

export function hasPublicToolDetails(event: ExternalAgentProgressEvent) {
  if (event.type === "knowledge") return event.status === "succeeded"
  if (event.type !== "tool") return false
  return (
    Object.keys(event.input ?? {}).length > 0 ||
    (event.output !== null && event.output !== undefined)
  )
}

/**
 * Renders a knowledge retrieval or tool execution event with its status and optional expandable details.
 *
 * @param event - The progress event to display.
 * @param title - The event title.
 * @param detail - Optional secondary event detail.
 * @param statusIcon - The status indicator to display.
 */
function PublicToolEventRow({
  event,
  title,
  detail,
  statusIcon,
}: {
  event: ExternalAgentProgressEvent
  title: string
  detail: string | null
  statusIcon: React.ReactNode
}) {
  const { t } = useLanguage()
  const isPreparing = event.stage === "preparing"
  const [isOpen, setIsOpen] = React.useState(false)
  const canExpand = hasPublicToolDetails(event)

  const leading = (
    <>
      <span className="flex size-7 shrink-0 items-center justify-center rounded-md bg-sky-500/10 text-sky-700 dark:text-sky-400">
        {event.type === "knowledge" ? (
          <DatabaseIcon className="size-3.5" />
        ) : (
          <WrenchIcon className="size-3.5" />
        )}
      </span>
      <span className="min-w-0 flex-1">
        <span className="block truncate text-sm font-medium text-foreground">
          {title}
          {event.server_name ? (
            <span className="ml-1 font-normal text-muted-foreground">
              @ {event.server_name}
            </span>
          ) : null}
        </span>
        {detail ? (
          <span className="block truncate text-xs text-muted-foreground">
            {detail}
          </span>
        ) : null}
      </span>
      {statusIcon}
    </>
  )

  return (
    <div className="overflow-hidden rounded-lg border bg-background/70">
      {canExpand ? (
        <button
          type="button"
          className="flex w-full items-center gap-2 px-3 py-2 text-left hover:bg-muted/50"
          aria-expanded={isOpen}
          onClick={() => setIsOpen((current) => !current)}
        >
          {leading}
          <ChevronDownIcon
            className={`size-4 text-muted-foreground transition-transform ${isOpen ? "rotate-180" : ""}`}
          />
        </button>
      ) : (
        <div className="flex items-center gap-2 px-3 py-2">{leading}</div>
      )}
      {canExpand && isOpen ? (
        <div className="grid gap-3 border-t bg-muted/20 p-3 text-xs">
          {Object.keys(event.input ?? {}).length > 0 ? (
            <div>
              <p className="mb-1 font-medium text-muted-foreground">
                {t("调用输入")}
                {event.input_truncated ? (
                  <span className="ml-1">({t("内容过长已截断")})</span>
                ) : null}
              </p>
              <ToolInputPreview
                input={event.input ?? {}}
                streaming={isPreparing}
              />
            </div>
          ) : null}
          {event.type === "knowledge" ? (
            <div>
              <p className="mb-1 font-medium text-muted-foreground">
                {t("调用结果")}
              </p>
              {event.hits.length > 0 ? (
                <div className="space-y-2">
                  {event.hits.map((hit, index) => (
                    <article
                      key={index}
                      className="rounded-md border bg-background p-3"
                    >
                      <div className="flex flex-wrap items-center gap-2 font-medium">
                        <span>{hit.document || t("未知文档")}</span>
                        <span className="text-muted-foreground">
                          {hit.knowledge_base}
                        </span>
                      </div>
                      <p className="mt-2 leading-5 break-words whitespace-pre-wrap text-muted-foreground">
                        {hit.content}
                      </p>
                    </article>
                  ))}
                </div>
              ) : (
                <p className="text-muted-foreground">
                  {t("未检索到相关知识片段")}
                </p>
              )}
            </div>
          ) : event.output !== null && event.output !== undefined ? (
            <div>
              <p className="mb-1 font-medium text-muted-foreground">
                {t("调用结果")}
              </p>
              <pre className="rounded-md bg-background p-3 font-mono leading-5 [overflow-wrap:anywhere] whitespace-pre-wrap">
                {typeof event.output === "string"
                  ? event.output
                  : JSON.stringify(event.output, null, 2)}
              </pre>
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  )
}

function PublicToolApproval({
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
  const isResolving = resolvingCallId === `${runId}:${call.call_id}`
  return (
    <section className="overflow-hidden rounded-lg border border-amber-600/30 bg-background/80">
      <div className="flex flex-wrap items-center gap-2 px-3 py-2">
        <span className="flex size-7 shrink-0 items-center justify-center rounded-md bg-amber-500/10 text-amber-700 dark:text-amber-400">
          <ShieldAlertIcon className="size-3.5" />
        </span>
        <div className="min-w-0 flex-1">
          <p className="truncate text-xs font-medium text-foreground">
            {t("工具调用需要确认")}
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
            {t("拒绝")}
          </Button>
          <Button
            type="button"
            size="xs"
            disabled={isResolving}
            onClick={() => onDecision(call.call_id, "approve")}
          >
            {isResolving ? <LoaderCircleIcon className="animate-spin" /> : null}
            {t("批准并执行")}
          </Button>
        </div>
      </div>
      <pre className="max-h-28 overflow-auto border-t bg-muted/20 px-3 py-2 font-mono text-[11px] leading-4 break-words whitespace-pre-wrap">
        {JSON.stringify(call.arguments, null, 2)}
      </pre>
    </section>
  )
}

function PublicExecutionProcess({ run }: { run: ExternalAgentRun }) {
  const { t } = useLanguage()
  const [isOpen, setIsOpen] = React.useState(true)
  const timeline = React.useMemo(() => {
    if (run.progress.some((event) => event.type === "analysis")) {
      return run.progress
    }
    const firstAnswer = run.progress.find((event) => event.type === "answer")
    if (!firstAnswer) return run.progress
    return run.progress.flatMap((event) =>
      event.id === firstAnswer.id
        ? [
            {
              ...firstAnswer,
              id: `${firstAnswer.id}-analysis`,
              type: "analysis" as const,
              status: "succeeded" as const,
              stage: "completed" as const,
              count: null,
            },
            event,
          ]
        : [event]
    )
  }, [run.progress])

  function title(event: ExternalAgentProgressEvent) {
    if (event.type === "knowledge") return t("知识库检索")
    if (event.type === "tool") return publicToolName(event, t) || t("工具")
    if (event.type === "answer")
      return t(event.status === "succeeded" ? "回答已生成" : "正在生成回答")
    if (event.stage === "preparing") return t("正在准备工具调用")
    if (event.stage === "running") return t("正在分析问题")
    if (event.stage === "reviewing") return t("正在整理工具结果")
    if (event.stage === "completed") return t("已完成分析")
    return t("正在分析问题")
  }

  function detail(event: ExternalAgentProgressEvent) {
    if (event.type === "analysis" || event.type === "answer") return null
    if (event.stage === "preparing") return null
    if (event.status === "running") {
      return t("正在调用 {name}", { name: title(event) })
    }
    if (event.status === "failed") {
      return typeof event.output === "string" && event.output
        ? event.output
        : t("调用失败")
    }
    if (event.type === "knowledge" && event.count !== null) {
      return t("已检索 {value} 个知识片段", { value: event.count })
    }
    return t("完成")
  }

  function statusIcon(event: ExternalAgentProgressEvent) {
    if (event.status === "running") {
      return <LoaderCircleIcon className="size-4 animate-spin text-sky-600" />
    }
    if (event.status === "failed") {
      return <CircleXIcon className="size-4 text-destructive" />
    }
    return <CircleCheckIcon className="size-4 text-emerald-600" />
  }

  return (
    <details
      className="group mb-4 rounded-xl bg-muted/50 px-3 py-2.5 text-sm"
      open={isOpen}
      onToggle={(event) => setIsOpen(event.currentTarget.open)}
    >
      <summary className="flex cursor-pointer list-none items-center gap-2 font-medium text-muted-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 [&::-webkit-details-marker]:hidden">
        <BrainIcon className="size-4" />
        <span className="flex-1">{t("执行过程")}</span>
        <ChevronDownIcon className="size-4 transition-transform group-open:rotate-180" />
      </summary>
      <div className="mt-2 space-y-2 border-l pl-4">
        {timeline.length === 0 ? (
          <div className="flex items-center gap-2 py-1 text-xs text-muted-foreground">
            <LoaderCircleIcon className="size-4 animate-spin" />
            {t(run.status === "queued" ? "等待执行" : "正在生成回答")}
          </div>
        ) : (
          timeline.map((event) => {
            const eventDetail = detail(event)
            return event.type === "knowledge" || event.type === "tool" ? (
              <PublicToolEventRow
                key={event.id}
                event={event}
                title={title(event)}
                detail={eventDetail}
                statusIcon={statusIcon(event)}
              />
            ) : (
              <div
                key={event.id}
                className="px-1 py-1 text-xs text-muted-foreground"
              >
                <div className="flex items-center gap-2">
                  {statusIcon(event)}
                  <span>{title(event)}</span>
                </div>
                {event.reasoning ? (
                  <ReasoningBlock reasoning={event.reasoning} />
                ) : null}
              </div>
            )
          })
        )}
      </div>
    </details>
  )
}

/**
 * Applies a streamed Agent run event to the corresponding run state.
 *
 * @param runs - The current Agent runs.
 * @param runId - The identifier of the run receiving incremental updates.
 * @param event - The streamed event to merge.
 * @param placeholderId - The temporary run identifier replaced by initial run metadata.
 * @returns The updated Agent runs.
 */
export function mergePublicRunEvent(
  runs: ExternalAgentRun[],
  runId: string,
  event: PublicAgentRunStreamEvent,
  placeholderId: string
) {
  if (event.type === "run") {
    return runs.map((run) =>
      run.id === placeholderId || run.id === event.run.id
        ? {
            ...event.run,
            result: event.run.result || run.result,
            live_stream_epoch: event.stream_epoch ?? run.live_stream_epoch,
            live_stream_cursor: event.live_sequence ?? run.live_stream_cursor,
            progress:
              event.run.progress.length > 0 ? event.run.progress : run.progress,
          }
        : run
    )
  }
  if (event.type === "progress") {
    return runs.map((run) => {
      if (run.id !== runId) return run
      const index = run.progress.findIndex(
        (progress) => progress.id === event.event.id
      )
      const progress = [...run.progress]
      if (index === -1) progress.push(event.event)
      else {
        const current = progress[index]
        progress[index] =
          current?.stage === "preparing" && event.event.type === "tool"
            ? {
                ...event.event,
                input: Object.fromEntries(
                  [
                    ...new Set([
                      ...Object.keys(current.input ?? {}),
                      ...Object.keys(event.event.input ?? {}),
                    ]),
                  ].map((field) => {
                    const currentValue = current.input?.[field]
                    const nextValue = event.event.input?.[field]
                    return [
                      field,
                      typeof currentValue === "string" &&
                      typeof nextValue === "string" &&
                      currentValue.length > nextValue.length &&
                      currentValue.startsWith(nextValue)
                        ? currentValue
                        : (nextValue ?? currentValue),
                    ]
                  })
                ),
                input_truncated:
                  current.input_truncated || event.event.input_truncated,
              }
            : event.event
      }
      if (event.event.type === "answer" && event.event.reasoning) {
        const analysisIndex = progress.findIndex(
          (item) => item.type === "analysis" && item.turn === event.event.turn
        )
        if (analysisIndex !== -1 && progress[analysisIndex]?.reasoning) {
          progress[analysisIndex] = {
            ...progress[analysisIndex],
            reasoning: "",
          }
        }
      }
      return { ...run, progress }
    })
  }
  if (event.type === "tool_input_delta") {
    return runs.map((run) => {
      if (run.id !== runId) return run
      const sameStream =
        !event.stream_epoch || event.stream_epoch === run.live_stream_epoch
      if (
        sameStream &&
        event.live_sequence &&
        run.live_stream_cursor &&
        compareLiveStreamIds(event.live_sequence, run.live_stream_cursor) <= 0
      ) {
        return run
      }
      const progress = [...run.progress]
      const index = progress.findIndex((item) => item.id === event.id)
      if (index === -1) {
        progress.push({
          id: event.id,
          type: "tool",
          status: "running",
          stage: "preparing",
          turn: event.turn,
          count: null,
          tool_name: event.tool_name,
          tool_label: event.tool_name,
          tool_kind: "unknown",
          server_name: "",
          input: { [event.field]: event.delta },
          output: null,
          input_truncated: event.input_truncated,
          hits: [],
        })
      } else {
        const current = progress[index]
        const input = sameStream ? (current.input ?? {}) : {}
        const currentValue =
          typeof input[event.field] === "string"
            ? String(input[event.field])
            : ""
        progress[index] = {
          ...current,
          tool_name: event.tool_name || current.tool_name,
          tool_label: event.tool_name || current.tool_label,
          input: {
            ...input,
            [event.field]: event.replace
              ? event.delta
              : currentValue + event.delta,
          },
          input_truncated: current.input_truncated || event.input_truncated,
        }
      }
      return {
        ...run,
        progress,
        live_stream_epoch: event.stream_epoch ?? run.live_stream_epoch,
        live_stream_cursor: event.live_sequence ?? run.live_stream_cursor,
      }
    })
  }
  if (event.type === "answer_delta") {
    return runs.map((run) =>
      run.id === runId
        ? (() => {
            const sameStream =
              !event.stream_epoch ||
              event.stream_epoch === run.live_stream_epoch
            if (
              sameStream &&
              event.live_sequence &&
              run.live_stream_cursor &&
              compareLiveStreamIds(
                event.live_sequence,
                run.live_stream_cursor
              ) <= 0
            ) {
              return run
            }
            return {
              ...run,
              result: sameStream ? run.result + event.delta : event.delta,
              live_stream_epoch: event.stream_epoch ?? run.live_stream_epoch,
              live_stream_cursor: event.live_sequence ?? run.live_stream_cursor,
            }
          })()
        : run
    )
  }
  if (event.type === "answer_reset") {
    return runs.map((run) =>
      run.id === runId
        ? (() => {
            const sameStream =
              !event.stream_epoch ||
              event.stream_epoch === run.live_stream_epoch
            if (
              sameStream &&
              event.live_sequence &&
              run.live_stream_cursor &&
              compareLiveStreamIds(
                event.live_sequence,
                run.live_stream_cursor
              ) <= 0
            ) {
              return run
            }
            return {
              ...run,
              result: "",
              live_stream_epoch: event.stream_epoch ?? run.live_stream_epoch,
              live_stream_cursor: event.live_sequence ?? run.live_stream_cursor,
            }
          })()
        : run
    )
  }
  if (event.type === "reasoning_delta") {
    return runs.map((run) => {
      if (run.id !== runId) return run
      const sameStream =
        !event.stream_epoch || event.stream_epoch === run.live_stream_epoch
      if (
        sameStream &&
        event.live_sequence &&
        run.live_stream_cursor &&
        compareLiveStreamIds(event.live_sequence, run.live_stream_cursor) <= 0
      ) {
        return run
      }
      const progress = [...run.progress]
      const index = progress.findIndex(
        (item) => item.type === "analysis" && item.turn === event.turn
      )
      if (index === -1) {
        progress.push({
          id: `reasoning-${event.turn}`,
          type: "analysis",
          status: "running",
          stage: "analyzing",
          turn: event.turn,
          count: null,
          reasoning: event.delta,
          hits: [],
        })
      } else {
        const current = progress[index]
        progress[index] = {
          ...current,
          reasoning: sameStream
            ? (current.reasoning ?? "") + event.delta
            : event.delta,
        }
      }
      return {
        ...run,
        progress,
        live_stream_epoch: event.stream_epoch ?? run.live_stream_epoch,
        live_stream_cursor: event.live_sequence ?? run.live_stream_cursor,
      }
    })
  }
  if (event.type === "approval_required") {
    return runs.map((run) =>
      run.id === runId ? { ...run, status: "awaiting_approval" } : run
    )
  }
  return runs.map((run) =>
    run.id === event.run.id
      ? {
          ...event.run,
          live_stream_epoch: event.stream_epoch ?? run.live_stream_epoch,
          live_stream_cursor: event.live_sequence ?? run.live_stream_cursor,
        }
      : run
  )
}

/**
 * Cancels the active public Agent stream.
 *
 * @param streamControllerRef - A reference containing the active stream controller.
 */
export function cancelPublicAgentStream(streamControllerRef: {
  current: AbortController | null
}) {
  const activeController = streamControllerRef.current
  streamControllerRef.current = null
  activeController?.abort()
}

/**
 * Renders the Agent identity, conversation controls, and conversation history.
 *
 * @param profile - The public Agent profile displayed in the history header.
 * @param conversations - The conversations available for selection.
 * @param activeConversationId - The identifier of the currently selected conversation.
 * @param onNew - Called when a new conversation is requested.
 * @param onSelect - Called with the identifier of the selected conversation.
 */
function ConversationHistory({
  profile,
  conversations,
  activeConversationId,
  onNew,
  onSelect,
  onDelete,
  deletingConversationId,
  onExport,
  exportingConversationId,
}: {
  profile: PublicAgentProfile | null
  conversations: PublicAgentConversation[]
  activeConversationId: string | null
  onNew: () => void
  onSelect: (conversationId: string) => void
  onDelete: (conversationId: string) => void
  deletingConversationId: string | null
  onExport: (conversationId: string) => void
  exportingConversationId: string | null
}) {
  const { t } = useLanguage()
  const [query, setQuery] = React.useState("")
  const filteredConversations = React.useMemo(() => {
    const normalized = query.trim().toLocaleLowerCase()
    if (!normalized) return conversations
    return conversations.filter((conversation) =>
      `${conversation.question} ${conversation.result}`
        .toLocaleLowerCase()
        .includes(normalized)
    )
  }, [conversations, query])
  return (
    <div className="flex h-full min-h-0 flex-col bg-background">
      <div className="flex min-h-16 items-center gap-3 border-b px-4">
        <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-primary text-primary-foreground">
          <BotIcon className="size-4" />
        </span>
        <p className="min-w-0 truncate text-sm font-semibold">
          {profile?.name ?? t("公开 Agent")}
        </p>
      </div>
      <div className="p-3">
        <Button
          type="button"
          variant="outline"
          className="w-full"
          onClick={onNew}
        >
          <MessageSquarePlusIcon data-icon="inline-start" />
          {t("新建对话")}
        </Button>
      </div>
      <div className="flex min-h-0 flex-1 flex-col px-3 pb-3">
        <div className="flex items-center gap-2 px-2 py-2 text-xs font-medium text-muted-foreground">
          <HistoryIcon className="size-3.5" />
          <span className="flex-1">{t("历史记录")}</span>
        </div>
        <div className="relative mb-2">
          <SearchIcon className="pointer-events-none absolute top-1/2 left-3 size-3.5 -translate-y-1/2 text-muted-foreground" />
          <input
            className="h-8 w-full rounded-md border bg-background pr-2 pl-8 text-xs outline-none placeholder:text-muted-foreground focus-visible:ring-2 focus-visible:ring-ring"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder={t("搜索历史记录")}
            aria-label={t("搜索历史记录")}
          />
        </div>
        <div className="min-h-0 flex-1 space-y-1 overflow-y-auto">
          {conversations.length === 0 ? (
            <p className="px-2 py-6 text-center text-xs text-muted-foreground">
              {t("暂无历史记录")}
            </p>
          ) : filteredConversations.length === 0 ? (
            <p className="px-2 py-6 text-center text-xs text-muted-foreground">
              {t("暂无匹配的历史记录")}
            </p>
          ) : (
            filteredConversations.map((conversation) => (
              <div
                key={conversation.conversation_id}
                className={`group flex items-center gap-1 rounded-lg px-2 py-1 transition-colors hover:bg-muted ${
                  activeConversationId === conversation.conversation_id
                    ? "bg-muted"
                    : ""
                }`}
              >
                <button
                  type="button"
                  className="min-w-0 flex-1 rounded-md px-1 py-1.5 text-left outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  aria-current={
                    activeConversationId === conversation.conversation_id
                      ? "page"
                      : undefined
                  }
                  onClick={() => onSelect(conversation.conversation_id)}
                >
                  <span className="block truncate text-sm font-medium">
                    {conversation.question || t("新对话")}
                  </span>
                  <span className="mt-1 block truncate text-xs text-muted-foreground">
                    {conversation.result || t("等待回答")}
                  </span>
                </button>
                <DropdownMenu modal={false}>
                  <DropdownMenuTrigger asChild>
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon-xs"
                      className="size-5 rounded-md p-0 text-muted-foreground"
                      aria-label={t("更多")}
                      title={t("更多")}
                      onClick={(event) => event.stopPropagation()}
                    >
                      {deletingConversationId ===
                        conversation.conversation_id ||
                      exportingConversationId ===
                        conversation.conversation_id ? (
                        <LoaderCircleIcon className="animate-spin" />
                      ) : (
                        <EllipsisIcon />
                      )}
                    </Button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent
                    side="bottom"
                    align="center"
                    sideOffset={4}
                    className="w-36 min-w-0 rounded-md p-1"
                  >
                    <DropdownMenuItem
                      className="h-8 px-2 py-1 text-xs [&_svg]:size-3.5"
                      disabled={Boolean(
                        deletingConversationId || exportingConversationId
                      )}
                      onSelect={() => onExport(conversation.conversation_id)}
                    >
                      <DownloadIcon />
                      {t("导出对话")}
                    </DropdownMenuItem>
                    <DropdownMenuSeparator />
                    <DropdownMenuItem
                      className="h-8 px-2 py-1 text-xs"
                      variant="destructive"
                      disabled={Boolean(
                        deletingConversationId || exportingConversationId
                      )}
                      onSelect={() => onDelete(conversation.conversation_id)}
                    >
                      {t("删除对话")}
                    </DropdownMenuItem>
                  </DropdownMenuContent>
                </DropdownMenu>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  )
}

/**
 * Renders the public Agent chat interface with conversation history, streaming responses, tool approvals, attachments, feedback, and run regeneration.
 *
 * @param agentId - The identifier of the public Agent to display
 * @param initialConversationId - The conversation to open initially, if provided
 */
export function PublicAgentChat({
  agentId,
  initialConversationId = null,
}: PublicAgentChatProps) {
  const router = useRouter()
  const { t } = useLanguage()
  const [confirm, confirmDialog] = useConfirmDialog()
  const { token, isSessionRestored } = useSession()
  const [profile, setProfile] = React.useState<PublicAgentProfile | null>(null)
  const [conversations, setConversations] = React.useState<
    PublicAgentConversation[]
  >([])
  const [activeConversationId, setActiveConversationId] = React.useState<
    string | null
  >(initialConversationId)
  const [runs, setRuns] = React.useState<ExternalAgentRun[]>([])
  const [question, setQuestion] = React.useState("")
  const [files, setFiles] = React.useState<File[]>([])
  const [isInitializing, setIsInitializing] = React.useState(true)
  const [isRunsLoading, setIsRunsLoading] = React.useState(false)
  const [isSending, setIsSending] = React.useState(false)
  const [regeneratingRunId, setRegeneratingRunId] = React.useState<
    string | null
  >(null)
  const [feedbackPendingRunId, setFeedbackPendingRunId] = React.useState<
    string | null
  >(null)
  const [fatalError, setFatalError] = React.useState<string | null>(null)
  const [sendError, setSendError] = React.useState<string | null>(null)
  const [isHistoryOpen, setIsHistoryOpen] = React.useState(false)
  const [deletingConversationId, setDeletingConversationId] = React.useState<
    string | null
  >(null)
  const [exportingConversationId, setExportingConversationId] = React.useState<
    string | null
  >(null)
  const [toolCallsByRun, setToolCallsByRun] = React.useState<
    Record<string, AgentToolCall[]>
  >({})
  const [resolvingCallId, setResolvingCallId] = React.useState<string | null>(
    null
  )
  const [sessionReady, setSessionReady] = React.useState(false)
  const streamControllerRef = React.useRef<AbortController | null>(null)
  const fileInputRef = React.useRef<HTMLInputElement>(null)
  const scrollRef = React.useRef<HTMLDivElement>(null)
  const initialConversationIdRef = React.useRef(initialConversationId)
  const tRef = React.useRef(t)
  const tokenRef = React.useRef(token)

  const loadRunToolCalls = React.useCallback(
    async (runId: string, controller?: AbortController) => {
      if (!token) return
      try {
        const calls = await listPublicAgentRunToolCalls(agentId, token, runId)
        if (controller && streamControllerRef.current !== controller) return
        setToolCallsByRun((current) => ({ ...current, [runId]: calls }))
      } catch {
        // A failed fetch is not fatal; the next stream event retries it.
      }
    },
    [agentId, token]
  )

  React.useEffect(() => {
    tRef.current = t
    tokenRef.current = token
  }, [t, token])

  React.useEffect(() => {
    if (!isSessionRestored || token) return
    streamControllerRef.current?.abort()
    const conversationId = initialConversationIdRef.current
    const next = conversationId
      ? `/chat/${agentId}?conversation_id=${encodeURIComponent(conversationId)}`
      : `/chat/${agentId}`
    router.replace(`/login?next=${encodeURIComponent(next)}`)
  }, [agentId, isSessionRestored, router, token])

  React.useEffect(() => {
    return () => streamControllerRef.current?.abort()
  }, [agentId])

  const refreshConversations = React.useCallback(async () => {
    if (!token) return []
    const response = await listPublicAgentConversations(agentId, token)
    setConversations(response.items)
    return response.items
  }, [agentId, token])

  React.useEffect(() => {
    if (!isSessionRestored) return
    const currentToken = tokenRef.current
    if (!currentToken) return
    let current = true
    ;(async () => {
      try {
        const { profile: nextProfile, conversations: nextConversations } =
          await initializePublicAgent(agentId, currentToken)
        if (!current) return
        setProfile(nextProfile)
        setConversations(nextConversations.items)
        const nextConversationId =
          initialConversationIdRef.current ??
          nextConversations.items[0]?.conversation_id ??
          null
        setActiveConversationId(nextConversationId)
        setIsRunsLoading(Boolean(nextConversationId))
        setSessionReady(true)
        if (nextConversationId && !initialConversationIdRef.current) {
          window.history.replaceState(
            null,
            "",
            `/chat/${agentId}?conversation_id=${encodeURIComponent(nextConversationId)}`
          )
        }
      } catch {
        if (current) {
          setFatalError(tRef.current("此 Agent 未发布或不可访问。"))
        }
      } finally {
        if (current) setIsInitializing(false)
      }
    })()
    return () => {
      current = false
    }
  }, [agentId, isSessionRestored, token])

  React.useEffect(() => {
    if (!sessionReady || !token) return
    if (streamControllerRef.current) return
    if (!activeConversationId) return
    let current = true
    listPublicAgentRuns(agentId, activeConversationId, token, {
      limit: 200,
      offset: 0,
    })
      .then((response) => {
        if (current) {
          const visibleRuns = latestRunVersions(response.items)
          setRuns(visibleRuns)
          for (const run of visibleRuns) {
            if (run.status === "awaiting_approval") {
              void loadRunToolCalls(run.id)
            }
          }
        }
      })
      .catch((error: unknown) => {
        if (current) setSendError(getErrorMessage(error, t))
      })
      .finally(() => {
        if (current) setIsRunsLoading(false)
      })
    return () => {
      current = false
    }
  }, [activeConversationId, agentId, loadRunToolCalls, sessionReady, t, token])

  React.useLayoutEffect(() => {
    const element = scrollRef.current
    if (element) element.scrollTop = element.scrollHeight
  }, [runs, isRunsLoading])

  function selectConversation(conversationId: string) {
    if (conversationId === activeConversationId) {
      setIsHistoryOpen(false)
      return
    }
    cancelPublicAgentStream(streamControllerRef)
    setIsSending(false)
    setSendError(null)
    setIsRunsLoading(true)
    setActiveConversationId(conversationId)
    setIsHistoryOpen(false)
    window.history.replaceState(
      null,
      "",
      `/chat/${agentId}?conversation_id=${encodeURIComponent(conversationId)}`
    )
  }

  function startNewConversation() {
    cancelPublicAgentStream(streamControllerRef)
    setActiveConversationId(null)
    setRuns([])
    setToolCallsByRun({})
    setResolvingCallId(null)
    setQuestion("")
    setFiles([])
    setSendError(null)
    setIsSending(false)
    setIsRunsLoading(false)
    setIsHistoryOpen(false)
    window.history.replaceState(null, "", `/chat/${agentId}`)
  }

  async function handleDeleteConversation(conversationId: string) {
    if (!token || deletingConversationId) return
    const confirmed = await confirm({
      title: t("删除对话"),
      description: t("删除对话说明"),
      confirmLabel: t("删除"),
      destructive: true,
    })
    if (!confirmed) return
    setDeletingConversationId(conversationId)
    setSendError(null)
    try {
      await deletePublicAgentConversation(agentId, conversationId, token)
      const nextConversations = await refreshConversations()
      if (activeConversationId === conversationId) {
        const nextId = nextConversations[0]?.conversation_id ?? null
        if (nextId) selectConversation(nextId)
        else startNewConversation()
      }
    } catch (error) {
      setSendError(getErrorMessage(error, t))
    } finally {
      setDeletingConversationId(null)
    }
  }

  async function handleExportConversation(conversationId: string) {
    if (!token || exportingConversationId || deletingConversationId) return
    setExportingConversationId(conversationId)
    setSendError(null)
    try {
      const pageSize = 200
      const exportedRuns: ExternalAgentRun[] = []
      for (let offset = 0; ; offset += pageSize) {
        const response = await listPublicAgentRuns(
          agentId,
          conversationId,
          token,
          {
            limit: pageSize,
            offset,
          }
        )
        exportedRuns.push(...response.items)
        if (
          exportedRuns.length >= response.total ||
          response.items.length < pageSize
        ) {
          break
        }
      }
      const conversation = conversations.find(
        (item) => item.conversation_id === conversationId
      )
      const messages: ConversationExportMessage[] = latestRunVersions(
        exportedRuns
      ).map((run) => ({
        question: run.question,
        answer: run.result,
        error: run.error,
        createdAt: run.created_at,
      }))
      downloadConversationMarkdown(
        conversation?.question || profile?.name || t("对话记录"),
        messages
      )
    } catch (error) {
      setSendError(getErrorMessage(error, t))
    } finally {
      setExportingConversationId(null)
    }
  }

  async function handleToolCallDecision(
    runId: string,
    callId: string,
    decision: "approve" | "reject"
  ) {
    if (!token || resolvingCallId) return
    setResolvingCallId(`${runId}:${callId}`)
    try {
      const run = await resolvePublicAgentRunToolCall(
        agentId,
        token,
        runId,
        callId,
        decision
      )
      setRuns((current) =>
        current.map((item) =>
          item.id === runId
            ? {
                ...run,
                progress:
                  run.progress.length > 0 ? run.progress : item.progress,
              }
            : item
        )
      )
      setToolCallsByRun((current) => {
        const next = { ...current }
        delete next[runId]
        return next
      })
      if (!streamControllerRef.current) {
        // This run was resumed from a paused conversation, not an active
        // stream. The backend requeued it; observe it until it reaches a
        // terminal status so the completed result is delivered.
        const controller = new AbortController()
        streamControllerRef.current = controller
        const observedRunId = runId
        void observePublicAgentRun(
          agentId,
          token,
          runId,
          (streamEvent) => {
            if (streamControllerRef.current !== controller) return
            setRuns((current) =>
              mergePublicRunEvent(
                current,
                observedRunId,
                streamEvent,
                observedRunId
              )
            )
            if (streamEvent.type === "approval_required") {
              void loadRunToolCalls(observedRunId, controller)
            }
            if (streamEvent.type === "error") {
              setSendError(streamEvent.run.error || t("回答失败，请稍后重试。"))
            }
          },
          controller.signal
        )
          .catch((error: unknown) => {
            const message = getErrorMessage(error, t)
            setSendError(message)
          })
          .finally(() => {
            if (streamControllerRef.current === controller) {
              streamControllerRef.current = null
            }
          })
      }
    } catch (error) {
      const message = getErrorMessage(error, t)
      setSendError(message)
    } finally {
      setResolvingCallId(null)
    }
  }

  async function handleRegenerateRun(runId: string) {
    if (
      !token ||
      isSending ||
      regeneratingRunId ||
      feedbackPendingRunId ||
      streamControllerRef.current
    ) {
      return
    }
    setRegeneratingRunId(runId)
    const previous = runs.find((run) => run.id === runId)
    let replacementId = runId
    const controller = new AbortController()
    streamControllerRef.current = controller
    try {
      const regenerated = await regeneratePublicAgentRun(agentId, token, runId)
      replacementId = regenerated.id
      setRuns((current) =>
        current.map((run) => (run.id === runId ? regenerated : run))
      )
      const restorePrevious = () => {
        if (!previous) return
        setRuns((current) =>
          current.map((run) => (run.id === regenerated.id ? previous : run))
        )
      }
      await observePublicAgentRun(
        agentId,
        token,
        regenerated.id,
        (event) => {
          if (streamControllerRef.current !== controller) return
          setRuns((current) =>
            mergePublicRunEvent(current, regenerated.id, event, regenerated.id)
          )
          if (
            (event.type === "error" || event.type === "complete") &&
            ["failed", "cancelled"].includes(event.run.status)
          ) {
            restorePrevious()
          }
          if (event.type === "error") {
            setSendError(event.run.error || t("回答失败，请稍后重试。"))
          }
        },
        controller.signal
      )
    } catch (error) {
      if (!controller.signal.aborted) {
        if (previous) {
          setRuns((current) =>
            current.map((run) => (run.id === replacementId ? previous : run))
          )
        }
        setSendError(getErrorMessage(error, t))
      }
    } finally {
      if (streamControllerRef.current === controller) {
        streamControllerRef.current = null
      }
      setRegeneratingRunId(null)
    }
  }

  async function handleRunFeedback(
    runId: string,
    value: "positive" | "negative" | null
  ) {
    if (!token || feedbackPendingRunId || regeneratingRunId) return
    const previous = runs.find((run) => run.id === runId)?.feedback ?? null
    setRuns((current) =>
      current.map((run) =>
        run.id === runId ? { ...run, feedback: value } : run
      )
    )
    setFeedbackPendingRunId(runId)
    try {
      const updated = await setPublicAgentRunFeedback(
        agentId,
        token,
        runId,
        value
      )
      setRuns((current) =>
        current.map((run) => (run.id === runId ? { ...run, ...updated } : run))
      )
    } catch (error) {
      setRuns((current) =>
        current.map((run) =>
          run.id === runId ? { ...run, feedback: previous } : run
        )
      )
      setSendError(getErrorMessage(error, t))
    } finally {
      setFeedbackPendingRunId(null)
    }
  }

  async function handleAsk(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const nextQuestion = question.trim()
    const currentProfile = profile
    if (!nextQuestion || isSending || !token || !currentProfile) return
    setQuestion("")
    setSendError(null)
    setIsSending(true)
    const controller = new AbortController()
    streamControllerRef.current = controller
    const placeholderId = `pending-${Date.now()}`
    const placeholder: ExternalAgentRun = {
      id: placeholderId,
      conversation_id: activeConversationId ?? "",
      question: nextQuestion,
      status: "running",
      result: "",
      error: null,
      progress: [],
      created_at: new Date().toISOString(),
      started_at: new Date().toISOString(),
      finished_at: null,
      updated_at: new Date().toISOString(),
    }
    setRuns((current) => [placeholder, ...current])
    let liveRunId = placeholderId
    try {
      const uploaded = files.length
        ? await uploadPublicAgentFiles(agentId, token, files)
        : []
      await streamPublicAgentRun(
        agentId,
        token,
        nextQuestion,
        (streamEvent) => {
          if (streamControllerRef.current !== controller) return
          if (streamEvent.type === "run") {
            liveRunId = streamEvent.run.id
            if (!activeConversationId) {
              setActiveConversationId(streamEvent.run.conversation_id)
              window.history.replaceState(
                null,
                "",
                `/chat/${agentId}?conversation_id=${encodeURIComponent(streamEvent.run.conversation_id)}`
              )
            }
          }
          setRuns((current) =>
            mergePublicRunEvent(current, liveRunId, streamEvent, placeholderId)
          )
          if (streamEvent.type === "approval_required") {
            void loadRunToolCalls(liveRunId, controller)
          }
          if (streamEvent.type === "error") {
            setSendError(streamEvent.run.error || t("回答失败，请稍后重试。"))
          }
        },
        controller.signal,
        activeConversationId,
        uploaded.map((item) => item.id)
      )
      setFiles([])
      await refreshConversations()
    } catch (error) {
      if (!controller.signal.aborted) {
        const message = getErrorMessage(error, t)
        setSendError(message)
        setRuns((current) =>
          current.map((run) =>
            run.id === placeholderId
              ? { ...run, status: "failed", error: message }
              : run
          )
        )
      }
    } finally {
      if (streamControllerRef.current === controller) {
        streamControllerRef.current = null
        setIsSending(false)
      }
    }
  }

  function handleCancelAsk() {
    cancelPublicAgentStream(streamControllerRef)
    setIsSending(false)
  }

  if (isInitializing) {
    return (
      <main className="flex min-h-svh items-center justify-center bg-muted/30 text-sm text-muted-foreground">
        <LoaderCircleIcon className="mr-2 size-4 animate-spin" />
        {t("正在加载")}
      </main>
    )
  }

  if (fatalError || !profile) {
    return (
      <main className="flex min-h-svh items-center justify-center bg-muted/30 p-6">
        <div className="max-w-md text-center">
          <span className="mx-auto flex size-12 items-center justify-center rounded-xl bg-destructive/10 text-destructive">
            <CircleAlertIcon className="size-5" />
          </span>
          <h1 className="mt-4 text-lg font-semibold">
            {t("无法打开公开对话")}
          </h1>
          <p className="mt-2 text-sm text-muted-foreground">
            {fatalError ?? t("此 Agent 未发布或不可访问。")}
          </p>
        </div>
      </main>
    )
  }

  const visibleRuns = [...runs].reverse()
  const historyProps = {
    profile,
    conversations,
    activeConversationId,
    onNew: startNewConversation,
    onSelect: selectConversation,
    onDelete: handleDeleteConversation,
    deletingConversationId,
    onExport: handleExportConversation,
    exportingConversationId,
  }

  return (
    <main className="grid h-svh min-h-0 bg-muted/20 lg:grid-cols-[240px_minmax(0,1fr)] xl:grid-cols-[280px_minmax(0,1fr)]">
      <aside className="hidden min-h-0 border-r lg:block">
        <ConversationHistory {...historyProps} />
      </aside>

      <section className="flex min-h-0 min-w-0 flex-col">
        <header className="flex min-h-16 shrink-0 items-center gap-3 border-b bg-background/95 px-4 backdrop-blur sm:px-6">
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="lg:hidden"
            aria-label={t("打开历史记录")}
            title={t("打开历史记录")}
            onClick={() => setIsHistoryOpen(true)}
          >
            <MenuIcon />
          </Button>
          <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-primary text-primary-foreground">
            <BotIcon className="size-4" />
          </span>
          <div className="min-w-0 flex-1">
            <h1 className="truncate text-sm font-semibold">{profile.name}</h1>
            <p className="truncate text-xs text-muted-foreground">
              {profile.description || t("公开对话")}
            </p>
          </div>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            aria-label={t("新建对话")}
            title={t("新建对话")}
            onClick={startNewConversation}
          >
            <MessageSquarePlusIcon />
          </Button>
        </header>

        <div ref={scrollRef} className="min-h-0 flex-1 overflow-y-auto">
          <div className="mx-auto flex min-h-full w-full max-w-5xl flex-col px-4 py-8 sm:px-8 2xl:max-w-6xl">
            {isRunsLoading ? (
              <div className="flex flex-1 items-center justify-center text-sm text-muted-foreground">
                <LoaderCircleIcon className="mr-2 size-4 animate-spin" />
                {t("正在加载")}
              </div>
            ) : visibleRuns.length === 0 ? (
              <div className="flex flex-1 flex-col items-center justify-center text-center">
                <span className="flex size-14 items-center justify-center rounded-xl bg-primary text-primary-foreground shadow-sm">
                  <BotIcon className="size-6" />
                </span>
                <h2 className="mt-4 text-base font-semibold">
                  {t("开始新对话")}
                </h2>
                <p className="mt-2 max-w-md text-sm leading-6 whitespace-pre-wrap text-muted-foreground">
                  {profile.description || t("输入问题，Agent 会为你生成回答。")}
                </p>
              </div>
            ) : (
              <div className="space-y-8">
                {visibleRuns.map((run) => (
                  <article key={run.id} className="space-y-4">
                    <div className="flex items-start gap-2">
                      <div className="ml-auto flex max-w-[85%] flex-col items-end gap-1">
                        <div className="rounded-2xl rounded-tr-md bg-primary px-4 py-2.5 text-sm leading-6 [overflow-wrap:anywhere] break-words whitespace-pre-wrap text-primary-foreground">
                          {run.question}
                        </div>
                        <CopyMessageButton value={run.question} />
                      </div>
                      <span className="flex size-8 shrink-0 items-center justify-center rounded-full bg-foreground text-background">
                        <UserIcon className="size-3.5" />
                      </span>
                    </div>
                    <div className="flex items-start gap-3">
                      <span className="mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-lg bg-foreground text-background shadow-sm">
                        <BotIcon className="size-4" />
                      </span>
                      <div className="min-w-0 flex-1">
                        <div className="rounded-2xl rounded-tl-md border bg-background p-4 shadow-xs">
                          <PublicExecutionProcess run={run} />
                          {toolCallsByRun[run.id]
                            ?.filter(
                              (call) => call.status === "awaiting_approval"
                            )
                            .map((call) => (
                              <PublicToolApproval
                                key={call.call_id}
                                runId={run.id}
                                call={call}
                                resolvingCallId={resolvingCallId}
                                onDecision={(callId, decision) =>
                                  handleToolCallDecision(
                                    run.id,
                                    callId,
                                    decision
                                  )
                                }
                                t={t}
                              />
                            ))}
                          {run.result ? (
                            <MarkdownContent
                              content={withArtifactDownloadLinks(
                                run.result,
                                run.progress
                              )}
                              className="text-sm leading-6"
                            />
                          ) : run.status === "failed" ? (
                            <p className="rounded-md border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
                              {run.error || t("回答失败，请稍后重试。")}
                            </p>
                          ) : run.status === "cancelled" ? (
                            <p className="text-sm text-muted-foreground">
                              {t("运行已取消")}
                            </p>
                          ) : null}
                        </div>
                        {run.status === "succeeded" && run.result ? (
                          <RunActionBar
                            result={run.result}
                            feedback={run.feedback}
                            regenerateDisabled={
                              isSending ||
                              isRunsLoading ||
                              Boolean(regeneratingRunId)
                            }
                            regenerating={regeneratingRunId === run.id}
                            feedbackPending={feedbackPendingRunId === run.id}
                            onRegenerate={() =>
                              void handleRegenerateRun(run.id)
                            }
                            onFeedback={(value) =>
                              void handleRunFeedback(run.id, value)
                            }
                            t={t}
                          />
                        ) : null}
                      </div>
                    </div>
                  </article>
                ))}
              </div>
            )}
          </div>
        </div>

        <div className="shrink-0 border-t bg-background p-3 sm:p-4">
          {sendError ? (
            <p
              role="alert"
              className="mx-auto mb-2 max-w-5xl text-xs text-destructive 2xl:max-w-6xl"
            >
              {sendError}
            </p>
          ) : null}
          <form
            className="relative mx-auto max-w-5xl rounded-xl border bg-background p-2 shadow-sm focus-within:ring-2 focus-within:ring-ring/40 2xl:max-w-6xl"
            onSubmit={handleAsk}
          >
            <input
              ref={fileInputRef}
              type="file"
              className="sr-only"
              multiple
              accept={acceptedUploadExtensions(
                AGENT_FILE_UPLOAD_SETTING.file_upload_type
              )}
              disabled={isSending}
              onChange={(event) => {
                const selected = Array.from(event.target.files ?? [])
                setSendError(null)
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
              className={`max-h-40 min-h-28 w-full resize-none bg-transparent px-3 pt-2 text-sm leading-6 outline-none placeholder:text-muted-foreground ${files.length ? "pb-2" : "pb-14"}`}
              placeholder={t("请输入问题")}
              aria-label={t("请输入问题")}
              maxLength={4000}
              rows={1}
              disabled={isSending}
            />
            <AgentAttachmentList
              files={files}
              onRemove={(indexToRemove) =>
                setFiles((current) =>
                  current.filter((_, index) => index !== indexToRemove)
                )
              }
              t={t}
            />
            <div className="absolute right-2 bottom-2 flex items-center gap-2">
              <Button
                type="button"
                variant="ghost"
                size="icon-lg"
                className="rounded-lg"
                aria-label={t("添加附件")}
                title={t("添加附件")}
                disabled={isSending}
                onClick={() => {
                  if (!fileInputRef.current) return
                  fileInputRef.current.value = ""
                  fileInputRef.current.click()
                }}
              >
                <PaperclipIcon />
              </Button>
              <Button
                type={isSending ? "button" : "submit"}
                size="icon-lg"
                className="rounded-lg"
                aria-label={t(isSending ? "停止生成" : "发送问题")}
                title={t(isSending ? "停止生成" : "发送问题")}
                onClick={isSending ? handleCancelAsk : undefined}
                disabled={!isSending && !question.trim()}
              >
                {isSending ? (
                  <SquareIcon className="fill-current" />
                ) : (
                  <SendIcon />
                )}
              </Button>
            </div>
          </form>
        </div>
      </section>

      <Dialog open={isHistoryOpen} onOpenChange={setIsHistoryOpen}>
        <DialogContent side="right" className="p-0 lg:hidden">
          <DialogHeader className="sr-only">
            <DialogTitle>{t("历史记录")}</DialogTitle>
            <DialogDescription>{t("选择或新建对话")}</DialogDescription>
          </DialogHeader>
          <ConversationHistory {...historyProps} />
        </DialogContent>
      </Dialog>
      {confirmDialog}
    </main>
  )
}
