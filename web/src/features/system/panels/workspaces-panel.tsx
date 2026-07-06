import {
  ArchiveIcon,
  Building2Icon,
  PencilIcon,
  PlusIcon,
  RotateCcwIcon,
  Trash2Icon,
} from "lucide-react"
import { useLanguage } from "@/components/language-provider"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import type { MeResponse, Workspace } from "@/features/system/types"
import { cn } from "@/lib/utils"
import { displayWorkspaceName, getMembershipRole } from "@/app/display"
import { StatusBadge } from "@/features/knowledge/status-badges"

type WorkspacesPanelProps = {
  me: MeResponse
  workspaces: Workspace[]
  selectedWorkspaceId: string | null
  workspaceError: string | null
  canCreateWorkspace: boolean
  onSelectWorkspace: (workspaceId: string) => void
  onOpenCreateWorkspace: () => void
  handleOpenEditWorkspace: (workspace: Workspace) => void
  handleArchiveWorkspace: (workspace: Workspace) => void | Promise<void>
  handleDeleteWorkspace: (workspace: Workspace) => void | Promise<void>
}

export function WorkspacesPanel({
  me,
  workspaces,
  selectedWorkspaceId,
  workspaceError,
  canCreateWorkspace,
  onSelectWorkspace,
  onOpenCreateWorkspace,
  handleOpenEditWorkspace,
  handleArchiveWorkspace,
  handleDeleteWorkspace,
}: WorkspacesPanelProps) {
  const { t } = useLanguage()

  return (
    <div
      id="system-panel-workspaces"
      role="tabpanel"
      aria-labelledby="system-tab-workspaces"
      className="grid gap-4 lg:h-full lg:overflow-y-auto lg:pr-1"
    >
      <Card className="min-w-0 gap-3 border-border/70 py-4 shadow-sm lg:min-h-full">
        <CardHeader className="flex-row items-start justify-between gap-4 px-4">
          <div className="flex min-w-0 items-start gap-3">
            <span className="flex size-8 shrink-0 items-center justify-center rounded-lg border bg-background">
              <Building2Icon className="size-4" />
            </span>
            <div className="min-w-0">
              <CardTitle>{t("工作空间")}</CardTitle>
              <CardDescription>{t("当前租户范围")}</CardDescription>
            </div>
          </div>
          {canCreateWorkspace ? (
            <Button
              type="button"
              size="sm"
              onClick={() => onOpenCreateWorkspace()}
            >
              <PlusIcon data-icon="inline-start" />
              {t("新建工作空间")}
            </Button>
          ) : null}
        </CardHeader>
        <CardContent className="min-w-0 px-4">
          {workspaceError ? (
            <p className="mb-3 text-sm text-destructive">{workspaceError}</p>
          ) : null}
          {workspaces.length ? (
            <div className="flex flex-col gap-2">
              {workspaces.map((workspace) => {
                const isSelected = workspace.id === selectedWorkspaceId
                const isArchived = workspace.status === "archived"
                const workspaceRole = getMembershipRole(me, workspace.id)
                const canUseThisWorkspace = Boolean(workspaceRole)
                const canManageThisWorkspace = me.user.is_global_admin

                return (
                  <div
                    key={workspace.id}
                    className={cn(
                      "flex w-full items-center justify-between gap-3 rounded-lg border bg-background px-4 py-2.5 text-left text-sm shadow-xs transition-colors hover:border-foreground/30 hover:bg-muted/50",
                      isSelected && "border-foreground bg-muted/60 shadow-sm"
                    )}
                  >
                    <button
                      type="button"
                      className="flex min-w-0 flex-1 flex-col gap-1 text-left disabled:cursor-not-allowed disabled:opacity-60"
                      disabled={isArchived || !canUseThisWorkspace}
                      onClick={() => onSelectWorkspace(workspace.id)}
                      title={
                        canUseThisWorkspace
                          ? t("切换工作空间")
                          : t("仅系统管理，无工作空间权限")
                      }
                    >
                      <span className="truncate font-medium">
                        {displayWorkspaceName(workspace, t)}
                      </span>
                      <span className="truncate text-muted-foreground">
                        {workspace.description || "-"}
                      </span>
                    </button>
                    <span className="flex shrink-0 items-center gap-2">
                      {workspace.is_default ? (
                        <Badge variant="outline">{t("默认")}</Badge>
                      ) : null}
                      <StatusBadge status={workspace.status} />
                      {canManageThisWorkspace ? (
                        <>
                          <Button
                            type="button"
                            variant="ghost"
                            size="icon-sm"
                            onClick={() => handleOpenEditWorkspace(workspace)}
                            title={t("编辑工作空间")}
                            aria-label={t("编辑工作空间")}
                          >
                            <PencilIcon />
                          </Button>
                          <Button
                            type="button"
                            variant="ghost"
                            size="icon-sm"
                            disabled={workspace.is_default}
                            onClick={() =>
                              void handleArchiveWorkspace(workspace)
                            }
                            title={
                              isArchived ? t("恢复工作空间") : t("归档工作空间")
                            }
                            aria-label={
                              isArchived ? t("恢复工作空间") : t("归档工作空间")
                            }
                          >
                            {isArchived ? <RotateCcwIcon /> : <ArchiveIcon />}
                          </Button>
                        </>
                      ) : null}
                      {canCreateWorkspace ? (
                        <Button
                          type="button"
                          variant="ghost"
                          size="icon-sm"
                          disabled={workspace.is_default}
                          onClick={() => void handleDeleteWorkspace(workspace)}
                          title={t("永久删除工作空间")}
                          aria-label={t("永久删除工作空间")}
                        >
                          <Trash2Icon />
                        </Button>
                      ) : null}
                    </span>
                  </div>
                )
              })}
            </div>
          ) : (
            <div className="flex min-h-28 items-center justify-center rounded-lg border border-dashed bg-muted/20">
              <p className="text-sm text-muted-foreground">
                {t("暂无工作空间")}
              </p>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
