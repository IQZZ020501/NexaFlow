"use client"

import * as React from "react"
import { useRouter } from "next/navigation"
import {
  CircleAlertIcon,
  CircleCheckIcon,
  CircleDotDashedIcon,
  HistoryIcon,
  LoaderCircleIcon,
  MenuIcon,
  MessageSquarePlusIcon,
  PaperclipIcon,
  PlayIcon,
  WorkflowIcon,
} from "lucide-react"

import { MarkdownContent } from "@/components/knowledge/markdown-content"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
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
  initializePublicWorkflow,
  listPublicWorkflowRuns,
  observePublicWorkflowRun,
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
import { acceptedUploadExtensions } from "@/lib/interaction-config"
import {
  workflowErrorMessage,
  workflowNodeLabel,
} from "@/lib/workflows/graph"

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

function ConversationHistory({
  profile,
  conversations,
  conversationId,
  onNew,
  onSelect,
}: {
  profile: PublicWorkflowProfile
  conversations: PublicWorkflowConversation[]
  conversationId: string | null
  onNew: () => void
  onSelect: (conversationId: string) => void
}) {
  const { t } = useLanguage()
  return (
    <div className="flex h-full min-h-0 flex-col bg-background">
      <div className="flex min-h-16 items-center gap-3 border-b px-4">
        <span className="flex size-9 items-center justify-center rounded-lg bg-foreground text-background">
          <WorkflowIcon className="size-4" />
        </span>
        <p className="truncate text-sm font-semibold">{profile.name}</p>
      </div>
      <div className="p-3">
        <Button type="button" variant="outline" className="w-full" onClick={onNew}>
          <MessageSquarePlusIcon />
          {t("新建对话")}
        </Button>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto px-3 pb-3">
        <p className="flex items-center gap-2 px-2 py-2 text-xs font-medium text-muted-foreground">
          <HistoryIcon className="size-3.5" />
          {t("历史记录")}
        </p>
        {conversations.map((item) => (
          <button
            key={item.conversation_id}
            type="button"
            className={`w-full rounded-md px-3 py-2 text-left hover:bg-muted ${conversationId === item.conversation_id ? "bg-muted" : ""}`}
            aria-current={conversationId === item.conversation_id ? "page" : undefined}
            onClick={() => onSelect(item.conversation_id)}
          >
            <span className="block truncate text-sm font-medium">
              {conversationLabel(item.inputs, t("工作流运行"))}
            </span>
            <span className="mt-1 block truncate text-xs text-muted-foreground">
              {t("运行 {count} 次", { count: item.run_count })}
            </span>
          </button>
        ))}
        {!conversations.length ? (
          <p className="px-2 py-6 text-center text-xs text-muted-foreground">
            {t("暂无历史记录")}
          </p>
        ) : null}
      </div>
    </div>
  )
}

export function PublicWorkflowChat({
  workflowId,
  initialConversationId = null,
}: {
  workflowId: string
  initialConversationId?: string | null
}) {
  const router = useRouter()
  const { language, t } = useLanguage()
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
  const [submittingFormRunId, setSubmittingFormRunId] = React.useState<string | null>(null)
  const [historyOpen, setHistoryOpen] = React.useState(false)
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
      .then((response) => active && setRuns(response.items))
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
    router.replace(
      nextId
        ? `/chat/${workflowId}?conversation_id=${encodeURIComponent(nextId)}`
        : `/chat/${workflowId}`
    )
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
      router.replace(
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
            ) : (
              runs.length ? runs.map((run) => (
                <article
                  key={run.id}
                  className="space-y-3 rounded-lg border bg-background p-4 shadow-xs"
                >
                  <div className="flex justify-end">
                    <div className="max-w-[85%] rounded-2xl rounded-tr-md bg-primary px-4 py-2.5 text-sm leading-6 break-words whitespace-pre-wrap text-primary-foreground [overflow-wrap:anywhere]">
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
                            ) : ["skipped", "awaiting_input"].includes(item.status) ? (
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
                    </section>
                  ) : null}
                  {run.error ? (
                    <p className="rounded-md bg-destructive/10 p-3 text-sm text-destructive">
                      {workflowErrorMessage(run.error, t)}
                    </p>
                  ) : null}
                </article>
              )) : profile.interaction_config.prologue ? (
                <div className="rounded-lg border bg-background p-4 text-sm leading-6 shadow-xs whitespace-pre-wrap">
                  {profile.interaction_config.prologue}
                </div>
              ) : null
            )}

            <form
              className="rounded-lg border bg-background p-4 shadow-xs"
              onSubmit={handleRun}
            >
              <div className="mb-4">
                <h2 className="text-sm font-semibold">
                  {profile.interaction_config.user_input_title || t("运行工作流")}
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
                        profile.interaction_config.file_upload_setting.file_upload_type
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
    </main>
  )
}
