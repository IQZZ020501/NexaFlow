import * as React from "react"
import { LoaderCircleIcon } from "lucide-react"
import { useLanguage } from "@/components/language-provider"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { getMe } from "@/features/auth/api"
import type { MeResponse } from "@/features/auth/types"
import { ApiError } from "@/lib/api-client"
import { listTeams, listWorkspaces } from "@/features/system/api"
import {
  type Team,
  type Workspace,
  type WorkspaceCreateResponse,
} from "@/features/system/types"
import { getPages, type PageKey } from "@/lib/pages"
import { displayWorkspaceName, hasWorkspaceMembership } from "@/app/display"
import { getErrorMessage } from "@/app/errors"
import type { AppNotification } from "@/app/notifications"
import {
  PAGE_PATHS,
  pathForRoute,
  routeFromPath,
  type AppRoute,
  type SystemTabKey,
} from "@/app/routing"
import { TOKEN_KEY, WORKSPACE_KEY } from "@/app/storage"
import { OperationNotification } from "@/components/app/operation-notification"
import { TopBar } from "@/components/app/top-bar"
import { ChangePasswordDialog } from "@/features/auth/change-password-dialog"
import { LoginScreen } from "@/features/auth/login-screen"
import { FeaturePage } from "@/features/pages/feature-page"
import { SystemPage } from "@/features/system/system-page"

export function App() {
  const { t } = useLanguage()
  const [token, setToken] = React.useState<string | null>(() =>
    localStorage.getItem(TOKEN_KEY)
  )
  const [mustChangePassword, setMustChangePassword] = React.useState(false)
  const [isPasswordDialogOpen, setIsPasswordDialogOpen] = React.useState(false)
  const [me, setMe] = React.useState<MeResponse | null>(null)
  const [workspaces, setWorkspaces] = React.useState<Workspace[]>([])
  const [teams, setTeams] = React.useState<Team[]>([])
  const [activePage, setActivePage] = React.useState<PageKey>(
    () => routeFromPath().page
  )
  const [activeSystemTab, setActiveSystemTab] = React.useState<SystemTabKey>(
    () => routeFromPath().systemTab
  )
  const [selectedWorkspaceId, setSelectedWorkspaceId] = React.useState<
    string | null
  >(() => localStorage.getItem(WORKSPACE_KEY))
  const [workspaceNotice, setWorkspaceNotice] =
    React.useState<WorkspaceCreateResponse | null>(null)
  const [isSessionLoading, setIsSessionLoading] = React.useState(Boolean(token))
  const [isTeamsLoading, setIsTeamsLoading] = React.useState(false)
  const [sessionError, setSessionError] = React.useState<string | null>(null)
  const [teamsError, setTeamsError] = React.useState<string | null>(null)
  const [notification, setNotification] =
    React.useState<AppNotification | null>(null)

  const logout = React.useCallback(() => {
    localStorage.removeItem(TOKEN_KEY)
    localStorage.removeItem(WORKSPACE_KEY)
    setToken(null)
    setMustChangePassword(false)
    setIsPasswordDialogOpen(false)
    setMe(null)
    setWorkspaces([])
    setTeams([])
    setSelectedWorkspaceId(null)
    setWorkspaceNotice(null)
    setSessionError(null)
    setTeamsError(null)
    setActivePage("apps")
    setActiveSystemTab("workspaces")
    window.history.pushState(null, "", PAGE_PATHS.apps)
  }, [])

  const notify = React.useCallback(
    (kind: AppNotification["kind"], message: string) => {
      setNotification({ id: Date.now(), kind, message })
    },
    []
  )

  const loadSession = React.useCallback(
    async (nextToken: string) => {
      try {
        const nextMe = await getMe(nextToken)
        setMe(nextMe)
        setMustChangePassword(nextMe.user.must_change_password)
        setSessionError(null)

        if (nextMe.user.must_change_password) {
          setWorkspaces([])
          setTeams([])
          setIsTeamsLoading(false)
          return
        }

        const nextWorkspaces = await listWorkspaces(nextToken)
        const storedWorkspaceId = localStorage.getItem(WORKSPACE_KEY)
        const activeNextWorkspaces = nextWorkspaces.filter(
          (workspace) => workspace.status === "active"
        )
        const membershipWorkspaceIds = new Set(
          nextMe.memberships.map((membership) => membership.workspace_id)
        )
        const nextWorkspaceId =
          activeNextWorkspaces.find(
            (workspace) =>
              workspace.id === storedWorkspaceId &&
              membershipWorkspaceIds.has(workspace.id)
          )?.id ??
          activeNextWorkspaces.find((workspace) =>
            membershipWorkspaceIds.has(workspace.id)
          )?.id ??
          null

        setWorkspaces(nextWorkspaces)
        setTeams([])
        setTeamsError(null)
        setIsTeamsLoading(Boolean(nextWorkspaceId))
        setSelectedWorkspaceId(nextWorkspaceId)

        if (nextWorkspaceId) {
          localStorage.setItem(WORKSPACE_KEY, nextWorkspaceId)
        } else {
          localStorage.removeItem(WORKSPACE_KEY)
        }
      } catch (error) {
        if (error instanceof ApiError && error.status === 401) {
          logout()
          return
        }

        setSessionError(getErrorMessage(error, t))
      } finally {
        setIsSessionLoading(false)
      }
    },
    [logout, t]
  )

  React.useEffect(() => {
    function handlePopState() {
      const route = routeFromPath()
      setActivePage(route.page)
      setActiveSystemTab(route.systemTab)
    }

    window.addEventListener("popstate", handlePopState)
    return () => window.removeEventListener("popstate", handlePopState)
  }, [])

  React.useEffect(() => {
    if (!token) {
      return
    }

    // eslint-disable-next-line react-hooks/set-state-in-effect
    void loadSession(token)
  }, [token, loadSession])

  React.useEffect(() => {
    if (!notification) {
      return
    }

    const timer = window.setTimeout(() => {
      setNotification((current) =>
        current?.id === notification.id ? null : current
      )
    }, 3200)

    return () => window.clearTimeout(timer)
  }, [notification])

  React.useEffect(() => {
    if (
      isSessionLoading ||
      !token ||
      !selectedWorkspaceId ||
      mustChangePassword
    ) {
      return
    }

    let isCurrent = true

    listTeams(token, selectedWorkspaceId)
      .then((payload) => {
        if (isCurrent) {
          setTeams(payload)
        }
      })
      .catch((error: unknown) => {
        if (isCurrent) {
          setTeams([])
          setTeamsError(getErrorMessage(error, t))
        }
      })
      .finally(() => {
        if (isCurrent) {
          setIsTeamsLoading(false)
        }
      })

    return () => {
      isCurrent = false
    }
  }, [token, selectedWorkspaceId, mustChangePassword, isSessionLoading, t])

  function handleLogin(nextToken: string, nextMustChangePassword: boolean) {
    localStorage.setItem(TOKEN_KEY, nextToken)
    setSessionError(null)
    setIsSessionLoading(true)
    setToken(nextToken)
    setMustChangePassword(nextMustChangePassword)
  }

  function navigateToRoute(route: AppRoute) {
    const path = pathForRoute(route)

    if (window.location.pathname !== path) {
      window.history.pushState(null, "", path)
    }

    setActivePage(route.page)
    setActiveSystemTab(route.systemTab)
  }

  function handlePageChange(page: PageKey) {
    navigateToRoute({
      page,
      systemTab: page === "system" ? activeSystemTab : "workspaces",
    })
  }

  function handleSystemTabChange(tab: SystemTabKey) {
    navigateToRoute({ page: "system", systemTab: tab })
  }

  function handleSelectWorkspace(workspaceId: string) {
    if (workspaceId === selectedWorkspaceId) {
      return
    }

    const nextWorkspace = workspaces.find(
      (workspace) => workspace.id === workspaceId
    )
    if (
      !nextWorkspace ||
      nextWorkspace.status !== "active" ||
      !hasWorkspaceMembership(me, workspaceId)
    ) {
      return
    }

    localStorage.setItem(WORKSPACE_KEY, workspaceId)
    setTeams([])
    setTeamsError(null)
    setIsTeamsLoading(true)
    setSelectedWorkspaceId(workspaceId)
    setWorkspaceNotice(null)
  }

  function clearSelectedWorkspace() {
    localStorage.removeItem(WORKSPACE_KEY)
    setTeams([])
    setTeamsError(null)
    setIsTeamsLoading(false)
    setSelectedWorkspaceId(null)
    setWorkspaceNotice(null)
  }

  function handleWorkspaceCreated(payload: WorkspaceCreateResponse) {
    setWorkspaces((current) => [...current, payload.workspace])
    setWorkspaceNotice(payload)
  }

  function handleWorkspaceUpdated(workspace: Workspace) {
    const nextWorkspaces = workspaces.map((item) =>
      item.id === workspace.id ? workspace : item
    )
    setWorkspaces(nextWorkspaces)

    if (workspace.id === selectedWorkspaceId && workspace.status !== "active") {
      const nextWorkspace = nextWorkspaces.find(
        (item) =>
          item.id !== workspace.id &&
          item.status === "active" &&
          hasWorkspaceMembership(me, item.id)
      )
      if (nextWorkspace) {
        handleSelectWorkspace(nextWorkspace.id)
      } else {
        clearSelectedWorkspace()
      }
    }
  }

  function handleWorkspaceDeleted(workspaceId: string) {
    const nextWorkspaces = workspaces.filter((item) => item.id !== workspaceId)
    setWorkspaces(nextWorkspaces)

    if (workspaceId === selectedWorkspaceId) {
      const nextWorkspace = nextWorkspaces.find(
        (item) =>
          item.status === "active" && hasWorkspaceMembership(me, item.id)
      )
      if (nextWorkspace) {
        handleSelectWorkspace(nextWorkspace.id)
      } else {
        clearSelectedWorkspace()
      }
    }
  }

  function handleTeamCreated(team: Team) {
    setTeams((current) => [...current, team])
  }

  function handleTeamUpdated(team: Team) {
    setTeams((current) =>
      current.map((item) => (item.id === team.id ? team : item))
    )
  }

  function handleTeamDeleted(teamId: string) {
    setTeams((current) => current.filter((item) => item.id !== teamId))
  }

  async function handlePasswordChanged() {
    setIsSessionLoading(true)
    setSessionError(null)
    setMustChangePassword(false)
    setIsPasswordDialogOpen(false)
    if (token) {
      await loadSession(token)
    }
    notify("success", t("密码已修改"))
  }

  if (!token) {
    return <LoginScreen onLogin={handleLogin} />
  }

  if (isSessionLoading && !me) {
    return (
      <main className="flex min-h-svh items-center justify-center bg-background">
        <LoaderCircleIcon className="animate-spin text-muted-foreground" />
      </main>
    )
  }

  if (!me) {
    return (
      <main className="flex min-h-svh items-center justify-center bg-muted/30 p-6">
        <Card className="w-full max-w-sm">
          <CardHeader>
            <CardTitle>{t("无法加载账号")}</CardTitle>
            <CardDescription>{sessionError ?? t("请重新登录")}</CardDescription>
          </CardHeader>
          <CardFooter>
            <Button className="w-full" onClick={logout}>
              {t("重新登录")}
            </Button>
          </CardFooter>
        </Card>
      </main>
    )
  }

  const featurePages = getPages(t)
  const activePageConfig = featurePages.find((page) => page.key === activePage)
  const activePageTitle = activePageConfig?.label ?? t("系统管理")
  const isChangePasswordDialogOpen = mustChangePassword || isPasswordDialogOpen
  const currentWorkspace =
    workspaces.find((workspace) => workspace.id === selectedWorkspaceId) ?? null
  const currentWorkspaceName = currentWorkspace
    ? displayWorkspaceName(currentWorkspace, t)
    : t("未选择工作空间")
  const workspaceOptions = workspaces.filter(
    (workspace) =>
      workspace.status === "active" && hasWorkspaceMembership(me, workspace.id)
  )

  return (
    <div className="min-h-svh overflow-x-hidden bg-muted/20">
      <TopBar
        me={me}
        activePage={activePage}
        featurePages={featurePages}
        currentWorkspaceName={currentWorkspaceName}
        selectedWorkspaceId={selectedWorkspaceId}
        workspaceOptions={workspaceOptions}
        onPageChange={handlePageChange}
        onSelectWorkspace={handleSelectWorkspace}
        onChangePassword={() => setIsPasswordDialogOpen(true)}
        onLogout={logout}
      />
      <OperationNotification
        notification={notification}
        onDismiss={() => setNotification(null)}
      />
      <main className="flex w-full min-w-0 flex-col gap-4 overflow-x-hidden px-4 py-6 sm:px-6 lg:px-8">
        {sessionError ? (
          <p className="text-sm text-destructive">{sessionError}</p>
        ) : null}

        {activePage === "system" ? (
          <>
            <div className="flex min-w-0 flex-col gap-1">
              <h1 className="truncate text-xl font-semibold">
                {activePageTitle}
              </h1>
            </div>
            <SystemPage
              me={me}
              token={token}
              workspaces={workspaces}
              teams={teams}
              selectedWorkspaceId={selectedWorkspaceId}
              workspaceNotice={workspaceNotice}
              isTeamsLoading={isTeamsLoading}
              teamsError={teamsError}
              activeSystemTab={activeSystemTab}
              onSelectWorkspace={handleSelectWorkspace}
              onSystemTabChange={handleSystemTabChange}
              onWorkspaceCreated={handleWorkspaceCreated}
              onWorkspaceUpdated={handleWorkspaceUpdated}
              onWorkspaceDeleted={handleWorkspaceDeleted}
              onTeamCreated={handleTeamCreated}
              onTeamUpdated={handleTeamUpdated}
              onTeamDeleted={handleTeamDeleted}
              onNotify={notify}
            />
          </>
        ) : (
          <FeaturePage
            page={activePageConfig ?? featurePages[0]}
            token={token}
            me={me}
            selectedWorkspaceId={selectedWorkspaceId}
            onNotify={notify}
          />
        )}
      </main>
      <ChangePasswordDialog
        open={isChangePasswordDialogOpen}
        token={token}
        title={mustChangePassword ? t("修改初始密码") : t("修改密码")}
        description={
          mustChangePassword
            ? t("设置新密码后继续使用 NexaFlow")
            : t("设置一个新的登录密码")
        }
        canDismiss={!mustChangePassword}
        requireCurrentPassword={!mustChangePassword}
        onOpenChange={setIsPasswordDialogOpen}
        onChanged={() => void handlePasswordChanged()}
      />
    </div>
  )
}

export default App
