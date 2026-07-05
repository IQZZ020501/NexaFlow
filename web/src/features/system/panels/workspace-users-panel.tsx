import {
  CircleCheckIcon,
  CircleOffIcon,
  LoaderCircleIcon,
  PlusIcon,
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
import type { Workspace, WorkspaceMember } from "@/lib/api"
import { cn } from "@/lib/utils"
import { displayWorkspaceName, formatDateTime } from "@/app/display"

type WorkspaceUsersPanelProps = {
  selectedWorkspace: Workspace | null
  selectedWorkspaceId: string | null
  workspaceMembers: WorkspaceMember[]
  workspaceMembersError: string | null
  isWorkspaceMembersLoading: boolean
  locale: string
  handleOpenCreateUser: () => void
}

export function WorkspaceUsersPanel({
  selectedWorkspace,
  selectedWorkspaceId,
  workspaceMembers,
  workspaceMembersError,
  isWorkspaceMembersLoading,
  locale,
  handleOpenCreateUser,
}: WorkspaceUsersPanelProps) {
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
              <CardDescription>
                {selectedWorkspace
                  ? displayWorkspaceName(selectedWorkspace, t)
                  : t("未选择工作空间")}
              </CardDescription>
            </div>
          </div>
          <Button
            type="button"
            size="sm"
            disabled={!selectedWorkspaceId}
            onClick={handleOpenCreateUser}
          >
            <PlusIcon data-icon="inline-start" />
            {t("新建用户")}
          </Button>
        </CardHeader>
        <CardContent className="min-w-0 px-4">
          {workspaceMembersError ? (
            <p className="mb-3 text-sm text-destructive">
              {workspaceMembersError}
            </p>
          ) : null}
          {isWorkspaceMembersLoading ? (
            <div className="flex min-h-28 items-center justify-center">
              <LoaderCircleIcon className="animate-spin text-muted-foreground" />
            </div>
          ) : workspaceMembers.length ? (
            <div className="min-w-0 overflow-x-auto rounded-lg border bg-background">
              <div
                role="table"
                aria-label={t("工作空间用户列表")}
                className="min-w-[980px] text-sm"
              >
                <div
                  role="row"
                  className="grid grid-cols-[160px_150px_280px_120px_120px_150px] border-b bg-muted/40 px-4 py-3 text-sm font-semibold text-muted-foreground"
                >
                  <span role="columnheader">{t("用户名")}</span>
                  <span role="columnheader">{t("账号")}</span>
                  <span role="columnheader">{t("邮箱")}</span>
                  <span role="columnheader">{t("空间角色")}</span>
                  <span role="columnheader">{t("状态")}</span>
                  <span role="columnheader">{t("创建时间")}</span>
                </div>
                {workspaceMembers.map((member, index) => {
                  const roleLabel =
                    member.role === "admin" ? t("管理员") : t("成员")

                  return (
                    <div
                      key={member.user.id}
                      role="row"
                      className={cn(
                        "grid grid-cols-[160px_150px_280px_120px_120px_150px] items-center border-b px-4 py-4 last:border-b-0 hover:bg-muted/40",
                        index % 2 === 1 && "bg-muted/20"
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
                        <span className="inline-flex rounded-md border border-border bg-muted px-2 py-0.5 text-xs font-medium whitespace-nowrap">
                          {roleLabel}
                        </span>
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
                          {member.user.is_active ? t("已启用") : t("已停用")}
                        </span>
                      </span>
                      <span
                        role="cell"
                        className="whitespace-nowrap text-muted-foreground"
                      >
                        {formatDateTime(member.user.created_at, locale)}
                      </span>
                    </div>
                  )
                })}
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
