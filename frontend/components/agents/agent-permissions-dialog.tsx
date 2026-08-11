import * as React from "react"
import {
  ChevronDownIcon,
  CircleCheckIcon,
  LoaderCircleIcon,
  Trash2Icon,
} from "lucide-react"

import { PermissionBadge } from "@/components/knowledge/status-badges"
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
import { Field, FieldGroup, FieldLabel } from "@/components/ui/field"
import { useLanguage } from "@/contexts/language-provider"
import type { Agent, AgentPermission } from "@/lib/api/agents"
import type { WorkspaceMember } from "@/lib/api/system"
import { cn } from "@/lib/utils"

type AgentPermissionsDialogProps = {
  agent: Agent | null
  members: WorkspaceMember[]
  permissions: AgentPermission[]
  isLoading: boolean
  isSaving: boolean
  onClose: () => void
  onGrant: (userId: string) => void | Promise<void>
  onRevoke: (userId: string) => void | Promise<void>
}

export function availableAgentPermissionTargets(
  members: WorkspaceMember[],
  agent: Agent,
  permissions: AgentPermission[]
) {
  const grantedUserIds = new Set(
    permissions.map((permission) => permission.user.id)
  )
  return members.filter(
    (member) =>
      member.user.id !== agent.created_by_user_id &&
      !grantedUserIds.has(member.user.id)
  )
}

export function AgentPermissionsDialog({
  agent,
  members,
  permissions,
  isLoading,
  isSaving,
  onClose,
  onGrant,
  onRevoke,
}: AgentPermissionsDialogProps) {
  const { t } = useLanguage()
  const [selectedUserId, setSelectedUserId] = React.useState("")
  const targets = agent
    ? availableAgentPermissionTargets(members, agent, permissions)
    : []
  const selectedTarget =
    targets.find((member) => member.user.id === selectedUserId) ??
    targets[0] ??
    null

  function closeDialog() {
    setSelectedUserId("")
    onClose()
  }

  return (
    <Dialog
      open={Boolean(agent)}
      onOpenChange={(open) => {
        if (!open) closeDialog()
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("资源授权")}</DialogTitle>
          <DialogDescription>{agent?.name ?? ""}</DialogDescription>
        </DialogHeader>

        {isLoading ? (
          <div className="flex min-h-36 items-center justify-center gap-2 text-sm text-muted-foreground">
            <LoaderCircleIcon className="size-4 animate-spin" />
            {t("正在加载")}
          </div>
        ) : agent ? (
          <>
            <form
              onSubmit={(event) => {
                event.preventDefault()
                if (selectedTarget) void onGrant(selectedTarget.user.id)
              }}
            >
              <FieldGroup>
                <Field>
                  <FieldLabel htmlFor="agent-permission-user">
                    {t("用户")}
                  </FieldLabel>
                  <DropdownMenu modal={false}>
                    <DropdownMenuTrigger asChild>
                      <Button
                        id="agent-permission-user"
                        type="button"
                        variant="outline"
                        className="h-10 w-full justify-between px-3 font-normal"
                        disabled={!targets.length || isSaving}
                      >
                        <span
                          className={cn(
                            "min-w-0 flex-1 truncate text-left",
                            !selectedTarget && "text-muted-foreground"
                          )}
                        >
                          {selectedTarget
                            ? `${selectedTarget.user.name} / ${selectedTarget.user.username}`
                            : t("选择用户")}
                        </span>
                        <ChevronDownIcon data-icon="inline-end" />
                      </Button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent
                      align="start"
                      className="w-(--radix-dropdown-menu-trigger-width)"
                    >
                      {targets.map((member) => (
                        <DropdownMenuItem
                          key={member.user.id}
                          className="justify-between"
                          onSelect={() => setSelectedUserId(member.user.id)}
                        >
                          <span className="min-w-0 truncate">
                            {member.user.name} / {member.user.username}
                          </span>
                          {member.user.id === selectedTarget?.user.id ? (
                            <CircleCheckIcon className="text-primary" />
                          ) : null}
                        </DropdownMenuItem>
                      ))}
                    </DropdownMenuContent>
                  </DropdownMenu>
                </Field>
                <Field>
                  <FieldLabel>{t("权限")}</FieldLabel>
                  <div className="flex h-10 items-center rounded-md border px-3">
                    <PermissionBadge permission="view" />
                  </div>
                </Field>
              </FieldGroup>
              <DialogFooter className="pt-5">
                <Button
                  type="submit"
                  disabled={isSaving || !selectedTarget}
                >
                  {isSaving ? (
                    <LoaderCircleIcon data-icon="inline-start" />
                  ) : null}
                  {t("保存授权")}
                </Button>
              </DialogFooter>
            </form>

            <div className="mt-5 rounded-md border">
              {permissions.length ? (
                permissions.map((permission) => (
                  <div
                    key={permission.user.id}
                    className="flex items-center gap-3 border-b px-3 py-2 last:border-b-0"
                  >
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm font-medium">
                        {permission.user.name}
                      </p>
                      <p className="truncate text-xs text-muted-foreground">
                        {permission.user.username}
                      </p>
                    </div>
                    <PermissionBadge permission="view" />
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon-sm"
                      title={t("撤销授权")}
                      aria-label={t("撤销授权")}
                      disabled={isSaving}
                      onClick={() => void onRevoke(permission.user.id)}
                    >
                      <Trash2Icon />
                    </Button>
                  </div>
                ))
              ) : (
                <p className="p-3 text-sm text-muted-foreground">
                  {t("暂无授权")}
                </p>
              )}
            </div>
          </>
        ) : null}
      </DialogContent>
    </Dialog>
  )
}
