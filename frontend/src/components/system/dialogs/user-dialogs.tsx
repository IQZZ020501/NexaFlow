import * as React from "react"
import { ChevronDownIcon, LoaderCircleIcon, PlusIcon } from "lucide-react"
import { useLanguage } from "@/contexts/language-provider"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { CopyButton } from "@/components/ui/copy-button"
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
import {
  Field,
  FieldDescription,
  FieldGroup,
  FieldLabel,
} from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import type { MeResponse, Team, Workspace } from "@/lib/api/system"
import { isEventFromDropdownMenu } from "@/lib/dom"
import { cn } from "@/lib/utils"
import { displayTeamName, displayWorkspaceName } from "@/lib/display"
import { FilterDropdown } from "@/components/app/filter-dropdown"
import type {
  CreatedUserCredentials,
  RoleAssignmentValue,
  UserCreateForm,
  UserForm,
  UserPasswordForm,
} from "@/lib/api/system"

type CreateUserDialogProps = {
  isUserCreateDialogOpen: boolean
  setIsUserCreateDialogOpen: React.Dispatch<React.SetStateAction<boolean>>
  userCreateForm: UserCreateForm
  setUserCreateForm: React.Dispatch<React.SetStateAction<UserCreateForm>>
  userCreateWorkspace: Workspace | null
  userCreateTeams: Team[]
  isUserCreateTeamsLoading: boolean
  activeWorkspaces: Workspace[]
  me: MeResponse
  selectedWorkspaceId: string | null
  isCreatingUser: boolean
  handleCreateUser: React.FormEventHandler<HTMLFormElement>
  handleUserCreateWorkspaceChange: (workspaceId: string) => void
}

/**
 * Renders a dialog for creating a user and configuring their workspace, teams, and global administrator privileges.
 *
 * @param isUserCreateDialogOpen - Whether the dialog is open.
 * @param setIsUserCreateDialogOpen - Updates the dialog's open state.
 * @param userCreateForm - Form values for the new user.
 * @param setUserCreateForm - Updates the new user form values.
 * @param userCreateWorkspace - Workspace currently selected for the new user.
 * @param userCreateTeams - Teams available in the selected workspace.
 * @param isUserCreateTeamsLoading - Whether teams for the selected workspace are loading.
 * @param activeWorkspaces - Workspaces available for selection.
 * @param me - Current user and their administrative permissions.
 * @param selectedWorkspaceId - Current administrator's workspace identifier.
 * @param isCreatingUser - Whether user creation is in progress.
 * @param handleCreateUser - Handles submission of the new user form.
 * @param handleUserCreateWorkspaceChange - Updates the selected workspace.
 */
export function CreateUserDialog({
  isUserCreateDialogOpen,
  setIsUserCreateDialogOpen,
  userCreateForm,
  setUserCreateForm,
  userCreateWorkspace,
  userCreateTeams,
  isUserCreateTeamsLoading,
  activeWorkspaces,
  me,
  selectedWorkspaceId,
  isCreatingUser,
  handleCreateUser,
  handleUserCreateWorkspaceChange,
}: CreateUserDialogProps) {
  const { t } = useLanguage()

  return (
    <Dialog
      open={isUserCreateDialogOpen}
      onOpenChange={setIsUserCreateDialogOpen}
    >
      <DialogContent
        side="right"
        className="flex flex-col gap-6"
        onInteractOutside={(event) => {
          if (isEventFromDropdownMenu(event)) {
            event.preventDefault()
          }
        }}
      >
        <DialogHeader>
          <DialogTitle>{t("新建用户")}</DialogTitle>
          <DialogDescription>
            {me.user.is_global_admin
              ? t("创建账号并分配工作空间与团队")
              : t("创建普通账号并加入当前工作空间")}
          </DialogDescription>
        </DialogHeader>
        <form
          className="flex min-h-0 flex-1 flex-col"
          onSubmit={handleCreateUser}
        >
          <FieldGroup className="max-sm:min-h-0 max-sm:flex-1 max-sm:overflow-y-auto max-sm:overscroll-contain">
            <div className="space-y-1">
              <h3 className="text-sm font-semibold">{t("基本信息")}</h3>
            </div>
            <Field>
              <FieldLabel htmlFor="newUserName">{t("姓名")}</FieldLabel>
              <Input
                id="newUserName"
                value={userCreateForm.name}
                onChange={(event) =>
                  setUserCreateForm((current) => ({
                    ...current,
                    name: event.target.value,
                  }))
                }
                required
              />
            </Field>
            <Field>
              <FieldLabel htmlFor="newUserUsername">{t("用户名")}</FieldLabel>
              <Input
                id="newUserUsername"
                value={userCreateForm.username}
                onChange={(event) =>
                  setUserCreateForm((current) => ({
                    ...current,
                    username: event.target.value,
                  }))
                }
                required
              />
            </Field>
            <Field>
              <FieldLabel htmlFor="newUserEmail">{t("邮箱")}</FieldLabel>
              <Input
                id="newUserEmail"
                type="email"
                value={userCreateForm.email}
                onChange={(event) =>
                  setUserCreateForm((current) => ({
                    ...current,
                    email: event.target.value,
                  }))
                }
                required
              />
            </Field>
            {me.user.is_global_admin ? (
              <Field>
                <FieldLabel id="newUserWorkspaceLabel">
                  {t("工作空间")}
                </FieldLabel>
                <DropdownMenu modal={false}>
                  <DropdownMenuTrigger asChild>
                    <Button
                      id="newUserWorkspace"
                      type="button"
                      variant="outline"
                      className="h-9 w-full justify-between px-3 font-normal"
                      aria-labelledby="newUserWorkspaceLabel newUserWorkspace"
                    >
                      <span
                        className={cn(
                          "min-w-0 flex-1 truncate text-left",
                          !userCreateWorkspace && "text-muted-foreground"
                        )}
                      >
                        {userCreateWorkspace
                          ? displayWorkspaceName(userCreateWorkspace, t)
                          : t("不指定工作空间")}
                      </span>
                      <ChevronDownIcon data-icon="inline-end" />
                    </Button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent
                    align="start"
                    className="w-(--radix-dropdown-menu-trigger-width)"
                  >
                    <DropdownMenuItem
                      onSelect={() => handleUserCreateWorkspaceChange("")}
                    >
                      {t("不指定工作空间")}
                    </DropdownMenuItem>
                    {activeWorkspaces.map((workspace) => (
                      <DropdownMenuItem
                        key={workspace.id}
                        className="justify-between"
                        onSelect={() =>
                          handleUserCreateWorkspaceChange(workspace.id)
                        }
                      >
                        <span className="min-w-0 truncate">
                          {displayWorkspaceName(workspace, t)}
                        </span>
                        {workspace.is_default ? (
                          <Badge variant="outline">{t("默认")}</Badge>
                        ) : null}
                      </DropdownMenuItem>
                    ))}
                  </DropdownMenuContent>
                </DropdownMenu>
              </Field>
            ) : null}
            {me.user.is_global_admin ? (
              <Field>
                <FieldLabel>{t("团队")}</FieldLabel>
                {!userCreateForm.workspaceId ? (
                  <FieldDescription>
                    {t("选择工作空间后可分配该空间下的团队")}
                  </FieldDescription>
                ) : isUserCreateTeamsLoading ? (
                  <div className="flex h-16 items-center justify-center rounded-lg border border-dashed">
                    <LoaderCircleIcon className="animate-spin text-muted-foreground" />
                  </div>
                ) : userCreateTeams.length ? (
                  <div className="grid gap-2 rounded-lg border p-2 max-sm:max-h-56 max-sm:overflow-y-auto max-sm:overscroll-contain">
                    {userCreateTeams.map((team) => (
                      <label
                        key={team.id}
                        className="flex items-center gap-2 rounded-md px-2 py-1.5 text-sm hover:bg-muted"
                      >
                        <input
                          type="checkbox"
                          className="size-4"
                          checked={userCreateForm.teamIds.includes(team.id)}
                          onChange={(event) =>
                            setUserCreateForm((current) => ({
                              ...current,
                              teamIds: event.target.checked
                                ? [...current.teamIds, team.id]
                                : current.teamIds.filter(
                                    (teamId) => teamId !== team.id
                                  ),
                            }))
                          }
                        />
                        <span className="min-w-0 truncate">
                          {displayTeamName(team, t)}
                        </span>
                      </label>
                    ))}
                  </div>
                ) : (
                  <FieldDescription>
                    {t("该工作空间下暂无团队")}
                  </FieldDescription>
                )}
              </Field>
            ) : null}
          </FieldGroup>
          <DialogFooter className="mt-auto pt-5 max-sm:sticky max-sm:bottom-0 max-sm:z-10 max-sm:border-t max-sm:bg-background max-sm:pt-3 max-sm:pb-[max(0.5rem,env(safe-area-inset-bottom))]">
            <Button
              type="button"
              variant="outline"
              onClick={() => setIsUserCreateDialogOpen(false)}
            >
              {t("取消")}
            </Button>
            <Button
              disabled={
                isCreatingUser ||
                (!me.user.is_global_admin && !selectedWorkspaceId)
              }
              aria-busy={isCreatingUser}
            >
              {isCreatingUser ? (
                <LoaderCircleIcon
                  data-icon="inline-start"
                  aria-hidden="true"
                  className="animate-spin motion-reduce:animate-none"
                />
              ) : (
                <PlusIcon data-icon="inline-start" />
              )}
              {t("新建")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

type EditUserDialogProps = {
  userForm: UserForm | null
  setUserForm: React.Dispatch<React.SetStateAction<UserForm | null>>
  canManageGlobalAdmin: boolean
  isSavingUser: boolean
  handleUpdateUser: React.FormEventHandler<HTMLFormElement>
  activeWorkspaces?: Workspace[]
  roleTeams?: Team[]
  isRoleTeamsLoading?: boolean
  initialWorkspaceRoles?: Record<string, RoleAssignmentValue>
  onRoleWorkspaceChange?: (workspaceId: string) => void
}

/**
 * Provides a dialog for editing a user's account information, global administrator
 * privileges (global admin), and workspace/team roles.
 */
export function EditUserDialog({
  userForm,
  setUserForm,
  canManageGlobalAdmin,
  isSavingUser,
  handleUpdateUser,
  activeWorkspaces = [],
  roleTeams = [],
  isRoleTeamsLoading = false,
  initialWorkspaceRoles,
  onRoleWorkspaceChange,
}: EditUserDialogProps) {
  const { t } = useLanguage()
  const isWorkspaceMode = userForm?.mode === "workspace"
  const activeRoleTeams = React.useMemo(
    () => roleTeams.filter((team) => team.status === "active"),
    [roleTeams]
  )
  const roleWorkspaceId = userForm?.roleWorkspaceId ?? ""
  const currentWorkspaceRole: RoleAssignmentValue = roleWorkspaceId
    ? (userForm?.workspaceRoles?.[roleWorkspaceId] ??
      (isWorkspaceMode ? "member" : "none"))
    : "none"
  const wasWorkspaceMember = roleWorkspaceId
    ? isWorkspaceMode ||
      (initialWorkspaceRoles?.[roleWorkspaceId] ?? "none") !== "none"
    : false
  const isInactiveUser = userForm?.isActive === false
  const selectedRoleWorkspace = activeWorkspaces.find(
    (workspace) => workspace.id === roleWorkspaceId
  )
  const showGlobalRoleEditor = Boolean(
    !isWorkspaceMode &&
      canManageGlobalAdmin &&
      activeWorkspaces.length &&
      userForm?.workspaceRoles
  )
  const showTeamRoleSection = isWorkspaceMode || showGlobalRoleEditor

  return (
    <Dialog
      open={Boolean(userForm)}
      onOpenChange={(open) => !open && setUserForm(null)}
    >
      <DialogContent
        className="max-h-[85svh] overflow-y-auto"
        onInteractOutside={(event) => {
          if (isEventFromDropdownMenu(event)) {
            event.preventDefault()
          }
        }}
      >
        <DialogHeader>
          <DialogTitle>{t("编辑用户")}</DialogTitle>
          <DialogDescription>
            {isWorkspaceMode
              ? t("管理用户在该工作空间下的团队角色")
              : t("更新账号基础信息")}
          </DialogDescription>
        </DialogHeader>
        {userForm ? (
          <form onSubmit={handleUpdateUser}>
            <FieldGroup>
              {isWorkspaceMode ? (
                <div className="grid gap-1 rounded-lg border bg-muted/20 p-3 text-sm">
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-medium">{userForm.name}</span>
                    {selectedRoleWorkspace ? (
                      <Badge variant="outline">
                        {displayWorkspaceName(selectedRoleWorkspace, t)}
                      </Badge>
                    ) : null}
                  </div>
                  <span className="truncate text-xs text-muted-foreground">
                    {userForm.username} · {userForm.email}
                  </span>
                </div>
              ) : (
                <>
                  <Field>
                    <FieldLabel htmlFor="userName">{t("姓名")}</FieldLabel>
                    <Input
                      id="userName"
                      value={userForm.name}
                      onChange={(event) =>
                        setUserForm((current) =>
                          current
                            ? { ...current, name: event.target.value }
                            : current
                        )
                      }
                      required
                    />
                  </Field>
                  <Field>
                    <FieldLabel htmlFor="userUsername">{t("账号")}</FieldLabel>
                    <Input
                      id="userUsername"
                      value={userForm.username}
                      onChange={(event) =>
                        setUserForm((current) =>
                          current
                            ? { ...current, username: event.target.value }
                            : current
                        )
                      }
                      required
                    />
                  </Field>
                  <Field>
                    <FieldLabel htmlFor="userEmail">{t("邮箱")}</FieldLabel>
                    <Input
                      id="userEmail"
                      type="email"
                      value={userForm.email}
                      onChange={(event) =>
                        setUserForm((current) =>
                          current
                            ? { ...current, email: event.target.value }
                            : current
                        )
                      }
                      required
                    />
                  </Field>
                </>
              )}

              {showTeamRoleSection ? (
                <div className="grid gap-3 rounded-lg border p-3">
                  <div className="text-sm font-medium">
                    {isWorkspaceMode ? t("团队角色") : t("空间与团队角色")}
                  </div>

                  {showGlobalRoleEditor ? (
                    <>
                      <Field>
                        <FieldLabel htmlFor="editUserRoleWorkspace">
                          {t("目标工作空间")}
                        </FieldLabel>
                        <FilterDropdown
                          id="editUserRoleWorkspace"
                          ariaLabel={t("目标工作空间")}
                          modal={false}
                          value={roleWorkspaceId}
                          options={activeWorkspaces.map((workspace) => ({
                            value: workspace.id,
                            label: displayWorkspaceName(workspace, t),
                          }))}
                          onChange={(value) => {
                            if (onRoleWorkspaceChange) {
                              onRoleWorkspaceChange(value)
                            } else {
                              setUserForm((current) =>
                                current
                                  ? { ...current, roleWorkspaceId: value }
                                  : current
                              )
                            }
                          }}
                        />
                      </Field>

                      <Field>
                        <FieldLabel htmlFor="editUserWorkspaceRole">
                          {t("工作空间角色")}
                        </FieldLabel>
                        <FilterDropdown
                          id="editUserWorkspaceRole"
                          ariaLabel={t("工作空间角色")}
                          modal={false}
                          disabled={!wasWorkspaceMember && isInactiveUser}
                          value={currentWorkspaceRole}
                          options={[
                            ...(!wasWorkspaceMember
                              ? [{ value: "none", label: t("未加入") }]
                              : []),
                            { value: "member", label: t("普通成员") },
                            { value: "admin", label: t("工作空间管理员") },
                          ]}
                          onChange={(value) =>
                            setUserForm((current) =>
                              current && roleWorkspaceId
                                ? {
                                    ...current,
                                    workspaceRoles: {
                                      ...current.workspaceRoles,
                                      [roleWorkspaceId]:
                                        value as RoleAssignmentValue,
                                    },
                                  }
                                : current
                            )
                          }
                        />
                      </Field>
                    </>
                  ) : null}

                  <Field>
                    {!isWorkspaceMode ? (
                      <FieldLabel>{t("团队角色")}</FieldLabel>
                    ) : null}
                    {isInactiveUser ? (
                      <FieldDescription>
                        {t("停用用户无法加入新工作空间或团队")}
                      </FieldDescription>
                    ) : null}
                    {!isWorkspaceMode && currentWorkspaceRole === "none" ? (
                      <FieldDescription>
                        {t("先将该用户加入此工作空间后可分配团队角色")}
                      </FieldDescription>
                    ) : isRoleTeamsLoading ? (
                      <div className="flex h-16 items-center justify-center rounded-lg border border-dashed">
                        <LoaderCircleIcon className="animate-spin text-muted-foreground" />
                      </div>
                    ) : activeRoleTeams.length ? (
                      <div className="grid max-h-48 gap-2 overflow-y-auto overscroll-contain rounded-lg border p-2">
                        {activeRoleTeams.map((team) => {
                          const currentTeamRole: RoleAssignmentValue =
                            userForm.teamRoles?.[team.id] ?? "none"
                          const isTeamDisabled =
                            isInactiveUser && currentTeamRole === "none"

                          return (
                            <div
                              key={team.id}
                              className="flex items-center justify-between gap-2 rounded-md px-2 py-1 text-sm"
                            >
                              <span className="min-w-0 flex-1 truncate">
                                {displayTeamName(team, t)}
                              </span>
                              <FilterDropdown
                                className="h-8 w-36 shrink-0"
                                ariaLabel={t("{team} 角色", {
                                  team: displayTeamName(team, t),
                                })}
                                modal={false}
                                disabled={isTeamDisabled}
                                value={currentTeamRole}
                                options={[
                                  { value: "none", label: t("未加入") },
                                  { value: "member", label: t("普通成员") },
                                  { value: "admin", label: t("团队管理员") },
                                ]}
                                onChange={(value) =>
                                  setUserForm((current) =>
                                    current
                                      ? {
                                          ...current,
                                          teamRoles: {
                                            ...current.teamRoles,
                                            [team.id]:
                                              value as RoleAssignmentValue,
                                          },
                                        }
                                      : current
                                  )
                                }
                              />
                            </div>
                          )
                        })}
                      </div>
                    ) : (
                      <FieldDescription>
                        {t("该工作空间下暂无团队")}
                      </FieldDescription>
                    )}
                  </Field>
                </div>
              ) : null}
            </FieldGroup>
            <DialogFooter className="pt-5 max-sm:sticky max-sm:bottom-0 max-sm:z-10 max-sm:border-t max-sm:bg-background max-sm:pt-3 max-sm:pb-[max(0.5rem,env(safe-area-inset-bottom))]">
              <Button
                type="button"
                variant="outline"
                onClick={() => setUserForm(null)}
              >
                {t("取消")}
              </Button>
              <Button disabled={isSavingUser} aria-busy={isSavingUser}>
                {isSavingUser ? (
                  <LoaderCircleIcon
                    data-icon="inline-start"
                    aria-hidden="true"
                    className="animate-spin motion-reduce:animate-none"
                  />
                ) : null}
                {t("保存")}
              </Button>
            </DialogFooter>
          </form>
        ) : null}
      </DialogContent>
    </Dialog>
  )
}

type UserPasswordDialogProps = {
  userPasswordForm: UserPasswordForm | null
  setUserPasswordForm: React.Dispatch<
    React.SetStateAction<UserPasswordForm | null>
  >
  isChangingUserPassword: boolean
  handleChangeUserPassword: React.FormEventHandler<HTMLFormElement>
}

export function UserPasswordDialog({
  userPasswordForm,
  setUserPasswordForm,
  isChangingUserPassword,
  handleChangeUserPassword,
}: UserPasswordDialogProps) {
  const { t } = useLanguage()

  return (
    <Dialog
      open={Boolean(userPasswordForm)}
      onOpenChange={(open) => !open && setUserPasswordForm(null)}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("修改密码")}</DialogTitle>
          <DialogDescription>
            {userPasswordForm
              ? t("为 {name} 设置新密码", {
                  name: userPasswordForm.user.name,
                })
              : t("设置新密码")}
          </DialogDescription>
        </DialogHeader>
        {userPasswordForm ? (
          <form onSubmit={handleChangeUserPassword}>
            <FieldGroup>
              <Field>
                <FieldLabel htmlFor="managedUserNewPassword">
                  {t("新密码")}
                </FieldLabel>
                <Input
                  id="managedUserNewPassword"
                  type="password"
                  autoComplete="new-password"
                  minLength={6}
                  value={userPasswordForm.newPassword}
                  onChange={(event) =>
                    setUserPasswordForm((current) =>
                      current
                        ? { ...current, newPassword: event.target.value }
                        : current
                    )
                  }
                  required
                />
                <FieldDescription>
                  {t("至少 6 位，并且包含一个大写字母")}
                </FieldDescription>
              </Field>
              <Field>
                <FieldLabel htmlFor="managedUserConfirmPassword">
                  {t("确认密码")}
                </FieldLabel>
                <Input
                  id="managedUserConfirmPassword"
                  type="password"
                  autoComplete="new-password"
                  minLength={6}
                  value={userPasswordForm.confirmPassword}
                  onChange={(event) =>
                    setUserPasswordForm((current) =>
                      current
                        ? {
                            ...current,
                            confirmPassword: event.target.value,
                          }
                        : current
                    )
                  }
                  required
                />
              </Field>
            </FieldGroup>
            <DialogFooter className="pt-5 max-sm:sticky max-sm:bottom-0 max-sm:z-10 max-sm:border-t max-sm:bg-background max-sm:pt-3 max-sm:pb-[max(0.5rem,env(safe-area-inset-bottom))]">
              <Button
                type="button"
                variant="outline"
                onClick={() => setUserPasswordForm(null)}
              >
                {t("取消")}
              </Button>
              <Button
                disabled={isChangingUserPassword}
                aria-busy={isChangingUserPassword}
              >
                {isChangingUserPassword ? (
                  <LoaderCircleIcon
                    data-icon="inline-start"
                    aria-hidden="true"
                    className="animate-spin motion-reduce:animate-none"
                  />
                ) : null}
                {t("保存")}
              </Button>
            </DialogFooter>
          </form>
        ) : null}
      </DialogContent>
    </Dialog>
  )
}

type CreatedUserPasswordDialogProps = {
  credentials: CreatedUserCredentials | null
  onClose: () => void
}

/**
 * Displays a newly created user's one-time initial password in a persistent modal
 * that remains open until the administrator explicitly closes it.
 */
export function CreatedUserPasswordDialog({
  credentials,
  onClose,
}: CreatedUserPasswordDialogProps) {
  const { t } = useLanguage()
  const closeButtonRef = React.useRef<HTMLButtonElement | null>(null)

  return (
    <Dialog
      open={Boolean(credentials)}
      onOpenChange={(open) => {
        if (!open) {
          onClose()
        }
      }}
    >
      <DialogContent
        onOpenAutoFocus={(event) => {
          event.preventDefault()
          closeButtonRef.current?.focus()
        }}
        onPointerDownOutside={(event) => event.preventDefault()}
        onInteractOutside={(event) => event.preventDefault()}
        onEscapeKeyDown={(event) => event.preventDefault()}
      >
        <DialogHeader>
          <DialogTitle>{t("用户已新建")}</DialogTitle>
          <DialogDescription>
            {t("初始密码 24 小时内有效，请复制保存后再关闭此窗口。")}
          </DialogDescription>
        </DialogHeader>
        {credentials ? (
          <div className="grid gap-3">
            <div className="grid gap-2 rounded-lg border bg-muted/20 p-3 text-sm">
              <div className="flex items-center justify-between gap-2">
                <span className="text-muted-foreground">{t("姓名")}</span>
                <span className="truncate font-medium">{credentials.name}</span>
              </div>
              <div className="flex items-center justify-between gap-2">
                <span className="text-muted-foreground">{t("账号")}</span>
                <span className="flex min-w-0 items-center gap-1 font-mono text-xs">
                  <span className="truncate">{credentials.username}</span>
                  <CopyButton
                    value={credentials.username}
                    label={t("复制账号")}
                    t={t}
                  />
                </span>
              </div>
              <div className="flex items-center justify-between gap-2">
                <span className="text-muted-foreground">{t("邮箱")}</span>
                <span className="truncate text-xs text-muted-foreground">
                  {credentials.email}
                </span>
              </div>
            </div>

            <div className="grid gap-2 rounded-lg border bg-muted/30 p-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="text-sm font-medium">{t("初始密码")}</span>
                <span className="text-xs text-muted-foreground">
                  {t("首次登录后需要修改密码")}
                </span>
              </div>
              <div className="flex items-center justify-between gap-2 rounded-md border bg-background px-3 py-2">
                <code className="min-w-0 flex-1 select-all break-all font-mono text-sm font-medium">
                  {credentials.initialPassword}
                </code>
                <CopyButton
                  value={credentials.initialPassword}
                  label={t("复制初始密码")}
                  showLabel
                  t={t}
                />
              </div>
            </div>
          </div>
        ) : null}
        <DialogFooter>
          <Button ref={closeButtonRef} type="button" onClick={onClose}>
            {t("我已保存，关闭")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
