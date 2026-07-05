import * as React from "react"
import {
  ChevronDownIcon,
  CircleCheckIcon,
  LoaderCircleIcon,
  PlusIcon,
} from "lucide-react"
import { useLanguage } from "@/components/language-provider"
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
import type { Workspace, WorkspaceCreateResponse } from "@/lib/api"
import { cn } from "@/lib/utils"
import { displayWorkspaceName } from "@/app/display"
import type {
  ScopeEditForm,
  TeamForm,
  WorkspaceForm,
} from "@/features/system/types"

type EditWorkspaceDialogProps = {
  workspaceEditForm: ScopeEditForm | null
  setWorkspaceEditForm: React.Dispatch<
    React.SetStateAction<ScopeEditForm | null>
  >
  workspaceError: string | null
  setWorkspaceError: React.Dispatch<React.SetStateAction<string | null>>
  isSavingWorkspace: boolean
  handleUpdateWorkspace: React.FormEventHandler<HTMLFormElement>
}

export function EditWorkspaceDialog({
  workspaceEditForm,
  setWorkspaceEditForm,
  workspaceError,
  setWorkspaceError,
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
          setWorkspaceError(null)
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
              {workspaceError ? (
                <p className="text-sm text-destructive">{workspaceError}</p>
              ) : null}
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
  teamError: string | null
  setTeamError: React.Dispatch<React.SetStateAction<string | null>>
  selectedWorkspace: Workspace | null
  selectedWorkspaceId: string | null
  isSavingTeam: boolean
  handleUpdateTeam: React.FormEventHandler<HTMLFormElement>
}

export function EditTeamDialog({
  teamEditForm,
  setTeamEditForm,
  teamError,
  setTeamError,
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
          setTeamError(null)
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
              {teamError ? (
                <p className="text-sm text-destructive">{teamError}</p>
              ) : null}
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
  workspaceError: string | null
  workspaceNotice: WorkspaceCreateResponse | null
  isCreatingWorkspace: boolean
  handleCreateWorkspace: React.FormEventHandler<HTMLFormElement>
}

export function CreateWorkspaceDialog({
  isWorkspaceDialogOpen,
  setIsWorkspaceDialogOpen,
  workspaceForm,
  setWorkspaceForm,
  workspaceError,
  workspaceNotice,
  isCreatingWorkspace,
  handleCreateWorkspace,
}: CreateWorkspaceDialogProps) {
  const { t } = useLanguage()

  return (
    <Dialog
      open={isWorkspaceDialogOpen}
      onOpenChange={setIsWorkspaceDialogOpen}
    >
      <DialogContent side="right">
        <DialogHeader>
          <DialogTitle>{t("新建工作空间")}</DialogTitle>
          <DialogDescription>{t("创建租户和负责人")}</DialogDescription>
        </DialogHeader>
        <form onSubmit={handleCreateWorkspace}>
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
              <FieldLabel htmlFor="adminName">{t("负责人姓名")}</FieldLabel>
              <Input
                id="adminName"
                value={workspaceForm.adminName}
                onChange={(event) =>
                  setWorkspaceForm((current) => ({
                    ...current,
                    adminName: event.target.value,
                  }))
                }
                required
              />
            </Field>
            <Field>
              <FieldLabel htmlFor="adminUsername">{t("负责人账号")}</FieldLabel>
              <Input
                id="adminUsername"
                value={workspaceForm.adminUsername}
                onChange={(event) =>
                  setWorkspaceForm((current) => ({
                    ...current,
                    adminUsername: event.target.value,
                  }))
                }
                required
              />
            </Field>
            <Field>
              <FieldLabel htmlFor="adminEmail">{t("负责人邮箱")}</FieldLabel>
              <Input
                id="adminEmail"
                type="email"
                value={workspaceForm.adminEmail}
                onChange={(event) =>
                  setWorkspaceForm((current) => ({
                    ...current,
                    adminEmail: event.target.value,
                  }))
                }
                required
              />
            </Field>
            {workspaceError ? (
              <p className="text-sm text-destructive">{workspaceError}</p>
            ) : null}
            {workspaceNotice ? (
              <div className="rounded-lg border bg-muted p-3 text-sm">
                <div className="font-medium">
                  {t("已创建 {name}", {
                    name: workspaceNotice.workspace.name,
                  })}
                </div>
                {workspaceNotice.admin_initial_password ? (
                  <div className="mt-1 font-mono text-xs">
                    {workspaceNotice.admin_initial_password}
                  </div>
                ) : null}
              </div>
            ) : null}
          </FieldGroup>
          <DialogFooter className="pt-5">
            <Button
              type="button"
              variant="outline"
              onClick={() => setIsWorkspaceDialogOpen(false)}
            >
              {t("取消")}
            </Button>
            <Button disabled={isCreatingWorkspace}>
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
  teamError: string | null
  isCreatingTeam: boolean
  handleCreateTeam: React.FormEventHandler<HTMLFormElement>
}

export function CreateTeamDialog({
  isTeamDialogOpen,
  setIsTeamDialogOpen,
  teamWorkspace,
  manageableWorkspaces,
  teamForm,
  setTeamForm,
  teamError,
  isCreatingTeam,
  handleCreateTeam,
}: CreateTeamDialogProps) {
  const { t } = useLanguage()

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
              <DropdownMenu>
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
                          setTeamForm((current) => ({
                            ...current,
                            workspaceId: workspace.id,
                          }))
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
            {teamError ? (
              <p className="text-sm text-destructive">{teamError}</p>
            ) : null}
          </FieldGroup>
          <DialogFooter className="pt-5">
            <Button
              type="button"
              variant="outline"
              onClick={() => setIsTeamDialogOpen(false)}
            >
              {t("取消")}
            </Button>
            <Button disabled={!teamForm.workspaceId || isCreatingTeam}>
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
