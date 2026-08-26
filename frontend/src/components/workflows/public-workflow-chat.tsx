"use client"

import * as React from "react"
import {
  CircleAlertIcon,
  CircleCheckIcon,
  CircleDotDashedIcon,
  DownloadIcon,
  EllipsisIcon,
  HistoryIcon,
  LoaderCircleIcon,
  MenuIcon,
  MessageSquarePlusIcon,
  PaperclipIcon,
  PlayIcon,
  SearchIcon,
  WorkflowIcon,
} from "lucide-react"

import { MarkdownContent } from "@/components/knowledge/markdown-content"
import { RunActionBar } from "@/components/app/run-action-bar"
import { useConfirmDialog } from "@/components/app/confirm-dialog"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
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
import { Input } from "@/components/ui/input"
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
 */
function ConversationHistory({
  profile,
  conversations,
  conversationId,
  onNew,
  onSelect,
  onDelete,
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
      conversationLabel(conversation.inputs, "")
        .toLocaleLowerCase()
        .includes(normalized)
    )
  }, [conversations, query])
  return (
    <div className="flex h-full min-h-0 flex-col bg-background">
      <div className="flex min-h-16 items-center gap-3 border-b px-4">
        <span className="flex size-9 items-center justify-center rounded-lg bg-foreground text-background">
          <WorkflowIcon className="size-4" />
        </span>
        <p className="truncate text-sm font-semibold">{profile.name}</p>
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
      <div className="min-h-0 flex-1 overflow-y-auto px-3 pb-3">
        <p className="flex items-center gap-2 px-2 py-2 text-xs font-medium text-muted-foreground">
          <HistoryIcon className="size-3.5" />
          {t("历史记录")}
        </p>
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
        {filteredConversations.map((item) => (
          <div
            key={item.conversation_id}
            className={`group flex items-center gap-1 rounded-md px-2 py-1 hover:bg-muted ${conversationId === item.conversation_id ? "bg-muted" : ""}`}
          >
            <button
              type="button"
              className="min-w-0 flex-1 rounded-md px-1 py-1.5 text-left outline-none focus-visible:ring-2 focus-visible:ring-ring"
              aria-current={
                conversationId === item.conversation_id ? "page" : undefined
              }
              onClick={() => onSelect(item.conversation_id)}
            >
              <span className="block truncate text-sm font-medium">
                {conversationLabel(item.inputs, t("工作流运行"))}
              </span>
              <span className="mt-1 block truncate text-xs text-muted-foreground">
                {t("运行 {count} 次", { count: item.run_count })}
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
  const { token, isSessionRestored } = useSession()
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
        const nextId =
          initialConversationId ??
          nextConversations.items[0]?.conversation_id ??
          null
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
    streamRef.current?.abort()
    setRuns([])
    setFiles([])
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
      setSubmittingFormRunId(null)
    }
  }

  if (loading || !profile) {
    return (
      <main className="flex min-h-svh items-center justify-center p-6 text-sm text-muted-foreground">
        {error ?? (
          <>
            <LoaderCircleIcon className="mr-2 size-4 animate-spin" />
            {t("正在加载")}
          </>
        )}
      </main>
    )
  }

  const history = (
    <ConversationHistory
      profile={profile}
      conversations={conversations}
      conversationId={conversationId}
      onNew={() => selectConversation(null)}
      onSelect={selectConversation}
      onDelete={handleDeleteConversation}
      deletingConversationId={deletingConversationId}
      onExport={handleExportConversation}
      exportingConversationId={exportingConversationId}
    />
  )

  return (
    <main className="grid h-svh min-h-0 bg-muted/20 md:grid-cols-[16rem_minmax(0,1fr)]">
      <aside className="hidden min-h-0 border-r md:block">{history}</aside>

      <section className="flex min-h-0 min-w-0 flex-col">
        <header className="flex min-h-16 items-center gap-3 border-b bg-background px-4 sm:px-6">
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="md:hidden"
            aria-label={t("打开历史记录")}
            title={t("打开历史记录")}
            onClick={() => setHistoryOpen(true)}
          >
            <MenuIcon />
          </Button>
          <span className="flex size-9 items-center justify-center rounded-lg bg-foreground text-background md:hidden">
            <WorkflowIcon className="size-4" />
          </span>
          <div className="min-w-0 flex-1">
            <h1 className="truncate text-sm font-semibold">{profile.name}</h1>
            <p className="truncate text-xs text-muted-foreground">
              {profile.description || t("工作流")}
            </p>
          </div>
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="md:hidden"
            onClick={() => selectConversation(null)}
          >
            <MessageSquarePlusIcon />
            {t("新建对话")}
          </Button>
        </header>

        <div
          ref={conversationScrollRef}
          className="min-h-0 flex-1 overflow-y-auto"
        >
          <div className="mx-auto w-full max-w-3xl space-y-6 px-4 py-8 sm:px-8">
            {runsLoading ? (
              <p className="flex items-center justify-center py-12 text-sm text-muted-foreground">
                <LoaderCircleIcon className="mr-2 size-4 animate-spin" />
                {t("正在加载")}
              </p>
            ) : runs.length ? (
              runs.map((run) => (
                <article
                  key={run.id}
                  className="space-y-3 rounded-lg border bg-background p-4 shadow-xs"
                >
                  <div className="flex justify-end">
                    <div className="max-w-[85%] rounded-2xl rounded-tr-md bg-primary px-4 py-2.5 text-sm leading-6 [overflow-wrap:anywhere] break-words whitespace-pre-wrap text-primary-foreground">
                      {typeof run.inputs.question === "string" &&
                      run.inputs.question.trim()
                        ? run.inputs.question
                        : t("工作流运行")}
                    </div>
                  </div>
                  <div className="flex items-center justify-between gap-3">
                    <p className="text-sm font-semibold">{t("工作流运行")}</p>
                    <Badge
                      variant={
                        run.status === "failed" ? "destructive" : "outline"
                      }
                    >
                      {t(
                        run.status === "succeeded"
                          ? "运行成功"
                          : run.status === "failed"
                            ? "运行失败"
                            : run.status === "awaiting_input"
                              ? "等待填写表单"
                              : "运行中"
                      )}
                    </Badge>
                  </div>
                  {run.progress.length ? (
                    <section>
                      <p className="mb-2 text-xs font-medium text-muted-foreground">
                        {t("节点执行记录")}
                      </p>
                      <div className="divide-y rounded-md border">
                        {run.progress.map((item) => (
                          <div
                            key={item.id}
                            className="flex items-center gap-2 px-3 py-2 text-sm"
                          >
                            {item.status === "failed" ? (
                              <CircleAlertIcon className="size-4 text-destructive" />
                            ) : item.status === "succeeded" ? (
                              <CircleCheckIcon className="size-4 text-emerald-600" />
                            ) : ["skipped", "awaiting_input"].includes(
                                item.status
                              ) ? (
                              <CircleDotDashedIcon className="size-4 text-muted-foreground" />
                            ) : (
                              <LoaderCircleIcon className="size-4 animate-spin text-muted-foreground" />
                            )}
                            <span
                              className="min-w-0 flex-1 truncate"
                              title={item.node_id}
                            >
                              {workflowNodeLabel(item.node_type, t)}
                            </span>
                          </div>
                        ))}
                      </div>
                    </section>
                  ) : null}
                  {run.status === "awaiting_input" && run.pending_form ? (
                    <WorkflowRuntimeForm
                      key={run.pending_form.runtime_node_id}
                      form={run.pending_form}
                      submitting={submittingFormRunId === run.id}
                      onSubmit={(data) => handleFormSubmit(run, data)}
                    />
                  ) : null}
                  {typeof run.outputs.result === "string" ||
                  run.status === "succeeded" ? (
                    <section>
                      <p className="mb-2 text-xs font-medium text-muted-foreground">
                        {t("运行结果")}
                      </p>
                      <MarkdownContent
                        content={workflowSpeechText(run.outputs)}
                        className="text-sm leading-6"
                      />
                      {run.status === "succeeded" &&
                      workflowSpeechText(run.outputs) ? (
                        <RunActionBar
                          result={workflowSpeechText(run.outputs)}
                          feedback={run.feedback}
                          regenerateDisabled={running || runsLoading}
                          regenerating={regeneratingRunId === run.id}
                          feedbackPending={feedbackPendingRunId === run.id}
                          onRegenerate={() => void handleRegenerateRun(run.id)}
                          onFeedback={(value) =>
                            void handleRunFeedback(run.id, value)
                          }
                          t={t}
                        />
                      ) : null}
                    </section>
                  ) : null}
                  {run.error ? (
                    <p className="rounded-md bg-destructive/10 p-3 text-sm text-destructive">
                      {workflowErrorMessage(run.error, t)}
                    </p>
                  ) : null}
                </article>
              ))
            ) : profile.interaction_config.prologue ? (
              <div className="rounded-lg border bg-background p-4 text-sm leading-6 whitespace-pre-wrap shadow-xs">
                {profile.interaction_config.prologue}
              </div>
            ) : null}

            <form
              className="rounded-lg border bg-background p-4 shadow-xs"
              onSubmit={handleRun}
            >
              <div className="mb-4">
                <h2 className="text-sm font-semibold">
                  {profile.interaction_config.user_input_title ||
                    t("运行工作流")}
                </h2>
                <p className="mt-1 text-xs text-muted-foreground">
                  {t("问题将作为开始节点的 question 输出注入已发布版本。")}
                </p>
              </div>
              <div className="grid gap-4">
                <label
                  className="grid gap-1.5 text-sm font-medium"
                  htmlFor="workflow-chat-question"
                >
                  {t("用户问题")}
                  <textarea
                    id="workflow-chat-question"
                    rows={4}
                    className="resize-y rounded-md border bg-background px-3 py-2 text-sm leading-6 outline-none focus-visible:ring-2 focus-visible:ring-ring"
                    value={question}
                    onChange={(event) => setQuestion(event.target.value)}
                    onKeyDown={(event) => {
                      if (
                        event.key === "Enter" &&
                        (event.metaKey || event.ctrlKey)
                      ) {
                        event.preventDefault()
                        event.currentTarget.form?.requestSubmit()
                      }
                    }}
                  />
                </label>
                {profile.interaction_config.file_upload ? (
                  <label className="grid gap-1.5 text-sm font-medium">
                    <span className="flex items-center gap-2">
                      <PaperclipIcon className="size-4" />
                      {t("文件上传")}
                    </span>
                    <Input
                      type="file"
                      multiple
                      accept={acceptedUploadExtensions(
                        profile.interaction_config.file_upload_setting
                          .file_upload_type
                      )}
                      onChange={(event) => {
                        const selected = Array.from(event.target.files ?? [])
                        setError(null)
                        setFiles(selected)
                      }}
                    />
                  </label>
                ) : null}
              </div>
              {error ? (
                <p role="alert" className="mt-4 text-sm text-destructive">
                  {error}
                </p>
              ) : null}
              <Button
                type="submit"
                className="mt-5"
                disabled={
                  running ||
                  runs.some((run) => run.status === "awaiting_input") ||
                  !question.trim()
                }
              >
                {running ? (
                  <LoaderCircleIcon className="animate-spin" />
                ) : (
                  <PlayIcon />
                )}
                {t("开始运行")}
              </Button>
            </form>
          </div>
        </div>
      </section>

      <Dialog open={historyOpen} onOpenChange={setHistoryOpen}>
        <DialogContent side="right" className="p-0 md:hidden">
          <DialogHeader className="sr-only">
            <DialogTitle>{t("历史记录")}</DialogTitle>
            <DialogDescription>{t("选择或新建对话")}</DialogDescription>
          </DialogHeader>
          {history}
        </DialogContent>
      </Dialog>
      {confirmDialog}
    </main>
  )
}
