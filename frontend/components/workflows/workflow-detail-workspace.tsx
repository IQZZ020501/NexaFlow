"use client"

import * as React from "react"
import dynamic from "next/dynamic"
import {
  ArrowLeftIcon,
  Clock3Icon,
  HistoryIcon,
  LayoutDashboardIcon,
  LoaderCircleIcon,
  PlayIcon,
  SaveIcon,
  ScrollTextIcon,
  SettingsIcon,
  ShieldCheckIcon,
  MoreHorizontalIcon,
  Trash2Icon,
  UploadIcon,
  UsersIcon,
  ChartNoAxesColumnIcon,
  WorkflowIcon,
} from "lucide-react"

import { AgentConfigFields } from "@/components/agents/agent-config-fields"
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
import type { TFunction } from "@/i18n"
import type { AgentDetailView } from "@/lib/agent-views"
import type { Agent } from "@/lib/api/agents"
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
  updateWorkflowDefinition,
  type WorkflowDefinition,
  type WorkflowGraph,
  type WorkflowNodeExecution,
  type WorkflowRun,
  type WorkflowRunStreamEvent,
  type WorkflowVersion,
} from "@/lib/api/workflows"
import { getErrorMessage } from "@/lib/errors"
import {
  initialWorkflowInputs,
  selectWorkflowRunTarget,
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
  onBack: () => void
  onDelete: () => void
  onManagePermissions: () => void
  onSaveApp: React.FormEventHandler<HTMLFormElement>
  onViewChange: (view: AgentDetailView) => void
  notify: (kind: "success" | "error", message: string) => void
  t: TFunction
}

const TERMINAL_STATUSES = new Set(["succeeded", "failed", "cancelled"])

function runStatusLabel(run: WorkflowRun, t: TFunction) {
  if (run.status === "queued") return t("等待执行")
  if (run.status === "running") return t("运行中")
  if (run.status === "succeeded") return t("运行成功")
  if (run.status === "cancelled") return t("运行已取消")
  return t("运行失败")
}

function parseObject(text: string) {
  const value: unknown = JSON.parse(text)
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error("object required")
  }
  return value as Record<string, unknown>
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
  onBack,
  onDelete,
  onManagePermissions,
  onSaveApp,
  onViewChange,
  notify,
  t,
}: WorkflowDetailWorkspaceProps) {
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
  const [settingsOpen, setSettingsOpen] = React.useState(false)
  const [historyOpen, setHistoryOpen] = React.useState(false)
  const [runOpen, setRunOpen] = React.useState(false)
  const [runDetailsOpen, setRunDetailsOpen] = React.useState(false)
  const [runInputs, setRunInputs] = React.useState("{}")
  const [runInputsInvalid, setRunInputsInvalid] = React.useState(false)
  const [runVersionNumber, setRunVersionNumber] = React.useState<number | null>(
    null
  )
  const runAbortRef = React.useRef<AbortController | null>(null)

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
  const renderNavItems = (itemClassName: string) =>
    navigationItems.map(({ view: navView, label, icon: Icon }) => (
      <Button
        key={navView}
        type="button"
        variant={visibleActiveView === navView ? "secondary" : "ghost"}
        className={itemClassName}
        aria-current={visibleActiveView === navView ? "page" : undefined}
        onClick={() => onViewChange(navView)}
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
          void loadExecutions(latestRun.id).catch(reportError)
          if (!TERMINAL_STATUSES.has(latestRun.status)) observeRun(latestRun)
        }
      })
      .catch((error: unknown) => {
        if (active) reportError(error)
      })
      .finally(() => {
        if (active) setIsLoading(false)
      })
    return () => {
      active = false
      runAbortRef.current?.abort()
    }
  }, [agent.id, loadExecutions, observeRun, reportError, token, workspaceId])

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
    let inputs: Record<string, unknown>
    try {
      inputs = parseObject(runInputs)
      setRunInputsInvalid(false)
    } catch {
      setRunInputsInvalid(true)
      return
    }
    if (!runTarget) return
    if (runTarget.source === "draft" && isAppDirty) return
    setIsRunning(true)
    try {
      if (runTarget.source === "draft" && isDirty && !(await saveDraft()))
        return
      const run = await createWorkflowRun(
        token,
        workspaceId,
        agent.id,
        inputs,
        runTarget.source,
        runTarget.versionNumber
      )
      setCurrentRun(run)
      setExecutions([])
      setRuntimeStatuses({})
      setRunOpen(false)
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
    setRunInputs(
      JSON.stringify(initialWorkflowInputs(target.graph ?? graph), null, 2)
    )
    setRunInputsInvalid(false)
    setRunOpen(true)
  }

  async function handleRestore(version: WorkflowVersion) {
    if (
      !agent.can_edit ||
      !window.confirm(
        t("将版本 v{version} 恢复为当前草稿？", {
          version: version.version_number,
        })
      )
    ) {
      return
    }
    try {
      const restored = await restoreWorkflowVersion(
        token,
        workspaceId,
        agent.id,
        version.version_number
      )
      setDefinition(restored)
      setGraph(restored.graph)
      setHistoryOpen(false)
      notify("success", t("工作流版本已恢复"))
    } catch (error) {
      reportError(error)
    }
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
    <div className="-mx-4 -my-6 flex min-h-[calc(100svh-3.5rem)] flex-col overflow-hidden bg-background sm:-mx-6 lg:-mx-8 lg:h-[calc(100svh-3.5rem)] lg:min-h-0">
      <header className="z-10 flex min-h-16 shrink-0 flex-wrap items-center gap-3 border-b bg-background/95 px-4 py-3 backdrop-blur sm:px-6">
        <Button
          type="button"
          variant="ghost"
          size="icon"
          aria-label={t("返回")}
          title={t("返回")}
          onClick={() => {
            if (visibleActiveView === "settings") {
              onViewChange("overview")
              return
            }
            if (!hasUnsavedChanges || window.confirm(t("放弃未保存的更改？")))
              onBack()
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
            {t("工作流")} · {currentViewLabel} · v{definition.revision}
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
            disabled={!isDirty || isSaving}
            onClick={() => void saveDraft()}
          >
            {isSaving ? (
              <LoaderCircleIcon className="animate-spin" />
            ) : (
              <SaveIcon />
            )}
            <span className="hidden sm:inline">{t("保存")}</span>
          </Button>
        ) : null}
        {visibleActiveView === "settings" ? (
          <Button
            type="button"
            variant="outline"
            disabled={
              agent.status !== "active" ||
              isRunning ||
              (!agent.can_edit && !latestPublishedVersion) ||
              Boolean(currentRun && !TERMINAL_STATUSES.has(currentRun.status))
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
            <DropdownMenuContent align="end">
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
        <aside className="hidden w-52 shrink-0 border-r bg-muted/20 p-3 lg:block">
          <nav className="space-y-1" aria-label={t("工作流详情导航")}>
            {renderNavItems("w-full justify-start")}
          </nav>
        </aside>
        <div className="flex min-w-0 flex-1 flex-col">
          <nav
            className="flex shrink-0 gap-1 overflow-x-auto border-b bg-background p-2 lg:hidden"
            aria-label={t("工作流详情导航")}
          >
            {renderNavItems("shrink-0")}
          </nav>
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
                onClick={() => setRunDetailsOpen(true)}
              >
                {t("查看运行结果")}
              </Button>
            </div>
          ) : null}
          {visibleActiveView === "settings" ? (
            <WorkflowCanvas
              key={`${definition.id}:${definition.revision}`}
              agent={agent}
              graph={graph}
              models={models}
              knowledgeBases={knowledgeBases}
              mcpServers={mcpServers}
              runtimeStatuses={runtimeStatuses}
              readOnly={!agent.can_edit}
              onChange={setGraph}
              t={t}
            />
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

      <Dialog open={runOpen} onOpenChange={setRunOpen}>
        <DialogContent className="max-w-xl">
          <form
            className="grid gap-4"
            onSubmit={(event) => void handleRun(event)}
          >
            <DialogHeader>
              <DialogTitle>{t("运行工作流")}</DialogTitle>
              <DialogDescription>
                {runTarget?.source === "published"
                  ? t("输入将从开始节点注入已发布版本 v{version}。", {
                      version: runTarget.versionNumber ?? "",
                    })
                  : t("输入将从开始节点注入当前草稿。")}
              </DialogDescription>
            </DialogHeader>
            <label
              className="grid gap-2 text-sm font-medium"
              htmlFor="workflow-run-version"
            >
              {t("运行版本")}
              <select
                id="workflow-run-version"
                className="h-9 rounded-md border bg-background px-2 text-sm"
                value={runVersionNumber ?? "draft"}
                onChange={(event) => {
                  const nextVersion =
                    event.target.value === "draft"
                      ? null
                      : Number(event.target.value)
                  const target = selectWorkflowRunTarget(
                    agent.can_edit,
                    versions,
                    nextVersion
                  )
                  if (!target) return
                  setRunVersionNumber(nextVersion)
                  setRunInputs(
                    JSON.stringify(
                      initialWorkflowInputs(target.graph ?? graph),
                      null,
                      2
                    )
                  )
                  setRunInputsInvalid(false)
                }}
              >
                {agent.can_edit ? (
                  <option value="draft">{t("当前草稿")}</option>
                ) : null}
                {versions.map((version) => (
                  <option key={version.id} value={version.version_number}>
                    {t("已发布版本 v{version}", {
                      version: version.version_number,
                    })}
                  </option>
                ))}
              </select>
            </label>
            <label
              className="grid gap-2 text-sm font-medium"
              htmlFor="workflow-run-inputs"
            >
              {t("运行输入")}
              <textarea
                id="workflow-run-inputs"
                className="min-h-64 resize-y rounded-md border bg-background p-3 font-mono text-xs leading-5 outline-none focus-visible:ring-2 focus-visible:ring-ring aria-invalid:border-destructive"
                value={runInputs}
                aria-invalid={runInputsInvalid}
                onChange={(event) => setRunInputs(event.target.value)}
              />
              {runInputsInvalid ? (
                <span className="text-xs font-normal text-destructive">
                  {t("请输入 JSON 对象")}
                </span>
              ) : null}
            </label>
            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                onClick={() => setRunOpen(false)}
              >
                {t("取消")}
              </Button>
              <Button
                type="submit"
                disabled={
                  isRunning ||
                  !runTarget ||
                  (runTarget.source === "draft" && isAppDirty)
                }
                title={
                  runTarget?.source === "draft" && isAppDirty
                    ? t("请先保存配置后再调试")
                    : undefined
                }
              >
                {isRunning ? (
                  <LoaderCircleIcon className="animate-spin" />
                ) : (
                  <PlayIcon />
                )}
                {runTarget?.source === "published"
                  ? t("开始运行")
                  : t("开始调试")}
              </Button>
            </DialogFooter>
          </form>
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
                      Boolean(
                        currentRun && !TERMINAL_STATUSES.has(currentRun.status)
                      )
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

      <Dialog open={runDetailsOpen} onOpenChange={setRunDetailsOpen}>
        <DialogContent className="max-h-[calc(100svh-2rem)] max-w-3xl overflow-y-auto">
          <DialogHeader>
            <DialogTitle>{t("运行结果")}</DialogTitle>
            <DialogDescription>
              {currentRun
                ? `${runStatusLabel(currentRun, t)} · ${currentRun.trace_id}`
                : ""}
            </DialogDescription>
          </DialogHeader>
          {currentRun ? (
            <div className="grid gap-5">
              <section className="grid gap-2">
                <h3 className="text-sm font-semibold">
                  {currentRun.last_error ? t("错误") : t("结果")}
                </h3>
                {currentRun.last_error ? (
                  <p className="rounded-md bg-destructive/10 p-3 text-sm text-destructive">
                    {currentRun.last_error}
                  </p>
                ) : (
                  <JsonBlock value={currentRun.outputs} />
                )}
              </section>
              <section className="grid gap-2">
                <h3 className="text-sm font-semibold">{t("节点执行记录")}</h3>
                <div className="divide-y rounded-md border">
                  {executions.map((execution) => (
                    <div key={execution.id} className="grid gap-2 p-3">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="text-sm font-medium">
                          {execution.node_id}
                        </span>
                        <Badge
                          variant={
                            execution.status === "failed"
                              ? "destructive"
                              : "outline"
                          }
                        >
                          {execution.status === "succeeded"
                            ? t("运行成功")
                            : execution.status === "failed"
                              ? t("运行失败")
                              : execution.status === "running"
                                ? t("运行中")
                                : t("已跳过")}
                        </Badge>
                        {execution.duration_ms !== null ? (
                          <span className="ml-auto flex items-center gap-1 text-xs text-muted-foreground">
                            <Clock3Icon className="size-3.5" />
                            {t("{duration} 毫秒", {
                              duration: execution.duration_ms,
                            })}
                          </span>
                        ) : null}
                      </div>
                      {execution.error ? (
                        <p className="text-xs text-destructive">
                          {execution.error}
                        </p>
                      ) : null}
                    </div>
                  ))}
                  {!executions.length ? (
                    <p className="p-4 text-sm text-muted-foreground">
                      {t("暂无节点执行记录")}
                    </p>
                  ) : null}
                </div>
              </section>
            </div>
          ) : null}
        </DialogContent>
      </Dialog>

      <Dialog
        open={settingsOpen}
        onOpenChange={(open) => {
          if (open || !isAppDirty || window.confirm(t("放弃未保存的更改？"))) {
            setSettingsOpen(open)
          }
        }}
      >
        <DialogContent className="max-h-[calc(100svh-2rem)] max-w-xl overflow-y-auto">
          <DialogHeader>
            <DialogTitle>{t("工作流设置")}</DialogTitle>
            <DialogDescription>
              {t("配置默认模型以及节点可使用的知识库和只读 MCP 工具。")}
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
                onClick={() => setSettingsOpen(false)}
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
    </div>
  )
}
