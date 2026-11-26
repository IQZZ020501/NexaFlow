import * as React from "react"
import {
  CircleCheckIcon,
  CircleOffIcon,
  LoaderCircleIcon,
  PencilIcon,
  PlusIcon,
  SearchIcon,
  UserCogIcon,
} from "lucide-react"
import { useLanguage } from "@/contexts/language-provider"
import { FilterDropdown } from "@/components/app/filter-dropdown"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import type { Workspace, WorkspaceMember } from "@/lib/api/system"
import { cn } from "@/lib/utils"
import {
  displayTeamName,
  displayWorkspaceName,
  formatDateTime,
} from "@/lib/display"
import { PHONE_LIST_QUERY, useMediaQuery } from "@/lib/use-media-query"

type WorkspaceUsersPanelProps = {
  selectedWorkspace: Workspace | null
  selectedWorkspaceId: string | null
  workspaceMembers: WorkspaceMember[]
  isWorkspaceMembersLoading: boolean
  locale: string
  handleOpenCreateUser: () => void
  handleOpenWorkspaceMembers: () => void
  handleOpenEditUser?: (member: WorkspaceMember) => void
}

type WorkspaceMemberStatusFilter = "all" | "active" | "inactive"
type WorkspaceMemberRoleFilter = "all" | "admin" | "member"

function workspaceMemberRoleClass(role: string) {
  return role === "admin"
    ? "border-amber-300/60 bg-amber-100 text-amber-700 dark:border-amber-500/40 dark:bg-amber-500/10 dark:text-amber-300"
    : "border-border bg-muted text-muted-foreground"
}

/**
 * Displays workspace details, member-management actions, and workspace users.
 *
 * @returns The workspace user-management panel.
 */
export function WorkspaceUsersPanel({
  selectedWorkspace,
  selectedWorkspaceId,
  workspaceMembers,
  isWorkspaceMembersLoading,
  locale,
  handleOpenCreateUser,
  handleOpenWorkspaceMembers,
  handleOpenEditUser,
}: WorkspaceUsersPanelProps) {
  const { t } = useLanguage()
  const isPhoneListLayout = useMediaQuery(PHONE_LIST_QUERY)
  const [searchQuery, setSearchQuery] = React.useState("")
  const [statusFilter, setStatusFilter] =
    React.useState<WorkspaceMemberStatusFilter>("all")
  const [roleFilter, setRoleFilter] =
    React.useState<WorkspaceMemberRoleFilter>("all")

  const filteredMembers = React.useMemo(() => {
    const query = searchQuery.trim().toLowerCase()
    return workspaceMembers.filter((member) => {
      if (
        query &&
        ![member.user.name, member.user.username, member.user.email]
          .join(" ")
          .toLowerCase()
          .includes(query)
      ) {
        return false
      }
      if (statusFilter === "active" && !member.user.is_active) {
        return false
      }
      if (statusFilter === "inactive" && member.user.is_active) {
        return false
      }
      if (roleFilter === "admin" && member.role !== "admin") {
        return false
      }
      if (roleFilter === "member" && member.role === "admin") {
        return false
      }
      return true
    })
  }, [roleFilter, searchQuery, statusFilter, workspaceMembers])

  function formatMemberTeams(member: WorkspaceMember) {
    if (!member.user.teams.length) {
      return "-"
    }
    return member.user.teams
      .map((team) =>
        team.role === "admin"
          ? `${displayTeamName(team, t)} (${t("管理员")})`
          : displayTeamName(team, t)
      )
      .join(", ")
  }

  const desktopGridClass = handleOpenEditUser
    ? "grid-cols-[minmax(110px,1fr)_minmax(100px,0.9fr)_minmax(180px,1.5fr)_96px_minmax(130px,1.1fr)_96px_156px_76px]"
    : "grid-cols-[minmax(120px,1fr)_minmax(110px,0.9fr)_minmax(190px,1.5fr)_100px_minmax(140px,1.2fr)_100px_160px]"

  return (
    <div
      id="system-panel-users"
      role="tabpanel"
      aria-labelledby="system-tab-users"
      className="grid min-w-0 gap-4 lg:h-full lg:min-h-0 lg:overflow-hidden lg:pr-1"
    >
      <Card className="min-w-0 gap-3 overflow-hidden border-border/70 py-4 shadow-sm lg:h-full lg:min-h-0">
        <CardHeader className="flex-row items-start justify-between gap-4 px-4 max-sm:flex-wrap">
          <div className="flex min-w-0 items-start gap-3">
            <span className="flex size-8 shrink-0 items-center justify-center rounded-lg border bg-background">
              <UserCogIcon className="size-4" />
            </span>
            <div className="min-w-0">
              <CardTitle>{t("用户管理")}</CardTitle>
              <CardDescription>
                {selectedWorkspace
                  ? displayWorkspaceName(selectedWorkspace, t)
                  : t("未选择工作空间")}
              </CardDescription>
            </div>
          </div>
          <div className="flex shrink-0 flex-wrap items-center gap-2 max-sm:w-full">
            <Button
              type="button"
              size="sm"
              variant="outline"
              disabled={!selectedWorkspaceId}
              onClick={handleOpenWorkspaceMembers}
            >
              <UserCogIcon data-icon="inline-start" />
              {t("管理成员")}
            </Button>
            <Button
              type="button"
              size="sm"
              disabled={!selectedWorkspaceId}
              onClick={handleOpenCreateUser}
            >
              <PlusIcon data-icon="inline-start" />
              {t("新建用户")}
            </Button>
          </div>
        </CardHeader>
        <CardContent className="min-w-0 px-4 lg:flex lg:min-h-0 lg:flex-1 lg:flex-col lg:overflow-hidden">
          {isWorkspaceMembersLoading ? (
            <div className="flex min-h-28 items-center justify-center">
              <LoaderCircleIcon className="animate-spin text-muted-foreground" />
            </div>
          ) : workspaceMembers.length ? (
            <div className="flex min-w-0 flex-col gap-3 lg:min-h-0 lg:flex-1 lg:overflow-hidden">
              <div className="grid shrink-0 gap-2 lg:grid-cols-[minmax(220px,1fr)_150px_150px]">
                <div className="relative">
                  <SearchIcon className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" />
                  <Input
                    value={searchQuery}
                    onChange={(event) => setSearchQuery(event.target.value)}
                    placeholder={t("搜索姓名、账号、邮箱")}
                    className="pl-9"
                  />
                </div>
                <FilterDropdown
                  ariaLabel={t("筛选用户状态")}
                  value={statusFilter}
                  onChange={(value) =>
                    setStatusFilter(value as WorkspaceMemberStatusFilter)
                  }
                  options={[
                    { value: "all", label: t("全部状态") },
                    { value: "active", label: t("已启用") },
                    { value: "inactive", label: t("已停用") },
                  ]}
                />
                <FilterDropdown
                  ariaLabel={t("筛选用户角色")}
                  value={roleFilter}
                  onChange={(value) =>
                    setRoleFilter(value as WorkspaceMemberRoleFilter)
                  }
                  options={[
                    { value: "all", label: t("全部角色") },
                    { value: "admin", label: t("管理员") },
                    { value: "member", label: t("成员") },
                  ]}
                />
              </div>

              {/* phones: card list instead of the desktop grid */}
              {isPhoneListLayout ? (
                <ul className="flex flex-col gap-2">
                  {filteredMembers.length ? (
                    filteredMembers.map((member) => (
                      <li
                        key={member.user.id}
                        className="rounded-xl border bg-background p-3 shadow-xs"
                      >
                        <div className="flex items-start justify-between gap-2">
                          <span
                            className="min-w-0 flex-1 truncate font-medium"
                            title={member.user.name}
                          >
                            {member.user.name}
                          </span>
                          <div className="flex shrink-0 items-center gap-1.5">
                            <span
                              className={cn(
                                "inline-flex shrink-0 rounded-md border px-2 py-0.5 text-xs font-medium whitespace-nowrap",
                                workspaceMemberRoleClass(member.role)
                              )}
                            >
                              {member.role === "admin"
                                ? t("管理员")
                                : t("成员")}
                            </span>
                            {handleOpenEditUser ? (
                              <Button
                                type="button"
                                variant="ghost"
                                size="icon-sm"
                                aria-label={t("编辑用户")}
                                title={t("编辑用户")}
                                onClick={() => handleOpenEditUser(member)}
                              >
                                <PencilIcon />
                              </Button>
                            ) : null}
                          </div>
                        </div>
                        <dl className="mt-2 grid gap-1 text-sm">
                          <WorkspaceMemberCardField
                            label={t("账号")}
                            value={member.user.username}
                          />
                          <WorkspaceMemberCardField
                            breakAll
                            label={t("邮箱")}
                            value={member.user.email}
                          />
                          <WorkspaceMemberCardField
                            label={t("所属团队")}
                            value={formatMemberTeams(member)}
                          />
                          <WorkspaceMemberCardField
                            label={t("状态")}
                            value={
                              member.user.is_active ? t("已启用") : t("已停用")
                            }
                          />
                          <WorkspaceMemberCardField
                            label={t("创建时间")}
                            value={formatDateTime(
                              member.user.created_at,
                              locale
                            )}
                          />
                        </dl>
                      </li>
                    ))
                  ) : (
                    <li className="rounded-xl border border-dashed bg-muted/20 p-4 text-center text-sm text-muted-foreground">
                      {t("没有匹配的用户")}
                    </li>
                  )}
                </ul>
              ) : null}

              <div className="hidden min-w-0 overflow-auto rounded-lg border bg-background md:block lg:min-h-0 lg:flex-1">
                <div
                  role="table"
                  aria-label={t("工作空间用户列表")}
                  className={cn(
                    "text-sm",
                    handleOpenEditUser ? "min-w-[920px]" : "min-w-[860px]"
                  )}
                >
                  <div
                    role="row"
                    className={cn(
                      "sticky top-0 z-10 grid border-b bg-[color-mix(in_oklch,var(--muted)_40%,var(--background))] px-4 py-3 text-sm font-semibold text-muted-foreground",
                      desktopGridClass
                    )}
                  >
                    <span role="columnheader">{t("用户名")}</span>
                    <span role="columnheader">{t("账号")}</span>
                    <span role="columnheader">{t("邮箱")}</span>
                    <span role="columnheader">{t("空间角色")}</span>
                    <span role="columnheader">{t("所属团队")}</span>
                    <span role="columnheader">{t("状态")}</span>
                    <span role="columnheader">{t("创建时间")}</span>
                    {handleOpenEditUser ? (
                      <span
                        role="columnheader"
                        className="sticky right-0 z-20 flex h-full items-center justify-end border-l bg-[color-mix(in_oklch,var(--muted)_40%,var(--background))] px-4"
                      >
                        {t("操作")}
                      </span>
                    ) : null}
                  </div>
                  {filteredMembers.length ? (
                    filteredMembers.map((member, index) => {
                      const roleLabel =
                        member.role === "admin" ? t("管理员") : t("成员")
                      const teamsSummary = formatMemberTeams(member)

                      return (
                        <div
                          key={member.user.id}
                          role="row"
                          className={cn(
                            "group grid items-center border-b bg-background px-4 py-4 last:border-b-0 hover:bg-[color-mix(in_oklch,var(--muted)_40%,var(--background))]",
                            desktopGridClass,
                            index % 2 === 1 &&
                              "bg-[color-mix(in_oklch,var(--muted)_20%,var(--background))]"
                          )}
                        >
                          <span
                            role="cell"
                            className="truncate font-medium"
                            title={member.user.name}
                          >
                            {member.user.name}
                          </span>
                          <span
                            role="cell"
                            className="truncate text-muted-foreground"
                            title={member.user.username}
                          >
                            {member.user.username}
                          </span>
                          <span
                            role="cell"
                            className="truncate text-muted-foreground"
                            title={member.user.email}
                          >
                            {member.user.email}
                          </span>
                          <span role="cell">
                            <span
                              className={cn(
                                "inline-flex rounded-md border px-2 py-0.5 text-xs font-medium whitespace-nowrap",
                                workspaceMemberRoleClass(member.role)
                              )}
                            >
                              {roleLabel}
                            </span>
                          </span>
                          <span
                            role="cell"
                            className="truncate text-muted-foreground"
                            title={teamsSummary}
                          >
                            {teamsSummary}
                          </span>
                          <span
                            role="cell"
                            className="flex items-center gap-2 whitespace-nowrap"
                          >
                            {member.user.is_active ? (
                              <CircleCheckIcon className="size-4 text-green-600" />
                            ) : (
                              <CircleOffIcon className="size-4 text-muted-foreground" />
                            )}
                            <span>
                              {member.user.is_active
                                ? t("已启用")
                                : t("已停用")}
                            </span>
                          </span>
                          <span
                            role="cell"
                            className="whitespace-nowrap text-muted-foreground"
                          >
                            {formatDateTime(member.user.created_at, locale)}
                          </span>
                          {handleOpenEditUser ? (
                            <span
                              role="cell"
                              className={cn(
                                "sticky right-0 z-[1] flex h-full items-center justify-end border-l bg-background px-4 whitespace-nowrap group-hover:bg-[color-mix(in_oklch,var(--muted)_40%,var(--background))]",
                                index % 2 === 1 &&
                                  "bg-[color-mix(in_oklch,var(--muted)_20%,var(--background))]"
                              )}
                            >
                              <Button
                                type="button"
                                variant="ghost"
                                size="icon-sm"
                                aria-label={t("编辑用户")}
                                title={t("编辑用户")}
                                onClick={() => handleOpenEditUser(member)}
                              >
                                <PencilIcon />
                              </Button>
                            </span>
                          ) : null}
                        </div>
                      )
                    })
                  ) : (
                    <div className="flex min-h-28 items-center justify-center bg-muted/20 px-4">
                      <p className="text-sm text-muted-foreground">
                        {t("没有匹配的用户")}
                      </p>
                    </div>
                  )}
                </div>
              </div>
            </div>
          ) : (
            <div className="flex min-h-28 items-center justify-center rounded-lg border border-dashed bg-muted/20">
              <p className="text-sm text-muted-foreground">{t("暂无用户")}</p>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

/**
 * Renders one `label: value` line of a phone workspace-member card.
 *
 * @param label - Localized field label.
 * @param value - Field value; truncated unless `breakAll` is set.
 * @param breakAll - Wraps long unbroken values such as email addresses.
 */
function WorkspaceMemberCardField({
  label,
  value,
  breakAll = false,
}: {
  label: string
  value: string
  breakAll?: boolean
}) {
  return (
    <div className="flex min-w-0 items-start gap-1.5">
      <dt className="shrink-0 text-muted-foreground">{label}</dt>
      <dd
        className={cn("min-w-0 flex-1", breakAll ? "break-all" : "truncate")}
        title={value}
      >
        {value}
      </dd>
    </div>
  )
}
