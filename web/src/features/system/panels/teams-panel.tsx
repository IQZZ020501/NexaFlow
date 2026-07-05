import {
  ArchiveIcon,
  PencilIcon,
  PlusIcon,
  RotateCcwIcon,
  Trash2Icon,
  UsersIcon,
  LoaderCircleIcon,
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
import type { Team, Workspace } from "@/lib/api"
import { displayTeamName, displayWorkspaceName } from "@/app/display"
import { StatusBadge } from "@/features/knowledge/status-badges"

type TeamsPanelProps = {
  selectedWorkspace: Workspace | null
  teams: Team[]
  teamsError: string | null
  isTeamsLoading: boolean
  canCreateTeam: boolean
  canManageWorkspace: boolean
  handleOpenCreateTeam: () => void
  handleOpenEditTeam: (team: Team) => void
  handleArchiveTeam: (team: Team) => void | Promise<void>
  handleDeleteTeam: (team: Team) => void | Promise<void>
}

export function TeamsPanel({
  selectedWorkspace,
  teams,
  teamsError,
  isTeamsLoading,
  canCreateTeam,
  canManageWorkspace,
  handleOpenCreateTeam,
  handleOpenEditTeam,
  handleArchiveTeam,
  handleDeleteTeam,
}: TeamsPanelProps) {
  const { t } = useLanguage()

  return (
    <div
      id="system-panel-teams"
      role="tabpanel"
      aria-labelledby="system-tab-teams"
      className="grid gap-4 lg:h-full lg:overflow-y-auto lg:pr-1"
    >
      <Card className="min-w-0 gap-4 border-border/70 py-5 shadow-sm lg:min-h-full">
        <CardHeader className="flex-row items-start justify-between gap-4 px-5">
          <div className="flex min-w-0 items-start gap-3">
            <span className="flex size-8 shrink-0 items-center justify-center rounded-lg border bg-background">
              <UsersIcon className="size-4" />
            </span>
            <div className="min-w-0">
              <CardTitle>{t("团队")}</CardTitle>
              <CardDescription>
                {selectedWorkspace
                  ? displayWorkspaceName(selectedWorkspace, t)
                  : t("未选择工作空间")}
              </CardDescription>
            </div>
          </div>
          {canCreateTeam ? (
            <Button type="button" size="sm" onClick={handleOpenCreateTeam}>
              <PlusIcon data-icon="inline-start" />
              {t("新建团队")}
            </Button>
          ) : null}
        </CardHeader>
        <CardContent className="min-w-0 px-5">
          {teamsError ? (
            <p className="text-sm text-destructive">{teamsError}</p>
          ) : isTeamsLoading ? (
            <div className="flex min-h-28 items-center justify-center">
              <LoaderCircleIcon className="animate-spin text-muted-foreground" />
            </div>
          ) : teams.length ? (
            <div className="flex flex-col gap-2">
              {teams.map((team) => {
                const isArchived = team.status === "archived"

                return (
                  <div
                    key={team.id}
                    className="flex items-center justify-between gap-3 rounded-lg border bg-background px-4 py-2.5 text-sm shadow-xs"
                  >
                    <span className="flex min-w-0 flex-col gap-1">
                      <span className="truncate font-medium">
                        {displayTeamName(team, t)}
                      </span>
                      <span className="truncate text-muted-foreground">
                        {team.description || "-"}
                      </span>
                    </span>
                    <span className="flex shrink-0 items-center gap-2">
                      {team.is_default ? (
                        <Badge variant="outline">{t("默认")}</Badge>
                      ) : null}
                      <StatusBadge status={team.status} />
                      {canManageWorkspace ? (
                        <>
                          <Button
                            type="button"
                            variant="ghost"
                            size="icon-sm"
                            onClick={() => handleOpenEditTeam(team)}
                            title={t("编辑团队")}
                            aria-label={t("编辑团队")}
                          >
                            <PencilIcon />
                          </Button>
                          <Button
                            type="button"
                            variant="ghost"
                            size="icon-sm"
                            disabled={team.is_default}
                            onClick={() => void handleArchiveTeam(team)}
                            title={isArchived ? t("恢复团队") : t("归档团队")}
                            aria-label={
                              isArchived ? t("恢复团队") : t("归档团队")
                            }
                          >
                            {isArchived ? <RotateCcwIcon /> : <ArchiveIcon />}
                          </Button>
                          <Button
                            type="button"
                            variant="ghost"
                            size="icon-sm"
                            disabled={team.is_default}
                            onClick={() => void handleDeleteTeam(team)}
                            title={t("永久删除团队")}
                            aria-label={t("永久删除团队")}
                          >
                            <Trash2Icon />
                          </Button>
                        </>
                      ) : null}
                    </span>
                  </div>
                )
              })}
            </div>
          ) : (
            <div className="flex min-h-28 items-center justify-center rounded-lg border border-dashed bg-muted/20">
              <p className="text-sm text-muted-foreground">{t("暂无团队")}</p>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
