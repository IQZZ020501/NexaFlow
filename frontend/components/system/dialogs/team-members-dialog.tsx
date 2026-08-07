import * as React from "react"
import {
  ChevronDownIcon,
  LoaderCircleIcon,
  UserMinusIcon,
  UserPlusIcon,
} from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
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
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { Field, FieldLabel } from "@/components/ui/field"
import { useLanguage } from "@/contexts/language-provider"
import type { Team, TeamMember, WorkspaceMember } from "@/lib/api/system"
import { displayTeamName } from "@/lib/display"
import { isEventFromDropdownMenu } from "@/lib/dom"
import { cn } from "@/lib/utils"

type TeamMembersDialogProps = {
  team: Team | null
  setTeam: React.Dispatch<React.SetStateAction<Team | null>>
  members: TeamMember[]
  workspaceMembers: WorkspaceMember[]
  isLoading: boolean
  isMutating: boolean
  canManageTeamAdmins: boolean
  onAddMember: (userId: string, role: string) => Promise<void>
  onUpdateMemberRole: (userId: string, role: string) => Promise<void>
  onRemoveMember: (userId: string) => Promise<void>
}

export function TeamMembersDialog({
  team,
  setTeam,
  members,
  workspaceMembers,
  isLoading,
  isMutating,
  canManageTeamAdmins,
  onAddMember,
  onUpdateMemberRole,
  onRemoveMember,
}: TeamMembersDialogProps) {
  const { t } = useLanguage()
  const [newUserId, setNewUserId] = React.useState("")
  const [newRole, setNewRole] = React.useState("member")
  const memberIds = React.useMemo(
    () => new Set(members.map((member) => member.user.id)),
    [members]
  )
  const candidates = React.useMemo(
    () =>
      workspaceMembers.filter(
        (member) => member.user.is_active && !memberIds.has(member.user.id)
      ),
    [memberIds, workspaceMembers]
  )
  const adminCount = members.filter((member) => member.role === "admin").length

  React.useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setNewUserId("")
    setNewRole("member")
  }, [team?.id])

  async function handleAdd() {
    if (!newUserId) {
      return
    }

    await onAddMember(newUserId, canManageTeamAdmins ? newRole : "member")
    setNewUserId("")
    setNewRole("member")
  }

  return (
    <Dialog
      open={Boolean(team)}
      onOpenChange={(open) => {
        if (!open) {
          setTeam(null)
          setNewUserId("")
          setNewRole("member")
        }
      }}
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
          <DialogTitle>{t("管理团队成员")}</DialogTitle>
          <DialogDescription>
            {team ? displayTeamName(team, t) : t("管理团队成员")}
          </DialogDescription>
        </DialogHeader>

        {team ? (
          <div className="flex min-h-0 flex-1 flex-col gap-5">
            <section className="grid gap-3 rounded-lg border p-4">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <h3 className="text-sm font-semibold">{t("添加成员")}</h3>
                  <p className="text-xs text-muted-foreground">
                    {t("只能添加当前工作空间中的成员")}
                  </p>
                </div>
                <UserPlusIcon className="size-4 text-muted-foreground" />
              </div>
              <Field>
                <FieldLabel htmlFor="teamMemberUser">{t("成员")}</FieldLabel>
                <DropdownMenu modal={false}>
                  <DropdownMenuTrigger asChild>
                    <Button
                      id="teamMemberUser"
                      type="button"
                      variant="outline"
                      className="h-9 w-full justify-between px-3 font-normal"
                      disabled={isLoading || isMutating || !candidates.length}
                    >
                      <span
                        className={cn(
                          "min-w-0 flex-1 truncate text-left",
                          !newUserId && "text-muted-foreground"
                        )}
                      >
                        {workspaceMembers.find(
                          (member) => member.user.id === newUserId
                        )?.user.name ??
                          (isLoading
                            ? t("正在加载")
                            : candidates.length
                              ? t("选择成员")
                              : t("暂无可加入成员"))}
                      </span>
                      <ChevronDownIcon data-icon="inline-end" />
                    </Button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent
                    align="start"
                    className="max-h-72 w-(--radix-dropdown-menu-trigger-width) overflow-y-auto"
                  >
                    {candidates.map((member) => (
                      <DropdownMenuItem
                        key={member.user.id}
                        onSelect={() => setNewUserId(member.user.id)}
                      >
                        <span className="min-w-0 truncate">
                          {member.user.name} · {member.user.username}
                        </span>
                      </DropdownMenuItem>
                    ))}
                  </DropdownMenuContent>
                </DropdownMenu>
              </Field>
              {canManageTeamAdmins ? (
                <Field>
                  <FieldLabel htmlFor="teamMemberRole">{t("角色")}</FieldLabel>
                  <DropdownMenu modal={false}>
                    <DropdownMenuTrigger asChild>
                      <Button
                        id="teamMemberRole"
                        type="button"
                        variant="outline"
                        className="h-9 w-full justify-between px-3 font-normal"
                        disabled={isMutating}
                      >
                        {newRole === "admin" ? t("管理员") : t("成员")}
                        <ChevronDownIcon data-icon="inline-end" />
                      </Button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent
                      align="start"
                      className="w-(--radix-dropdown-menu-trigger-width)"
                    >
                      <DropdownMenuItem onSelect={() => setNewRole("member")}>
                        {t("成员")}
                      </DropdownMenuItem>
                      <DropdownMenuItem onSelect={() => setNewRole("admin")}>
                        {t("管理员")}
                      </DropdownMenuItem>
                    </DropdownMenuContent>
                  </DropdownMenu>
                </Field>
              ) : null}
              <Button
                type="button"
                size="sm"
                className="w-full"
                disabled={!newUserId || isLoading || isMutating}
                onClick={() => void handleAdd()}
              >
                {isMutating ? (
                  <LoaderCircleIcon data-icon="inline-start" />
                ) : (
                  <UserPlusIcon data-icon="inline-start" />
                )}
                {t("添加成员")}
              </Button>
            </section>

            <section className="min-h-0 flex-1 overflow-y-auto">
              <div className="mb-3 flex items-center justify-between gap-3">
                <h3 className="text-sm font-semibold">{t("团队成员")}</h3>
                <Badge variant="outline">{members.length}</Badge>
              </div>
              {isLoading ? (
                <div className="flex min-h-28 items-center justify-center">
                  <LoaderCircleIcon className="animate-spin text-muted-foreground" />
                </div>
              ) : members.length ? (
                <div className="grid gap-2">
                  {members.map((member) => {
                    const isLastAdmin =
                      member.role === "admin" && adminCount <= 1

                    return (
                      <div
                        key={member.user.id}
                        className="flex items-center justify-between gap-3 rounded-lg border px-3 py-2.5"
                      >
                        <div className="min-w-0">
                          <p className="truncate text-sm font-medium">
                            {member.user.name}
                          </p>
                          <p className="truncate text-xs text-muted-foreground">
                            {member.user.username} · {member.user.email}
                          </p>
                        </div>
                        <div className="flex shrink-0 items-center gap-1.5">
                          {canManageTeamAdmins ? (
                            <DropdownMenu modal={false}>
                              <DropdownMenuTrigger asChild>
                                <Button
                                  type="button"
                                  variant="outline"
                                  size="sm"
                                  disabled={isMutating || isLastAdmin}
                                  title={
                                    isLastAdmin
                                      ? t("不能移除最后一个管理员")
                                      : t("更新成员角色")
                                  }
                                >
                                  {member.role === "admin"
                                    ? t("管理员")
                                    : t("成员")}
                                  <ChevronDownIcon data-icon="inline-end" />
                                </Button>
                              </DropdownMenuTrigger>
                              <DropdownMenuContent align="end">
                                <DropdownMenuItem
                                  disabled={member.role === "member"}
                                  onSelect={() =>
                                    void onUpdateMemberRole(
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
                                    void onUpdateMemberRole(
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
                            <Badge variant="outline">
                              {member.role === "admin"
                                ? t("管理员")
                                : t("成员")}
                            </Badge>
                          )}
                          <Button
                            type="button"
                            variant="ghost"
                            size="icon-sm"
                            disabled={
                              isMutating ||
                              isLastAdmin ||
                              (member.role === "admin" && !canManageTeamAdmins)
                            }
                            title={
                              isLastAdmin
                                ? t("不能移除最后一个管理员")
                                : t("移除成员")
                            }
                            aria-label={t("移除成员")}
                            onClick={() => void onRemoveMember(member.user.id)}
                          >
                            <UserMinusIcon />
                          </Button>
                        </div>
                      </div>
                    )
                  })}
                </div>
              ) : (
                <div className="flex min-h-28 items-center justify-center rounded-lg border border-dashed bg-muted/20">
                  <p className="text-sm text-muted-foreground">
                    {t("暂无团队成员")}
                  </p>
                </div>
              )}
            </section>
          </div>
        ) : null}
      </DialogContent>
    </Dialog>
  )
}
