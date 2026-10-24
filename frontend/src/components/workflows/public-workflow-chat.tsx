"use client"

import * as React from "react"
import {
  ArrowUpIcon,
  ChevronDownIcon,
  CircleAlertIcon,
  CircleCheckIcon,
  CircleDotDashedIcon,
  DownloadIcon,
  EllipsisIcon,
  HistoryIcon,
  LoaderCircleIcon,
  MenuIcon,
  MessageSquarePlusIcon,
  PlusIcon,
  SearchIcon,
  UserIcon,
  WorkflowIcon,
  XIcon,
} from "lucide-react"

import { MarkdownContent } from "@/components/knowledge/markdown-content"
import {
  feedbackConfirmationLabel,
  RunActionBar,
} from "@/components/app/run-action-bar"
import { useConfirmDialog } from "@/components/app/confirm-dialog"
import {
  AgentAttachmentList,
  appendAttachmentFiles,
  RunAttachmentCards,
  transferredFiles,
} from "@/components/agents/agent-attachment-list"
import { Button } from "@/components/ui/button"
import { CopyButton } from "@/components/ui/copy-button"
import { SpeechInputButton } from "@/components/ui/speech-input-button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { IconButton } from "@/components/ui/icon-button"
import { MessageTimestamp } from "@/components/agents/message-timestamp"
import { WorkflowRuntimeForm } from "@/components/workflows/workflow-runtime-form"
import { useLanguage } from "@/contexts/language-provider"
import { useSession } from "@/contexts/session-context"
import {
  createPublicWorkflowRun,
  deletePublicWorkflowConversation,
  initializePublicWorkflow,
  listPublicWorkflowConversations,
  listPublicWorkflowRuns,
  observePublicWorkflowRun,
  regeneratePublicWorkflowRun,
  setPublicWorkflowRunFeedback,
  submitPublicWorkflowForm,
  uploadPublicWorkflowFiles,
  type ExternalWorkflowRun,
  type PublicWorkflowConversation,
  type PublicWorkflowProfile,
  type PublicWorkflowRunStreamEvent,
} from "@/lib/api/public-workflows"
import { compareLiveStreamIds } from "@/lib/api/agents"
import { speakBrowserText, workflowSpeechText } from "@/lib/browser-tts"
import { getErrorMessage } from "@/lib/errors"
import {
  downloadConversationMarkdown,
  type ConversationExportMessage,
} from "@/lib/conversation-export"
import { latestRunVersions } from "@/lib/run-versions"
import { acceptedUploadExtensions } from "@/lib/interaction-config"
import { workflowErrorMessage, workflowNodeLabel } from "@/lib/workflows/graph"
import { useVisualViewportShellStyle } from "@/lib/visual-viewport"

/**
 * Derives a conversation title from the question input.
 *
 * @param inputs - The conversation inputs containing an optional question
 * @param fallback - The title to use when the question is absent or blank
 * @returns The trimmed question text or the fallback title
 */
function conversationLabel(inputs: Record<string, unknown>, fallback: string) {
  const question = inputs.question
  return (
    (typeof question === "string" && question.trim() ? question.trim() : "") ||
    fallback
  )
}

function conversationResult(
  outputs: Record<string, unknown>,
  fallback: string
) {
  const result = workflowSpeechText(outputs)
  return result && result !== "{}" ? result : fallback
}

type PublicWorkflowProgress = ExternalWorkflowRun["progress"][number]

function JsonBlock({ value }: { value: unknown }) {
  return (
    <pre className="max-h-64 overflow-auto rounded-md bg-muted p-3 font-mono text-xs leading-5 break-words whitespace-pre-wrap">
      {JSON.stringify(value, null, 2)}
    </pre>
  )
}

function PublicWorkflowNodeDetails({
  item,
  label,
  statusIcon,
  statusDetail,
}: {
  item: PublicWorkflowProgress
  label: string
  statusIcon: React.ReactNode
  statusDetail: string
}) {
  const { t } = useLanguage()
  const inputs = item.inputs ?? {}
  const outputs = item.outputs ?? {}

  return (
    <details className="group rounded-md border bg-background/60">
      <summary className="flex cursor-pointer list-none items-center gap-2 px-2 py-2 transition-colors outline-none hover:bg-muted/40 focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset [&::-webkit-details-marker]:hidden">
        {statusIcon}
        <span className="min-w-0 flex-1 truncate text-xs" title={item.node_id}>
          {label}
        </span>
        <span className="shrink-0 text-[11px] text-muted-foreground">
          {statusDetail}
        </span>
        <ChevronDownIcon className="size-3.5 shrink-0 text-muted-foreground transition-transform group-open:rotate-180" />
      </summary>
      <div className="grid gap-3 border-t bg-muted/20 px-2.5 py-3">
        {item.error ? (
          <section className="grid gap-1.5">
            <h4 className="text-xs font-medium text-destructive">
              {t("错误")}
            </h4>
            <p className="rounded-md bg-destructive/10 px-2.5 py-2 text-xs leading-5 break-words whitespace-pre-wrap text-destructive">
              {workflowErrorMessage(item.error, t)}
            </p>
          </section>
        ) : null}
        <section className="grid gap-1.5">
          <h4 className="text-xs font-medium text-muted-foreground">
            {t("输入内容")}
          </h4>
          <JsonBlock value={inputs} />
        </section>
        <section className="grid gap-1.5">
          <h4 className="text-xs font-medium text-muted-foreground">
            {t("输出内容")}
          </h4>
          {Object.keys(outputs).length ? (
            <JsonBlock value={outputs} />
          ) : (
            <p className="rounded-md border bg-background px-2.5 py-2 text-xs text-muted-foreground">
              {t("暂无输出内容")}
            </p>
          )}
        </section>
      </div>
    </details>
  )
}

function PublicWorkflowExecutionProcess({ run }: { run: ExternalWorkflowRun }) {
  const { t } = useLanguage()
  const [isOpen, setIsOpen] = React.useState(true)
  const progress = run.progress

  function title(item: PublicWorkflowProgress) {
    return item.node_title?.trim() || workflowNodeLabel(item.node_type, t)
  }

  function detail(item: PublicWorkflowProgress) {
    if (item.status === "running") return t("运行中")
    if (item.status === "awaiting_input") return t("等待填写表单")
    if (item.status === "awaiting_child") return t("等待执行")
    if (item.status === "failed") {
      return item.error ? workflowErrorMessage(item.error, t) : t("运行失败")
    }
    if (item.status === "skipped") return t("已跳过")
    return item.duration_ms === null || item.duration_ms === undefined
      ? t("完成")
      : t("{duration} 毫秒", { duration: item.duration_ms })
  }

  function statusIcon(item: PublicWorkflowProgress) {
    if (item.status === "running") {
      return <LoaderCircleIcon className="size-4 animate-spin text-sky-600" />
    }
    if (item.status === "failed") {
      return <CircleAlertIcon className="size-4 text-destructive" />
    }
    if (["skipped", "awaiting_input", "awaiting_child"].includes(item.status)) {
      return <CircleDotDashedIcon className="size-4 text-muted-foreground" />
    }
    return <CircleCheckIcon className="size-4 text-emerald-600" />
  }

  if (
    progress.length === 0 &&
    ["succeeded", "failed", "cancelled"].includes(run.status)
  ) {
    return null
  }

  return (
    <details
      className="group mb-4 rounded-xl bg-muted/50 px-3 py-2.5 text-sm"
      open={isOpen}
      onToggle={(event) => setIsOpen(event.currentTarget.open)}
    >
      <summary className="flex cursor-pointer list-none items-center gap-2 font-medium text-muted-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 [&::-webkit-details-marker]:hidden">
        <WorkflowIcon className="size-4" />
        <span className="flex-1">{t("执行过程")}</span>
        <ChevronDownIcon className="size-4 transition-transform group-open:rotate-180" />
      </summary>
      <div className="mt-2 space-y-1.5 border-l pl-3">
        {progress.length === 0 ? (
          <div className="flex items-center gap-2 py-1 text-xs text-muted-foreground">
            <LoaderCircleIcon className="size-4 animate-spin" />
            {t(run.status === "queued" ? "等待执行" : "正在生成回答")}
          </div>
        ) : (
          progress.map((item) => (
            <PublicWorkflowNodeDetails
              key={item.id}
              item={item}
              label={title(item)}
              statusIcon={statusIcon(item)}
              statusDetail={detail(item)}
            />
          ))
        )}
      </div>
    </details>
  )
}

function updateRun(
  runs: ExternalWorkflowRun[],
  runId: string,
  event: PublicWorkflowRunStreamEvent
) {
  return runs.map((run) => {
    if (run.id !== runId) return run
    if (event.type === "answer_delta") {
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
      const previous =
        sameStream && typeof run.outputs.result === "string"
          ? run.outputs.result
          : ""
      return {
        ...run,
        outputs: { ...run.outputs, result: previous + event.delta },
        live_stream_epoch: event.stream_epoch ?? run.live_stream_epoch,
        live_stream_cursor: event.live_sequence ?? run.live_stream_cursor,
      }
    }
    if (event.type === "progress") {
      const progress = [...run.progress]
      const index = progress.findIndex((item) => item.id === event.event.id)
      if (index === -1) progress.push(event.event)
      else progress[index] = event.event
      return { ...run, progress }
    }
    return {
      ...event.run,
      outputs:
        Object.keys(event.run.outputs).length > 0
          ? event.run.outputs
          : run.outputs,
      progress: event.run.progress.length ? event.run.progress : run.progress,
    }
  })
}

/**
 * Renders the workflow conversation history with controls for creating and selecting conversations.
 *
 * @param profile - The workflow profile displayed in the history header
 * @param conversations - The conversations available for selection
 * @param conversationId - The currently selected conversation ID
 * @param onNew - Called when a new conversation is requested
 * @param onSelect - Called with the ID of the selected conversation
 * @param onClose - Called when the panel is dismissed; omitted when the panel is always visible
 */
function ConversationHistory({
  profile,
  conversations,
  conversationId,
  onNew,
  onSelect,
  onDelete,
  onClose,
  deletingConversationId,
  onExport,
  exportingConversationId,
}: {
  profile: PublicWorkflowProfile
  conversations: PublicWorkflowConversation[]
  conversationId: string | null
  onNew: () => void
  onSelect: (conversationId: string) => void
  onDelete: (conversationId: string) => void
  onClose?: () => void
  deletingConversationId: string | null
  onExport: (conversationId: string) => void
  exportingConversationId: string | null
}) {
  const { t } = useLanguage()
  const [query, setQuery] = React.useState("")
  const filteredConversations = React.useMemo(() => {
    const normalized = query.trim().toLocaleLowerCase()
    if (!normalized) return conversations
    return conversations.filter((conversation) => {
      const question = conversationLabel(conversation.inputs, "")
      const result = conversationResult(conversation.outputs, "")
      return `${question} ${result}`.toLocaleLowerCase().includes(normalized)
    })
  }, [conversations, query])
  return (
    <div className="flex h-full min-h-0 flex-col bg-background">
      <div className="flex min-h-16 items-center gap-3 border-b px-4 pt-[env(safe-area-inset-top)]">
        <span className="flex size-9 items-center justify-center rounded-lg bg-foreground text-background">
          <WorkflowIcon className="size-4" />
        </span>
        <p className="min-w-0 flex-1 truncate text-sm font-semibold">
          {profile.name}
        </p>
        {onClose ? (
          <IconButton label={t("关闭")} onClick={onClose}>
            <XIcon />
          </IconButton>
        ) : null}
      </div>
      <div className="p-3">
        <Button
          type="button"
          variant="outline"
          className="w-full"
          onClick={onNew}
        >
          <MessageSquarePlusIcon />
          {t("新建对话")}
        </Button>
      </div>
      <div className="flex min-h-0 flex-1 flex-col px-3 pb-[max(0.75rem,env(safe-area-inset-bottom))]">
        <div className="flex items-center gap-2 px-2 py-2 text-xs font-medium text-muted-foreground">
          <HistoryIcon className="size-3.5" />
          <span className="flex-1">{t("历史记录")}</span>
        </div>
        <div className="relative mb-2">
          <SearchIcon className="pointer-events-none absolute top-1/2 left-3 size-3.5 -translate-y-1/2 text-muted-foreground" />
          <input
            className="h-10 w-full rounded-md border bg-background pr-2 pl-8 text-base outline-none placeholder:text-muted-foreground focus-visible:ring-2 focus-visible:ring-ring sm:h-8 sm:text-xs"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder={t("搜索历史记录")}
            aria-label={t("搜索历史记录")}
          />
        </div>
        <div className="min-h-0 flex-1 space-y-1 overflow-y-auto">
          {filteredConversations.map((item) => (
            <div
              key={item.conversation_id}
              className={`group flex items-center gap-1 rounded-md px-2 py-1.5 hover:bg-muted ${conversationId === item.conversation_id ? "bg-muted" : ""}`}
            >
              <button
                type="button"
                className="min-w-0 flex-1 rounded-md px-1 py-2 text-left outline-none focus-visible:ring-2 focus-visible:ring-ring"
                aria-current={
                  conversationId === item.conversation_id ? "page" : undefined
                }
                onClick={() => onSelect(item.conversation_id)}
              >
                <span className="block truncate text-sm font-medium">
                  {conversationLabel(item.inputs, t("工作流运行"))}
                </span>
                <span className="mt-1 block truncate text-xs text-muted-foreground">
                  {conversationResult(item.outputs, t("等待回答"))}
                </span>
              </button>
              <DropdownMenu modal={false}>
                <DropdownMenuTrigger asChild>
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon-xs"
                    className="size-8 shrink-0 rounded-md p-0 text-muted-foreground sm:size-5"
                    aria-label={t("更多")}
                    title={t("更多")}
                    onClick={(event) => event.stopPropagation()}
                  >
                    {deletingConversationId === item.conversation_id ||
                    exportingConversationId === item.conversation_id ? (
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
                    onSelect={() => onExport(item.conversation_id)}
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
                    onSelect={() => onDelete(item.conversation_id)}
                  >
                    {t("删除对话")}
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            </div>
          ))}
          {!conversations.length ? (
            <p className="px-2 py-6 text-center text-xs text-muted-foreground">
              {t("暂无历史记录")}
            </p>
          ) : !filteredConversations.length ? (
            <p className="px-2 py-6 text-center text-xs text-muted-foreground">
              {t("暂无匹配的历史记录")}
            </p>
          ) : null}
        </div>
      </div>
    </div>
  )
}

/**
 * Renders the chat interface for a published public workflow.
 *
 * @param workflowId - The identifier of the workflow to run.
 * @param initialConversationId - The conversation to load initially, if provided.
 */
export function PublicWorkflowChat({
  workflowId,
  initialConversationId = null,
}: {
  workflowId: string
  initialConversationId?: string | null
}) {
  const { language, t } = useLanguage()
  const [confirm, confirmDialog] = useConfirmDialog()
  const { token, isSessionRestored, notify } = useSession()
  const viewportStyle = useVisualViewportShellStyle()
  const [profile, setProfile] = React.useState<PublicWorkflowProfile | null>(
    null
  )
  const [conversations, setConversations] = React.useState<
    PublicWorkflowConversation[]
  >([])
  const [conversationId, setConversationId] = React.useState<string | null>(
    initialConversationId
  )
  const [runs, setRuns] = React.useState<ExternalWorkflowRun[]>([])
  const [question, setQuestion] = React.useState("")
  const [composerGeneration, setComposerGeneration] = React.useState(0)
  const [files, setFiles] = React.useState<File[]>([])
  const [loading, setLoading] = React.useState(true)
  const [runsLoading, setRunsLoading] = React.useState(false)
  const [running, setRunning] = React.useState(false)
  const [regeneratingRunId, setRegeneratingRunId] = React.useState<
    string | null
  >(null)
  const [feedbackPendingRunId, setFeedbackPendingRunId] = React.useState<
    string | null
  >(null)
  const [submittingFormRunId, setSubmittingFormRunId] = React.useState<
    string | null
  >(null)
  const [historyOpen, setHistoryOpen] = React.useState(false)
  const [deletingConversationId, setDeletingConversationId] = React.useState<
    string | null
  >(null)
  const [exportingConversationId, setExportingConversationId] = React.useState<
    string | null
  >(null)
  const [error, setError] = React.useState<string | null>(null)
  const streamRef = React.useRef<AbortController | null>(null)
  const fileInputRef = React.useRef<HTMLInputElement>(null)
  const conversationScrollRef = React.useRef<HTMLDivElement>(null)

  React.useEffect(() => () => streamRef.current?.abort(), [])

  React.useEffect(() => {
    if (!isSessionRestored || !token) return
    let active = true
    initializePublicWorkflow(workflowId, token)
      .then(({ profile: nextProfile, conversations: nextConversations }) => {
        if (!active) return
        setProfile(nextProfile)
        setConversations(nextConversations.items)
        const nextId = initialConversationId
        setRunsLoading(Boolean(nextId))
        setConversationId(nextId)
      })
      .catch(() => active && setError(t("此工作流未发布或不可访问。")))
      .finally(() => active && setLoading(false))
    return () => {
      active = false
    }
  }, [initialConversationId, isSessionRestored, t, token, workflowId])

  React.useEffect(() => {
    if (!token || !conversationId) return
    let active = true
    listPublicWorkflowRuns(workflowId, conversationId, token)
      .then((response) => active && setRuns(latestRunVersions(response.items)))
      .catch((reason) => active && setError(getErrorMessage(reason, t)))
      .finally(() => active && setRunsLoading(false))
    return () => {
      active = false
    }
  }, [conversationId, t, token, workflowId])

  React.useLayoutEffect(() => {
    if (conversationScrollRef.current) {
      conversationScrollRef.current.scrollTop =
        conversationScrollRef.current.scrollHeight
    }
  }, [runs, runsLoading])

  function selectConversation(nextId: string | null) {
    setComposerGeneration((current) => current + 1)
    streamRef.current?.abort()
    setRunning(false)
    setRuns([])
    setFiles([])
    setQuestion("")
    setRunsLoading(Boolean(nextId))
    setConversationId(nextId)
    setError(null)
    setHistoryOpen(false)
    window.history.replaceState(
      null,
      "",
      nextId
        ? `/chat/${workflowId}?conversation_id=${encodeURIComponent(nextId)}`
        : `/chat/${workflowId}`
    )
  }

  async function handleDeleteConversation(nextId: string) {
    if (!token || deletingConversationId) return
    const confirmed = await confirm({
      title: t("删除对话"),
      description: t("删除对话说明"),
      confirmLabel: t("删除"),
      destructive: true,
    })
    if (!confirmed) return
    setDeletingConversationId(nextId)
    setError(null)
    try {
      await deletePublicWorkflowConversation(workflowId, nextId, token)
      const refreshed = await listPublicWorkflowConversations(workflowId, token)
      setConversations(refreshed.items)
      if (conversationId === nextId) {
        selectConversation(refreshed.items[0]?.conversation_id ?? null)
      }
    } catch (reason) {
      setError(getErrorMessage(reason, t))
    } finally {
      setDeletingConversationId(null)
    }
  }

  async function handleExportConversation(nextId: string) {
    if (!token || exportingConversationId || deletingConversationId) return
    setExportingConversationId(nextId)
    setError(null)
    try {
      const pageSize = 200
      const exportedRuns: ExternalWorkflowRun[] = []
      for (let offset = 0; ; offset += pageSize) {
        const response = await listPublicWorkflowRuns(
          workflowId,
          nextId,
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
        (item) => item.conversation_id === nextId
      )
      const messages: ConversationExportMessage[] = latestRunVersions(
        exportedRuns
      ).map((run) => ({
        question:
          typeof run.inputs.question === "string"
            ? run.inputs.question
            : t("工作流运行"),
        answer: workflowSpeechText(run.outputs),
        error: run.error,
        createdAt: run.created_at,
      }))
      downloadConversationMarkdown(
        conversation
          ? conversationLabel(conversation.inputs, profile?.name ?? "")
          : profile?.name || t("对话记录"),
        messages
      )
    } catch (reason) {
      setError(getErrorMessage(reason, t))
    } finally {
      setExportingConversationId(null)
    }
  }

  async function handleRun(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const nextQuestion = question.trim()
    if (!token || !profile || running || !nextQuestion) return
    setRunning(true)
    setError(null)
    try {
      const uploaded = files.length
        ? await uploadPublicWorkflowFiles(workflowId, token, files)
        : []
      const run = await createPublicWorkflowRun(
        workflowId,
        token,
        nextQuestion,
        conversationId,
        uploaded.map((item) => item.id)
      )
      setQuestion("")
      const nextConversationId = run.conversation_id
      setConversationId(nextConversationId)
      setRuns((current) => [run, ...current])
      window.history.replaceState(
        null,
        "",
        `/chat/${workflowId}?conversation_id=${encodeURIComponent(nextConversationId)}`
      )
      if (!["succeeded", "failed", "cancelled"].includes(run.status)) {
        const controller = new AbortController()
        streamRef.current = controller
        await observePublicWorkflowRun(
          workflowId,
          token,
          run.id,
          (streamEvent) => {
            setRuns((current) => updateRun(current, run.id, streamEvent))
            if (
              streamEvent.type === "complete" &&
              streamEvent.run.status === "succeeded" &&
              profile.interaction_config.tts_type === "BROWSER"
            ) {
              speakBrowserText(
                workflowSpeechText(streamEvent.run.outputs),
                language
              )
            }
          },
          controller.signal
        )
        if (streamRef.current === controller) streamRef.current = null
      } else if (
        run.status === "succeeded" &&
        profile.interaction_config.tts_type === "BROWSER"
      ) {
        speakBrowserText(workflowSpeechText(run.outputs), language)
      }
      setFiles([])
      const refreshed = await initializePublicWorkflow(workflowId, token)
      setConversations(refreshed.conversations.items)
    } catch (reason) {
      if (!(reason instanceof DOMException && reason.name === "AbortError")) {
        setError(getErrorMessage(reason, t))
      }
    } finally {
      setRunning(false)
    }
  }

  async function handleRegenerateRun(runId: string) {
    if (
      !token ||
      running ||
      regeneratingRunId ||
      feedbackPendingRunId ||
      streamRef.current
    ) {
      return
    }
    setRegeneratingRunId(runId)
    const previous = runs.find((run) => run.id === runId)
    let replacementId = runId
    const controller = new AbortController()
    streamRef.current = controller
    try {
      const regenerated = await regeneratePublicWorkflowRun(
        workflowId,
        token,
        runId
      )
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
      await observePublicWorkflowRun(
        workflowId,
        token,
        regenerated.id,
        (streamEvent) => {
          if (streamRef.current !== controller) return
          setRuns((current) => updateRun(current, regenerated.id, streamEvent))
          if (
            (streamEvent.type === "error" || streamEvent.type === "complete") &&
            ["failed", "cancelled"].includes(streamEvent.run.status)
          ) {
            restorePrevious()
          }
        },
        controller.signal
      )
    } catch (reason) {
      if (!(reason instanceof DOMException && reason.name === "AbortError")) {
        if (previous) {
          setRuns((current) =>
            current.map((run) => (run.id === replacementId ? previous : run))
          )
        }
        setError(getErrorMessage(reason, t))
      }
    } finally {
      if (streamRef.current === controller) streamRef.current = null
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
      const updated = await setPublicWorkflowRunFeedback(
        workflowId,
        token,
        runId,
        value
      )
      setRuns((current) =>
        current.map((run) => (run.id === runId ? { ...run, ...updated } : run))
      )
      notify("success", feedbackConfirmationLabel(value, t))
    } catch (reason) {
      setRuns((current) =>
        current.map((run) =>
          run.id === runId ? { ...run, feedback: previous } : run
        )
      )
      setError(getErrorMessage(reason, t))
    } finally {
      setFeedbackPendingRunId(null)
    }
  }

  async function handleFormSubmit(
    run: ExternalWorkflowRun,
    data: Record<string, unknown>
  ) {
    if (!token || !run.pending_form || submittingFormRunId) return
    setSubmittingFormRunId(run.id)
    setRunning(true)
    setError(null)
    try {
      const resumed = await submitPublicWorkflowForm(
        workflowId,
        token,
        run.id,
        run.pending_form.runtime_node_id,
        data
      )
      setRuns((current) =>
        current.map((item) =>
          item.id === run.id ? { ...resumed, progress: item.progress } : item
        )
      )
      const controller = new AbortController()
      streamRef.current = controller
      await observePublicWorkflowRun(
        workflowId,
        token,
        run.id,
        (streamEvent) => {
          setRuns((current) => updateRun(current, run.id, streamEvent))
          if (
            streamEvent.type === "complete" &&
            streamEvent.run.status === "succeeded" &&
            profile?.interaction_config.tts_type === "BROWSER"
          ) {
            speakBrowserText(
              workflowSpeechText(streamEvent.run.outputs),
              language
            )
          }
        },
        controller.signal
      )
      const refreshed = await initializePublicWorkflow(workflowId, token)
      setConversations(refreshed.conversations.items)
    } catch (reason) {
      if (!(reason instanceof DOMException && reason.name === "AbortError")) {
        setError(getErrorMessage(reason, t))
      }
    } finally {
      if (streamRef.current) streamRef.current = null
      setSubmittingFormRunId(null)
      setRunning(false)
    }
  }

  if (loading) {
    return (
      <main className="flex min-h-dvh items-center justify-center bg-muted/30 p-6 text-sm text-muted-foreground">
        {error ? (
          <div className="max-w-md text-center text-destructive">{error}</div>
        ) : (
          <>
            <LoaderCircleIcon className="mr-2 size-4 animate-spin" />
            {t("正在加载")}
          </>
        )}
      </main>
    )
  }

  if (error && !profile) {
    return (
      <main className="flex min-h-dvh items-center justify-center bg-muted/30 p-6">
        <div className="max-w-md text-center">
          <span className="mx-auto flex size-12 items-center justify-center rounded-xl bg-destructive/10 text-destructive">
            <CircleAlertIcon className="size-5" />
          </span>
          <h1 className="mt-4 text-lg font-semibold">
            {t("无法打开公开对话")}
          </h1>
          <p className="mt-2 text-sm text-muted-foreground">{error}</p>
        </div>
      </main>
    )
  }

  if (!profile) return null

  const historyProps = {
    profile,
    conversations,
    conversationId,
    onNew: () => selectConversation(null),
    onSelect: selectConversation,
    onDelete: handleDeleteConversation,
    deletingConversationId,
    onExport: handleExportConversation,
    exportingConversationId,
  }
  const visibleRuns = [...runs].reverse()
  const hasPendingForm = runs.some((run) => run.status === "awaiting_input")
  const composerDisabled = running || runsLoading || hasPendingForm

  return (
    <main
      className="grid h-dvh min-h-0 overflow-hidden bg-muted/20 lg:h-svh lg:grid-cols-[240px_minmax(0,1fr)] xl:grid-cols-[280px_minmax(0,1fr)]"
      style={viewportStyle}
    >
      <aside className="hidden min-h-0 border-r lg:block">
        <ConversationHistory {...historyProps} />
      </aside>

      <section className="flex min-h-0 min-w-0 flex-col">
        <header className="flex min-h-16 shrink-0 items-center gap-2 border-b bg-background/95 px-3 pt-[env(safe-area-inset-top)] backdrop-blur sm:gap-3 sm:px-6">
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="lg:hidden"
            aria-label={t("打开历史记录")}
            title={t("打开历史记录")}
            onClick={() => setHistoryOpen(true)}
          >
            <MenuIcon />
          </Button>
          <span className="hidden size-9 shrink-0 items-center justify-center rounded-lg bg-primary text-primary-foreground sm:flex">
            <WorkflowIcon className="size-4" />
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
            onClick={() => selectConversation(null)}
          >
            <MessageSquarePlusIcon />
          </Button>
        </header>

        <div
          ref={conversationScrollRef}
          className="min-h-0 flex-1 overflow-x-hidden overflow-y-auto overscroll-contain"
        >
          <div className="mx-auto flex min-h-full w-full max-w-5xl flex-col px-3 py-4 sm:px-8 sm:py-8">
            {runsLoading ? (
              <div className="flex flex-1 items-center justify-center text-sm text-muted-foreground">
                <LoaderCircleIcon className="mr-2 size-4 animate-spin" />
                {t("正在加载")}
              </div>
            ) : visibleRuns.length === 0 ? (
              <div className="flex flex-1 flex-col items-center justify-center text-center">
                <span className="flex size-14 items-center justify-center rounded-xl bg-primary text-primary-foreground shadow-sm">
                  <WorkflowIcon className="size-6" />
                </span>
                <h2 className="mt-4 text-base font-semibold">
                  {t("开始新对话")}
                </h2>
                <p className="mt-2 max-w-md text-sm leading-6 whitespace-pre-wrap text-muted-foreground">
                  {profile.description ||
                    profile.interaction_config.prologue ||
                    t("输入问题，工作流会按照已发布配置执行。")}
                </p>
              </div>
            ) : (
              <div className="space-y-6 sm:space-y-8">
                {visibleRuns.map((run) => {
                  const questionValue =
                    typeof run.inputs.question === "string" &&
                    run.inputs.question.trim()
                      ? run.inputs.question
                      : t("工作流运行")
                  const result = workflowSpeechText(run.outputs) || ""
                  const hasResult = Boolean(result.trim() && result !== "{}")
                  return (
                    <article key={run.id} className="space-y-4">
                      <div className="flex items-start justify-end gap-2">
                        <div className="flex max-w-[85%] min-w-0 flex-col items-end gap-1">
                          <RunAttachmentCards
                            attachments={run.inputs.files}
                            t={t}
                          />
                          <div className="rounded-2xl rounded-tr-md bg-primary px-4 py-2.5 text-sm leading-6 [overflow-wrap:anywhere] break-words whitespace-pre-wrap text-primary-foreground">
                            {questionValue}
                          </div>
                          <CopyButton t={t} value={questionValue} />
                        </div>
                        <span className="hidden size-8 shrink-0 items-center justify-center rounded-full bg-foreground text-background sm:flex">
                          <UserIcon className="size-3.5" />
                        </span>
                      </div>

                      <div className="flex items-start gap-3">
                        <span className="mt-0.5 hidden size-8 shrink-0 items-center justify-center rounded-lg bg-foreground text-background shadow-sm sm:flex">
                          <WorkflowIcon className="size-4" />
                        </span>
                        <div className="min-w-0 flex-1">
                          <div className="rounded-2xl rounded-tl-md border bg-background p-3 shadow-xs sm:p-4">
                            <PublicWorkflowExecutionProcess run={run} />
                            {run.status === "awaiting_input" &&
                            run.pending_form ? (
                              <WorkflowRuntimeForm
                                key={run.pending_form.runtime_node_id}
                                form={run.pending_form}
                                submitting={submittingFormRunId === run.id}
                                onSubmit={(data) => handleFormSubmit(run, data)}
                              />
                            ) : null}
                            {hasResult ? (
                              <MarkdownContent
                                content={result}
                                className="text-sm leading-6"
                              />
                            ) : run.status === "failed" ? (
                              <p className="rounded-md border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
                                {run.error
                                  ? workflowErrorMessage(run.error, t)
                                  : t("运行失败")}
                              </p>
                            ) : null}
                          </div>
                          <div className="flex flex-wrap items-start justify-between gap-2">
                            <MessageTimestamp
                              value={run.started_at ?? run.created_at}
                            />
                            {run.status === "succeeded" && hasResult ? (
                              <RunActionBar
                                result={result}
                                feedback={run.feedback}
                                regenerateDisabled={running || runsLoading}
                                regenerating={regeneratingRunId === run.id}
                                feedbackPending={
                                  feedbackPendingRunId === run.id
                                }
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
                      </div>
                    </article>
                  )
                })}
              </div>
            )}
          </div>
        </div>

        <div className="shrink-0 border-t bg-background p-2 pb-[max(0.5rem,env(safe-area-inset-bottom))] sm:p-4 sm:pb-[max(1rem,env(safe-area-inset-bottom))]">
          {error ? (
            <p
              role="alert"
              className="mx-auto mb-2 max-w-3xl text-xs text-destructive"
            >
              {error}
            </p>
          ) : null}
          <form
            className="mx-auto max-w-3xl rounded-xl border border-input bg-muted/20 p-1.5 shadow-xs transition-[background-color,border-color,box-shadow] focus-within:border-ring focus-within:bg-card focus-within:shadow-sm focus-within:ring-3 focus-within:ring-ring/20"
            onSubmit={handleRun}
            onDragOver={(event) => {
              if (
                profile.interaction_config.file_upload &&
                event.dataTransfer.types.includes("Files")
              ) {
                event.preventDefault()
              }
            }}
            onDrop={(event) => {
              if (!profile.interaction_config.file_upload) return
              const dropped = transferredFiles(event.dataTransfer)
              if (!dropped.length) return
              event.preventDefault()
              if (composerDisabled) return
              setError(null)
              setFiles((current) => appendAttachmentFiles(current, dropped))
            }}
          >
            {profile.interaction_config.file_upload ? (
              <input
                ref={fileInputRef}
                type="file"
                className="sr-only"
                multiple
                accept={acceptedUploadExtensions(
                  profile.interaction_config.file_upload_setting
                    .file_upload_type
                )}
                disabled={composerDisabled}
                onChange={(event) => {
                  const selected = Array.from(event.target.files ?? [])
                  setError(null)
                  setFiles((current) =>
                    appendAttachmentFiles(current, selected)
                  )
                }}
              />
            ) : null}
            <textarea
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              onPaste={(event) => {
                if (
                  !profile.interaction_config.file_upload ||
                  composerDisabled
                ) {
                  return
                }
                const pasted = transferredFiles(event.clipboardData)
                if (!pasted.length) return
                event.preventDefault()
                setError(null)
                setFiles((current) => appendAttachmentFiles(current, pasted))
              }}
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
              className="max-h-32 min-h-11 w-full resize-none bg-transparent px-2.5 py-2 text-base leading-6 outline-none selection:bg-primary selection:text-primary-foreground placeholder:text-muted-foreground sm:min-h-12 sm:text-sm"
              placeholder={t("请输入问题")}
              aria-label={t("请输入问题")}
              enterKeyHint="send"
              autoComplete="off"
              maxLength={4000}
              rows={1}
              disabled={composerDisabled}
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
            <div className="flex items-end justify-between gap-2 px-0.5 pb-0.5">
              <div className="flex min-w-0 items-center gap-1">
                {profile.interaction_config.file_upload ? (
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon-sm"
                    className="rounded-md text-muted-foreground hover:text-foreground"
                    aria-label={t("添加附件")}
                    title={t("添加附件")}
                    disabled={composerDisabled}
                    onClick={() => {
                      if (!fileInputRef.current) return
                      fileInputRef.current.value = ""
                      fileInputRef.current.click()
                    }}
                  >
                    <PlusIcon />
                  </Button>
                ) : null}
                {profile.interaction_config.stt_type === "BROWSER" ? (
                  <SpeechInputButton
                    key={`${workflowId}:${composerGeneration}`}
                    value={question}
                    onChange={setQuestion}
                    onError={(message) => notify("error", message)}
                    disabled={composerDisabled}
                  />
                ) : null}
              </div>
              <Button
                type="submit"
                size="icon"
                className="rounded-full"
                aria-label={t("发送问题")}
                title={t("发送问题")}
                disabled={composerDisabled || !question.trim()}
              >
                {running ? (
                  <LoaderCircleIcon className="animate-spin" />
                ) : (
                  <ArrowUpIcon />
                )}
              </Button>
            </div>
          </form>
        </div>
      </section>

      <Dialog open={historyOpen} onOpenChange={setHistoryOpen}>
        <DialogContent
          side="right"
          className="flex h-full min-h-0 flex-col gap-0 overflow-hidden p-0 max-sm:max-w-none lg:hidden"
        >
          <DialogHeader className="sr-only">
            <DialogTitle>{t("历史记录")}</DialogTitle>
            <DialogDescription>{t("选择或新建对话")}</DialogDescription>
          </DialogHeader>
          <ConversationHistory
            {...historyProps}
            onClose={() => setHistoryOpen(false)}
          />
        </DialogContent>
      </Dialog>
      {confirmDialog}
    </main>
  )
}
