"use client"

import * as React from "react"
import {
  ArchiveIcon,
  BracesIcon,
  Code2Icon,
  EyeIcon,
  LoaderCircleIcon,
  NetworkIcon,
  PlusIcon,
  PowerIcon,
  RefreshCwIcon,
  SearchIcon,
  ShieldCheckIcon,
  SparklesIcon,
  Trash2Icon,
  WrenchIcon,
} from "lucide-react"

import { useConfirmDialog } from "@/components/app/confirm-dialog"
import { McpSourceDialog } from "@/components/tools/mcp-source-dialog"
import { PythonToolDialog } from "@/components/tools/python-tool-dialog"
import { ToolPermissionsDialog } from "@/components/tools/tool-permissions-dialog"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { CardMoreMenu } from "@/components/ui/card-more-menu"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { Input } from "@/components/ui/input"
import { Spec } from "@/components/ui/spec"
import { useLanguage } from "@/contexts/language-provider"
import { useSession } from "@/contexts/session-context"
import {
  archivePythonTool,
  deleteToolSource,
  getTool,
  listAllTools,
  listAllToolSources,
  refreshToolSource,
  setPythonToolEnabled,
  setToolSourceEnabled,
  updateToolPolicy,
  type ToolDetail,
  type ToolKind,
  type ToolSourceDetail,
  type ToolSummary,
} from "@/lib/api/tools"
import { getMembershipRole } from "@/lib/display"
import { isEventFromDropdownMenu } from "@/lib/dom"
import { getErrorMessage } from "@/lib/errors"
import {
  toolDisplayDescription,
  toolDisplayName,
  toolSourceDisplayName,
} from "@/lib/tool-display"

type ToolGroup = "mine" | "shared" | "builtin"

function toolGroup(tool: ToolSummary, userId: string): ToolGroup {
  if (tool.kind === "builtin") return "builtin"
  return tool.created_by_user_id === userId ? "mine" : "shared"
}

function kindIcon(kind: ToolKind) {
  if (kind === "python") return Code2Icon
  if (kind === "mcp") return NetworkIcon
  return SparklesIcon
}

function toolIsAvailable(tool: ToolSummary) {
  return (
    tool.status === "active" &&
    tool.availability === "available" &&
    Boolean(tool.current_version_id)
  )
}

function kindLabel(kind: ToolKind) {
  return kind === "python" ? "Python" : kind === "mcp" ? "MCP" : "内置"
}

function permissionLabel(permission: NonNullable<ToolSummary["permission"]>) {
  if (permission === "use") return "使用权限"
  if (permission === "view") return "查看权限"
  if (permission === "admin") return "管理权限"
  return "所有者"
}

function transportLabel(transport: ToolSourceDetail["transport"]) {
  if (transport === "streamable_http") return "Streamable HTTP"
  if (transport === "sse") return "SSE"
  return "stdio"
}

export function ToolsPage() {
  const { t } = useLanguage()
  const { token, me, selectedWorkspaceId, notify } = useSession()
  const [confirmAction, confirmDialog] = useConfirmDialog()
  const [tools, setTools] = React.useState<ToolSummary[]>([])
  const [sources, setSources] = React.useState<ToolSourceDetail[]>([])
  const [search, setSearch] = React.useState("")
  const [isLoading, setIsLoading] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)
  const [busyId, setBusyId] = React.useState<string | null>(null)
  const [pythonDialog, setPythonDialog] = React.useState<{
    open: boolean
    tool: ToolSummary | null
  }>({ open: false, tool: null })
  const [mcpDialogOpen, setMcpDialogOpen] = React.useState(false)
  const [permissionTool, setPermissionTool] =
    React.useState<ToolSummary | null>(null)
  const [detailTarget, setDetailTarget] = React.useState<ToolSummary | null>(
    null
  )
  const [detailTool, setDetailTool] = React.useState<ToolDetail | null>(null)
  const [isDetailLoading, setIsDetailLoading] = React.useState(false)
  const [detailError, setDetailError] = React.useState<string | null>(null)
  const addToolTriggerRef = React.useRef<HTMLButtonElement>(null)
  const requestRef = React.useRef(0)
  const message = React.useCallback(
    (kind: "success" | "error", value: string) => notify(kind, value),
    [notify]
  )

  const membershipRole = getMembershipRole(me, selectedWorkspaceId)
  const canUsePrivilegedMcp = membershipRole === "admin"

  const load = React.useCallback(async () => {
    if (!token || !selectedWorkspaceId) {
      setTools([])
      setSources([])
      return
    }
    const requestId = ++requestRef.current
    setIsLoading(true)
    setError(null)
    try {
      const [nextTools, nextSources] = await Promise.all([
        listAllTools(token, selectedWorkspaceId),
        listAllToolSources(token, selectedWorkspaceId),
      ])
      if (requestId !== requestRef.current) return
      setTools(nextTools)
      setSources(nextSources)
    } catch (nextError) {
      if (requestId !== requestRef.current) return
      setTools([])
      setSources([])
      setError(getErrorMessage(nextError, t))
    } finally {
      if (requestId === requestRef.current) setIsLoading(false)
    }
  }, [selectedWorkspaceId, t, token])

  React.useEffect(() => {
    // Load the workspace catalog when its controlled context changes.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load()
    return () => {
      requestRef.current += 1
    }
  }, [load])

  if (!token || !me || !selectedWorkspaceId) return null
  const accessToken = token
  const workspaceId = selectedWorkspaceId
  const displayToolName = (tool: ToolSummary) => toolDisplayName(tool, t)
  const displayToolDescription = (tool: ToolSummary) =>
    toolDisplayDescription(tool, t)
  const displaySourceName = (tool: ToolSummary) =>
    toolSourceDisplayName(tool.source, t)

  const query = search.trim().toLowerCase()
  const filteredTools = tools.filter(
    (tool) =>
      !query ||
      `${displayToolName(tool)} ${displayToolDescription(tool)} ${displaySourceName(tool)} ${tool.function_name}`
        .toLowerCase()
        .includes(query)
  )
  const filteredSources = sources.filter(
    (source) =>
      !query ||
      `${source.name} ${source.url ?? ""} ${source.stdio_command ?? ""} ${source.transport ?? ""}`
        .toLowerCase()
        .includes(query)
  )
  const groups: Array<{ id: ToolGroup; label: string; tools: ToolSummary[] }> =
    [
      {
        id: "mine",
        label: t("我的工具"),
        tools: filteredTools.filter(
          (tool) => toolGroup(tool, me.user.id) === "mine"
        ),
      },
      {
        id: "shared",
        label: t("共享给我的"),
        tools: filteredTools.filter(
          (tool) => toolGroup(tool, me.user.id) === "shared"
        ),
      },
      {
        id: "builtin",
        label: t("内置工具"),
        tools: filteredTools.filter(
          (tool) => toolGroup(tool, me.user.id) === "builtin"
        ),
      },
    ]

  function upsertTool(updated: ToolSummary) {
    setTools((current) => {
      const exists = current.some((tool) => tool.id === updated.id)
      return exists
        ? current.map((tool) => (tool.id === updated.id ? updated : tool))
        : [updated, ...current]
    })
  }

  function upsertSource(updated: ToolSourceDetail) {
    setSources((current) => {
      const exists = current.some((source) => source.id === updated.id)
      return exists
        ? current.map((source) => (source.id === updated.id ? updated : source))
        : [updated, ...current]
    })
  }

  async function loadDetail(tool: ToolSummary) {
    setIsDetailLoading(true)
    setDetailError(null)
    try {
      setDetailTool(await getTool(accessToken, workspaceId, tool.id))
    } catch (nextError) {
      setDetailTool(null)
      setDetailError(getErrorMessage(nextError, t))
    } finally {
      setIsDetailLoading(false)
    }
  }

  async function openDetail(tool: ToolSummary) {
    if (tool.kind === "python") {
      setPythonDialog({ open: true, tool })
      return
    }
    setDetailTarget(tool)
    setDetailTool(null)
    await loadDetail(tool)
  }

  async function togglePythonTool(tool: ToolSummary) {
    if (busyId) return
    if (tool.kind !== "python") return
    const enabled = tool.status === "disabled"
    if (
      !enabled &&
      !(await confirmAction({
        description: t(
          "禁用工具“{name}”？已绑定的 Agent 和 Workflow 将无法调用它。",
          {
            name: displayToolName(tool),
          }
        ),
        confirmLabel: t("禁用"),
        destructive: true,
      }))
    ) {
      return
    }
    setBusyId(tool.id)
    try {
      const updated = await setPythonToolEnabled(
        accessToken,
        workspaceId,
        tool.id,
        enabled
      )
      upsertTool(updated)
      message("success", enabled ? t("工具已启用") : t("工具已禁用"))
    } catch (nextError) {
      message("error", getErrorMessage(nextError, t))
    } finally {
      setBusyId(null)
    }
  }

  async function setMcpPolicy(
    tool: ToolSummary,
    mode: "approval_required" | "read_only" | "disabled"
  ) {
    if (busyId || tool.kind !== "mcp") return
    if (
      mode === "read_only" &&
      !(await confirmAction({
        description: t("确认将工具“{name}”标记为只读并允许自动执行吗？", {
          name: displayToolName(tool),
        }),
      }))
    ) {
      return
    }
    if (
      mode === "disabled" &&
      !(await confirmAction({
        description: t(
          "禁用工具“{name}”？已绑定的 Agent 和 Workflow 将无法调用它。",
          { name: displayToolName(tool) }
        ),
        confirmLabel: t("禁用"),
        destructive: true,
      }))
    ) {
      return
    }
    setBusyId(tool.id)
    try {
      upsertTool(
        await updateToolPolicy(accessToken, workspaceId, tool.id, mode)
      )
      message("success", t("MCP 工具策略已更新"))
    } catch (nextError) {
      message("error", getErrorMessage(nextError, t))
    } finally {
      setBusyId(null)
    }
  }

  async function refreshSource(source: ToolSourceDetail) {
    if (busyId) return
    setBusyId(source.id)
    try {
      const updated = await refreshToolSource(
        accessToken,
        workspaceId,
        source.id
      )
      upsertSource(updated)
      await load()
      message("success", t("MCP 工具列表已刷新"))
    } catch (nextError) {
      message("error", getErrorMessage(nextError, t))
    } finally {
      setBusyId(null)
    }
  }

  async function toggleSource(source: ToolSourceDetail) {
    if (busyId) return
    const enabled = source.status !== "active"
    if (
      !enabled &&
      !(await confirmAction({
        description: t("禁用来源“{name}”？该来源下的工具将暂时不可用。", {
          name: source.name,
        }),
        confirmLabel: t("禁用"),
        destructive: true,
      }))
    ) {
      return
    }
    setBusyId(source.id)
    try {
      upsertSource(
        await setToolSourceEnabled(accessToken, workspaceId, source.id, enabled)
      )
      await load()
      message("success", enabled ? t("工具来源已启用") : t("工具来源已禁用"))
    } catch (nextError) {
      message("error", getErrorMessage(nextError, t))
    } finally {
      setBusyId(null)
    }
  }

  async function archiveTool(tool: ToolSummary) {
    if (busyId || tool.kind !== "python") return
    if (
      !(await confirmAction({
        description: t("归档工具“{name}”？此操作会使所有已绑定版本不可用。", {
          name: displayToolName(tool),
        }),
        confirmLabel: t("归档"),
        destructive: true,
      }))
    ) {
      return
    }
    setBusyId(tool.id)
    try {
      await archivePythonTool(accessToken, workspaceId, tool.id)
      setTools((current) => current.filter((item) => item.id !== tool.id))
      message("success", t("工具已归档"))
    } catch (nextError) {
      message("error", getErrorMessage(nextError, t))
    } finally {
      setBusyId(null)
    }
  }

  async function removeSource(source: ToolSourceDetail) {
    if (busyId) return
    if (
      !(await confirmAction({
        description: t("删除来源“{name}”？该来源下的全部工具都会被移除。", {
          name: source.name,
        }),
        confirmLabel: t("删除"),
        destructive: true,
      }))
    ) {
      return
    }
    setBusyId(source.id)
    try {
      await deleteToolSource(accessToken, workspaceId, source.id)
      setTools((current) =>
        current.filter((item) => item.source.id !== source.id)
      )
      setSources((current) => current.filter((item) => item.id !== source.id))
      message("success", t("工具来源已删除"))
    } catch (nextError) {
      message("error", getErrorMessage(nextError, t))
    } finally {
      setBusyId(null)
    }
  }

  return (
    <main className="min-w-0 space-y-6">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <h1 className="text-2xl font-semibold">{t("工具")}</h1>
          <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
            {t("统一管理 Python、MCP 与内置工具，以及它们的版本和授权。")}
          </p>
        </div>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button ref={addToolTriggerRef} type="button">
              <PlusIcon />
              {t("添加工具")}
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-56">
            <DropdownMenuItem
              onSelect={() => setPythonDialog({ open: true, tool: null })}
            >
              <Code2Icon />
              {t("Python 工具")}
            </DropdownMenuItem>
            <DropdownMenuItem onSelect={() => setMcpDialogOpen(true)}>
              <NetworkIcon />
              {t("MCP Server")}
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuItem disabled>
              <SparklesIcon />
              {t("Skill（后续开放）")}
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>

      <div className="rounded-lg border bg-background p-3 shadow-sm">
        <div className="relative min-w-0 sm:w-[320px]">
          <SearchIcon className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            role="searchbox"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder={t("搜索名称、描述或来源")}
            className="pl-9"
          />
        </div>
      </div>

      {!isLoading && !error && filteredSources.length ? (
        <section aria-labelledby="tool-source-group">
          <div className="mb-3 flex items-center gap-2">
            <h2 id="tool-source-group" className="text-sm font-semibold">
              {t("MCP Server")}
            </h2>
            <Badge variant="secondary">{filteredSources.length}</Badge>
          </div>
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">
            {filteredSources.map((source) => {
              const active = source.status === "active"
              return (
                <article
                  key={source.id}
                  className="flex min-h-40 min-w-0 flex-col rounded-md border p-3"
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="flex min-w-0 gap-3">
                      <span className="flex size-9 shrink-0 items-center justify-center rounded-md bg-violet-500/10 text-violet-700 dark:text-violet-400">
                        <NetworkIcon className="size-5" />
                      </span>
                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-center gap-2">
                          <h3 className="truncate text-sm font-semibold">
                            {source.name}
                          </h3>
                          <Badge variant={active ? "secondary" : "outline"}>
                            {t(active ? "已启用" : "已停用")}
                          </Badge>
                        </div>
                        <p className="mt-1 truncate text-sm text-muted-foreground">
                          {source.transport === "stdio"
                            ? t("stdio 命令：{command}", {
                                command: source.stdio_command ?? "-",
                              })
                            : source.url}
                        </p>
                      </div>
                    </div>
                  </div>
                  {source.last_error ? (
                    <p className="mt-3 line-clamp-2 text-xs leading-5 text-destructive">
                      {source.last_error}
                    </p>
                  ) : null}
                  <div className="mt-auto flex items-end justify-between gap-2 pt-4">
                    <dl className="grid min-w-0 flex-1 grid-cols-2 gap-3 text-sm">
                      <Spec
                        label={t("连接方式")}
                        value={t(transportLabel(source.transport))}
                      />
                      <Spec
                        label={t("工具")}
                        value={String(source.tool_count)}
                      />
                    </dl>
                    <CardMoreMenu
                      label={t("管理来源 {name}", { name: source.name })}
                    >
                      <DropdownMenuItem
                        disabled={Boolean(busyId)}
                        onSelect={() => void refreshSource(source)}
                      >
                        <RefreshCwIcon />
                        {t("刷新工具")}
                      </DropdownMenuItem>
                      <DropdownMenuItem
                        disabled={Boolean(busyId)}
                        onSelect={() => void toggleSource(source)}
                      >
                        <PowerIcon />
                        {active ? t("禁用") : t("启用")}
                      </DropdownMenuItem>
                      <DropdownMenuSeparator />
                      <DropdownMenuItem
                        variant="destructive"
                        disabled={Boolean(busyId)}
                        onSelect={() => void removeSource(source)}
                      >
                        <Trash2Icon />
                        {t("删除来源")}
                      </DropdownMenuItem>
                    </CardMoreMenu>
                  </div>
                </article>
              )
            })}
          </div>
        </section>
      ) : null}

      {isLoading ? (
        <div className="flex min-h-72 items-center justify-center gap-2 rounded-xl border text-sm text-muted-foreground">
          <LoaderCircleIcon className="size-4 animate-spin" />
          {t("正在加载工具")}
        </div>
      ) : error ? (
        <div className="flex min-h-72 flex-col items-center justify-center gap-3 rounded-xl border border-dashed bg-muted/20 p-6 text-center">
          <p className="font-medium">{t("工具加载失败")}</p>
          <p className="text-sm text-muted-foreground">{error}</p>
          <Button type="button" variant="outline" onClick={() => void load()}>
            <RefreshCwIcon />
            {t("重试")}
          </Button>
        </div>
      ) : tools.length === 0 ? (
        <div className="flex min-h-72 flex-col items-center justify-center rounded-xl border border-dashed bg-muted/20 px-6 text-center">
          <span className="flex size-12 items-center justify-center rounded-xl bg-muted text-muted-foreground">
            <WrenchIcon className="size-5" />
          </span>
          <p className="mt-4 font-medium">{t("还没有工具")}</p>
          <p className="mt-1 max-w-md text-sm text-muted-foreground">
            {t(
              "添加 Python 工具或连接 MCP Server 后，可授权给 Agent 与 Workflow 使用。"
            )}
          </p>
        </div>
      ) : filteredTools.length === 0 ? (
        <div className="flex min-h-52 items-center justify-center rounded-xl border border-dashed text-sm text-muted-foreground">
          {t("没有匹配的工具")}
        </div>
      ) : (
        <div className="space-y-7">
          {groups.map((group) =>
            group.tools.length ? (
              <section
                key={group.id}
                aria-labelledby={`tool-group-${group.id}`}
              >
                <div className="mb-3 flex items-center gap-2">
                  <h2
                    id={`tool-group-${group.id}`}
                    className="text-sm font-semibold"
                  >
                    {group.label}
                  </h2>
                  <Badge variant="secondary">{group.tools.length}</Badge>
                </div>
                <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">
                  {group.tools.map((tool) => {
                    const Icon = kindIcon(tool.kind)
                    const available = toolIsAvailable(tool)
                    const source = sources.find(
                      (item) => item.id === tool.source.id
                    )
                    return (
                      <article
                        key={tool.id}
                        role="button"
                        tabIndex={0}
                        className="relative flex min-h-40 min-w-0 cursor-pointer flex-col rounded-md border p-3 transition-colors outline-none hover:bg-muted/40 focus-visible:ring-2 focus-visible:ring-ring"
                        onClick={(event) => {
                          if (isEventFromDropdownMenu(event)) return
                          void openDetail(tool)
                        }}
                        onKeyDown={(event) => {
                          if (event.target !== event.currentTarget) return
                          if (event.key === "Enter" || event.key === " ") {
                            event.preventDefault()
                            void openDetail(tool)
                          }
                        }}
                      >
                        <div className="flex items-start justify-between gap-3">
                          <div className="flex min-w-0 gap-3">
                            <span className="flex size-9 shrink-0 items-center justify-center rounded-md bg-sky-500/10 text-sky-700 dark:text-sky-400">
                              <Icon className="size-5" />
                            </span>
                            <div className="min-w-0 flex-1">
                              <div className="flex flex-wrap items-center gap-2">
                                <h3 className="truncate text-sm font-semibold">
                                  {displayToolName(tool)}
                                </h3>
                                <Badge
                                  variant={available ? "secondary" : "outline"}
                                >
                                  {available ? t("可用") : t("不可用")}
                                </Badge>
                                {tool.permission ? (
                                  <Badge variant="outline">
                                    {t(permissionLabel(tool.permission))}
                                  </Badge>
                                ) : null}
                                {source?.status === "disabled" ? (
                                  <Badge variant="outline">
                                    {t("来源已禁用")}
                                  </Badge>
                                ) : null}
                              </div>
                              <p className="mt-1 truncate font-mono text-sm text-muted-foreground">
                                {tool.function_name}
                              </p>
                            </div>
                          </div>
                          {tool.can_manage ? (
                            <span className="absolute right-3 bottom-3">
                              <CardMoreMenu
                                label={t("管理工具 {name}", {
                                  name: displayToolName(tool),
                                })}
                              >
                                {tool.kind === "python" ? (
                                  <DropdownMenuItem
                                    onSelect={() =>
                                      setPythonDialog({ open: true, tool })
                                    }
                                  >
                                    <BracesIcon />
                                    {t("编辑")}
                                  </DropdownMenuItem>
                                ) : (
                                  <DropdownMenuItem
                                    onSelect={() => void openDetail(tool)}
                                  >
                                    <EyeIcon />
                                    {t("查看详情")}
                                  </DropdownMenuItem>
                                )}
                                <DropdownMenuItem
                                  onSelect={() => setPermissionTool(tool)}
                                >
                                  <ShieldCheckIcon />
                                  {t("授权")}
                                </DropdownMenuItem>
                                {tool.kind === "mcp" ? (
                                  <DropdownMenuItem
                                    disabled={!source || Boolean(busyId)}
                                    onSelect={() =>
                                      source && void refreshSource(source)
                                    }
                                  >
                                    <RefreshCwIcon />
                                    {t("刷新工具")}
                                  </DropdownMenuItem>
                                ) : null}
                                {tool.kind === "mcp" ? (
                                  <>
                                    <DropdownMenuSeparator />
                                    <DropdownMenuLabel>
                                      {t("工具执行策略")}
                                    </DropdownMenuLabel>
                                    {source?.status === "disabled" ? (
                                      <DropdownMenuItem disabled>
                                        {t("来源已禁用")}
                                      </DropdownMenuItem>
                                    ) : tool.status === "disabled" &&
                                      membershipRole !== "admin" ? (
                                      <DropdownMenuItem disabled>
                                        {t("工具调用已禁用")}
                                      </DropdownMenuItem>
                                    ) : (
                                      <>
                                        <DropdownMenuItem
                                          disabled={Boolean(busyId)}
                                          onSelect={() =>
                                            void setMcpPolicy(tool, "read_only")
                                          }
                                        >
                                          <ShieldCheckIcon />
                                          {t("只读自动执行")}
                                        </DropdownMenuItem>
                                        <DropdownMenuItem
                                          disabled={Boolean(busyId)}
                                          onSelect={() =>
                                            void setMcpPolicy(
                                              tool,
                                              "approval_required"
                                            )
                                          }
                                        >
                                          <ShieldCheckIcon />
                                          {t("每次调用前审批")}
                                        </DropdownMenuItem>
                                        {membershipRole === "admin" &&
                                        tool.status !== "disabled" ? (
                                          <DropdownMenuItem
                                            variant="destructive"
                                            disabled={Boolean(busyId)}
                                            onSelect={() =>
                                              void setMcpPolicy(
                                                tool,
                                                "disabled"
                                              )
                                            }
                                          >
                                            <PowerIcon />
                                            {t("禁用")}
                                          </DropdownMenuItem>
                                        ) : null}
                                      </>
                                    )}
                                  </>
                                ) : tool.kind === "python" &&
                                  (tool.status === "active" ||
                                    tool.status === "disabled") ? (
                                  <DropdownMenuItem
                                    disabled={Boolean(busyId)}
                                    onSelect={() => void togglePythonTool(tool)}
                                  >
                                    <PowerIcon />
                                    {tool.status === "active"
                                      ? t("禁用")
                                      : t("启用")}
                                  </DropdownMenuItem>
                                ) : null}
                                {tool.kind === "python" ||
                                (tool.kind === "mcp" && source) ? (
                                  <>
                                    <DropdownMenuSeparator />
                                    <DropdownMenuItem
                                      variant="destructive"
                                      disabled={Boolean(busyId)}
                                      onSelect={() =>
                                        tool.kind === "python"
                                          ? void archiveTool(tool)
                                          : source && void removeSource(source)
                                      }
                                    >
                                      {tool.kind === "python" ? (
                                        <ArchiveIcon />
                                      ) : (
                                        <Trash2Icon />
                                      )}
                                      {tool.kind === "python"
                                        ? t("归档")
                                        : t("删除来源")}
                                    </DropdownMenuItem>
                                  </>
                                ) : null}
                              </CardMoreMenu>
                            </span>
                          ) : null}
                        </div>

                        <p className="mt-3 line-clamp-2 text-sm leading-5 text-muted-foreground">
                          {displayToolDescription(tool) || t("暂无描述")}
                        </p>

                        <dl
                          className={`mt-auto grid min-w-0 grid-cols-2 gap-3 pt-4 text-sm ${tool.can_manage ? "pr-10" : ""}`}
                        >
                          <Spec
                            label={t("类型")}
                            value={t(kindLabel(tool.kind))}
                          />
                          <Spec
                            label={t("来源")}
                            value={displaySourceName(tool)}
                          />
                        </dl>
                      </article>
                    )
                  })}
                </div>
              </section>
            ) : null
          )}
        </div>
      )}

      <PythonToolDialog
        open={pythonDialog.open}
        onOpenChange={(open) =>
          setPythonDialog((current) => ({ ...current, open }))
        }
        token={accessToken}
        workspaceId={workspaceId}
        tool={pythonDialog.tool}
        onChanged={upsertTool}
        onArchived={(toolId) =>
          setTools((current) => current.filter((tool) => tool.id !== toolId))
        }
        onMessage={message}
      />
      <McpSourceDialog
        open={mcpDialogOpen}
        onOpenChange={setMcpDialogOpen}
        token={accessToken}
        workspaceId={workspaceId}
        canUsePrivileged={canUsePrivilegedMcp}
        returnFocusRef={addToolTriggerRef}
        onCreated={(source) => {
          setSources((current) => [source, ...current])
          message("success", t("MCP Server 已添加"))
          void load()
        }}
        onError={(value) => message("error", value)}
      />
      <ToolPermissionsDialog
        open={Boolean(permissionTool)}
        onOpenChange={(open) => !open && setPermissionTool(null)}
        token={accessToken}
        workspaceId={workspaceId}
        tool={permissionTool}
        onMessage={message}
      />

      <Dialog
        open={Boolean(detailTarget)}
        onOpenChange={(open) => {
          if (open) return
          setDetailTarget(null)
          setDetailTool(null)
          setDetailError(null)
        }}
      >
        <DialogContent className="max-h-[calc(100svh-2rem)] w-[calc(100%-2rem)] overflow-y-auto sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle>
              {detailTool
                ? displayToolName(detailTool)
                : detailTarget
                  ? displayToolName(detailTarget)
                  : t("工具详情")}
            </DialogTitle>
            <DialogDescription>
              {detailTool
                ? displayToolDescription(detailTool)
                : detailTarget
                  ? displayToolDescription(detailTarget)
                  : ""}
            </DialogDescription>
          </DialogHeader>
          {isDetailLoading ? (
            <div className="flex min-h-48 items-center justify-center gap-2 text-sm text-muted-foreground">
              <LoaderCircleIcon className="size-4 animate-spin" />
              {t("正在加载")}
            </div>
          ) : detailError && detailTarget ? (
            <div
              role="alert"
              className="flex min-h-48 flex-col items-center justify-center gap-3 rounded-xl border border-dashed bg-muted/20 p-6 text-center"
            >
              <p className="font-medium">{t("工具加载失败")}</p>
              <p className="max-w-sm text-xs text-muted-foreground">
                {detailError}
              </p>
              <Button
                type="button"
                variant="outline"
                onClick={() => void loadDetail(detailTarget)}
              >
                <RefreshCwIcon />
                {t("重试")}
              </Button>
            </div>
          ) : detailTool ? (
            <div className="space-y-4">
              <div className="flex flex-wrap gap-2">
                <Badge>{t(kindLabel(detailTool.kind))}</Badge>
                <Badge variant="outline">
                  {toolSourceDisplayName(detailTool.source, t)}
                </Badge>
                <Badge variant="outline">
                  {detailTool.permission
                    ? t(permissionLabel(detailTool.permission))
                    : t("无权限")}
                </Badge>
              </div>
              <div>
                <h3 className="mb-2 text-sm font-medium">{t("输入 Schema")}</h3>
                <pre className="max-h-64 overflow-auto rounded-lg bg-muted p-3 text-xs">
                  {JSON.stringify(detailTool.input_schema ?? {}, null, 2)}
                </pre>
              </div>
              <div>
                <h3 className="mb-2 text-sm font-medium">{t("输出 Schema")}</h3>
                <pre className="max-h-64 overflow-auto rounded-lg bg-muted p-3 text-xs">
                  {JSON.stringify(detailTool.output_schema ?? {}, null, 2)}
                </pre>
              </div>
              {!detailTool.can_manage ? (
                <p className="rounded-lg border bg-muted/25 p-3 text-xs text-muted-foreground">
                  {t(
                    "只显示已发布的脱敏详情；草稿和代码仅所有者或管理员可见。"
                  )}
                </p>
              ) : null}
            </div>
          ) : null}
        </DialogContent>
      </Dialog>
      {confirmDialog}
    </main>
  )
}
