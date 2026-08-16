"use client"

import * as React from "react"
import dynamic from "next/dynamic"
import {
  ArrowLeftIcon,
  ChevronDownIcon,
  CopyIcon,
  HistoryIcon,
  LayoutDashboardIcon,
  LoaderCircleIcon,
  Maximize2Icon,
  Minimize2Icon,
  PaperclipIcon,
  PlayIcon,
  PlusIcon,
  SaveIcon,
  ScrollTextIcon,
  SendIcon,
  SettingsIcon,
  ShieldCheckIcon,
  MoreHorizontalIcon,
  Trash2Icon,
  UploadIcon,
  UsersIcon,
  ChartNoAxesColumnIcon,
  WorkflowIcon,
  XIcon,
} from "lucide-react"

import { AgentConfigFields } from "@/components/agents/agent-config-fields"
import { useConfirmDialog } from "@/components/app/confirm-dialog"
import { AgentAttachmentList } from "@/components/agents/agent-attachment-list"
import { MarkdownContent } from "@/components/knowledge/markdown-content"
import {
  AgentConversationUsersPanel,
  AgentLogsPanel,
  AgentMonitoringPanel,
  AgentOverviewPanel,
} from "@/components/agents/agent-management-panels"
import type { AgentFormState } from "@/components/agents/agents-page"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { IconButton } from "@/components/ui/icon-button"
import { WorkflowRuntimeForm } from "@/components/workflows/workflow-runtime-form"
import type { TFunction } from "@/i18n"
import type { AgentDetailView } from "@/lib/agent-views"
import { compareLiveStreamIds, type Agent } from "@/lib/api/agents"
import type { KnowledgeBase } from "@/lib/api/knowledge"
import type { RegisteredModel } from "@/lib/api/llm"
import type { McpServer } from "@/lib/api/mcp"
import {
  createWorkflowRun,
  getWorkflowDefinition,
  listWorkflowNodeExecutions,
  listWorkflowRuns,
  listWorkflowVersions,
  observeWorkflowRun,
  publishWorkflow,
  restoreWorkflowVersion,
  submitWorkflowForm,
  updateWorkflowDefinition,
  uploadWorkflowFiles,
  type WorkflowDefinition,
  type WorkflowGraph,
  type WorkflowNodeExecution,
  type WorkflowRun,
  type WorkflowRunStreamEvent,
  type WorkflowVersion,
} from "@/lib/api/workflows"
import { workflowSpeechText } from "@/lib/browser-tts"
import { copyText } from "@/lib/clipboard"
import { getErrorMessage } from "@/lib/errors"
import { acceptedUploadExtensions } from "@/lib/interaction-config"
import {
  selectWorkflowRunTarget,
  workflowErrorMessage,
  workflowExecutionNodeLabel,
  workflowGraphSignature,
} from "@/lib/workflows/graph"
import { cn } from "@/lib/utils"

const WorkflowCanvas = dynamic(() => import("./workflow-canvas"), {
  ssr: false,
  loading: () => (
    <div className="flex min-h-[520px] items-center justify-center">
      <LoaderCircleIcon className="size-5 animate-spin text-muted-foreground" />
    </div>
  ),
})

type WorkflowDetailWorkspaceProps = {
  agent: Agent
  form: AgentFormState
  setForm: React.Dispatch<React.SetStateAction<AgentFormState>>
  models: RegisteredModel[]
  knowledgeBases: KnowledgeBase[]
  mcpServers: McpServer[]
  token: string
  workspaceId: string
  canManagePublishing: boolean
  isAppDirty: boolean
  isSavingApp: boolean
  activeView: AgentDetailView
  standalone?: boolean
  onBack: () => void
  onDelete: () => void
  onManagePermissions: () => void
  onSaveApp: (event?: React.FormEvent<HTMLFormElement>) => void
  onViewChange: (view: AgentDetailView) => void
  notify: (kind: "success" | "error", message: string) => void
  t: TFunction
}

const TERMINAL_STATUSES = new Set(["succeeded", "failed", "cancelled"])

function runStatusLabel(run: WorkflowRun, t: TFunction) {
  if (run.status === "queued") return t("等待执行")
  if (run.status === "running") return t("运行中")
  if (run.status === "awaiting_input") return t("等待填写表单")
  if (run.status === "succeeded") return t("运行成功")
  if (run.status === "cancelled") return t("运行已取消")
  return t("运行失败")
}

function JsonBlock({ value }: { value: unknown }) {
  return (
    <pre className="max-h-64 overflow-auto whitespace-pre-wrap break-words rounded-md bg-muted p-3 font-mono text-xs leading-5">
      {JSON.stringify(value, null, 2)}
    </pre>
  )
}

export function WorkflowDetailWorkspace({
  agent,
  form,
  setForm,
  models,
  knowledgeBases,
  mcpServers,
  token,
  workspaceId,
  canManagePublishing,
  isAppDirty,
  isSavingApp,
  activeView,
  standalone,
  onBack,
  onDelete,
  onManagePermissions,
  onSaveApp,
  onViewChange,
  notify,
  t,
}: WorkflowDetailWorkspaceProps) {
  const [confirmAction, confirmDialog] = useConfirmDialog()
  const [definition, setDefinition] = React.useState<WorkflowDefinition | null>(
    null
  )
  const [graph, setGraph] = React.useState<WorkflowGraph | null>(null)
  const [versions, setVersions] = React.useState<WorkflowVersion[]>([])
  const [currentRun, setCurrentRun] = React.useState<WorkflowRun | null>(null)
  const [executions, setExecutions] = React.useState<WorkflowNodeExecution[]>(
    []
  )
  const [runtimeStatuses, setRuntimeStatuses] = React.useState<
    Record<string, WorkflowNodeExecution["status"]>
  >({})
  const [isLoading, setIsLoading] = React.useState(true)
  const [isSaving, setIsSaving] = React.useState(false)
  const [isPublishing, setIsPublishing] = React.useState(false)
  const [isRunning, setIsRunning] = React.useState(false)
  const [isSubmittingForm, setIsSubmittingForm] = React.useState(false)
  const [settingsOpen, setSettingsOpen] = React.useState(false)
  const [historyOpen, setHistoryOpen] = React.useState(false)
  const [runOpen, setRunOpen] = React.useState(false)
  const [runDetailsOpen, setRunDetailsOpen] = React.useState(false)
  const [runExpanded, setRunExpanded] = React.useState(false)
  const [paletteOpen, setPaletteOpen] = React.useState(false)
  const [canvasGeneration, setCanvasGeneration] = React.useState(0)
  const [runQuestion, setRunQuestion] = React.useState("")
  const [runFiles, setRunFiles] = React.useState<File[]>([])
  const [runQuestionInvalid, setRunQuestionInvalid] = React.useState(false)
  const [runVersionNumber, setRunVersionNumber] = React.useState<number | null>(
    null
  )
  const runAbortRef = React.useRef<AbortController | null>(null)
  const runFileInputRef = React.useRef<HTMLInputElement>(null)
  const runScrollRef = React.useRef<HTMLDivElement>(null)

  const isDirty = Boolean(
    definition &&
      graph &&
      workflowGraphSignature(definition.graph) !== workflowGraphSignature(graph)
  )
  const hasUnsavedChanges = isDirty || isAppDirty
  const latestPublishedVersion = versions.reduce(
    (latest, version) => Math.max(latest, version.version_number),
    0
  )
  const runTarget = selectWorkflowRunTarget(
    agent.can_edit,
    versions,
    runVersionNumber
  )
  const currentRunQuestion =
    typeof currentRun?.inputs.question === "string"
      ? currentRun.inputs.question
      : ""
  const currentRunOutput =
    typeof currentRun?.outputs.result === "string"
      ? currentRun.outputs.result
      : currentRun?.status === "succeeded"
        ? workflowSpeechText(currentRun.outputs)
        : ""

  React.useLayoutEffect(() => {
    if (runScrollRef.current) {
      runScrollRef.current.scrollTop = runScrollRef.current.scrollHeight
    }
  }, [currentRunOutput, currentRun?.status, runOpen])

  const isRunActive = Boolean(
    currentRun && !TERMINAL_STATUSES.has(currentRun.status)
  )
  const runInputDisabled =
    isRunning ||
    isRunActive ||
    (runTarget?.source === "draft" && isAppDirty)
  const visibleRunFiles = form.interactionConfig.file_upload ? runFiles : []
  const executionGraph = currentRun
    ? currentRun.source === "published"
      ? (versions.find((version) => version.graph_hash === currentRun.graph_hash)
          ?.graph ?? null)
      : definition?.graph_hash === currentRun.graph_hash
        ? definition.graph
        : null
    : null
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
  const changeView = async (view: AgentDetailView) => {
    if (
      visibleActiveView === "settings" &&
      view !== "settings" &&
      hasUnsavedChanges &&
      !(await confirmAction({
        description: t("放弃未保存的更改？"),
        confirmLabel: t("放弃更改"),
        destructive: true,
      }))
    ) {
      return
    }
    onViewChange(view)
  }
  const renderNavItems = (itemClassName: string) =>
    navigationItems.map(({ view: navView, label, icon: Icon }) => (
      <Button
        key={navView}
        type="button"
        variant={visibleActiveView === navView ? "secondary" : "ghost"}
        className={itemClassName}
        aria-current={visibleActiveView === navView ? "page" : undefined}
        onClick={() => void changeView(navView)}
      >
        <Icon data-icon="inline-start" />
        {label}
      </Button>
    ))

  const reportError = React.useCallback(
    (error: unknown) => notify("error", getErrorMessage(error, t)),
    [notify, t]
  )

  const loadExecutions = React.useCallback(
    async (runId: string) => {
      const response = await listWorkflowNodeExecutions(
        token,
        workspaceId,
        agent.id,
        runId
      )
      setExecutions(response.items)
      setRuntimeStatuses(
        Object.fromEntries(
          response.items.map((item) => [item.node_id, item.status])
      )
      )
    },
    [agent.id, token, workspaceId]
  )

  const applyRunEvent = React.useCallback(
    (event: WorkflowRunStreamEvent) => {
      if (event.type === "answer_delta") {
        setCurrentRun((current) => {
          if (!current) return current
          const sameStream =
            !event.stream_epoch ||
            event.stream_epoch === current.live_stream_epoch
          if (
            sameStream &&
            event.live_sequence &&
            current.live_stream_cursor &&
            compareLiveStreamIds(
              event.live_sequence,
              current.live_stream_cursor
            ) <= 0
          ) {
            return current
          }
          const previous =
            sameStream && typeof current.outputs.result === "string"
              ? current.outputs.result
              : ""
          return {
            ...current,
            outputs: { ...current.outputs, result: previous + event.delta },
            live_stream_epoch:
              event.stream_epoch ?? current.live_stream_epoch,
            live_stream_cursor:
              event.live_sequence ?? current.live_stream_cursor,
          }
        })
        return
      }
      if ("run" in event) {
        setCurrentRun(event.run)
        if (event.type !== "run")
          void loadExecutions(event.run.id).catch(reportError)
        return
      }
      if (event.type === "workflow_node_started") {
        setRuntimeStatuses((current) => ({
          ...current,
          [event.node_id]: "running",
        }))
        return
      }
      setRuntimeStatuses((current) => ({
        ...current,
        [event.node_id]: event.status,
      }))
    },
    [loadExecutions, reportError]
  )

  const observeRun = React.useCallback(
    (run: WorkflowRun) => {
      runAbortRef.current?.abort()
      const controller = new AbortController()
      runAbortRef.current = controller
      void observeWorkflowRun(
        token,
        workspaceId,
        agent.id,
        run.id,
        applyRunEvent,
        controller.signal
      ).catch((error: unknown) => {
        if (!controller.signal.aborted) reportError(error)
      })
    },
    [agent.id, applyRunEvent, reportError, token, workspaceId]
  )
  const loadExecutionsRef = React.useRef(loadExecutions)
  const observeRunRef = React.useRef(observeRun)
  const reportErrorRef = React.useRef(reportError)

  React.useEffect(() => {
    loadExecutionsRef.current = loadExecutions
    observeRunRef.current = observeRun
    reportErrorRef.current = reportError
  }, [loadExecutions, observeRun, reportError])

  React.useEffect(() => {
    let active = true
    Promise.all([
      getWorkflowDefinition(token, workspaceId, agent.id),
      listWorkflowVersions(token, workspaceId, agent.id),
      listWorkflowRuns(token, workspaceId, agent.id, { limit: 1 }),
    ])
      .then(([nextDefinition, nextVersions, runs]) => {
        if (!active) return
        setDefinition(nextDefinition)
        setGraph(nextDefinition.graph)
        setVersions(nextVersions.items)
        const latestRun = runs[0] ?? null
        setCurrentRun(latestRun)
        if (latestRun) {
          void loadExecutionsRef.current(latestRun.id).catch(
            reportErrorRef.current
          )
          if (!TERMINAL_STATUSES.has(latestRun.status)) {
            observeRunRef.current(latestRun)
          }
        }
      })
      .catch((error: unknown) => {
        if (active) reportErrorRef.current(error)
      })
      .finally(() => {
        if (active) setIsLoading(false)
      })
    return () => {
      active = false
      runAbortRef.current?.abort()
    }
  }, [agent.id, token, workspaceId])

  async function saveDraft() {
    if (!definition || !graph || !agent.can_edit) return definition
    setIsSaving(true)
    try {
      const updated = await updateWorkflowDefinition(
        token,
        workspaceId,
        agent.id,
        definition.revision,
        graph
      )
      setDefinition(updated)
      setGraph(updated.graph)
      notify("success", t("工作流已保存"))
      return updated
    } catch (error) {
      reportError(error)
      return null
    } finally {
      setIsSaving(false)
    }
  }

  async function handleSaveAll() {
    if (!agent.can_edit) return
    if (isDirty && !(await saveDraft())) return
    if (isAppDirty) {
      try {
        await onSaveApp()
      } catch (error) {
        reportError(error)
      }
    }
  }

  async function handlePublish() {
    if (!canManagePublishing || isPublishing) return
    setIsPublishing(true)
    try {
      if (isDirty && !(await saveDraft())) return
      const version = await publishWorkflow(token, workspaceId, agent.id)
      const nextVersions = await listWorkflowVersions(
        token,
        workspaceId,
        agent.id
      )
      setVersions(nextVersions.items)
      notify(
        "success",
        t("工作流版本 v{version} 已发布", { version: version.version_number })
      )
    } catch (error) {
      reportError(error)
    } finally {
      setIsPublishing(false)
    }
  }

  async function handleRun(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const question = runQuestion.trim()
    if (!question) {
      setRunQuestionInvalid(true)
      return
    }
    setRunQuestionInvalid(false)
    if (!runTarget) return
    if (runTarget.source === "draft" && isAppDirty) return
    setIsRunning(true)
    try {
      if (runTarget.source === "draft" && isDirty && !(await saveDraft()))
        return
      const uploaded =
        form.interactionConfig.file_upload && runFiles.length
          ? await uploadWorkflowFiles(
              token,
              workspaceId,
              agent.id,
              runFiles
            )
          : []
      const run = await createWorkflowRun(
        token,
        workspaceId,
        agent.id,
        question,
        runTarget.source,
        runTarget.versionNumber,
        uploaded.map((item) => item.id)
      )
      setCurrentRun(run)
      setExecutions([])
      setRunDetailsOpen(false)
      setRuntimeStatuses({})
      setRunQuestion("")
      setRunFiles([])
      observeRun(run)
      notify(
        "success",
        t(
          runTarget.source === "published"
            ? "工作流运行已开始"
            : "工作流调试已开始"
        )
      )
    } catch (error) {
      reportError(error)
    } finally {
      setIsRunning(false)
    }
  }

  async function handleFormSubmit(data: Record<string, unknown>) {
    if (!currentRun?.pending_form || isSubmittingForm) return
    setIsSubmittingForm(true)
    try {
      const run = await submitWorkflowForm(
        token,
        workspaceId,
        agent.id,
        currentRun.id,
        currentRun.pending_form.runtime_node_id,
        data
      )
      setCurrentRun(run)
      observeRun(run)
    } catch (error) {
      reportError(error)
    } finally {
      setIsSubmittingForm(false)
    }
  }

  async function handleCopyText(value: string) {
    try {
      await copyText(value)
      notify("success", t("已复制"))
    } catch {
      notify("error", t("复制失败"))
    }
  }

  function openRunDialog(
    versionNumber: number | null = agent.can_edit
      ? null
      : latestPublishedVersion || null
  ) {
    if (!graph) return
    const target = selectWorkflowRunTarget(
      agent.can_edit,
      versions,
      versionNumber
    )
    if (!target) return
    setRunVersionNumber(versionNumber)
    setRunQuestion("")
    setRunFiles([])
    setRunQuestionInvalid(false)
    setRunDetailsOpen(false)
    setRunExpanded(false)
    setRunOpen(true)
  }

  async function handleRestore(version: WorkflowVersion) {
    if (
      !agent.can_edit ||
      !definition ||
      !(await confirmAction({
        description: t("将版本 v{version} 恢复为当前草稿？", {
          version: version.version_number,
        }),
        confirmLabel: t("恢复"),
      }))
    ) {
      return
    }
    try {
      const restored = await restoreWorkflowVersion(
        token,
        workspaceId,
        agent.id,
        version.version_number,
        definition.revision
      )
      setDefinition(restored)
      setGraph(restored.graph)
      setCanvasGeneration((current) => current + 1)
      setHistoryOpen(false)
      notify("success", t("工作流版本已恢复"))
    } catch (error) {
      reportError(error)
    }
  }

  async function handleBack() {
    if (
      hasUnsavedChanges &&
      !(await confirmAction({
        description: t("放弃未保存的更改？"),
        confirmLabel: t("放弃更改"),
        destructive: true,
      }))
    ) {
      return
    }
    onBack()
  }

  async function changeSettingsOpen(open: boolean) {
    if (
      !open &&
      isAppDirty &&
      !(await confirmAction({
        description: t("放弃未保存的更改？"),
        confirmLabel: t("放弃更改"),
        destructive: true,
      }))
    ) {
      return
    }
    setSettingsOpen(open)
  }

  if (isLoading || !definition || !graph) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center gap-2 text-sm text-muted-foreground">
        <LoaderCircleIcon className="size-4 animate-spin" />
        {t("正在加载")}
      </div>
    )
  }

  return (
    <div
      className={
        standalone
          ? "flex h-svh flex-col overflow-hidden bg-background"
          : "-mx-4 -my-6 flex min-h-[calc(100svh-3.5rem)] flex-col overflow-hidden bg-background sm:-mx-6 lg:-mx-8 lg:h-[calc(100svh-3.5rem)] lg:min-h-0"
      }
    >
      <header className="z-10 flex min-h-16 shrink-0 flex-wrap items-center gap-3 border-b bg-background/95 px-4 py-3 backdrop-blur sm:px-6">
        <Button
          type="button"
          variant="ghost"
          size="icon"
          aria-label={t("返回")}
          title={t("返回")}
          onClick={() => {
            if (visibleActiveView === "settings") {
              void changeView("overview")
              return
            }
            void handleBack()
          }}
        >
          <ArrowLeftIcon />
        </Button>
        <span className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-foreground text-background shadow-sm">
          <WorkflowIcon className="size-5" />
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
                {t("已发布")}
              </Badge>
            ) : null}
            {hasUnsavedChanges ? (
              <Badge variant="secondary">{t("未保存")}</Badge>
            ) : null}
          </div>
          <p className="mt-0.5 hidden truncate text-xs text-muted-foreground sm:block">
            {t("工作流")} · {currentViewLabel}
          </p>
        </div>
        {visibleActiveView === "settings" ? (
          <IconButton
            label={t("版本历史")}
            onClick={() => setHistoryOpen(true)}
          >
            <HistoryIcon />
          </IconButton>
        ) : null}
        {visibleActiveView === "settings" && agent.can_edit ? (
          <IconButton
            label={t("应用设置")}
            onClick={() => setSettingsOpen(true)}
          >
            <SettingsIcon />
          </IconButton>
        ) : null}
        {visibleActiveView === "settings" && agent.can_edit ? (
          <Button
            type="button"
            variant="outline"
            aria-label={t("保存")}
            disabled={(!isDirty && !isAppDirty) || isSaving || isSavingApp}
            onClick={() => void handleSaveAll()}
          >
            {isSaving || isSavingApp ? (
              <LoaderCircleIcon className="animate-spin" />
            ) : (
              <SaveIcon />
            )}
            <span className="hidden sm:inline">{t("保存")}</span>
          </Button>
        ) : null}
        {visibleActiveView === "settings" && agent.can_edit ? (
          <Button
            type="button"
            variant="outline"
            aria-label={t("添加节点")}
            onClick={() => setPaletteOpen(true)}
          >
            <PlusIcon />
            <span className="hidden sm:inline">{t("添加节点")}</span>
          </Button>
        ) : null}
        {visibleActiveView === "settings" ? (
          <Button
            type="button"
            variant="outline"
            aria-label={agent.can_edit ? t("调试运行") : t("运行已发布版本")}
            disabled={
              agent.status !== "active" ||
              isRunning ||
              (!agent.can_edit && !latestPublishedVersion) ||
              isRunActive
            }
            title={
              !agent.can_edit && !latestPublishedVersion
                ? t("暂无可运行的已发布版本")
                : undefined
            }
            onClick={() => openRunDialog()}
          >
            <PlayIcon />
            <span className="hidden sm:inline">
              {agent.can_edit ? t("调试运行") : t("运行已发布版本")}
            </span>
          </Button>
        ) : null}
        {canManagePublishing ? (
          <Button
            type="button"
            aria-label={t("发布版本")}
            disabled={isPublishing || agent.status !== "active" || isAppDirty}
            title={isAppDirty ? t("请先保存更改后再发布。") : undefined}
            onClick={() => void handlePublish()}
          >
            {isPublishing ? (
              <LoaderCircleIcon className="animate-spin" />
            ) : (
              <UploadIcon />
            )}
            <span className="hidden sm:inline">{t("发布版本")}</span>
          </Button>
        ) : null}
        {agent.can_edit ? (
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
                {t("删除工作流")}
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        ) : null}
      </header>

      <div className="flex min-h-0 flex-1">
        {standalone ? null : (
          <aside className="hidden w-52 shrink-0 border-r bg-muted/20 p-3 lg:block">
            <nav className="space-y-1" aria-label={t("工作流详情导航")}>
              {renderNavItems("w-full justify-start")}
            </nav>
          </aside>
        )}
        <div className="relative flex min-w-0 flex-1 flex-col">
          {standalone ? null : (
            <nav
              className="flex shrink-0 gap-1 overflow-x-auto border-b bg-background p-2 lg:hidden"
              aria-label={t("工作流详情导航")}
            >
              {renderNavItems("shrink-0")}
            </nav>
          )}
          {visibleActiveView === "settings" && currentRun ? (
            <div className="flex flex-wrap items-center gap-3 border-b bg-muted/25 px-4 py-2 text-xs">
              <Badge
                variant={
                  currentRun.status === "failed" ? "destructive" : "outline"
                }
                className={cn(
                  currentRun.status === "running" &&
                    "border-sky-500 text-sky-700 dark:text-sky-400"
                )}
              >
                {runStatusLabel(currentRun, t)}
              </Badge>
              <span className="text-muted-foreground">
                {t("已执行 {count} 个节点", { count: currentRun.step_count })}
              </span>
              <span className="text-muted-foreground">
                {t("令牌 {count}", { count: currentRun.token_usage })}
              </span>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                className="ml-auto"
                onClick={() => setRunOpen(true)}
              >
                {t("查看运行结果")}
              </Button>
            </div>
          ) : null}
          {visibleActiveView === "settings" ? (
            <>
              <WorkflowCanvas
                key={`${definition.id}:${canvasGeneration}`}
                agent={agent}
                graph={graph}
                models={models}
                knowledgeBases={knowledgeBases}
                mcpServers={mcpServers}
                runtimeStatuses={runtimeStatuses}
                readOnly={!agent.can_edit}
                paletteOpen={paletteOpen}
                onClosePalette={() => setPaletteOpen(false)}
                form={form}
                setForm={setForm}
                onChange={setGraph}
                t={t}
              />
              {runOpen ? (
                <aside
                  role="dialog"
                  aria-modal="false"
                  aria-label={t("运行工作流")}
                  className={cn(
                    "absolute z-40 flex min-h-0 overflow-hidden rounded-2xl border border-border/80 bg-background/98 shadow-[0_24px_80px_-32px_rgba(0,0,0,0.55)] backdrop-blur-xl transition-[inset,width] duration-200",
                    runExpanded
                      ? "inset-2 sm:inset-y-3 sm:right-3 sm:left-auto sm:w-2/3 lg:w-1/3 lg:min-w-96"
                      : "inset-2 sm:inset-y-4 sm:right-4 sm:left-auto sm:w-96"
                  )}
                >
                  <form
                    className="flex min-h-0 flex-1 flex-col"
                    onSubmit={(event) => void handleRun(event)}
                  >
                    <header className="flex shrink-0 items-center gap-3 border-b bg-background/95 px-4 py-3">
                      <span className="flex size-9 shrink-0 items-center justify-center rounded-lg border bg-muted/50 shadow-xs">
                        <WorkflowIcon className="size-[18px] text-foreground" />
                      </span>
                      <span className="min-w-0 flex-1">
                        <strong className="block truncate text-sm font-semibold">
                          {form.name || agent.name}
                        </strong>
                        <span className="block text-[11px] text-muted-foreground">
                          {agent.can_edit ? t("调试运行") : t("运行已发布版本")}
                        </span>
                      </span>
                      <IconButton
                        label={t(runExpanded ? "收起" : "展开")}
                        className="size-8 text-muted-foreground hover:text-foreground"
                        onClick={() => setRunExpanded((current) => !current)}
                      >
                        {runExpanded ? (
                          <Minimize2Icon className="size-4" />
                        ) : (
                          <Maximize2Icon className="size-4" />
                        )}
                      </IconButton>
                      <IconButton
                        label={t("关闭")}
                        className="size-8 text-muted-foreground hover:text-foreground"
                        onClick={() => setRunOpen(false)}
                      >
                        <XIcon className="size-4" />
                      </IconButton>
                    </header>

                    <div
                      ref={runScrollRef}
                      className="min-h-0 flex-1 space-y-5 overflow-y-auto bg-muted/10 px-4 py-5"
                    >
                      {form.interactionConfig.prologue ? (
                        <div className="flex items-start gap-2.5">
                          <span className="flex size-8 shrink-0 items-center justify-center rounded-lg border bg-background shadow-xs">
                            <WorkflowIcon className="size-4" />
                          </span>
                          <div className="max-w-[85%] whitespace-pre-wrap rounded-2xl rounded-tl-md border bg-background px-3.5 py-3 text-sm leading-6 shadow-xs">
                            {form.interactionConfig.prologue}
                          </div>
                        </div>
                      ) : !currentRun ? (
                        <div className="flex min-h-full flex-col items-center justify-center px-6 text-center">
                          <span className="flex size-12 items-center justify-center rounded-2xl border bg-background shadow-sm">
                            <WorkflowIcon className="size-5 text-muted-foreground" />
                          </span>
                          <p className="mt-4 max-w-xs text-sm leading-6 text-muted-foreground">
                          {runTarget?.source === "published"
                            ? t("问题将作为开始节点的 question 输出注入已发布版本 v{version}。", {
                                version: runTarget.versionNumber ?? "",
                              })
                            : t("问题将作为开始节点的 question 输出注入当前草稿。")}
                          </p>
                        </div>
                      ) : null}

                      {currentRun ? (
                        <div className="grid gap-4">
                          {currentRunQuestion ? (
                            <div className="ml-auto grid max-w-[85%] justify-items-end gap-1">
                              <p className="rounded-2xl rounded-tr-md bg-foreground px-3.5 py-2.5 text-sm leading-6 text-background shadow-sm">
                                {currentRunQuestion}
                              </p>
                              <Button
                                type="button"
                                variant="ghost"
                                size="icon-xs"
                                className="text-muted-foreground"
                                aria-label={t("复制")}
                                title={t("复制")}
                                onClick={() =>
                                  void handleCopyText(currentRunQuestion)
                                }
                              >
                                <CopyIcon />
                              </Button>
                            </div>
                          ) : null}
                          <div className="flex items-start gap-2.5">
                            <span className="flex size-8 shrink-0 items-center justify-center rounded-lg border bg-background shadow-xs">
                              <WorkflowIcon className="size-4" />
                            </span>
                            <article className="grid min-w-0 flex-1 gap-4 rounded-2xl rounded-tl-md border bg-background p-3.5 shadow-xs">
                              <div className="flex flex-wrap items-center gap-2">
                                <Badge
                                  variant={
                                    currentRun.status === "failed"
                                      ? "destructive"
                                      : "outline"
                                  }
                                >
                                  {runStatusLabel(currentRun, t)}
                                </Badge>
                                <span className="text-xs text-muted-foreground">
                                  {t("已执行 {count} 个节点", {
                                    count: currentRun.step_count,
                                  })}
                                </span>
                              </div>

                              {currentRun.status === "awaiting_input" &&
                              currentRun.pending_form ? (
                                <WorkflowRuntimeForm
                                  key={currentRun.pending_form.runtime_node_id}
                                  form={currentRun.pending_form}
                                  submitting={isSubmittingForm}
                                  onSubmit={handleFormSubmit}
                                />
                              ) : null}

                              {currentRunOutput ? (
                                <section className="grid gap-2">
                                  <h3 className="text-xs font-medium text-muted-foreground">
                                    {t("运行结果")}
                                  </h3>
                                  <MarkdownContent
                                    content={currentRunOutput}
                                    className="text-sm leading-6"
                                  />
                                </section>
                              ) : null}

                              {currentRun.last_error ? (
                                <p className="rounded-lg bg-destructive/10 p-3 text-sm text-destructive">
                                  {workflowErrorMessage(currentRun.last_error, t)}
                                </p>
                              ) : currentRun.status !== "succeeded" &&
                                currentRun.status !== "awaiting_input" ? (
                                <p className="flex items-center gap-2 text-sm text-muted-foreground">
                                  <LoaderCircleIcon className="size-4 animate-spin" />
                                  {runStatusLabel(currentRun, t)}
                                </p>
                              ) : null}

                              {currentRunOutput || executions.length ? (
                                <div className="flex items-center justify-end gap-1 border-t pt-2">
                                  {currentRunOutput ? (
                                    <Button
                                      type="button"
                                      variant="ghost"
                                      size="icon-xs"
                                      className="text-muted-foreground"
                                      aria-label={t("复制")}
                                      title={t("复制")}
                                      onClick={() =>
                                        void handleCopyText(currentRunOutput)
                                      }
                                    >
                                      <CopyIcon />
                                    </Button>
                                  ) : null}
                                  {executions.length ? (
                                    <Button
                                      type="button"
                                      variant="ghost"
                                      size="sm"
                                      onClick={() => setRunDetailsOpen(true)}
                                    >
                                      {t("执行详情")}
                                    </Button>
                                  ) : null}
                                </div>
                              ) : null}
                            </article>
                          </div>
                        </div>
                      ) : null}
                    </div>

                    <footer className="shrink-0 border-t bg-background/95 p-3.5">
                      {runQuestionInvalid ? (
                        <p className="mb-2 text-xs text-destructive">
                          {t("请输入问题")}
                        </p>
                      ) : null}
                      <div className="relative rounded-2xl border bg-muted/20 p-1.5 shadow-sm transition-[background-color,border-color,box-shadow] focus-within:border-ring focus-within:bg-background focus-within:shadow-md">
                        {form.interactionConfig.file_upload ? (
                          <input
                            ref={runFileInputRef}
                            type="file"
                            className="sr-only"
                            multiple
                            accept={acceptedUploadExtensions(
                              form.interactionConfig.file_upload_setting
                                .file_upload_type
                            )}
                            disabled={runInputDisabled}
                            onChange={(event) => {
                              setRunFiles(Array.from(event.target.files ?? []))
                            }}
                          />
                        ) : null}
                        <textarea
                          id="workflow-run-question"
                          rows={3}
                          aria-label={
                            form.interactionConfig.user_input_title ||
                            t("请输入问题")
                          }
                          className={cn(
                            "block min-h-20 w-full resize-none bg-transparent px-2 py-2 text-sm leading-6 outline-none disabled:cursor-not-allowed",
                            visibleRunFiles.length ? "pb-2" : "pb-12"
                          )}
                          placeholder={
                            form.interactionConfig.user_input_title || t("请输入问题")
                          }
                          value={runQuestion}
                          disabled={runInputDisabled}
                          aria-invalid={runQuestionInvalid}
                          onChange={(event) => {
                            setRunQuestion(event.target.value)
                            if (runQuestionInvalid && event.target.value.trim()) {
                              setRunQuestionInvalid(false)
                            }
                          }}
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
                        <AgentAttachmentList
                          files={visibleRunFiles}
                          onRemove={(indexToRemove) =>
                            setRunFiles((current) =>
                              current.filter((_, index) => index !== indexToRemove)
                            )
                          }
                          t={t}
                        />
                        <div className="absolute right-2 bottom-2 flex items-center gap-1.5">
                          {form.interactionConfig.file_upload ? (
                            <Button
                              type="button"
                              variant="ghost"
                              size="icon"
                              className="size-9 rounded-xl"
                              aria-label={t("添加附件")}
                              title={
                                runTarget?.source === "draft" && isAppDirty
                                  ? t("请先保存配置后再调试")
                                  : t("添加附件")
                              }
                              disabled={runInputDisabled}
                              onClick={() => {
                                if (!runFileInputRef.current) return
                                runFileInputRef.current.value = ""
                                runFileInputRef.current.click()
                              }}
                            >
                              <PaperclipIcon />
                            </Button>
                          ) : null}
                          <Button
                            type="submit"
                            size="icon"
                            className="size-9 rounded-xl"
                            aria-label={t("发送问题")}
                            title={
                              runTarget?.source === "draft" && isAppDirty
                                ? t("请先保存配置后再调试")
                                : t("发送问题")
                            }
                            disabled={
                              runInputDisabled ||
                              !runTarget ||
                              !runQuestion.trim()
                            }
                          >
                            {isRunning ? (
                              <LoaderCircleIcon className="animate-spin" />
                            ) : (
                              <SendIcon />
                            )}
                          </Button>
                        </div>
                      </div>
                    </footer>
                  </form>
                </aside>
              ) : null}
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

      <Dialog open={runDetailsOpen} onOpenChange={setRunDetailsOpen}>
        <DialogContent className="max-h-[calc(100svh-2rem)] max-w-2xl grid-rows-[auto_minmax(0,1fr)] overflow-hidden p-0">
          <DialogHeader className="border-b px-5 py-4">
            <DialogTitle>{t("执行详情")}</DialogTitle>
            <DialogDescription>{t("节点执行记录")}</DialogDescription>
          </DialogHeader>
          <div className="min-h-0 overflow-y-auto p-5">
            <div className="overflow-hidden rounded-lg border bg-muted/10">
              {executions.map((execution) => (
                <details
                  key={execution.id}
                  className="group border-b last:border-b-0"
                >
                  <summary className="flex cursor-pointer list-none items-center gap-2 px-3 py-2.5 transition-colors hover:bg-muted/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring [&::-webkit-details-marker]:hidden">
                    <span
                      className={cn(
                        "size-2 shrink-0 rounded-full",
                        execution.status === "succeeded"
                          ? "bg-emerald-500"
                          : execution.status === "failed"
                            ? "bg-destructive"
                            : execution.status === "running"
                              ? "animate-pulse bg-sky-500"
                              : "bg-muted-foreground/40"
                      )}
                    />
                    <span
                      className="min-w-0 flex-1 truncate text-sm"
                      title={execution.node_id}
                    >
                      {workflowExecutionNodeLabel(
                        execution.node_id,
                        execution.node_type,
                        executionGraph,
                        t
                      )}
                    </span>
                    {execution.duration_ms !== null ? (
                      <span className="shrink-0 text-xs text-muted-foreground">
                        {t("{duration} 毫秒", {
                          duration: execution.duration_ms,
                        })}
                      </span>
                    ) : null}
                    <ChevronDownIcon
                      aria-hidden="true"
                      className="size-4 shrink-0 text-muted-foreground transition-transform group-open:rotate-180"
                    />
                  </summary>
                  <div className="grid gap-3 border-t bg-muted/20 px-3 py-3">
                    {execution.error ? (
                      <section className="grid gap-1.5">
                        <h4 className="text-xs font-medium text-destructive">
                          {t("错误")}
                        </h4>
                        <p className="break-words rounded-md bg-destructive/10 px-2.5 py-2 text-xs leading-5 text-destructive whitespace-pre-wrap [overflow-wrap:anywhere]">
                          {workflowErrorMessage(execution.error, t)}
                        </p>
                      </section>
                    ) : null}
                    <section className="grid gap-1.5">
                      <h4 className="text-xs font-medium text-muted-foreground">
                        {t("输出内容")}
                      </h4>
                      {Object.keys(execution.outputs).length ? (
                        <JsonBlock value={execution.outputs} />
                      ) : (
                        <p className="rounded-md border bg-background px-2.5 py-2 text-xs text-muted-foreground">
                          {t("暂无输出内容")}
                        </p>
                      )}
                    </section>
                    <section className="grid gap-1.5">
                      <h4 className="text-xs font-medium text-muted-foreground">
                        {t("输入内容")}
                      </h4>
                      <JsonBlock value={execution.inputs} />
                    </section>
                    {Object.keys(execution.model_usage).length ? (
                      <section className="grid gap-1.5">
                        <h4 className="text-xs font-medium text-muted-foreground">
                          {t("模型用量")}
                        </h4>
                        <JsonBlock value={execution.model_usage} />
                      </section>
                    ) : null}
                  </div>
                </details>
              ))}
            </div>
          </div>
        </DialogContent>
      </Dialog>

      <Dialog open={historyOpen} onOpenChange={setHistoryOpen}>
        <DialogContent className="max-h-[calc(100svh-2rem)] max-w-2xl overflow-y-auto">
          <DialogHeader>
            <DialogTitle>{t("版本历史")}</DialogTitle>
            <DialogDescription>
              {t("已发布版本不可修改，可恢复为新的草稿修订。")}
            </DialogDescription>
          </DialogHeader>
          <div className="divide-y rounded-md border">
            {versions.length ? (
              versions.map((version) => (
              <div key={version.id} className="flex items-center gap-3 p-3">
                <Badge>v{version.version_number}</Badge>
                <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium">
                      {t("草稿修订 {revision}", {
                        revision: version.definition_revision,
                      })}
                    </p>
                    <p className="truncate text-xs text-muted-foreground">
                      {new Date(version.created_at).toLocaleString()} ·{" "}
                      {version.graph_hash.slice(0, 12)}
                    </p>
                </div>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  disabled={
                    agent.status !== "active" ||
                    isRunning ||
                      isRunActive
                  }
                  onClick={() => {
                    setHistoryOpen(false)
                    openRunDialog(version.version_number)
                  }}
                >
                  <PlayIcon />
                  {t("运行")}
                </Button>
                  {agent.can_edit ? (
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      onClick={() => void handleRestore(version)}
                    >
                      {t("恢复")}
                    </Button>
                  ) : null}
              </div>
              ))
            ) : (
              <p className="p-6 text-center text-sm text-muted-foreground">
                {t("暂无已发布版本")}
              </p>
            )}
          </div>
        </DialogContent>
      </Dialog>

      <Dialog
        open={settingsOpen}
        onOpenChange={(open) => void changeSettingsOpen(open)}
      >
        <DialogContent className="max-h-[calc(100svh-2rem)] max-w-xl overflow-y-auto">
          <DialogHeader>
            <DialogTitle>{t("工作流设置")}</DialogTitle>
            <DialogDescription>
              {t("配置工作流的默认模型；知识库和只读 MCP 工具由节点选择。")}
            </DialogDescription>
          </DialogHeader>
          <form onSubmit={onSaveApp}>
            <AgentConfigFields
              form={form}
              setForm={setForm}
              models={models}
              knowledgeBases={knowledgeBases}
              mcpServers={mcpServers}
              readOnly={!agent.can_edit}
              t={t}
            />
            <DialogFooter className="pt-5">
              <Button
                type="button"
                variant="outline"
                onClick={() => void changeSettingsOpen(false)}
              >
                {t("关闭")}
              </Button>
              <Button type="submit" disabled={isSavingApp}>
                {isSavingApp ? (
                  <LoaderCircleIcon className="animate-spin" />
                ) : (
                  <SaveIcon />
                )}
                {t("保存")}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
      {confirmDialog}
    </div>
  )
}
