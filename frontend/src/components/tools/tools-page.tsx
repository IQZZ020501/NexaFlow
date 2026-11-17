"use client"

import * as React from "react"
import {
  EyeIcon,
  FolderInputIcon,
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
  XIcon,
} from "lucide-react"

import { useConfirmDialog } from "@/components/app/confirm-dialog"
import { FilterDropdown } from "@/components/app/filter-dropdown"
import { MarkdownContent } from "@/components/knowledge/markdown-content"
import {
  ResourceBulkMoveBar,
  toggleResourceSelection,
} from "@/components/resource-folders/resource-bulk-move-bar"
import { ResourceFolderLayout } from "@/components/resource-folders/resource-folder-layout"
import { ResourceFolderPickerDialog } from "@/components/resource-folders/resource-folder-picker-dialog"
import { ResourceFolderTree } from "@/components/resource-folders/resource-folder-tree"
import { useResourceFolders } from "@/components/resource-folders/use-resource-folders"
import { BuiltinToolIcon } from "@/components/tools/builtin-tool-icon"
import { McpSourceDialog } from "@/components/tools/mcp-source-dialog"
import { McpOAuthDialog } from "@/components/tools/mcp-oauth"
import { McpLongTasksDialog } from "@/components/tools/mcp-long-tasks"
import { SkillDialog } from "@/components/tools/skill-dialog"
import {
  deleteAgentSkill,
  listAllAgentSkills,
  updateAgentSkill,
  type AgentSkill,
} from "@/lib/api/agent-skills"
import { ToolPermissionsDialog } from "@/components/tools/tool-permissions-dialog"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { CardMoreMenu } from "@/components/ui/card-more-menu"
import {
  ResourceCard,
  ResourceCardActions,
  ResourceCardFooter,
  ResourceCardMeta,
  ResourceCardHeader,
  ResourceCardIcon,
  ResourceCardSpecs,
  ResourceCardTitle,
  resourceCardGridClass,
} from "@/components/ui/resource-card"
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
import { IconButton } from "@/components/ui/icon-button"
import { Spec } from "@/components/ui/spec"
import { useLanguage } from "@/contexts/language-provider"
import { useSession } from "@/contexts/session-context"
import { languageLocales } from "@/i18n"
import {
  deleteToolSource,
  getTool,
  listAllTools,
  listAllToolSources,
  refreshToolSource,
  setToolSourceEnabled,
  updateToolPolicy,
  type ToolDetail,
  type ToolKind,
  type ToolSourceDetail,
  type ToolSummary,
} from "@/lib/api/tools"
import {
  builtinSkillMarkdown,
  isBuiltinSkillTool,
} from "@/lib/builtin-skill-docs"
import { formatDateTime, getMembershipRole } from "@/lib/display"
import { getErrorMessage } from "@/lib/errors"
import {
  toolDisplayDescription,
  toolDisplayName,
  toolSourceDisplayName,
} from "@/lib/tool-display"
import { groupTools } from "@/lib/tool-groups"
import { isRegularTool } from "@/lib/tool-visibility"
import { cn } from "@/lib/utils"

const catalogTabs = [
  { kind: "builtin", label: "Skills" },
  { kind: "mcp", label: "MCP" },
] as const satisfies ReadonlyArray<{ kind: ToolKind; label: string }>

type ToolSortKey = "updated_at" | "created_at" | "name"

function sortToolResources<
  T extends { created_at?: string; updated_at?: string },
>(
  resources: T[],
  sortKey: ToolSortKey,
  locale: string,
  getName: (resource: T) => string
) {
  const collator = new Intl.Collator(locale, {
    numeric: true,
    sensitivity: "base",
  })
  return [...resources].sort((left, right) => {
    if (sortKey === "name") {
      return collator.compare(getName(left), getName(right))
    }
    return (
      Date.parse(right[sortKey] ?? "") - Date.parse(left[sortKey] ?? "") ||
      collator.compare(getName(left), getName(right))
    )
  })
}

/**
 * Selects the icon associated with a tool kind.
 *
 * @param kind - The tool category used to determine the icon
 * @returns The icon component for the tool kind
 */
function kindIcon(kind: ToolKind) {
  if (kind === "mcp") return NetworkIcon
  return SparklesIcon
}

/**
 * Determines whether a tool is active, available, and has a current version.
 *
 * @param tool - The tool summary to evaluate
 * @returns `true` if the tool is active and available with a current version, `false` otherwise.
 */
function toolIsAvailable(tool: ToolSummary) {
  return (
    tool.status === "active" &&
    tool.availability === "available" &&
    Boolean(tool.current_version_id)
  )
}

/**
 * Provides the display label for a tool kind.
 *
 * @param kind - The tool kind to label
 * @returns `MCP` or `内置` for the corresponding tool kind
 */
function kindLabel(kind: ToolKind) {
  return kind === "mcp" ? "MCP" : "内置"
}

/**
 * Gets the localized label for a tool permission level.
 *
 * @param permission - The tool permission level to label
 * @returns The Chinese label for the permission level
 */
function permissionLabel(permission: NonNullable<ToolSummary["permission"]>) {
  if (permission === "use") return "使用权限"
  if (permission === "view") return "查看权限"
  if (permission === "admin") return "管理权限"
  return "所有者"
}

/**
 * Formats a tool source transport for display.
 *
 * @param transport - The tool source transport type
 * @returns The human-readable transport label
 */
function transportLabel(transport: ToolSourceDetail["transport"]) {
  if (transport === "streamable_http") return "Streamable HTTP"
  if (transport === "sse") return "SSE"
  return "stdio"
}

/**
 * Manages workspace tools and MCP sources, including discovery, search, permissions, execution policies, and lifecycle actions.
 *
 * @returns The workspace tools management interface.
 */
export function ToolsPage({ initialKind }: { initialKind?: ToolKind } = {}) {
  const { language, t } = useLanguage()
  const { token, me, selectedWorkspaceId, notify } = useSession()
  const resourceFolders = useResourceFolders("tool")
  const [confirmAction, confirmDialog] = useConfirmDialog()
  const [activeKind, setActiveKind] = React.useState<ToolKind>(
    initialKind ?? "builtin"
  )
  const [tools, setTools] = React.useState<ToolSummary[]>([])
  const [sources, setSources] = React.useState<ToolSourceDetail[]>([])
  const [search, setSearch] = React.useState("")
  const [toolSortKey, setToolSortKey] =
    React.useState<ToolSortKey>("updated_at")
  const [isLoading, setIsLoading] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)
  const [busyId, setBusyId] = React.useState<string | null>(null)
  const [mcpDialogOpen, setMcpDialogOpen] = React.useState(false)
  const [oauthSource, setOAuthSource] = React.useState<ToolSourceDetail | null>(
    null
  )
  const [taskSource, setTaskSource] = React.useState<ToolSourceDetail | null>(
    null
  )
  const [skillDialogOpen, setSkillDialogOpen] = React.useState(false)
  const [workspaceSkills, setWorkspaceSkills] = React.useState<AgentSkill[]>([])
  const deletedSkillIds = React.useRef(new Set<string>())
  const [editingSkill, setEditingSkill] = React.useState<
    AgentSkill | undefined
  >()
  const [permissionTool, setPermissionTool] =
    React.useState<ToolSummary | null>(null)
  const [moveToolTarget, setMoveToolTarget] =
    React.useState<ToolSummary | null>(null)
  const [selectedToolIds, setSelectedToolIds] = React.useState<string[]>([])
  const [isBatchManaging, setIsBatchManaging] = React.useState(false)
  const [isBatchMoveOpen, setIsBatchMoveOpen] = React.useState(false)
  const [managedSourceId, setManagedSourceId] = React.useState<string | null>(
    null
  )
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
      setWorkspaceSkills([])
      return
    }
    const requestId = ++requestRef.current
    setIsLoading(true)
    setError(null)
    try {
      const [nextTools, nextSources, nextSkills] = await Promise.all([
        listAllTools(token, selectedWorkspaceId),
        listAllToolSources(token, selectedWorkspaceId),
        listAllAgentSkills(token, selectedWorkspaceId),
      ])
      if (requestId !== requestRef.current) return
      setTools(nextTools)
      setSources(nextSources)
      setWorkspaceSkills(
        nextSkills.filter((skill) => !deletedSkillIds.current.has(skill.id))
      )
    } catch (nextError) {
      if (requestId !== requestRef.current) return
      setTools([])
      setSources([])
      setWorkspaceSkills([])
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
  const locale = languageLocales[language]
  const displayToolName = (tool: ToolSummary) => toolDisplayName(tool, t)
  const displayToolDescription = (tool: ToolSummary) =>
    toolDisplayDescription(tool, t)
  const displaySourceName = (tool: ToolSummary) =>
    toolSourceDisplayName(tool.source, t)

  const catalogTools = tools.filter(
    (tool) =>
      (tool.kind === "builtin" || tool.kind === "mcp") &&
      isRegularTool(tool.function_name) &&
      (!initialKind || tool.kind === activeKind)
  )
  const catalogSources = initialKind && activeKind !== "mcp" ? [] : sources
  const query = search.trim().toLowerCase()
  const filteredTools = sortToolResources(
    catalogTools.filter(
      (tool) =>
        resourceFolders.isInSelectedFolder(tool.folder_id) &&
        (!query ||
          `${displayToolName(tool)} ${displayToolDescription(tool)} ${displaySourceName(tool)}`
            .toLowerCase()
            .includes(query))
    ),
    toolSortKey,
    locale,
    displayToolName
  )
  const isSkillsTab = Boolean(initialKind) && activeKind === "builtin"
  const filteredWorkspaceSkills = workspaceSkills.filter(
    (skill) =>
      !query ||
      `${skill.name} ${skill.description}`.toLowerCase().includes(query)
  )
  const builtinSkillTools = sortToolResources(
    tools.filter(
      (tool) =>
        isBuiltinSkillTool(tool.function_name) &&
        (!query ||
          `${displayToolName(tool)} ${displayToolDescription(tool)}`
            .toLowerCase()
            .includes(query))
    ),
    toolSortKey,
    locale,
    displayToolName
  )
  const builtinTools = filteredTools.filter(
    (tool) => tool.kind === "builtin" && !isBuiltinSkillTool(tool.function_name)
  )
  const sourceGroups = groupTools(
    catalogTools.filter(
      (tool) =>
        tool.kind === "mcp" &&
        resourceFolders.isInSelectedFolder(tool.folder_id)
    )
  ).map((group) => ({ source: group.tools[0]!.source, tools: group.tools }))
  for (const source of catalogSources) {
    if (
      !sourceGroups.some((group) => group.source.id === source.id) &&
      !catalogTools.some((tool) => tool.source.id === source.id) &&
      resourceFolders.selectedFolderId === null
    ) {
      sourceGroups.push({ source, tools: [] })
    }
  }
  const mcpGroups = sortToolResources(
    sourceGroups
      .filter(
        ({ source, tools: sourceTools }) =>
          !query ||
          source.name.toLowerCase().includes(query) ||
          sourceTools.some((tool) =>
            `${displayToolName(tool)} ${displayToolDescription(tool)}`
              .toLowerCase()
              .includes(query)
          )
      )
      .map((group) => ({
        ...group,
        created_at: group.tools
          .map((tool) => tool.created_at ?? "")
          .sort()
          .at(-1),
        updated_at: group.tools
          .map((tool) => tool.updated_at ?? "")
          .sort()
          .at(-1),
        ...sources.find((source) => source.id === group.source.id),
        name: group.source.name,
      })),
    toolSortKey,
    locale,
    (group) => group.source.name
  )
  const flatTools = filteredTools.filter((tool) => tool.kind !== "mcp")
  const managedTools = tools.filter(
    (tool) =>
      tool.kind === "mcp" &&
      tool.source.id === managedSourceId &&
      tool.can_manage
  )
  const managedSourceName =
    managedTools[0]?.source.name ??
    sources.find((source) => source.id === managedSourceId)?.name ??
    ""
  const movableToolIds = filteredTools
    .filter((tool) => tool.can_manage && tool.kind !== "builtin")
    .map((tool) => tool.id)
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
    setDetailTarget(tool)
    setDetailTool(null)
    await loadDetail(tool)
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

  async function removeSkill(skill: AgentSkill) {
    if (busyId || !skill.can_manage) return
    if (
      !(await confirmAction({
        description: t(
          "删除 Skill“{name}”？删除后无法再调用，历史版本和执行记录会保留。",
          { name: skill.name }
        ),
        confirmLabel: t("删除"),
        destructive: true,
      }))
    )
      return
    setBusyId(skill.id)
    try {
      await deleteAgentSkill(accessToken, workspaceId, skill.id)
      deletedSkillIds.current.add(skill.id)
      setWorkspaceSkills((current) =>
        current.filter((item) => item.id !== skill.id)
      )
      if (editingSkill?.id === skill.id) {
        setSkillDialogOpen(false)
        setEditingSkill(undefined)
      }
      message("success", t("Skill 已删除"))
    } catch (cause) {
      message("error", getErrorMessage(cause, t))
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
      setManagedSourceId((current) => (current === source.id ? null : current))
      message("success", t("工具来源已删除"))
    } catch (nextError) {
      message("error", getErrorMessage(nextError, t))
    } finally {
      setBusyId(null)
    }
  }

  const detailFunctionName =
    detailTool?.function_name ?? detailTarget?.function_name
  const skillMarkdown = detailFunctionName
    ? builtinSkillMarkdown(detailFunctionName)
    : null

  function renderToolManagementMenu(tool: ToolSummary) {
    const source = sources.find((item) => item.id === tool.source.id)
    return (
      <CardMoreMenu
        label={t("管理工具 {name}", {
          name: displayToolName(tool),
        })}
      >
        <DropdownMenuItem onSelect={() => setMoveToolTarget(tool)}>
          <FolderInputIcon />
          {t("移动到文件夹")}
        </DropdownMenuItem>
        {tool.kind === "builtin" ? (
          <DropdownMenuItem onSelect={() => void openDetail(tool)}>
            <EyeIcon />
            {t("查看详情")}
          </DropdownMenuItem>
        ) : null}
        <DropdownMenuItem onSelect={() => setPermissionTool(tool)}>
          <ShieldCheckIcon />
          {t("授权")}
        </DropdownMenuItem>
        {tool.kind === "mcp" ? (
          <DropdownMenuItem
            disabled={!source || Boolean(busyId)}
            onSelect={() => source && void refreshSource(source)}
          >
            <RefreshCwIcon />
            {t("刷新工具")}
          </DropdownMenuItem>
        ) : null}
        {tool.kind === "mcp" ? (
          <>
            <DropdownMenuSeparator />
            <DropdownMenuLabel>{t("工具执行策略")}</DropdownMenuLabel>
            {source?.status === "disabled" ? (
              <DropdownMenuItem disabled>{t("来源已禁用")}</DropdownMenuItem>
            ) : (
              <>
                <DropdownMenuItem
                  disabled={Boolean(busyId)}
                  onSelect={() => void setMcpPolicy(tool, "read_only")}
                >
                  <ShieldCheckIcon />
                  {t("只读自动执行")}
                </DropdownMenuItem>
                <DropdownMenuItem
                  disabled={Boolean(busyId)}
                  onSelect={() => void setMcpPolicy(tool, "approval_required")}
                >
                  <ShieldCheckIcon />
                  {t("每次调用前审批")}
                </DropdownMenuItem>
                {tool.status !== "disabled" ? (
                  <DropdownMenuItem
                    variant="destructive"
                    disabled={Boolean(busyId)}
                    onSelect={() => void setMcpPolicy(tool, "disabled")}
                  >
                    <PowerIcon />
                    {t("禁用")}
                  </DropdownMenuItem>
                ) : null}
              </>
            )}
          </>
        ) : null}
        {tool.kind === "mcp" && source ? (
          <>
            <DropdownMenuSeparator />
            <DropdownMenuItem
              variant="destructive"
              disabled={Boolean(busyId)}
              onSelect={() => void removeSource(source)}
            >
              <Trash2Icon />
              {t("删除来源")}
            </DropdownMenuItem>
          </>
        ) : null}
      </CardMoreMenu>
    )
  }

  function renderCatalogToolCard(tool: ToolSummary) {
    const Icon = kindIcon(tool.kind)
    const available = toolIsAvailable(tool)
    const selected = selectedToolIds.includes(tool.id)

    return (
      <ResourceCard
        key={tool.id}
        as="article"
        interactive
        selected={selected}
        pressed={isBatchManaging && tool.can_manage ? selected : undefined}
        onActivate={() => {
          if (isBatchManaging && tool.can_manage) {
            setSelectedToolIds((current) =>
              toggleResourceSelection(current, tool.id)
            )
            return
          }
          void openDetail(tool)
        }}
      >
        <ResourceCardHeader>
          <div className="flex min-w-0 gap-3">
            <ResourceCardIcon tone="sky">
              <BuiltinToolIcon
                functionName={tool.function_name}
                fallback={Icon}
                className="size-5"
              />
            </ResourceCardIcon>
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2">
                <ResourceCardTitle as="h3">
                  {displayToolName(tool)}
                </ResourceCardTitle>
                <Badge variant={available ? "secondary" : "outline"}>
                  {available ? t("可用") : t("不可用")}
                </Badge>
                {tool.permission ? (
                  <Badge variant="outline">
                    {t(permissionLabel(tool.permission))}
                  </Badge>
                ) : null}
              </div>
            </div>
          </div>
          {tool.can_manage ? (
            <ResourceCardActions>
              {isBatchManaging ? (
                <input
                  type="checkbox"
                  className="size-4 shrink-0 accent-primary"
                  aria-label={t("选择 {value}", {
                    value: displayToolName(tool),
                  })}
                  checked={selected}
                  onClick={(event) => event.stopPropagation()}
                  onChange={(event) =>
                    setSelectedToolIds((current) =>
                      event.target.checked
                        ? [...current, tool.id]
                        : current.filter((id) => id !== tool.id)
                    )
                  }
                />
              ) : null}
              {renderToolManagementMenu(tool)}
            </ResourceCardActions>
          ) : null}
        </ResourceCardHeader>

        <p className="mt-3 line-clamp-2 text-sm leading-5 text-muted-foreground">
          {displayToolDescription(tool) || t("暂无描述")}
        </p>
        {tool.updated_at ? (
          <ResourceCardMeta>
            {t("更新时间")} · {formatDateTime(tool.updated_at, locale)}
          </ResourceCardMeta>
        ) : null}

        <ResourceCardFooter>
          <ResourceCardSpecs>
            <Spec label={t("类型")} value={t(kindLabel(tool.kind))} />
            <Spec label={t("来源")} value={displaySourceName(tool)} />
          </ResourceCardSpecs>
        </ResourceCardFooter>
      </ResourceCard>
    )
  }
  return (
    <main className="min-w-0 space-y-6">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <h1 className="text-2xl font-semibold">{t("工具")}</h1>
          <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
            {t("管理自己的 MCP 与 Skills；共享给你的资源可按授权使用。")}
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
            <DropdownMenuItem onSelect={() => setMcpDialogOpen(true)}>
              <NetworkIcon />
              {t("MCP Server")}
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuItem onSelect={() => setSkillDialogOpen(true)}>
              <SparklesIcon />
              {t("Skills")}
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>

      <ResourceFolderLayout
        sidebar={
          <ResourceFolderTree
            folders={resourceFolders.folders}
            selectedFolderId={resourceFolders.selectedFolderId}
            canManageAllFolders={me?.user.is_global_admin ?? false}
            currentUserId={me?.user.id ?? null}
            isLoading={resourceFolders.isLoading}
            onSelect={resourceFolders.setSelectedFolderId}
            onCreate={resourceFolders.create}
            onRename={resourceFolders.rename}
            onDelete={resourceFolders.remove}
            onFolderDeleted={(folderId, parentId) =>
              setTools((current) =>
                current.map((tool) =>
                  tool.folder_id === folderId
                    ? { ...tool, folder_id: parentId }
                    : tool
                )
              )
            }
          />
        }
      >
        <div
          role="search"
          className="flex flex-col gap-3 rounded-lg border bg-background p-3 shadow-sm sm:flex-row sm:items-center sm:justify-between"
        >
          <div className="flex min-w-0 flex-col gap-2 sm:flex-row">
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
            <FilterDropdown
              ariaLabel={t("排序")}
              value={toolSortKey}
              options={[
                { value: "updated_at", label: t("最近更新") },
                { value: "created_at", label: t("创建时间") },
                { value: "name", label: t("名称") },
              ]}
              className="h-9 sm:w-32"
              onChange={(value) => setToolSortKey(value as ToolSortKey)}
            />
          </div>
          {movableToolIds.length || initialKind ? (
            <div className="flex flex-wrap items-center justify-end gap-2 max-sm:w-full max-sm:justify-between sm:gap-3">
              <ResourceBulkMoveBar
                resourceIds={movableToolIds}
                selectedIds={selectedToolIds}
                isManaging={isBatchManaging}
                onSelectedIdsChange={setSelectedToolIds}
                onManagingChange={setIsBatchManaging}
                onMove={() => setIsBatchMoveOpen(true)}
              />
              {initialKind ? (
                <div
                  role="group"
                  aria-label={t("工具")}
                  className="grid w-fit shrink-0 grid-cols-2 gap-0.5 rounded-lg bg-muted/70 p-0.5 max-sm:w-full sm:h-[var(--theme-control-large-height)]"
                >
                  {catalogTabs.map((tab) => {
                    const isActive = activeKind === tab.kind

                    return (
                      <button
                        key={tab.kind}
                        type="button"
                        aria-pressed={isActive}
                        className={`inline-flex min-w-18 items-center justify-center rounded-md px-3 text-sm font-medium whitespace-nowrap transition-[background-color,color,box-shadow] duration-150 outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1 focus-visible:ring-offset-background motion-reduce:transition-none max-sm:h-11 ${
                          isActive
                            ? "bg-background text-foreground shadow-xs"
                            : "text-muted-foreground hover:bg-background/60 hover:text-foreground"
                        }`}
                        onClick={() => setActiveKind(tab.kind)}
                      >
                        {t(tab.label)}
                      </button>
                    )
                  })}
                </div>
              ) : null}
            </div>
          ) : null}
        </div>

        {!isLoading && !error && mcpGroups.length ? (
          <section aria-labelledby="tool-source-group">
            <div className="mb-3 flex items-center gap-2">
              <h2 id="tool-source-group" className="text-sm font-semibold">
                {t("MCP 工具")}
              </h2>
              <Badge variant="secondary">{mcpGroups.length}</Badge>
            </div>
            <div className={resourceCardGridClass}>
              {mcpGroups.map(({ source, tools: sourceTools }) => {
                const detail = sources.find((item) => item.id === source.id)
                const manageableTools = sourceTools.filter(
                  (tool) => tool.can_manage
                )
                const selected =
                  manageableTools.length > 0 &&
                  manageableTools.every((tool) =>
                    selectedToolIds.includes(tool.id)
                  )
                return (
                  <ResourceCard
                    key={source.id}
                    as="article"
                    aria-label={source.name}
                    selected={selected}
                  >
                    <ResourceCardHeader>
                      <div className="flex min-w-0 items-center gap-3">
                        <ResourceCardIcon tone="sky">
                          <NetworkIcon className="size-5" />
                        </ResourceCardIcon>
                        <div className="min-w-0">
                          <ResourceCardTitle as="h3">
                            {source.name}
                          </ResourceCardTitle>
                          <p className="mt-1 text-xs text-muted-foreground">
                            {t("MCP 工具")}
                          </p>
                        </div>
                      </div>
                      <ResourceCardActions>
                        {isBatchManaging && manageableTools.length ? (
                          <input
                            type="checkbox"
                            className="size-4 shrink-0 accent-primary"
                            aria-label={t("选择 {value}", {
                              value: source.name,
                            })}
                            checked={selected}
                            ref={(element) => {
                              if (element)
                                element.indeterminate =
                                  !selected &&
                                  manageableTools.some((tool) =>
                                    selectedToolIds.includes(tool.id)
                                  )
                            }}
                            onChange={(event) =>
                              setSelectedToolIds((current) => {
                                const ids = new Set(
                                  manageableTools.map((tool) => tool.id)
                                )
                                return event.target.checked
                                  ? [...new Set([...current, ...ids])]
                                  : current.filter((id) => !ids.has(id))
                              })
                            }
                          />
                        ) : null}
                        {detail || manageableTools.length ? (
                          <CardMoreMenu
                            label={t("管理来源 {name}", { name: source.name })}
                          >
                            {manageableTools.length ? (
                              <DropdownMenuItem
                                onSelect={() => setManagedSourceId(source.id)}
                              >
                                <WrenchIcon />
                                {t("管理工具")}
                              </DropdownMenuItem>
                            ) : null}
                            {detail?.mcp_server_id &&
                            detail.transport !== "stdio" ? (
                              <>
                                <DropdownMenuItem
                                  onSelect={() => setOAuthSource(detail)}
                                >
                                  {t("OAuth 连接")}
                                </DropdownMenuItem>
                                <DropdownMenuItem
                                  onSelect={() => setTaskSource(detail)}
                                >
                                  {t("长任务契约")}
                                </DropdownMenuItem>
                              </>
                            ) : null}
                            {detail ? (
                              <>
                                <DropdownMenuItem
                                  disabled={Boolean(busyId)}
                                  onSelect={() => void refreshSource(detail)}
                                >
                                  <RefreshCwIcon />
                                  {t("刷新工具")}
                                </DropdownMenuItem>
                                <DropdownMenuItem
                                  disabled={Boolean(busyId)}
                                  onSelect={() => void toggleSource(detail)}
                                >
                                  <PowerIcon />
                                  {detail.status === "active"
                                    ? t("禁用")
                                    : t("启用")}
                                </DropdownMenuItem>
                                <DropdownMenuSeparator />
                                <DropdownMenuItem
                                  variant="destructive"
                                  disabled={Boolean(busyId)}
                                  onSelect={() => void removeSource(detail)}
                                >
                                  <Trash2Icon />
                                  {t("删除来源")}
                                </DropdownMenuItem>
                              </>
                            ) : null}
                          </CardMoreMenu>
                        ) : null}
                      </ResourceCardActions>
                    </ResourceCardHeader>
                    {detail ? (
                      <div className="mt-3 flex flex-wrap items-center gap-2">
                        <Badge
                          variant={
                            detail.status === "active" ? "secondary" : "outline"
                          }
                        >
                          {detail.status === "active"
                            ? t("可用")
                            : t("来源已禁用")}
                        </Badge>
                        <Badge variant="outline">
                          {t(transportLabel(detail.transport))}
                        </Badge>
                        <Badge variant="outline">
                          {t("{value} 个工具", { value: detail.tool_count })}
                        </Badge>
                      </div>
                    ) : null}
                    {detail?.last_error ? (
                      <p className="mt-2 max-h-40 overflow-y-auto whitespace-pre-wrap break-words text-xs text-destructive [overflow-wrap:anywhere]">
                        {getErrorMessage(new Error(detail.last_error), t)}
                      </p>
                    ) : null}
                  </ResourceCard>
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
        ) : isSkillsTab ? (
          query &&
          builtinSkillTools.length === 0 &&
          builtinTools.length === 0 &&
          filteredWorkspaceSkills.length === 0 ? (
            <div className="flex min-h-52 items-center justify-center rounded-xl border border-dashed text-sm text-muted-foreground">
              {t("没有匹配的工具")}
            </div>
          ) : (
            <div className="space-y-8">
              {builtinTools.length ? (
                <section aria-labelledby="builtin-tools-heading">
                  <div className="mb-3 flex items-center gap-2">
                    <h2
                      id="builtin-tools-heading"
                      className="text-sm font-semibold"
                    >
                      {t("内置工具")}
                    </h2>
                    <Badge variant="secondary">{builtinTools.length}</Badge>
                  </div>
                  <div className={resourceCardGridClass}>
                    {builtinTools.map((tool) => (
                      <ResourceCard
                        key={tool.id}
                        as="article"
                        interactive
                        onActivate={() => void openDetail(tool)}
                      >
                        <span className="flex min-w-0 items-center gap-3">
                          <ResourceCardIcon>
                            <BuiltinToolIcon
                              functionName={tool.function_name}
                              className="size-5"
                            />
                          </ResourceCardIcon>
                          <span className="truncate text-sm font-semibold">
                            {displayToolName(tool)}
                          </span>
                        </span>
                        <span className="mt-3 line-clamp-2 text-sm text-muted-foreground">
                          {displayToolDescription(tool) || t("暂无描述")}
                        </span>
                      </ResourceCard>
                    ))}
                  </div>
                </section>
              ) : null}
              <section aria-labelledby="builtin-skills-heading">
                <div className="mb-3 flex items-center gap-2">
                  <h2
                    id="builtin-skills-heading"
                    className="text-sm font-semibold"
                  >
                    {t("内置 Skills")}
                  </h2>
                  <Badge variant="secondary">{builtinSkillTools.length}</Badge>
                </div>
                {builtinSkillTools.length ? (
                  <div className={resourceCardGridClass}>
                    {builtinSkillTools.map((tool) => (
                      <ResourceCard
                        key={tool.id}
                        as="article"
                        interactive
                        onActivate={() => void openDetail(tool)}
                      >
                        <div className="flex min-w-0 gap-3">
                          <ResourceCardIcon>
                            <BuiltinToolIcon
                              functionName={tool.function_name}
                              className="size-5"
                            />
                          </ResourceCardIcon>
                          <div className="min-w-0">
                            <ResourceCardTitle as="h3">
                              {displayToolName(tool)}{" "}
                              <span className="font-normal text-muted-foreground">
                                {t("Skill")}
                              </span>
                            </ResourceCardTitle>
                          </div>
                        </div>
                        <p className="mt-3 line-clamp-2 text-sm leading-5 text-muted-foreground">
                          {displayToolDescription(tool) || t("暂无描述")}
                        </p>
                      </ResourceCard>
                    ))}
                  </div>
                ) : (
                  <div className="flex min-h-24 items-center justify-center rounded-xl border border-dashed text-sm text-muted-foreground">
                    {t("没有匹配的工具")}
                  </div>
                )}
              </section>
              <section aria-labelledby="workspace-skills-heading">
                <div className="mb-3 flex items-center gap-2">
                  <h2
                    id="workspace-skills-heading"
                    className="text-sm font-semibold"
                  >
                    {t("自定义 Skills")}
                  </h2>
                  <Badge variant="secondary">
                    {filteredWorkspaceSkills.length}
                  </Badge>
                </div>
                {filteredWorkspaceSkills.length ? (
                  <div className={resourceCardGridClass}>
                    {filteredWorkspaceSkills.map((skill) => (
                      <ResourceCard
                        key={skill.id}
                        as="article"
                        className="gap-0"
                      >
                        <Button
                          variant="ghost"
                          className="h-auto max-w-full min-w-0 justify-start px-0 py-0 text-left text-sm font-semibold [overflow-wrap:anywhere] break-words whitespace-normal"
                          onClick={() => {
                            setEditingSkill(skill)
                            setSkillDialogOpen(true)
                          }}
                        >
                          {skill.name}
                        </Button>
                        <p
                          title={skill.description}
                          className="mt-1 line-clamp-2 text-sm break-words text-muted-foreground"
                        >
                          {skill.description}
                        </p>
                        <div className="mt-auto flex flex-wrap items-center gap-2 pt-3">
                          {!skill.can_manage ? (
                            <Badge variant="outline">{t("共享给我的")}</Badge>
                          ) : null}
                          <Badge variant="secondary">
                            {skill.status === "disabled"
                              ? t("已停用")
                              : skill.current_version_number
                                ? `${t("已发布版本")} ${skill.current_version_number}`
                                : t("草稿")}
                          </Badge>
                          {skill.can_manage ? (
                            <Button
                              variant="outline"
                              size="sm"
                              disabled={busyId !== null}
                              onClick={() => void removeSkill(skill)}
                            >
                              <Trash2Icon />
                              {t("删除")}
                            </Button>
                          ) : null}
                          {skill.can_manage ? (
                            <Button
                              variant="outline"
                              size="sm"
                              disabled={busyId === skill.id}
                              onClick={async () => {
                                setBusyId(skill.id)
                                try {
                                  await updateAgentSkill(
                                    accessToken,
                                    workspaceId,
                                    skill.id,
                                    {
                                      status:
                                        skill.status === "active"
                                          ? "disabled"
                                          : "active",
                                    }
                                  )
                                  await load()
                                } catch (cause) {
                                  message("error", getErrorMessage(cause, t))
                                } finally {
                                  setBusyId(null)
                                }
                              }}
                            >
                              {skill.status === "active"
                                ? t("停用")
                                : t("启用")}
                            </Button>
                          ) : null}
                        </div>
                      </ResourceCard>
                    ))}
                  </div>
                ) : (
                  <div className="flex min-h-36 flex-col items-center justify-center rounded-xl border border-dashed bg-muted/20 px-6 text-center">
                    <p className="font-medium">
                      {workspaceSkills.length
                        ? t("没有匹配的 Skill")
                        : t("还没有可用的 Skill")}
                    </p>
                    <p className="mt-1 max-w-md text-sm text-muted-foreground">
                      {t("从添加工具新建或导入 Skill。")}
                    </p>
                    <Button
                      className="mt-4"
                      type="button"
                      onClick={() => setSkillDialogOpen(true)}
                    >
                      <SparklesIcon />
                      {t("新建 Skill")}
                    </Button>
                  </div>
                )}
              </section>
            </div>
          )
        ) : catalogTools.length === 0 && catalogSources.length === 0 ? (
          <div className="flex min-h-72 flex-col items-center justify-center rounded-xl border border-dashed bg-muted/20 px-6 text-center">
            <span className="flex size-12 items-center justify-center rounded-xl bg-muted text-muted-foreground">
              <WrenchIcon className="size-5" />
            </span>
            <p className="mt-4 font-medium">{t("还没有工具")}</p>
            <p className="mt-1 max-w-md text-sm text-muted-foreground">
              {t("连接 MCP Server 后，可授权给 Agent 与 Workflow 使用。")}
            </p>
          </div>
        ) : filteredTools.length === 0 && mcpGroups.length === 0 ? (
          <div className="flex min-h-52 items-center justify-center rounded-xl border border-dashed text-sm text-muted-foreground">
            {t("没有匹配的工具")}
          </div>
        ) : (
          <div className={resourceCardGridClass}>
            {flatTools.map((tool) => renderCatalogToolCard(tool))}
          </div>
        )}
      </ResourceFolderLayout>

      <Dialog
        open={managedSourceId !== null}
        onOpenChange={(open) => !open && setManagedSourceId(null)}
      >
        <DialogContent className="flex max-h-[80svh] flex-col overflow-hidden">
          <DialogHeader>
            <DialogTitle className="break-words">
              {t("管理 {name} 的工具", { name: managedSourceName })}
            </DialogTitle>
            <DialogDescription>
              {t("按工具管理权限与执行策略。")}
            </DialogDescription>
          </DialogHeader>
          <div className="min-h-0 divide-y overflow-y-auto">
            {managedTools.map((tool) => (
              <div
                key={tool.id}
                className="flex flex-wrap items-center gap-2 py-3"
              >
                <span className="min-w-0 flex-1 basis-32 truncate text-sm font-medium">
                  {displayToolName(tool)}
                </span>
                <Badge variant="outline">
                  {toolIsAvailable(tool) ? t("可用") : t("不可用")}
                </Badge>
                {tool.policy_mode ? (
                  <Badge variant="outline">
                    {t(
                      tool.policy_mode === "read_only"
                        ? "只读自动执行"
                        : tool.policy_mode === "disabled"
                          ? "工具调用已禁用"
                          : "每次调用前审批"
                    )}
                  </Badge>
                ) : null}
                {tool.availability === "unavailable" &&
                tool.status === "active" ? (
                  <Badge variant="outline">{t("上游未发现该工具")}</Badge>
                ) : null}
                {renderToolManagementMenu(tool)}
              </div>
            ))}
          </div>
        </DialogContent>
      </Dialog>

      <ResourceFolderPickerDialog
        open={isBatchMoveOpen}
        folders={resourceFolders.folders}
        currentFolderId={resourceFolders.selectedFolderId}
        onOpenChange={setIsBatchMoveOpen}
        onMove={async (folderId) => {
          const resourceIds = selectedToolIds.filter((id) =>
            movableToolIds.includes(id)
          )
          await resourceFolders.moveMany(resourceIds, folderId)
          setTools((current) =>
            current.map((tool) =>
              resourceIds.includes(tool.id)
                ? { ...tool, folder_id: folderId }
                : tool
            )
          )
          setSelectedToolIds([])
          setIsBatchManaging(false)
        }}
      />

      <ResourceFolderPickerDialog
        open={moveToolTarget !== null}
        folders={resourceFolders.folders}
        currentFolderId={moveToolTarget?.folder_id ?? null}
        onOpenChange={(open) => !open && setMoveToolTarget(null)}
        onMove={async (folderId) => {
          if (!moveToolTarget) return
          await resourceFolders.move(moveToolTarget.id, folderId)
          setTools((current) =>
            current.map((tool) =>
              tool.id === moveToolTarget.id
                ? { ...tool, folder_id: folderId }
                : tool
            )
          )
          setSelectedToolIds((current) =>
            current.filter((id) => id !== moveToolTarget.id)
          )
        }}
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
      {oauthSource?.mcp_server_id ? (
        <McpOAuthDialog
          key={oauthSource.id}
          token={accessToken}
          workspaceId={workspaceId}
          serverId={oauthSource.mcp_server_id}
          onClose={() => setOAuthSource(null)}
          onChanged={() => void load()}
        />
      ) : null}
      {taskSource?.mcp_server_id ? (
        <McpLongTasksDialog
          key={taskSource.id}
          token={accessToken}
          workspaceId={workspaceId}
          serverId={taskSource.mcp_server_id}
          onClose={() => setTaskSource(null)}
          onChanged={() => void load()}
        />
      ) : null}
      <SkillDialog
        key={`${workspaceId}:${editingSkill?.id ?? "new"}:${skillDialogOpen}`}
        open={skillDialogOpen}
        onOpenChange={(open) => {
          setSkillDialogOpen(open)
          if (!open) setEditingSkill(undefined)
        }}
        token={accessToken}
        workspaceId={workspaceId}
        skill={editingSkill}
        onSaved={() => void load()}
        returnFocusRef={addToolTriggerRef}
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
        <DialogContent
          className={cn(
            "flex max-h-[calc(100dvh-2rem)] min-w-0 flex-col gap-0 overflow-hidden p-0",
            skillMarkdown ? "max-w-4xl" : "max-w-2xl"
          )}
        >
          <IconButton
            label={t("关闭")}
            className="absolute top-4 right-4 z-20 text-muted-foreground hover:text-foreground sm:top-5 sm:right-5"
            onClick={() => {
              setDetailTarget(null)
              setDetailTool(null)
              setDetailError(null)
            }}
          >
            <XIcon />
          </IconButton>
          <DialogHeader className="min-w-0 shrink-0 border-b bg-muted/20 px-5 py-5 pr-16 sm:px-8 sm:py-6 sm:pr-20">
            {skillMarkdown ? (
              <div className="flex items-start gap-3">
                <span className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-muted/70">
                  <BuiltinToolIcon
                    functionName={detailFunctionName}
                    className="size-6"
                  />
                </span>
                <div className="min-w-0 flex-1">
                  <DialogTitle className="text-lg leading-7">
                    {detailTool
                      ? displayToolName(detailTool)
                      : detailTarget
                        ? displayToolName(detailTarget)
                        : t("工具详情")}{" "}
                    <span className="text-sm font-normal text-muted-foreground">
                      {t("Skill")}
                    </span>
                  </DialogTitle>
                  <DialogDescription className="mt-1 leading-6 [overflow-wrap:anywhere]">
                    {detailTool
                      ? displayToolDescription(detailTool)
                      : detailTarget
                        ? displayToolDescription(detailTarget)
                        : ""}
                  </DialogDescription>
                </div>
              </div>
            ) : (
              <>
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
              </>
            )}
          </DialogHeader>
          <div className="min-h-0 min-w-0 flex-1 overflow-x-hidden overflow-y-auto overscroll-contain px-5 py-6 sm:px-8 sm:py-8">
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
            ) : detailTool && skillMarkdown ? (
              <article className="mx-auto max-w-[76ch] min-w-0">
                <MarkdownContent
                  content={skillMarkdown}
                  className="leading-7 [overflow-wrap:anywhere] [&_h1]:mb-5 [&_h1]:text-xl [&_h1]:leading-8 [&_h2]:mt-8 [&_h2]:text-base [&_h2]:leading-7 [&_h2:first-child]:mt-0 [&_h3]:mt-6 [&_li]:my-1.5 [&_p]:my-3"
                />
              </article>
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
                  <h3 className="mb-2 text-sm font-medium">
                    {t("输入 Schema")}
                  </h3>
                  <pre className="max-h-64 overflow-auto rounded-lg bg-muted p-3 text-xs">
                    {JSON.stringify(detailTool.input_schema ?? {}, null, 2)}
                  </pre>
                </div>
                <div>
                  <h3 className="mb-2 text-sm font-medium">
                    {t("输出 Schema")}
                  </h3>
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
          </div>
        </DialogContent>
      </Dialog>
      {confirmDialog}
    </main>
  )
}
