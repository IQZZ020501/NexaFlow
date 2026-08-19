import * as React from "react"
import { ChevronDownIcon, LoaderCircleIcon, PlusIcon } from "lucide-react"
import { useLanguage } from "@/contexts/language-provider"
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
import type {
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
          <FieldGroup>
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
              <label className="flex items-start gap-3 rounded-lg border p-3 text-sm">
                <input
                  type="checkbox"
                  className="mt-0.5 size-4"
                  checked={userCreateForm.isGlobalAdmin}
                  onChange={(event) =>
                    setUserCreateForm((current) => ({
                      ...current,
                      isGlobalAdmin: event.target.checked,
                    }))
                  }
                />
                <span className="grid gap-1">
                  <span className="font-medium">{t("全局管理员权限")}</span>
                  <span className="text-xs text-muted-foreground">
                    {t("可治理全部工作空间")}
                  </span>
                </span>
              </label>
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
                  <div className="grid gap-2 rounded-lg border p-2">
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
          <DialogFooter className="mt-auto pt-5">
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
            >
              {isCreatingUser ? (
                <LoaderCircleIcon data-icon="inline-start" />
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
}

export function EditUserDialog({
  userForm,
  setUserForm,
  canManageGlobalAdmin,
  isSavingUser,
  handleUpdateUser,
}: EditUserDialogProps) {
  const { t } = useLanguage()

  return (
    <Dialog
      open={Boolean(userForm)}
      onOpenChange={(open) => !open && setUserForm(null)}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("编辑用户")}</DialogTitle>
          <DialogDescription>{t("更新账号基础信息")}</DialogDescription>
        </DialogHeader>
        {userForm ? (
          <form onSubmit={handleUpdateUser}>
            <FieldGroup>
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
              {canManageGlobalAdmin ? (
                <label className="flex items-start gap-3 rounded-lg border p-3 text-sm">
                  <input
                    type="checkbox"
                    className="mt-0.5 size-4"
                    checked={userForm.isGlobalAdmin}
                    onChange={(event) =>
                      setUserForm((current) =>
                        current
                          ? {
                              ...current,
                              isGlobalAdmin: event.target.checked,
                            }
                          : current
                      )
                    }
                  />
                  <span className="grid gap-1">
                    <span className="font-medium">{t("全局管理员权限")}</span>
                    <span className="text-xs text-muted-foreground">
                      {t("可治理全部工作空间")}
                    </span>
                  </span>
                </label>
              ) : null}
            </FieldGroup>
            <DialogFooter className="pt-5">
              <Button
                type="button"
                variant="outline"
                onClick={() => setUserForm(null)}
              >
                {t("取消")}
              </Button>
              <Button disabled={isSavingUser}>
                {isSavingUser ? (
                  <LoaderCircleIcon data-icon="inline-start" />
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
            <DialogFooter className="pt-5">
              <Button
                type="button"
                variant="outline"
                onClick={() => setUserPasswordForm(null)}
              >
                {t("取消")}
              </Button>
              <Button disabled={isChangingUserPassword}>
                {isChangingUserPassword ? (
                  <LoaderCircleIcon data-icon="inline-start" />
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
