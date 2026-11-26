import * as React from "react"
import {
  ChevronDownIcon,
  LoaderCircleIcon,
  RefreshCwIcon,
  SearchIcon,
  UserCogIcon,
  UserMinusIcon,
  UserPlusIcon,
} from "lucide-react"

import { useConfirmDialog } from "@/components/app/confirm-dialog"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { DisabledButtonHint } from "@/components/ui/disabled-button-hint"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { Input } from "@/components/ui/input"
import { TeamCandidateSearch } from "@/components/system/team-candidate-search"
import { useLanguage } from "@/contexts/language-provider"
import {
  addTeamMember,
  listTeamMembers,
  listWorkspaceMembers,
  removeTeamMember,
  updateTeamMember,
  type MeResponse,
  type Team,
  type TeamMember,
  type Workspace,
  type WorkspaceMember,
} from "@/lib/api/system"
import {
  displayTeamName,
  displayWorkspaceName,
  getMembershipRole,
} from "@/lib/display"
import { getErrorMessage } from "@/lib/errors"
import type { AppNotification } from "@/lib/notifications"
import { PHONE_LIST_QUERY, useMediaQuery } from "@/lib/use-media-query"
import { cn } from "@/lib/utils"

type TeamMembersPanelProps = {
  me: MeResponse
  token: string
  selectedWorkspace: Workspace | null
  managedTeams: Team[]
  isTeamsLoading: boolean
  onNotify: (kind: AppNotification["kind"], message: string) => void
}

/**
 * Direct system-settings panel for team administrators (and workspace/global
 * administrators when navigating directly to ``/system/team-members``) to view,
 * add, and remove members within their managed teams.
 */
export function TeamMembersPanel({
  me,
  token,
  selectedWorkspace,
  managedTeams,
  isTeamsLoading,
  onNotify,
}: TeamMembersPanelProps) {
  const { t } = useLanguage()
  const isPhoneListLayout = useMediaQuery(PHONE_LIST_QUERY)
  const [confirmAction, confirmDialog] = useConfirmDialog()
  const [selectedTeamId, setSelectedTeamId] = React.useState("")
  const [searchQuery, setSearchQuery] = React.useState("")
  const [members, setMembers] = React.useState<TeamMember[]>([])
  const [workspaceMembers, setWorkspaceMembers] = React.useState<
    WorkspaceMember[]
  >([])
  const [newUserId, setNewUserId] = React.useState("")
  const [newRole, setNewRole] = React.useState("member")
  const [loadedTeamId, setLoadedTeamId] = React.useState<string | null>(null)
  const [refreshTick, setRefreshTick] = React.useState(0)
  const [isRefreshing, setIsRefreshing] = React.useState(false)
  const [isMutating, setIsMutating] = React.useState(false)

  const selectedTeam = React.useMemo(() => {
    if (!managedTeams.length) {
      return null
    }
    return (
      managedTeams.find((team) => team.id === selectedTeamId) ??
      managedTeams.find((team) => team.status === "active") ??
      managedTeams[0]
    )
  }, [managedTeams, selectedTeamId])

  const canManageTeamAdmins = Boolean(
    selectedTeam &&
      (me.user.is_global_admin ||
        getMembershipRole(me, selectedTeam.workspace_id) === "admin")
  )
  const isTeamArchived = Boolean(selectedTeam && selectedTeam.status !== "active")
  const isLoading = Boolean(
    selectedTeam && (loadedTeamId !== selectedTeam.id || isRefreshing)
  )

  React.useEffect(() => {
    if (!selectedTeam) {
      return
    }
    let cancelled = false
    void Promise.all([
      listTeamMembers(token, selectedTeam.workspace_id, selectedTeam.id),
      listWorkspaceMembers(token, selectedTeam.workspace_id),
    ])
      .then(([nextMembers, nextCandidates]) => {
        if (cancelled) {
          return
        }
        setMembers(nextMembers)
        setWorkspaceMembers(nextCandidates)
      })
      .catch((error: unknown) => {
        if (cancelled) {
          return
        }
        setMembers([])
        setWorkspaceMembers([])
        onNotify("error", getErrorMessage(error, t))
      })
      .finally(() => {
        if (cancelled) {
          return
        }
        setLoadedTeamId(selectedTeam.id)
        setIsRefreshing(false)
      })
    return () => {
      cancelled = true
    }
  }, [onNotify, refreshTick, selectedTeam, t, token])

  const activeMembers = React.useMemo(
    () => (selectedTeam ? members : []),
    [members, selectedTeam]
  )
  const activeWorkspaceMembers = React.useMemo(
    () => (selectedTeam ? workspaceMembers : []),
    [selectedTeam, workspaceMembers]
  )
  const memberIds = React.useMemo(
    () => new Set(activeMembers.map((member) => member.user.id)),
    [activeMembers]
  )
  const candidates = React.useMemo(
    () =>
      activeWorkspaceMembers.filter(
        (member) =>
          member.user.is_active &&
          !memberIds.has(member.user.id) &&
          (canManageTeamAdmins || !member.user.is_global_admin)
      ),
    [activeWorkspaceMembers, canManageTeamAdmins, memberIds]
  )
  const filteredMembers = React.useMemo(() => {
    const query = searchQuery.trim().toLowerCase()
    if (!query) {
      return activeMembers
    }
    return activeMembers.filter((member) =>
      [member.user.name, member.user.username, member.user.email]
        .join(" ")
        .toLowerCase()
        .includes(query)
    )
  }, [activeMembers, searchQuery])

  const adminCount = activeMembers.filter((member) => member.role === "admin").length

  async function handleAddMember() {
    if (!selectedTeam || !newUserId || isTeamArchived) {
      return
    }
    setIsMutating(true)
    try {
      const created = await addTeamMember(
        token,
        selectedTeam.workspace_id,
        selectedTeam.id,
        {
          user_id: newUserId,
          role: canManageTeamAdmins ? newRole : "member",
        }
      )
      setMembers((current) => [...current, created])
      setNewUserId("")
      setNewRole("member")
      onNotify("success", t("团队成员已添加"))
    } catch (error) {
      onNotify("error", getErrorMessage(error, t))
    } finally {
      setIsMutating(false)
    }
  }

  async function handleUpdateRole(userId: string, role: string) {
    if (!selectedTeam || isTeamArchived) {
      return
    }
    setIsMutating(true)
    try {
      const updated = await updateTeamMember(
        token,
        selectedTeam.workspace_id,
        selectedTeam.id,
        userId,
        { role }
      )
      setMembers((current) =>
        current.map((item) => (item.user.id === userId ? updated : item))
      )
      onNotify("success", t("团队成员已更新"))
    } catch (error) {
      onNotify("error", getErrorMessage(error, t))
    } finally {
      setIsMutating(false)
    }
  }

  async function handleRemoveMember(member: TeamMember) {
    if (!selectedTeam || isTeamArchived) {
      return
    }
    if (
      !(await confirmAction({
        description: t("移除 {name}？", { name: member.user.name }),
        confirmLabel: t("移除"),
        destructive: true,
      }))
    ) {
      return
    }
    setIsMutating(true)
    try {
      await removeTeamMember(
        token,
        selectedTeam.workspace_id,
        selectedTeam.id,
        member.user.id
      )
      setMembers((current) =>
        current.filter((item) => item.user.id !== member.user.id)
      )
      onNotify("success", t("团队成员已移除"))
    } catch (error) {
      onNotify("error", getErrorMessage(error, t))
    } finally {
      setIsMutating(false)
    }
  }

  return (
    <>
      <div
        id="system-panel-team-members"
        role="tabpanel"
        aria-labelledby="system-tab-team-members"
        className="grid min-w-0 gap-4 lg:h-full lg:min-h-0 lg:overflow-hidden lg:pr-1"
      >
        <Card className="min-w-0 gap-3 overflow-hidden border-border/70 py-4 shadow-sm lg:flex lg:h-full lg:min-h-0 lg:flex-col">
          <CardHeader className="flex-row flex-wrap items-start justify-between gap-4 px-4">
            <div className="flex min-w-0 items-start gap-3">
              <span className="flex size-8 shrink-0 items-center justify-center rounded-lg border bg-background">
                <UserCogIcon className="size-4" />
              </span>
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <CardTitle>{t("团队成员")}</CardTitle>
                  {selectedTeam ? (
                    <Badge variant="outline">{activeMembers.length}</Badge>
                  ) : null}
                </div>
                <CardDescription>
                  {selectedTeam
                    ? `${displayTeamName(selectedTeam, t)}${
                        selectedWorkspace
                          ? ` · ${displayWorkspaceName(selectedWorkspace, t)}`
                          : ""
                      }`
                    : selectedWorkspace
                      ? displayWorkspaceName(selectedWorkspace, t)
                      : t("未选择工作空间")}
                </CardDescription>
              </div>
            </div>

            {selectedTeam ? (
              <div className="flex flex-wrap items-center gap-2 max-sm:w-full">
                {managedTeams.length > 1 ? (
                  <DropdownMenu modal={false}>
                    <DropdownMenuTrigger asChild>
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        aria-label={t("选择团队")}
                        className="max-w-56 justify-between gap-2"
                      >
                        <span className="truncate">
                          {displayTeamName(selectedTeam, t)}
                        </span>
                        <ChevronDownIcon className="size-4 shrink-0 text-muted-foreground" />
                      </Button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end" className="min-w-48">
                      {managedTeams.map((team) => (
                        <DropdownMenuItem
                          key={team.id}
                          onSelect={() => {
                            setSelectedTeamId(team.id)
                            setNewUserId("")
                            setNewRole("member")
                            setSearchQuery("")
                          }}
                        >
                          <span className="truncate">
                            {displayTeamName(team, t)}
                          </span>
                        </DropdownMenuItem>
                      ))}
                    </DropdownMenuContent>
                  </DropdownMenu>
                ) : null}
                <Button
                  type="button"
                  variant="outline"
                  size="icon-sm"
                  onClick={() => {
                    setIsRefreshing(true)
                    setRefreshTick((tick) => tick + 1)
                  }}
                  disabled={isLoading || isMutating}
                  aria-label={t("刷新")}
                  title={t("刷新")}
                >
                  <RefreshCwIcon
                    className={cn("size-4", isLoading && "animate-spin")}
                  />
                </Button>
              </div>
            ) : null}
          </CardHeader>

          <CardContent className="min-w-0 px-4 lg:flex lg:min-h-0 lg:flex-1 lg:flex-col lg:overflow-hidden">
            {isTeamsLoading ? (
              <div className="flex min-h-32 items-center justify-center">
                <LoaderCircleIcon className="animate-spin text-muted-foreground" />
              </div>
            ) : !selectedTeam ? (
              <div className="flex min-h-32 items-center justify-center rounded-lg border border-dashed bg-muted/20 px-4 text-center">
                <p className="text-sm text-muted-foreground">
                  {t("当前工作空间暂无您管理的团队")}
                </p>
              </div>
            ) : (
              <div className="flex min-h-0 flex-1 flex-col gap-3">
                {isTeamArchived ? (
                  <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-800 dark:text-amber-200">
                    {t("该团队已归档，恢复后方可调整成员")}
                  </div>
                ) : null}

                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="relative min-w-48 flex-1 max-sm:w-full">
                    <SearchIcon className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" />
                    <Input
                      className="pl-9"
                      value={searchQuery}
                      onChange={(event) => setSearchQuery(event.target.value)}
                      placeholder={t("搜索已有成员（姓名、账号、邮箱）")}
                      aria-label={t("搜索团队成员")}
                    />
                  </div>

                  <div className="flex flex-wrap items-center gap-2 max-sm:w-full">
                    <TeamCandidateSearch
                      ariaLabel={t("选择成员")}
                      candidates={candidates}
                      value={newUserId}
                      onChange={setNewUserId}
                      isLoading={isLoading}
                      disabled={isMutating || isTeamArchived}
                      className="min-w-56 max-sm:flex-1"
                    />

                    {canManageTeamAdmins ? (
                      <DropdownMenu modal={false}>
                        <DropdownMenuTrigger asChild>
                          <Button
                            type="button"
                            variant="outline"
                            size="sm"
                            className="h-9 min-w-24 justify-between px-3 font-normal"
                            disabled={isMutating || isTeamArchived}
                          >
                            {newRole === "admin" ? t("管理员") : t("成员")}
                            <ChevronDownIcon data-icon="inline-end" />
                          </Button>
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="end">
                          <DropdownMenuItem
                            onSelect={() => setNewRole("member")}
                          >
                            {t("成员")}
                          </DropdownMenuItem>
                          <DropdownMenuItem
                            onSelect={() => setNewRole("admin")}
                          >
                            {t("管理员")}
                          </DropdownMenuItem>
                        </DropdownMenuContent>
                      </DropdownMenu>
                    ) : null}

                    <Button
                      type="button"
                      size="sm"
                      disabled={
                        !newUserId || isLoading || isMutating || isTeamArchived
                      }
                      onClick={() => void handleAddMember()}
                    >
                      {isMutating ? (
                        <LoaderCircleIcon className="size-4 animate-spin" />
                      ) : (
                        <UserPlusIcon data-icon="inline-start" />
                      )}
                      {t("添加成员")}
                    </Button>
                  </div>
                </div>

                {isLoading ? (
                  <div className="flex min-h-32 items-center justify-center">
                    <LoaderCircleIcon className="animate-spin text-muted-foreground" />
                  </div>
                ) : filteredMembers.length ? (
                  isPhoneListLayout ? (
                    <ul className="flex flex-col gap-2 overflow-y-auto">
                      {filteredMembers.map((member) => {
                        const isLastAdmin =
                          member.role === "admin" && adminCount <= 1
                        const isProtectedAdmin =
                          member.role === "admin" && !canManageTeamAdmins
                        const removeDisabledReason = isTeamArchived
                          ? t("该团队已归档，恢复后方可调整成员")
                          : isLastAdmin
                            ? t("不能移除最后一个管理员")
                            : isProtectedAdmin
                              ? t("只有工作空间管理员可以管理团队管理员")
                              : undefined

                        return (
                          <li
                            key={member.user.id}
                            className="flex items-center justify-between gap-3 rounded-xl border bg-background p-3 shadow-xs"
                          >
                            <div className="min-w-0 flex-1">
                              <div className="flex items-center gap-2">
                                <span className="truncate font-medium">
                                  {member.user.name}
                                </span>
                                <span
                                  className={cn(
                                    "inline-flex shrink-0 rounded-md border px-2 py-0.5 text-xs font-medium whitespace-nowrap",
                                    member.role === "admin"
                                      ? "border-red-300/60 bg-red-100 text-red-600 dark:border-red-500/40 dark:bg-red-500/10 dark:text-red-300"
                                      : "border-border bg-muted text-muted-foreground"
                                  )}
                                >
                                  {member.role === "admin"
                                    ? t("管理员")
                                    : t("成员")}
                                </span>
                              </div>
                              <p className="truncate text-xs text-muted-foreground">
                                {member.user.username} · {member.user.email}
                              </p>
                            </div>
                            <DisabledButtonHint reason={removeDisabledReason}>
                              <Button
                                type="button"
                                variant="ghost"
                                size="icon-sm"
                                disabled={
                                  isMutating ||
                                  isTeamArchived ||
                                  isLastAdmin ||
                                  isProtectedAdmin
                                }
                                title={removeDisabledReason ?? t("移除成员")}
                                aria-label={t("移除成员")}
                                onClick={() => void handleRemoveMember(member)}
                              >
                                <UserMinusIcon />
                              </Button>
                            </DisabledButtonHint>
                          </li>
                        )
                      })}
                    </ul>
                  ) : (
                    <div
                      role="region"
                      aria-label={t("团队成员")}
                      tabIndex={0}
                      className="min-h-0 flex-1 overflow-auto rounded-lg border bg-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring"
                    >
                      <table className="w-full min-w-[680px] border-collapse text-sm">
                        <thead className="sticky top-0 z-10 border-b bg-[color-mix(in_oklch,var(--muted)_40%,var(--background))] text-left text-sm font-semibold text-muted-foreground">
                          <tr>
                            <th className="px-4 py-3 font-semibold">{t("用户名")}</th>
                            <th className="px-4 py-3 font-semibold">{t("账号")}</th>
                            <th className="px-4 py-3 font-semibold">{t("邮箱")}</th>
                            <th className="px-4 py-3 font-semibold">{t("角色")}</th>
                            <th className="px-4 py-3 text-right font-semibold">
                              {t("操作")}
                            </th>
                          </tr>
                        </thead>
                        <tbody className="divide-y">
                          {filteredMembers.map((member, index) => {
                            const isSelf = member.user.id === me.user.id
                            const isLastAdmin =
                              member.role === "admin" && adminCount <= 1
                            const isProtectedAdmin =
                              member.role === "admin" && !canManageTeamAdmins
                            const roleDisabledReason = isTeamArchived
                              ? t("该团队已归档，恢复后方可调整成员")
                              : isLastAdmin
                                ? t("不能移除最后一个管理员")
                                : isMutating
                                  ? t("保存中")
                                  : undefined
                            const removeDisabledReason =
                              roleDisabledReason ??
                              (isProtectedAdmin
                                ? t("只有工作空间管理员可以管理团队管理员")
                                : undefined)

                            return (
                              <tr
                                key={member.user.id}
                                className={cn(
                                  "bg-background hover:bg-[color-mix(in_oklch,var(--muted)_40%,var(--background))]",
                                  index % 2 === 1 &&
                                    "bg-[color-mix(in_oklch,var(--muted)_20%,var(--background))]"
                                )}
                              >
                                <td className="px-4 py-4 font-medium">
                                  <div className="flex items-center gap-2">
                                    <span className="truncate">
                                      {member.user.name}
                                    </span>
                                    {isSelf ? (
                                      <Badge variant="outline">
                                        {t("当前账号")}
                                      </Badge>
                                    ) : null}
                                    {!member.user.is_active ? (
                                      <Badge variant="secondary">
                                        {t("已停用")}
                                      </Badge>
                                    ) : null}
                                  </div>
                                </td>
                                <td className="px-4 py-4 text-muted-foreground">
                                  {member.user.username}
                                </td>
                                <td className="px-4 py-4 text-muted-foreground">
                                  {member.user.email}
                                </td>
                                <td className="px-4 py-4">
                                  {canManageTeamAdmins ? (
                                    <DropdownMenu modal={false}>
                                      <DisabledButtonHint
                                        reason={roleDisabledReason}
                                      >
                                        <DropdownMenuTrigger asChild>
                                          <Button
                                            type="button"
                                            variant="outline"
                                            size="sm"
                                            disabled={
                                              isMutating ||
                                              isTeamArchived ||
                                              isLastAdmin
                                            }
                                            title={
                                              roleDisabledReason ??
                                              t("更新成员角色")
                                            }
                                          >
                                            {member.role === "admin"
                                              ? t("管理员")
                                              : t("成员")}
                                            <ChevronDownIcon data-icon="inline-end" />
                                          </Button>
                                        </DropdownMenuTrigger>
                                      </DisabledButtonHint>
                                      <DropdownMenuContent align="start">
                                        <DropdownMenuItem
                                          disabled={member.role === "member"}
                                          onSelect={() =>
                                            void handleUpdateRole(
                                              member.user.id,
                                              "member"
                                            )
                                          }
                                        >
                                          {t("成员")}
                                        </DropdownMenuItem>
                                        <DropdownMenuItem
                                          disabled={member.role === "admin"}
                                          onSelect={() =>
                                            void handleUpdateRole(
                                              member.user.id,
                                              "admin"
                                            )
                                          }
                                        >
                                          {t("管理员")}
                                        </DropdownMenuItem>
                                      </DropdownMenuContent>
                                    </DropdownMenu>
                                  ) : (
                                    <span
                                      className={cn(
                                        "inline-flex rounded-md border px-2 py-0.5 text-xs font-medium whitespace-nowrap",
                                        member.role === "admin"
                                          ? "border-red-300/60 bg-red-100 text-red-600 dark:border-red-500/40 dark:bg-red-500/10 dark:text-red-300"
                                          : "border-border bg-muted text-muted-foreground"
                                      )}
                                    >
                                      {member.role === "admin"
                                        ? t("管理员")
                                        : t("成员")}
                                    </span>
                                  )}
                                </td>
                                <td className="px-4 py-4 text-right">
                                  <DisabledButtonHint
                                    reason={removeDisabledReason}
                                  >
                                    <Button
                                      type="button"
                                      variant="ghost"
                                      size="icon-sm"
                                      disabled={
                                        isMutating ||
                                        isTeamArchived ||
                                        isLastAdmin ||
                                        isProtectedAdmin
                                      }
                                      title={
                                        removeDisabledReason ?? t("移除成员")
                                      }
                                      aria-label={t("移除成员")}
                                      onClick={() =>
                                        void handleRemoveMember(member)
                                      }
                                    >
                                      <UserMinusIcon />
                                    </Button>
                                  </DisabledButtonHint>
                                </td>
                              </tr>
                            )
                          })}
                        </tbody>
                      </table>
                    </div>
                  )
                ) : (
                  <div className="flex min-h-28 items-center justify-center rounded-lg border border-dashed bg-muted/20 px-4 text-center">
                    <p className="text-sm text-muted-foreground">
                      {searchQuery.trim()
                        ? t("未找到匹配的团队成员")
                        : t("暂无团队成员")}
                    </p>
                  </div>
                )}
              </div>
            )}
          </CardContent>
        </Card>
      </div>
      {confirmDialog}
    </>
  )
}
