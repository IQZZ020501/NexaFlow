"use client"

import * as React from "react"
import dynamic from "next/dynamic"
import {
  ArrowLeftIcon,
  Clock3Icon,
  HistoryIcon,
  LoaderCircleIcon,
  PencilIcon,
  PlayIcon,
  SaveIcon,
  SettingsIcon,
  ShieldCheckIcon,
  Trash2Icon,
  UploadIcon,
  WorkflowIcon,
} from "lucide-react"

import { AgentConfigFields } from "@/components/agents/agent-config-fields"
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
import { IconButton } from "@/components/ui/icon-button"
import type { TFunction } from "@/i18n"
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
  onBack: () => void
  onDelete: () => void
  onManagePermissions: () => void
  onSaveApp: React.FormEventHandler<HTMLFormElement>
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
  onBack,
  onDelete,
  onManagePermissions,
  onSaveApp,
  notify,
  t,
}: WorkflowDetailWorkspaceProps) {
  const [definition, setDefinition] = React.useState<WorkflowDefinition | null>(null)
  const [graph, setGraph] = React.useState<WorkflowGraph | null>(null)
  const [versions, setVersions] = React.useState<WorkflowVersion[]>([])
  const [currentRun, setCurrentRun] = React.useState<WorkflowRun | null>(null)
  const [executions, setExecutions] = React.useState<WorkflowNodeExecution[]>([])
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
  const [runVersionNumber, setRunVersionNumber] = React.useState<number | null>(null)
  const [view, setView] = React.useState<"details" | "canvas">("details")
  const runAbortRef = React.useRef<AbortController | null>(null)

  const isDirty = Boolean(
    definition &&
      graph &&
      workflowGraphSignature(definition.graph) !== workflowGraphSignature(graph)
  )
  const hasUnsavedChanges = isDirty || isAppDirty
  const nodeCount = graph?.nodes.length ?? 0
  const edgeCount = graph?.edges.length ?? 0
  const latestPublishedVersion = versions.reduce(
    (latest, version) => Math.max(latest, version.version_number),
    0
  )
  const runTarget = selectWorkflowRunTarget(
    agent.can_edit,
    versions,
    runVersionNumber
  )

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
        Object.fromEntries(response.items.map((item) => [item.node_id, item.status]))
      )
    },
    [agent.id, token, workspaceId]
  )

  const applyRunEvent = React.useCallback(
    (event: WorkflowRunStreamEvent) => {
      if ("run" in event) {
        setCurrentRun(event.run)
        if (event.type !== "run") void loadExecutions(event.run.id).catch(reportError)
        return
      }
      if (event.type === "workflow_node_started") {
        setRuntimeStatuses((current) => ({ ...current, [event.node_id]: "running" }))
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
      const nextVersions = await listWorkflowVersions(token, workspaceId, agent.id)
      setVersions(nextVersions.items)
      notify("success", t("工作流版本 v{version} 已发布", { version: version.version_number }))
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
      if (runTarget.source === "draft" && isDirty && !(await saveDraft())) return
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
    const target = selectWorkflowRunTarget(agent.can_edit, versions, versionNumber)
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
        t("将版本 v{version} 恢复为当前草稿？", { version: version.version_number })
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
    <div className="flex min-h-[calc(100dvh-6rem)] flex-col overflow-hidden rounded-md border bg-background">
      <header className="flex min-h-16 flex-wrap items-center gap-2 px-3 py-2 sm:px-4">
        <IconButton
          label={t("返回")}
          onClick={() => {
            if (view === "canvas") {
              setView("details")
              return
            }
            if (!hasUnsavedChanges || window.confirm(t("放弃未保存的更改？"))) onBack()
          }}
        >
          <ArrowLeftIcon />
        </IconButton>
        <span className="flex size-9 shrink-0 items-center justify-center rounded-md bg-emerald-500/10 text-emerald-700 dark:text-emerald-400">
          <WorkflowIcon className="size-5" />
        </span>
        <div className="mr-auto min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="max-w-64 truncate text-base font-semibold sm:max-w-md">{agent.name}</h1>
            <Badge variant="secondary">{t("工作流")}</Badge>
            <Badge variant="outline">v{definition.revision}</Badge>
            {hasUnsavedChanges ? <Badge variant="destructive">{t("未保存")}</Badge> : null}
          </div>
          <p className="mt-0.5 max-w-96 truncate text-xs text-muted-foreground">
            {agent.description || t("暂无描述")}
          </p>
        </div>
        <IconButton label={t("版本历史")} onClick={() => setHistoryOpen(true)}>
          <HistoryIcon />
        </IconButton>
        {agent.can_edit ? (
          <>
            <IconButton label={t("应用设置")} onClick={() => setSettingsOpen(true)}>
              <SettingsIcon />
            </IconButton>
            <IconButton label={t("资源授权")} onClick={onManagePermissions}>
              <ShieldCheckIcon />
            </IconButton>
            <IconButton label={t("删除工作流")} onClick={onDelete}>
              <Trash2Icon />
            </IconButton>
          </>
        ) : null}
        {view === "canvas" && agent.can_edit ? (
          <Button type="button" variant="outline" disabled={!isDirty || isSaving} onClick={() => void saveDraft()}>
            {isSaving ? <LoaderCircleIcon className="animate-spin" /> : <SaveIcon />}
            {t("保存")}
          </Button>
        ) : null}
        {view === "details" ? (
          <Button type="button" variant="outline" onClick={() => setView("canvas")}>
            <PencilIcon />
            {agent.can_edit ? t("编辑画布") : t("查看画布")}
          </Button>
        ) : null}
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
          {agent.can_edit ? t("调试运行") : t("运行已发布版本")}
        </Button>
        {canManagePublishing ? (
          <Button
            type="button"
            disabled={isPublishing || agent.status !== "active" || isAppDirty}
            title={isAppDirty ? t("请先保存更改后再发布。") : undefined}
            onClick={() => void handlePublish()}
          >
            {isPublishing ? <LoaderCircleIcon className="animate-spin" /> : <UploadIcon />}
            {t("发布版本")}
          </Button>
        ) : null}
      </header>

      {view === "details" ? (
        <main className="flex-1 border-t">
          <section className="grid grid-cols-2 divide-x border-b sm:grid-cols-4">
            <div className="grid gap-1 px-4 py-4">
              <span className="text-xs text-muted-foreground">{t("节点数量")}</span>
              <strong className="text-xl font-semibold tabular-nums">{nodeCount}</strong>
            </div>
            <div className="grid gap-1 px-4 py-4 sm:border-r">
              <span className="text-xs text-muted-foreground">{t("连线数量")}</span>
              <strong className="text-xl font-semibold tabular-nums">{edgeCount}</strong>
            </div>
            <div className="grid gap-1 border-t px-4 py-4 sm:border-t-0 sm:border-r">
              <span className="text-xs text-muted-foreground">{t("草稿修订")}</span>
              <strong className="text-xl font-semibold tabular-nums">v{definition.revision}</strong>
            </div>
            <div className="grid gap-1 border-t px-4 py-4 sm:border-t-0">
              <span className="text-xs text-muted-foreground">{t("已发布版本")}</span>
              <strong className="text-xl font-semibold tabular-nums">
                {latestPublishedVersion ? `v${latestPublishedVersion}` : "-"}
              </strong>
            </div>
          </section>
          <section className="grid gap-8 p-5 lg:grid-cols-[minmax(0,1.2fr)_minmax(16rem,0.8fr)] lg:p-8">
            <div className="grid content-start gap-4">
              <div>
                <h2 className="text-lg font-semibold">{t("工作流详情")}</h2>
                <p className="mt-2 max-w-2xl text-sm leading-6 text-muted-foreground">
                  {agent.description || t("暂无描述")}
                </p>
              </div>
              <p className="max-w-2xl text-sm leading-6 text-muted-foreground">
                {t("当前草稿包含 {nodes} 个节点和 {edges} 条连线。", {
                  nodes: nodeCount,
                  edges: edgeCount,
                })}
              </p>
              <div>
                <Button type="button" onClick={() => setView("canvas")}>
                  <PencilIcon />
                  {agent.can_edit ? t("编辑画布") : t("查看画布")}
                </Button>
              </div>
            </div>
            <div className="grid content-start gap-3 border-t pt-5 lg:border-l lg:border-t-0 lg:pl-8 lg:pt-0">
              <h2 className="text-sm font-semibold">{t("最近运行")}</h2>
              {currentRun ? (
                <div className="flex flex-wrap items-center gap-2 text-sm">
                  <Badge variant={currentRun.status === "failed" ? "destructive" : "outline"}>
                    {runStatusLabel(currentRun, t)}
                  </Badge>
                  <span className="text-xs text-muted-foreground">
                    {t("已执行 {count} 个节点", { count: currentRun.step_count })}
                  </span>
                  <Button type="button" variant="ghost" size="sm" onClick={() => setRunDetailsOpen(true)}>
                    {t("查看运行结果")}
                  </Button>
                </div>
              ) : (
                <p className="text-sm text-muted-foreground">{t("尚未运行")}</p>
              )}
            </div>
          </section>
        </main>
      ) : null}

      {view === "canvas" && currentRun ? (
        <div className="flex flex-wrap items-center gap-3 border-t bg-muted/25 px-4 py-2 text-xs">
          <Badge
            variant={currentRun.status === "failed" ? "destructive" : "outline"}
            className={cn(currentRun.status === "running" && "border-sky-500 text-sky-700 dark:text-sky-400")}
          >
            {runStatusLabel(currentRun, t)}
          </Badge>
          <span className="text-muted-foreground">
            {t("已执行 {count} 个节点", { count: currentRun.step_count })}
          </span>
          <span className="text-muted-foreground">
            {t("令牌 {count}", { count: currentRun.token_usage })}
          </span>
          <Button type="button" variant="ghost" size="sm" className="ml-auto" onClick={() => setRunDetailsOpen(true)}>
            {t("查看运行结果")}
          </Button>
        </div>
      ) : null}

      {view === "canvas" ? (
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
      ) : null}

      <Dialog open={runOpen} onOpenChange={setRunOpen}>
        <DialogContent className="max-w-xl">
          <form className="grid gap-4" onSubmit={(event) => void handleRun(event)}>
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
            <label className="grid gap-2 text-sm font-medium" htmlFor="workflow-run-version">
              {t("运行版本")}
              <select
                id="workflow-run-version"
                className="h-9 rounded-md border bg-background px-2 text-sm"
                value={runVersionNumber ?? "draft"}
                onChange={(event) => {
                  const nextVersion = event.target.value === "draft" ? null : Number(event.target.value)
                  const target = selectWorkflowRunTarget(agent.can_edit, versions, nextVersion)
                  if (!target) return
                  setRunVersionNumber(nextVersion)
                  setRunInputs(JSON.stringify(initialWorkflowInputs(target.graph ?? graph), null, 2))
                  setRunInputsInvalid(false)
                }}
              >
                {agent.can_edit ? <option value="draft">{t("当前草稿")}</option> : null}
                {versions.map((version) => (
                  <option key={version.id} value={version.version_number}>
                    {t("已发布版本 v{version}", { version: version.version_number })}
                  </option>
                ))}
              </select>
            </label>
            <label className="grid gap-2 text-sm font-medium" htmlFor="workflow-run-inputs">
              {t("运行输入")}
              <textarea
                id="workflow-run-inputs"
                className="min-h-64 resize-y rounded-md border bg-background p-3 font-mono text-xs leading-5 outline-none focus-visible:ring-2 focus-visible:ring-ring aria-invalid:border-destructive"
                value={runInputs}
                aria-invalid={runInputsInvalid}
                onChange={(event) => setRunInputs(event.target.value)}
              />
              {runInputsInvalid ? <span className="text-xs font-normal text-destructive">{t("请输入 JSON 对象")}</span> : null}
            </label>
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => setRunOpen(false)}>{t("取消")}</Button>
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
                {isRunning ? <LoaderCircleIcon className="animate-spin" /> : <PlayIcon />}
                {runTarget?.source === "published" ? t("开始运行") : t("开始调试")}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      <Dialog open={historyOpen} onOpenChange={setHistoryOpen}>
        <DialogContent className="max-h-[calc(100svh-2rem)] max-w-2xl overflow-y-auto">
          <DialogHeader>
            <DialogTitle>{t("版本历史")}</DialogTitle>
            <DialogDescription>{t("已发布版本不可修改，可恢复为新的草稿修订。")}</DialogDescription>
          </DialogHeader>
          <div className="divide-y rounded-md border">
            {versions.length ? versions.map((version) => (
              <div key={version.id} className="flex items-center gap-3 p-3">
                <Badge>v{version.version_number}</Badge>
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium">{t("草稿修订 {revision}", { revision: version.definition_revision })}</p>
                  <p className="truncate text-xs text-muted-foreground">{new Date(version.created_at).toLocaleString()} · {version.graph_hash.slice(0, 12)}</p>
                </div>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  disabled={
                    agent.status !== "active" ||
                    isRunning ||
                    Boolean(currentRun && !TERMINAL_STATUSES.has(currentRun.status))
                  }
                  onClick={() => {
                    setHistoryOpen(false)
                    openRunDialog(version.version_number)
                  }}
                >
                  <PlayIcon />
                  {t("运行")}
                </Button>
                {agent.can_edit ? <Button type="button" variant="outline" size="sm" onClick={() => void handleRestore(version)}>{t("恢复")}</Button> : null}
              </div>
            )) : <p className="p-6 text-center text-sm text-muted-foreground">{t("暂无已发布版本")}</p>}
          </div>
        </DialogContent>
      </Dialog>

      <Dialog open={runDetailsOpen} onOpenChange={setRunDetailsOpen}>
        <DialogContent className="max-h-[calc(100svh-2rem)] max-w-3xl overflow-y-auto">
          <DialogHeader>
            <DialogTitle>{t("运行结果")}</DialogTitle>
            <DialogDescription>{currentRun ? `${runStatusLabel(currentRun, t)} · ${currentRun.trace_id}` : ""}</DialogDescription>
          </DialogHeader>
          {currentRun ? (
            <div className="grid gap-5">
              <section className="grid gap-2">
                <h3 className="text-sm font-semibold">{currentRun.last_error ? t("错误") : t("结果")}</h3>
                {currentRun.last_error ? <p className="rounded-md bg-destructive/10 p-3 text-sm text-destructive">{currentRun.last_error}</p> : <JsonBlock value={currentRun.outputs} />}
              </section>
              <section className="grid gap-2">
                <h3 className="text-sm font-semibold">{t("节点执行记录")}</h3>
                <div className="divide-y rounded-md border">
                  {executions.map((execution) => (
                    <div key={execution.id} className="grid gap-2 p-3">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="text-sm font-medium">{execution.node_id}</span>
                        <Badge variant={execution.status === "failed" ? "destructive" : "outline"}>{execution.status === "succeeded" ? t("运行成功") : execution.status === "failed" ? t("运行失败") : execution.status === "running" ? t("运行中") : t("已跳过")}</Badge>
                        {execution.duration_ms !== null ? <span className="ml-auto flex items-center gap-1 text-xs text-muted-foreground"><Clock3Icon className="size-3.5" />{t("{duration} 毫秒", { duration: execution.duration_ms })}</span> : null}
                      </div>
                      {execution.error ? <p className="text-xs text-destructive">{execution.error}</p> : null}
                    </div>
                  ))}
                  {!executions.length ? <p className="p-4 text-sm text-muted-foreground">{t("暂无节点执行记录")}</p> : null}
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
            <DialogDescription>{t("配置默认模型以及节点可使用的知识库和只读 MCP 工具。")}</DialogDescription>
          </DialogHeader>
          <form onSubmit={onSaveApp}>
            <AgentConfigFields form={form} setForm={setForm} models={models} knowledgeBases={knowledgeBases} mcpServers={mcpServers} readOnly={!agent.can_edit} t={t} />
            <DialogFooter className="pt-5">
              <Button type="button" variant="outline" onClick={() => setSettingsOpen(false)}>{t("关闭")}</Button>
              <Button type="submit" disabled={isSavingApp}>
                {isSavingApp ? <LoaderCircleIcon className="animate-spin" /> : <SaveIcon />}
                {t("保存")}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  )
}
