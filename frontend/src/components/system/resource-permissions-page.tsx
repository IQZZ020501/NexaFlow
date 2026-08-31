"use client"

import * as React from "react"
import { useRouter } from "next/navigation"
import {
  BookOpenIcon,
  BoxesIcon,
  CheckIcon,
  ChevronDownIcon,
  LoaderCircleIcon,
  SparklesIcon,
  UserRoundIcon,
  WrenchIcon,
} from "lucide-react"

import { StatusBadge } from "@/components/knowledge/status-badges"
import { Badge } from "@/components/ui/badge"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { FilterDropdown } from "@/components/app/filter-dropdown"
import { useLanguage } from "@/contexts/language-provider"
import { useSession } from "@/contexts/session-context"
import {
  grantAgentPermission,
  listAgentPermissions,
  listAllAgents,
  revokeAgentPermission,
  type Agent,
} from "@/lib/api/agents"
import {
  listKnowledgeBasePermissions,
  listKnowledgeBases,
  revokeKnowledgeBasePermission,
  upsertKnowledgeBasePermission,
  type KnowledgeBaseListItem,
} from "@/lib/api/knowledge"
import {
  listAllToolPermissions,
  listAllTools,
  revokeToolPermission,
  setToolPermission,
  type ToolSummary,
} from "@/lib/api/tools"
import {
  listAllWorkspaceMembers,
  type WorkspaceMember,
} from "@/lib/api/system"
import { displayWorkspaceName, getMembershipRole } from "@/lib/display"
import { getErrorMessage } from "@/lib/errors"
import { ApiError } from "@/lib/api-client"
import type { TFunction } from "@/i18n"
import { toolDisplayDescription, toolDisplayName } from "@/lib/tool-display"
import { cn } from "@/lib/utils"

export type ResourcePermissionPageType = "apps" | "knowledge" | "tools"
type PermissionValue = "none" | "view" | "manage"

type ResourceRow = {
  id: string
  name: string
  description: string
  status: string
  ownerId: string | null
}

const PAGE_CONFIG = {
  apps: { label: "应用", icon: SparklesIcon, color: "text-violet-600" },
  knowledge: { label: "知识库", icon: BookOpenIcon, color: "text-blue-600" },
  tools: { label: "工具", icon: WrenchIcon, color: "text-emerald-600" },
} as const

const RESOURCE_PERMISSION_TYPES: ResourcePermissionPageType[] = [
  "apps",
  "knowledge",
  "tools",
]

export function ResourcePermissionNavGroup({
  activeType,
  onSelect,
}: {
  activeType?: ResourcePermissionPageType
  onSelect: (type: ResourcePermissionPageType) => void
}) {
  const { t } = useLanguage()

  return (
    <details className="group" open={Boolean(activeType)}>
      <summary
        className={cn(
          "flex min-w-32 cursor-pointer list-none items-center justify-between gap-2 rounded-md px-3 py-1.5 text-left text-sm font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground lg:min-w-0 [&::-webkit-details-marker]:hidden",
          activeType &&
            "bg-foreground text-background hover:bg-foreground hover:text-background"
        )}
      >
        <span className="flex min-w-0 items-center gap-2">
          <BoxesIcon className="size-4 shrink-0" />
          <span>{t("资源授权")}</span>
        </span>
        <ChevronDownIcon className="size-4 shrink-0 transition-transform group-open:rotate-180" />
      </summary>
      <div className="mt-1 space-y-0.5 border-l pl-3 lg:ml-3">
        {RESOURCE_PERMISSION_TYPES.map((type) => {
          const config = PAGE_CONFIG[type]
          const Icon = config.icon
          return (
            <button
              key={type}
              type="button"
              onClick={() => onSelect(type)}
              className={cn(
                "flex w-full items-center justify-start gap-2 rounded-md px-3 py-2 text-sm text-muted-foreground transition-colors hover:bg-muted hover:text-foreground",
                activeType === type && "bg-primary/10 text-primary"
              )}
            >
              <Icon className="size-4 shrink-0" />
              <span>{t(config.label)}</span>
            </button>
          )
        })}
      </div>
    </details>
  )
}

function rowsForApps(items: Agent[]): ResourceRow[] {
  return items.map((item) => ({
    id: item.id,
    name: item.name,
    description: item.description,
    status: item.status,
    ownerId: item.created_by_user_id,
  }))
}

function rowsForKnowledge(items: KnowledgeBaseListItem[]): ResourceRow[] {
  return items.map((item) => ({
    id: item.id,
    name: item.name,
    description: item.description,
    status: item.status,
    ownerId: item.created_by_user_id,
  }))
}

function rowsForTools(items: ToolSummary[], t: TFunction): ResourceRow[] {
  return items.map((item) => ({
    id: item.id,
    name: toolDisplayName(item, t),
    description: toolDisplayDescription(item, t),
    status: item.status,
    ownerId: item.created_by_user_id,
  }))
}

function permissionLabel(value: PermissionValue, t: TFunction) {
  if (value === "manage") return t("管理")
  if (value === "view") return t("查看")
  return t("不授权")
}

export function ResourcePermissionsPage({
  type,
}: {
  type: ResourcePermissionPageType
}) {
  const { t } = useLanguage()
  const session = useSession()
  const router = useRouter()
  const config = PAGE_CONFIG[type]
  const ResourceIcon = config.icon
  const [resources, setResources] = React.useState<ResourceRow[]>([])
  const [resourcesType, setResourcesType] =
    React.useState<ResourcePermissionPageType>(type)
  const [members, setMembers] = React.useState<WorkspaceMember[]>([])
  const [selectedMemberId, setSelectedMemberId] = React.useState<string | null>(
    null
  )
  const [permissionByResource, setPermissionByResource] = React.useState<
    Record<string, PermissionValue>
  >({})
  const [memberSearch, setMemberSearch] = React.useState("")
  const [isLoading, setIsLoading] = React.useState(true)
  const [isPermissionsLoading, setIsPermissionsLoading] = React.useState(false)
  const [busyResourceId, setBusyResourceId] = React.useState<string | null>(
    null
  )
  const [error, setError] = React.useState<string | null>(null)
  const resourcesRequestRef = React.useRef(0)
  const permissionsRequestRef = React.useRef(0)

  const manageableWorkspaces = React.useMemo(() => {
    const me = session.me
    if (!me) return []
    return session.workspaces.filter(
      (workspace) =>
        workspace.status === "active" &&
        (me.user.is_global_admin
          ? true
          : workspace.id === session.selectedWorkspaceId &&
            getMembershipRole(me, workspace.id) === "admin")
    )
  }, [session.me, session.selectedWorkspaceId, session.workspaces])
  const selectedWorkspaceId = session.selectedWorkspaceId
  const selectedWorkspace =
    manageableWorkspaces.find(
      (workspace) => workspace.id === selectedWorkspaceId
    ) ??
    manageableWorkspaces[0] ??
    null
  const canManage = Boolean(
    session.me &&
    selectedWorkspace &&
    (session.me.user.is_global_admin ||
      getMembershipRole(session.me, selectedWorkspace.id) === "admin")
  )

  React.useEffect(() => {
    if (
      session.isSessionRestored &&
      !session.isSessionLoading &&
      session.me &&
      !canManage
    ) {
      router.replace("/app/apps")
    }
  }, [
    canManage,
    router,
    session.isSessionLoading,
    session.isSessionRestored,
    session.me,
  ])

  const loadResources = React.useCallback(async () => {
    const requestId = ++resourcesRequestRef.current
    permissionsRequestRef.current += 1
    setResources([])
    setResourcesType(type)
    setMembers([])
    setSelectedMemberId(null)
    setPermissionByResource({})
    if (!session.token || !selectedWorkspace || !canManage) return
    setIsLoading(true)
    setError(null)
    try {
      const [nextResources, nextMembers] = await Promise.all([
        type === "apps"
          ? listAllAgents(session.token, selectedWorkspace.id).then(rowsForApps)
          : type === "knowledge"
            ? listKnowledgeBases(session.token, selectedWorkspace.id, {
                limit: 200,
              }).then(rowsForKnowledge)
            : listAllTools(session.token, selectedWorkspace.id).then((items) =>
                rowsForTools(items, t)
              ),
        listAllWorkspaceMembers(session.token, selectedWorkspace.id),
      ])
      const activeMembers = nextMembers.filter(
        (member) => member.user.is_active
      )
      if (requestId !== resourcesRequestRef.current) return
      setResources(nextResources)
      setResourcesType(type)
      setMembers(activeMembers)
      setSelectedMemberId((current) =>
        current && activeMembers.some((member) => member.user.id === current)
          ? current
          : (activeMembers[0]?.user.id ?? null)
      )
    } catch (cause) {
      if (requestId !== resourcesRequestRef.current) return
      setResources([])
      setMembers([])
      setSelectedMemberId(null)
      setError(getErrorMessage(cause, t))
    } finally {
      if (requestId === resourcesRequestRef.current) setIsLoading(false)
    }
  }, [canManage, selectedWorkspace, session.token, t, type])

  React.useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void loadResources()
    return () => {
      resourcesRequestRef.current += 1
    }
  }, [loadResources])

  const selectedMember =
    members.find((member) => member.user.id === selectedMemberId) ?? null

  const loadPermissions = React.useCallback(async () => {
    const requestId = ++permissionsRequestRef.current
    if (!session.token || !selectedWorkspace || !selectedMember) {
      setPermissionByResource({})
      return
    }
    if (resourcesType !== type) {
      // resources still belong to the previously active tab; the type switch
      // is in flight and would otherwise hit the wrong endpoint with stale ids.
      setPermissionByResource({})
      return
    }
    setIsPermissionsLoading(true)
    try {
      // One request per resource because the existing API has no bulk
      // permission endpoint; add a bulk endpoint when the catalog grows
      // beyond practical page sizes.
      const entries: Array<readonly [string, PermissionValue]> = []
      const staleIds: string[] = []
      await Promise.all(
        resources.map(async (resource) => {
          try {
            const permissions =
              type === "apps"
                ? await listAgentPermissions(
                    session.token!,
                    selectedWorkspace.id,
                    resource.id
                  )
                : type === "knowledge"
                  ? await listKnowledgeBasePermissions(
                      session.token!,
                      selectedWorkspace.id,
                      resource.id
                    )
                  : await listAllToolPermissions(
                      session.token!,
                      selectedWorkspace.id,
                      resource.id
                    )
            const grant = permissions.find(
              (permission) => permission.user.id === selectedMember.user.id
            )
            const value: PermissionValue =
              selectedMember.role === "admin" ||
              resource.ownerId === selectedMember.user.id
                ? "manage"
                : !grant
                  ? "none"
                  : type === "knowledge" && grant.permission === "edit"
                    ? "manage"
                    : "view"
            entries.push([resource.id, value] as const)
          } catch (cause) {
      if (cause instanceof ApiError && cause.status === 404) {
              // The resource was deleted after the list loaded; drop it
              // instead of failing the whole permission table.
              staleIds.push(resource.id)
            } else {
              throw cause
            }
          }
        })
      )
      if (requestId === permissionsRequestRef.current) {
        if (staleIds.length) {
          const stale = new Set(staleIds)
          setResources((current) =>
            current.filter((resource) => !stale.has(resource.id))
          )
          session.notify("info", t("部分资源已不存在，已从列表移除"))
        }
        setPermissionByResource(Object.fromEntries(entries))
      }
    } catch (cause) {
      if (requestId === permissionsRequestRef.current) {
        setPermissionByResource({})
        session.notify("error", getErrorMessage(cause, t))
      }
    } finally {
      if (requestId === permissionsRequestRef.current) {
        setIsPermissionsLoading(false)
      }
    }
  }, [resources, resourcesType, selectedMember, selectedWorkspace, session, t, type])

  React.useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void loadPermissions()
    return () => {
      permissionsRequestRef.current += 1
    }
  }, [loadPermissions])

  const filteredMembers = members.filter((member) =>
    `${member.user.name} ${member.user.username} ${member.user.email}`
      .toLowerCase()
      .includes(memberSearch.trim().toLowerCase())
  )

  async function updatePermission(
    resource: ResourceRow,
    value: PermissionValue
  ) {
    if (
      !session.token ||
      !selectedWorkspace ||
      !selectedMember ||
      busyResourceId
    )
      return
    if (
      selectedMember.role === "admin" ||
      resource.ownerId === selectedMember.user.id
    )
      return
    if (type === "apps" && value === "manage") return
    setBusyResourceId(resource.id)
    try {
      if (value === "none") {
        if (type === "apps")
          await revokeAgentPermission(
            session.token,
            selectedWorkspace.id,
            resource.id,
            selectedMember.user.id
          )
        else if (type === "knowledge")
          await revokeKnowledgeBasePermission(
            session.token,
            selectedWorkspace.id,
            resource.id,
            selectedMember.user.id
          )
        else
          await revokeToolPermission(
            session.token,
            selectedWorkspace.id,
            resource.id,
            selectedMember.user.id
          )
      } else if (type === "apps") {
        await grantAgentPermission(
          session.token,
          selectedWorkspace.id,
          resource.id,
          selectedMember.user.id
        )
      } else if (type === "knowledge") {
        await upsertKnowledgeBasePermission(
          session.token,
          selectedWorkspace.id,
          resource.id,
          selectedMember.user.id,
          value === "manage" ? "edit" : "view"
        )
      } else {
        await setToolPermission(
          session.token,
          selectedWorkspace.id,
          resource.id,
          selectedMember.user.id,
          value === "manage" ? "use" : "view"
        )
      }
      setPermissionByResource((current) => ({
        ...current,
        [resource.id]: value,
      }))
      session.notify("success", t("资源授权已更新"))
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 404) {
        // The resource was deleted after the list loaded; drop it instead
        // of showing an error for a row that no longer exists.
        setResources((current) =>
          current.filter((item) => item.id !== resource.id)
        )
        session.notify("info", t("资源已不存在，已从列表移除"))
      } else {
        session.notify("error", getErrorMessage(cause, t))
      }
    } finally {
      setBusyResourceId(null)
    }
  }

  if (!session.me || !session.token || !canManage || !selectedWorkspace)
    return null

  return (
    <div className="w-full min-w-0">
      {error ? (
        <Card>
          <CardContent className="py-10 text-center text-sm text-destructive">
            {error}
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-4 lg:grid-cols-[250px_minmax(0,1fr)]">
          <aside className="min-w-0">
            <Card className="gap-4 py-5 lg:sticky lg:top-0">
              <CardHeader className="gap-1 px-5">
                <CardTitle className="flex items-center gap-2">
                  <UserRoundIcon className="size-4" />
                  {t("工作空间")}
                </CardTitle>
                <CardDescription>{t("选择工作空间下的用户")}</CardDescription>
              </CardHeader>
              <CardContent className="space-y-4 px-3">
                <FilterDropdown
                  ariaLabel={t("选择工作空间")}
                  value={selectedWorkspace.id}
                  onChange={session.selectWorkspace}
                  options={manageableWorkspaces.map((workspace) => ({
                    value: workspace.id,
                    label: displayWorkspaceName(workspace, t),
                  }))}
                  className="h-10 w-full justify-between px-3 font-normal"
                />
                <div className="border-t pt-4">
                  <p className="mb-2 px-3 text-xs font-medium text-muted-foreground">
                    {t("工作空间成员")}
                  </p>
                  <Input
                    value={memberSearch}
                    onChange={(event) => setMemberSearch(event.target.value)}
                    placeholder={t("搜索成员")}
                  />
                  <div className="mt-2 max-h-[calc(100svh-26rem)] space-y-1 overflow-y-auto">
                    {isLoading ? (
                      <div className="flex min-h-12 items-center justify-center gap-2 text-sm text-muted-foreground">
                        <LoaderCircleIcon className="size-4 animate-spin" />
                        {t("正在加载")}
                      </div>
                    ) : filteredMembers.length ? (
                      filteredMembers.map((member) => (
                        <button
                          key={member.user.id}
                          type="button"
                          className={cn(
                            "flex w-full items-center gap-2 rounded-md px-3 py-2 text-left transition-colors hover:bg-muted",
                            member.user.id === selectedMemberId &&
                              "bg-primary/10 text-primary"
                          )}
                          onClick={() => setSelectedMemberId(member.user.id)}
                        >
                          <span className="min-w-0 flex-1 truncate text-sm">
                            {member.user.name}
                            <span className="block truncate text-xs text-muted-foreground">
                              {member.user.username}
                            </span>
                          </span>
                          {member.role === "admin" ? (
                            <Badge variant="secondary">{t("管理员")}</Badge>
                          ) : null}
                        </button>
                      ))
                    ) : (
                      <p className="px-3 py-2 text-sm text-muted-foreground">
                        {t("暂无成员")}
                      </p>
                    )}
                  </div>
                </div>
              </CardContent>
            </Card>
          </aside>

          <Card className="min-w-0 gap-0 overflow-hidden py-0">
            <CardHeader className="gap-1 border-b px-5 py-5">
              <CardTitle className="flex items-center gap-2">
                <ResourceIcon className={cn("size-5", config.color)} />
                {t(config.label)}
              </CardTitle>
              <CardDescription>
                {selectedMember
                  ? `${selectedMember.user.name} / ${selectedMember.user.username}`
                  : t("选择用户")}
              </CardDescription>
            </CardHeader>
            <CardContent className="p-0">
              <div className="grid gap-2 border-b bg-muted/30 px-5 py-3 text-sm font-medium text-muted-foreground lg:grid-cols-[minmax(0,1fr)_minmax(250px,0.8fr)]">
                <span>{t("名称")}</span>
                <span>{t("权限")}</span>
              </div>
              {isLoading || isPermissionsLoading ? (
                <div className="flex min-h-48 items-center justify-center gap-2 text-sm text-muted-foreground">
                  <LoaderCircleIcon className="size-4 animate-spin" />
                  {t("正在加载")}
                </div>
              ) : resources.length ? (
                resources.map((resource) => {
                  const value = permissionByResource[resource.id] ?? "none"
                  const locked =
                    selectedMember?.role === "admin" ||
                    resource.ownerId === selectedMember?.user.id
                  const busy = busyResourceId === resource.id
                  return (
                    <div
                      key={resource.id}
                      className="grid items-center gap-4 border-b px-5 py-4 last:border-b-0 lg:grid-cols-[minmax(0,1fr)_minmax(250px,0.8fr)]"
                    >
                      <div className="min-w-0">
                        <p className="truncate text-sm font-medium">
                          {resource.name}
                        </p>
                        <p className="truncate text-xs text-muted-foreground">
                          {resource.description || t("暂无描述")}
                        </p>
                        {resource.status !== "active" ? (
                          <StatusBadge status={resource.status} />
                        ) : null}
                      </div>
                      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-sm">
                        {(["none", "view", "manage"] as PermissionValue[]).map(
                          (permission) => (
                            <label
                              key={permission}
                              className={cn(
                                "inline-flex items-center gap-2",
                                locked ||
                                  busy ||
                                  (type === "apps" && permission === "manage")
                                  ? "cursor-not-allowed opacity-60"
                                  : "cursor-pointer"
                              )}
                            >
                              <input
                                type="radio"
                                name={`${resource.id}-${selectedMember?.user.id}`}
                                checked={value === permission}
                                disabled={
                                  !selectedMember ||
                                  locked ||
                                  busy ||
                                  (type === "apps" && permission === "manage")
                                }
                                onChange={() =>
                                  void updatePermission(resource, permission)
                                }
                                className="size-4 accent-primary"
                              />
                              {permissionLabel(permission, t)}
                            </label>
                          )
                        )}
                        {busy ? (
                          <LoaderCircleIcon className="size-4 animate-spin text-muted-foreground" />
                        ) : locked ? (
                          <CheckIcon className="size-4 text-primary" />
                        ) : null}
                      </div>
                    </div>
                  )
                })
              ) : (
                <div className="py-16 text-center text-sm text-muted-foreground">
                  {t("暂无数据")}
                </div>
              )}
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  )
}
