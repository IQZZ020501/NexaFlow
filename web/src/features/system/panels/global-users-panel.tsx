import * as React from "react"
import {
  CircleCheckIcon,
  CircleOffIcon,
  LockIcon,
  LoaderCircleIcon,
  PencilIcon,
  PlusIcon,
  SearchIcon,
  Trash2Icon,
  UserCogIcon,
} from "lucide-react"
import { useLanguage } from "@/components/language-provider"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import type { MeResponse, User, Workspace } from "@/features/system/types"
import { formatDateTime } from "@/app/display"
import { FilterDropdown } from "@/components/app/filter-dropdown"
import type { UserRoleFilter, UserStatusFilter } from "@/features/system/types"
import { cn } from "@/lib/utils"
import { displayWorkspaceName } from "@/app/display"
import {
  formatUserTeams,
  formatUserWorkspaces,
  getUserRoleClass,
  getUserRoleLabel,
} from "@/features/system/system-utils"

type GlobalUsersPanelProps = {
  me: MeResponse
  users: User[]
  filteredUsers: User[]
  workspaces: Workspace[]
  isUsersLoading: boolean
  userSearch: string
  setUserSearch: React.Dispatch<React.SetStateAction<string>>
  userStatusFilter: UserStatusFilter
  setUserStatusFilter: React.Dispatch<React.SetStateAction<UserStatusFilter>>
  userRoleFilter: UserRoleFilter
  setUserRoleFilter: React.Dispatch<React.SetStateAction<UserRoleFilter>>
  userWorkspaceFilter: string
  setUserWorkspaceFilter: React.Dispatch<React.SetStateAction<string>>
  locale: string
  handleOpenCreateUser: () => void
  handleToggleUser: (user: User) => void | Promise<void>
  handleOpenEditUser: (user: User) => void
  handleOpenUserPasswordDialog: (user: User) => void
  handleDeleteUser: (user: User) => void | Promise<void>
}

export function GlobalUsersPanel({
  me,
  users,
  filteredUsers,
  workspaces,
  isUsersLoading,
  userSearch,
  setUserSearch,
  userStatusFilter,
  setUserStatusFilter,
  userRoleFilter,
  setUserRoleFilter,
  userWorkspaceFilter,
  setUserWorkspaceFilter,
  locale,
  handleOpenCreateUser,
  handleToggleUser,
  handleOpenEditUser,
  handleOpenUserPasswordDialog,
  handleDeleteUser,
}: GlobalUsersPanelProps) {
  const { t } = useLanguage()

  return (
    <div
      id="system-panel-users"
      role="tabpanel"
      aria-labelledby="system-tab-users"
      className="grid min-w-0 gap-4 lg:h-full lg:overflow-y-auto lg:pr-1"
    >
      <Card className="min-w-0 gap-3 overflow-hidden border-border/70 py-4 shadow-sm lg:min-h-full">
        <CardHeader className="flex-row items-start justify-between gap-4 px-4">
          <div className="flex min-w-0 items-start gap-3">
            <span className="flex size-8 shrink-0 items-center justify-center rounded-lg border bg-background">
              <UserCogIcon className="size-4" />
            </span>
            <div className="min-w-0">
              <CardTitle>{t("用户管理")}</CardTitle>
              <CardDescription>{t("全局账号")}</CardDescription>
            </div>
          </div>
          <Button type="button" size="sm" onClick={handleOpenCreateUser}>
            <PlusIcon data-icon="inline-start" />
            {t("新建用户")}
          </Button>
        </CardHeader>
        <CardContent className="min-w-0 px-4">
          {isUsersLoading ? (
            <div className="flex min-h-28 items-center justify-center">
              <LoaderCircleIcon className="animate-spin text-muted-foreground" />
            </div>
          ) : users.length ? (
            <div className="grid gap-3">
              <div className="grid gap-2 lg:grid-cols-[minmax(220px,1fr)_150px_170px_190px]">
                <div className="relative">
                  <SearchIcon className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" />
                  <Input
                    value={userSearch}
                    onChange={(event) => setUserSearch(event.target.value)}
                    placeholder={t("搜索姓名、账号、邮箱")}
                    className="pl-9"
                  />
                </div>
                <FilterDropdown
                  ariaLabel={t("筛选用户状态")}
                  value={userStatusFilter}
                  onChange={(value) =>
                    setUserStatusFilter(value as UserStatusFilter)
                  }
                  options={[
                    { value: "all", label: t("全部状态") },
                    { value: "active", label: t("已启用") },
                    { value: "inactive", label: t("已停用") },
                  ]}
                />
                <FilterDropdown
                  ariaLabel={t("筛选用户角色")}
                  value={userRoleFilter}
                  onChange={(value) =>
                    setUserRoleFilter(value as UserRoleFilter)
                  }
                  options={[
                    { value: "all", label: t("全部角色") },
                    { value: "global_admin", label: t("全局管理员") },
                    {
                      value: "workspace_admin",
                      label: t("工作空间管理员"),
                    },
                    { value: "team_admin", label: t("团队管理员") },
                    { value: "member", label: t("普通用户") },
                  ]}
                />
                <FilterDropdown
                  ariaLabel={t("筛选工作空间")}
                  value={userWorkspaceFilter}
                  onChange={setUserWorkspaceFilter}
                  options={[
                    { value: "all", label: t("全部工作空间") },
                    ...workspaces.map((workspace) => ({
                      value: workspace.id,
                      label: displayWorkspaceName(workspace, t),
                    })),
                  ]}
                />
              </div>
              <div className="min-w-0 overflow-x-auto rounded-lg border bg-background">
                <div
                  role="table"
                  aria-label={t("用户列表")}
                  className="min-w-[1700px] text-sm"
                >
                  <div
                    role="row"
                    className="grid grid-cols-[150px_140px_260px_240px_220px_130px_120px_180px_160px] border-b bg-muted/40 px-4 py-3 text-sm font-semibold text-muted-foreground"
                  >
                    <span role="columnheader">{t("用户名")}</span>
                    <span role="columnheader">{t("账号")}</span>
                    <span role="columnheader">{t("邮箱")}</span>
                    <span role="columnheader">{t("所属工作空间")}</span>
                    <span role="columnheader">{t("所属团队")}</span>
                    <span role="columnheader">{t("用户角色")}</span>
                    <span role="columnheader">{t("状态")}</span>
                    <span role="columnheader">{t("创建时间")}</span>
                    <span role="columnheader" className="text-right">
                      {t("操作")}
                    </span>
                  </div>
                  {filteredUsers.map((user, index) => {
                    const workspaceNames = formatUserWorkspaces(user, t)
                    const teamNames = formatUserTeams(user, t)
                    const roleLabel = getUserRoleLabel(user, t)

                    return (
                      <div
                        key={user.id}
                        role="row"
                        className={cn(
                          "grid grid-cols-[150px_140px_260px_240px_220px_130px_120px_180px_160px] items-center border-b px-4 py-4 last:border-b-0 hover:bg-muted/40",
                          index % 2 === 1 && "bg-muted/20"
                        )}
                      >
                        <span
                          role="cell"
                          className="truncate font-medium"
                          title={user.name}
                        >
                          {user.name}
                        </span>
                        <span
                          role="cell"
                          className="truncate text-muted-foreground"
                          title={user.username}
                        >
                          {user.username}
                        </span>
                        <span
                          role="cell"
                          className="truncate text-muted-foreground"
                          title={user.email}
                        >
                          {user.email}
                        </span>
                        <span
                          role="cell"
                          className="truncate"
                          title={workspaceNames}
                        >
                          {workspaceNames}
                        </span>
                        <span
                          role="cell"
                          className="truncate"
                          title={teamNames}
                        >
                          {teamNames}
                        </span>
                        <span role="cell">
                          <span
                            className={cn(
                              "inline-flex rounded-md border px-2 py-0.5 text-xs font-medium whitespace-nowrap",
                              getUserRoleClass(user)
                            )}
                          >
                            {roleLabel}
                          </span>
                        </span>
                        <span
                          role="cell"
                          className="flex items-center gap-2 whitespace-nowrap"
                        >
                          {user.is_active ? (
                            <CircleCheckIcon className="size-4 text-green-600" />
                          ) : (
                            <CircleOffIcon className="size-4 text-muted-foreground" />
                          )}
                          <span>
                            {user.is_active ? t("已启用") : t("已停用")}
                          </span>
                        </span>
                        <span
                          role="cell"
                          className="whitespace-nowrap text-muted-foreground"
                        >
                          {formatDateTime(user.created_at, locale)}
                        </span>
                        <span
                          role="cell"
                          className="flex items-center justify-end gap-2 whitespace-nowrap"
                        >
                          <button
                            type="button"
                            className={cn(
                              "flex h-6 w-11 shrink-0 items-center rounded-full p-0.5 transition-colors",
                              user.is_active ? "bg-primary" : "bg-muted"
                            )}
                            disabled={user.id === me.user.id}
                            onClick={() => void handleToggleUser(user)}
                            title={
                              user.id === me.user.id
                                ? t("不能停用当前账号")
                                : t("切换用户状态")
                            }
                            aria-label={t("切换用户状态")}
                          >
                            <span
                              className={cn(
                                "size-5 rounded-full bg-background shadow-sm transition-transform",
                                user.is_active && "translate-x-5"
                              )}
                            />
                          </button>
                          <span className="h-5 w-px bg-border" />
                          <Button
                            type="button"
                            variant="ghost"
                            size="icon-sm"
                            onClick={() => handleOpenEditUser(user)}
                            title={t("编辑用户")}
                            aria-label={t("编辑用户")}
                          >
                            <PencilIcon />
                          </Button>
                          <Button
                            type="button"
                            variant="ghost"
                            size="icon-sm"
                            onClick={() => handleOpenUserPasswordDialog(user)}
                            title={t("修改密码")}
                            aria-label={t("修改密码")}
                          >
                            <LockIcon />
                          </Button>
                          <Button
                            type="button"
                            variant="ghost"
                            size="icon-sm"
                            disabled={user.id === me.user.id}
                            onClick={() => void handleDeleteUser(user)}
                            title={
                              user.id === me.user.id
                                ? t("不能删除当前账号")
                                : t("删除用户")
                            }
                            aria-label={t("删除用户")}
                          >
                            <Trash2Icon />
                          </Button>
                        </span>
                      </div>
                    )
                  })}
                  {!filteredUsers.length ? (
                    <div className="px-4 py-8 text-center text-sm text-muted-foreground">
                      {t("没有匹配的用户")}
                    </div>
                  ) : null}
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
