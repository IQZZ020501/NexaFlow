import * as React from "react"
import {
  ChevronDownIcon,
  CircleCheckIcon,
  LoaderCircleIcon,
  PlusIcon,
} from "lucide-react"
import { useLanguage } from "@/contexts/language-provider"
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
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { Field, FieldGroup, FieldLabel } from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import type { User, Workspace } from "@/lib/api/system"
import { cn } from "@/lib/utils"
import { displayWorkspaceName } from "@/lib/display"
import type {
  ScopeEditForm,
  TeamForm,
  WorkspaceForm,
  WorkspaceMember,
} from "@/lib/api/system"

type EditWorkspaceDialogProps = {
  workspaceEditForm: ScopeEditForm | null
  setWorkspaceEditForm: React.Dispatch<
    React.SetStateAction<ScopeEditForm | null>
  >
  isSavingWorkspace: boolean
  handleUpdateWorkspace: React.FormEventHandler<HTMLFormElement>
}

export function EditWorkspaceDialog({
  workspaceEditForm,
  setWorkspaceEditForm,
  isSavingWorkspace,
  handleUpdateWorkspace,
}: EditWorkspaceDialogProps) {
  const { t } = useLanguage()

  return (
    <Dialog
      open={Boolean(workspaceEditForm)}
      onOpenChange={(open) => {
        if (!open) {
          setWorkspaceEditForm(null)
        }
      }}
    >
      <DialogContent side="right">
        <DialogHeader>
          <DialogTitle>{t("编辑工作空间")}</DialogTitle>
          <DialogDescription>{t("更新名称和描述")}</DialogDescription>
        </DialogHeader>
        {workspaceEditForm ? (
          <form onSubmit={handleUpdateWorkspace}>
            <FieldGroup>
              <Field>
                <FieldLabel htmlFor="editWorkspaceName">{t("名称")}</FieldLabel>
                <Input
                  id="editWorkspaceName"
                  value={workspaceEditForm.name}
                  onChange={(event) =>
                    setWorkspaceEditForm((current) =>
                      current
                        ? { ...current, name: event.target.value }
                        : current
                    )
                  }
                  required
                />
              </Field>
              <Field>
                <FieldLabel htmlFor="editWorkspaceDescription">
                  {t("描述")}
                </FieldLabel>
                <Input
                  id="editWorkspaceDescription"
                  value={workspaceEditForm.description}
                  onChange={(event) =>
                    setWorkspaceEditForm((current) =>
                      current
                        ? { ...current, description: event.target.value }
                        : current
                    )
                  }
                />
              </Field>
            </FieldGroup>
            <DialogFooter className="pt-5">
              <Button
                type="button"
                variant="outline"
                onClick={() => setWorkspaceEditForm(null)}
              >
                {t("取消")}
              </Button>
              <Button disabled={isSavingWorkspace}>
                {isSavingWorkspace ? (
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

type EditTeamDialogProps = {
  teamEditForm: ScopeEditForm | null
  setTeamEditForm: React.Dispatch<React.SetStateAction<ScopeEditForm | null>>
  selectedWorkspace: Workspace | null
  selectedWorkspaceId: string | null
  isSavingTeam: boolean
  handleUpdateTeam: React.FormEventHandler<HTMLFormElement>
}

export function EditTeamDialog({
  teamEditForm,
  setTeamEditForm,
  selectedWorkspace,
  selectedWorkspaceId,
  isSavingTeam,
  handleUpdateTeam,
}: EditTeamDialogProps) {
  const { t } = useLanguage()

  return (
    <Dialog
      open={Boolean(teamEditForm)}
      onOpenChange={(open) => {
        if (!open) {
          setTeamEditForm(null)
        }
      }}
    >
      <DialogContent side="right">
        <DialogHeader>
          <DialogTitle>{t("编辑团队")}</DialogTitle>
          <DialogDescription>
            {selectedWorkspace
              ? displayWorkspaceName(selectedWorkspace, t)
              : t("先选择工作空间")}
          </DialogDescription>
        </DialogHeader>
        {teamEditForm ? (
          <form onSubmit={handleUpdateTeam}>
            <FieldGroup>
              <Field>
                <FieldLabel htmlFor="editTeamName">{t("名称")}</FieldLabel>
                <Input
                  id="editTeamName"
                  value={teamEditForm.name}
                  onChange={(event) =>
                    setTeamEditForm((current) =>
                      current
                        ? { ...current, name: event.target.value }
                        : current
                    )
                  }
                  required
                />
              </Field>
              <Field>
                <FieldLabel htmlFor="editTeamDescription">
                  {t("描述")}
                </FieldLabel>
                <Input
                  id="editTeamDescription"
                  value={teamEditForm.description}
                  onChange={(event) =>
                    setTeamEditForm((current) =>
                      current
                        ? { ...current, description: event.target.value }
                        : current
                    )
                  }
                />
              </Field>
            </FieldGroup>
            <DialogFooter className="pt-5">
              <Button
                type="button"
                variant="outline"
                onClick={() => setTeamEditForm(null)}
              >
                {t("取消")}
              </Button>
              <Button disabled={!selectedWorkspaceId || isSavingTeam}>
                {isSavingTeam ? (
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

type CreateWorkspaceDialogProps = {
  isWorkspaceDialogOpen: boolean
  setIsWorkspaceDialogOpen: React.Dispatch<React.SetStateAction<boolean>>
  workspaceForm: WorkspaceForm
  setWorkspaceForm: React.Dispatch<React.SetStateAction<WorkspaceForm>>
  users: User[]
  isUsersLoading: boolean
  isCreatingWorkspace: boolean
  handleCreateWorkspace: React.FormEventHandler<HTMLFormElement>
}

export function CreateWorkspaceDialog({
  isWorkspaceDialogOpen,
  setIsWorkspaceDialogOpen,
  workspaceForm,
  setWorkspaceForm,
  users,
  isUsersLoading,
  isCreatingWorkspace,
  handleCreateWorkspace,
}: CreateWorkspaceDialogProps) {
  const { t } = useLanguage()
  const activeUsers = users.filter((user) => user.is_active)
  const adminUser =
    activeUsers.find((user) => user.id === workspaceForm.adminUserId) ?? null

  return (
    <Dialog
      open={isWorkspaceDialogOpen}
      onOpenChange={setIsWorkspaceDialogOpen}
    >
      <DialogContent side="right" className="flex flex-col gap-6">
        <DialogHeader>
          <DialogTitle>{t("新建工作空间")}</DialogTitle>
          <DialogDescription>
            {t("创建工作空间并指定已有用户为负责人")}
          </DialogDescription>
        </DialogHeader>
        <form
          className="flex min-h-0 flex-1 flex-col"
          onSubmit={handleCreateWorkspace}
        >
          <FieldGroup>
            <Field>
              <FieldLabel htmlFor="workspaceName">{t("名称")}</FieldLabel>
              <Input
                id="workspaceName"
                value={workspaceForm.name}
                onChange={(event) =>
                  setWorkspaceForm((current) => ({
                    ...current,
                    name: event.target.value,
                  }))
                }
                required
              />
            </Field>
            <Field>
              <FieldLabel htmlFor="workspaceDescription">
                {t("描述")}
              </FieldLabel>
              <Input
                id="workspaceDescription"
                value={workspaceForm.description}
                onChange={(event) =>
                  setWorkspaceForm((current) => ({
                    ...current,
                    description: event.target.value,
                  }))
                }
              />
            </Field>
            <Field>
              <FieldLabel id="workspaceAdminLabel">{t("负责人")}</FieldLabel>
              <DropdownMenu modal={false}>
                <DropdownMenuTrigger asChild>
                  <Button
                    id="workspaceAdmin"
                    type="button"
                    variant="outline"
                    className="h-9 w-full justify-between px-3 font-normal"
                    aria-labelledby="workspaceAdminLabel workspaceAdmin"
                    disabled={isUsersLoading}
                  >
                    <span
                      className={cn(
                        "min-w-0 flex-1 truncate text-left",
                        !adminUser && "text-muted-foreground"
                      )}
                    >
                      {adminUser
                        ? `${adminUser.name} · ${adminUser.username}`
                        : isUsersLoading
                          ? t("正在加载")
                          : t("选择负责人")}
                    </span>
                    <ChevronDownIcon data-icon="inline-end" />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent
                  align="start"
                  className="max-h-72 w-(--radix-dropdown-menu-trigger-width) overflow-y-auto"
                >
                  {activeUsers.length ? (
                    activeUsers.map((user) => (
                      <DropdownMenuItem
                        key={user.id}
                        className="items-start justify-between gap-3"
                        onSelect={() =>
                          setWorkspaceForm((current) => ({
                            ...current,
                            adminUserId: user.id,
                          }))
                        }
                      >
                        <span className="min-w-0">
                          <span className="block truncate font-medium">
                            {user.name}
                          </span>
                          <span className="block truncate text-xs text-muted-foreground">
                            {user.username} · {user.email}
                          </span>
                        </span>
                        {user.id === workspaceForm.adminUserId ? (
                          <CircleCheckIcon className="mt-0.5 shrink-0" />
                        ) : null}
                      </DropdownMenuItem>
                    ))
                  ) : (
                    <DropdownMenuItem disabled>
                      {t("暂无可选用户")}
                    </DropdownMenuItem>
                  )}
                </DropdownMenuContent>
              </DropdownMenu>
            </Field>
          </FieldGroup>
          <DialogFooter className="mt-auto pt-5">
            <Button
              type="button"
              variant="outline"
              onClick={() => setIsWorkspaceDialogOpen(false)}
            >
              {t("取消")}
            </Button>
            <Button
              disabled={isCreatingWorkspace || !workspaceForm.adminUserId}
            >
              {isCreatingWorkspace ? (
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

type CreateTeamDialogProps = {
  isTeamDialogOpen: boolean
  setIsTeamDialogOpen: React.Dispatch<React.SetStateAction<boolean>>
  teamWorkspace: Workspace | null
  manageableWorkspaces: Workspace[]
  teamForm: TeamForm
  setTeamForm: React.Dispatch<React.SetStateAction<TeamForm>>
  isCreatingTeam: boolean
  handleCreateTeam: React.FormEventHandler<HTMLFormElement>
  teamAdminCandidates: WorkspaceMember[]
  isTeamAdminCandidatesLoading: boolean
  handleTeamWorkspaceChange: (workspaceId: string) => void
}

export function CreateTeamDialog({
  isTeamDialogOpen,
  setIsTeamDialogOpen,
  teamWorkspace,
  manageableWorkspaces,
  teamForm,
  setTeamForm,
  isCreatingTeam,
  handleCreateTeam,
  teamAdminCandidates,
  isTeamAdminCandidatesLoading,
  handleTeamWorkspaceChange,
}: CreateTeamDialogProps) {
  const { t } = useLanguage()
  const teamAdminUser =
    teamAdminCandidates.find(
      (member) => member.user.id === teamForm.adminUserId
    )?.user ?? null

  return (
    <Dialog open={isTeamDialogOpen} onOpenChange={setIsTeamDialogOpen}>
      <DialogContent side="right">
        <DialogHeader>
          <DialogTitle>{t("新建团队")}</DialogTitle>
          <DialogDescription>
            {teamWorkspace
              ? displayWorkspaceName(teamWorkspace, t)
              : t("先选择工作空间")}
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={handleCreateTeam}>
          <FieldGroup>
            <Field>
              <FieldLabel id="teamWorkspaceLabel">{t("工作空间")}</FieldLabel>
              <DropdownMenu modal={false}>
                <DropdownMenuTrigger asChild>
                  <Button
                    id="teamWorkspace"
                    type="button"
                    variant="outline"
                    className="h-9 w-full justify-between px-3 font-normal"
                    disabled={!manageableWorkspaces.length}
                    aria-labelledby="teamWorkspaceLabel teamWorkspace"
                  >
                    <span
                      className={cn(
                        "min-w-0 flex-1 truncate text-left",
                        !teamWorkspace && "text-muted-foreground"
                      )}
                    >
                      {teamWorkspace
                        ? displayWorkspaceName(teamWorkspace, t)
                        : t("选择工作空间")}
                    </span>
                    <ChevronDownIcon data-icon="inline-end" />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent
                  align="start"
                  className="w-(--radix-dropdown-menu-trigger-width)"
                >
                  <DropdownMenuGroup>
                    {manageableWorkspaces.map((workspace) => (
                      <DropdownMenuItem
                        key={workspace.id}
                        onSelect={() =>
                          handleTeamWorkspaceChange(workspace.id)
                        }
                        className="justify-between"
                      >
                        <span className="truncate">
                          {displayWorkspaceName(workspace, t)}
                        </span>
                        {workspace.id === teamForm.workspaceId ? (
                          <CircleCheckIcon className="text-primary" />
                        ) : null}
                      </DropdownMenuItem>
                    ))}
                  </DropdownMenuGroup>
                </DropdownMenuContent>
              </DropdownMenu>
            </Field>
            <Field>
              <FieldLabel htmlFor="teamName">{t("名称")}</FieldLabel>
              <Input
                id="teamName"
                value={teamForm.name}
                onChange={(event) =>
                  setTeamForm((current) => ({
                    ...current,
                    name: event.target.value,
                  }))
                }
                required
              />
            </Field>
            <Field>
              <FieldLabel htmlFor="teamDescription">{t("描述")}</FieldLabel>
              <Input
                id="teamDescription"
                value={teamForm.description}
                onChange={(event) =>
                  setTeamForm((current) => ({
                    ...current,
                    description: event.target.value,
                  }))
                }
              />
            </Field>
            <Field>
              <FieldLabel id="teamAdminLabel">{t("团队管理员")}</FieldLabel>
              <DropdownMenu modal={false}>
                <DropdownMenuTrigger asChild>
                  <Button
                    id="teamAdmin"
                    type="button"
                    variant="outline"
                    className="h-9 w-full justify-between px-3 font-normal"
                    aria-labelledby="teamAdminLabel teamAdmin"
                    disabled={isTeamAdminCandidatesLoading || !teamWorkspace}
                  >
                    <span
                      className={cn(
                        "min-w-0 flex-1 truncate text-left",
                        !teamAdminUser && "text-muted-foreground"
                      )}
                    >
                      {teamAdminUser
                        ? `${teamAdminUser.name} · ${teamAdminUser.username}`
                        : isTeamAdminCandidatesLoading
                          ? t("正在加载")
                          : t("选择团队管理员")}
                    </span>
                    <ChevronDownIcon data-icon="inline-end" />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent
                  align="start"
                  className="max-h-72 w-(--radix-dropdown-menu-trigger-width) overflow-y-auto"
                >
                  {teamAdminCandidates.filter((member) => member.user.is_active)
                    .length ? (
                    teamAdminCandidates
                      .filter((member) => member.user.is_active)
                      .map((member) => (
                        <DropdownMenuItem
                          key={member.user.id}
                          className="items-start justify-between gap-3"
                          onSelect={() =>
                            setTeamForm((current) => ({
                              ...current,
                              adminUserId: member.user.id,
                            }))
                          }
                        >
                          <span className="min-w-0">
                            <span className="block truncate font-medium">
                              {member.user.name}
                            </span>
                            <span className="block truncate text-xs text-muted-foreground">
                              {member.user.username} · {member.user.email}
                            </span>
                          </span>
                          {member.user.id === teamForm.adminUserId ? (
                            <CircleCheckIcon className="mt-0.5 shrink-0" />
                          ) : null}
                        </DropdownMenuItem>
                      ))
                  ) : (
                    <DropdownMenuItem disabled>
                      {t("暂无可选成员")}
                    </DropdownMenuItem>
                  )}
                </DropdownMenuContent>
              </DropdownMenu>
            </Field>
          </FieldGroup>
          <DialogFooter className="pt-5">
            <Button
              type="button"
              variant="outline"
              onClick={() => setIsTeamDialogOpen(false)}
            >
              {t("取消")}
            </Button>
            <Button
              disabled={
                !teamForm.workspaceId || !teamForm.adminUserId || isCreatingTeam
              }
            >
              {isCreatingTeam ? (
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
