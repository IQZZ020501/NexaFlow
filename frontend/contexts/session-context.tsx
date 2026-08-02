"use client"

import * as React from "react"

import { useLanguage } from "@/contexts/language-provider"
import { ApiError } from "@/lib/api-client"
import { getMe, type MeResponse } from "@/lib/api/auth"
import {
  listTeams,
  listWorkspaces,
  type Team,
  type Workspace,
  type WorkspaceCreateResponse,
} from "@/lib/api/system"
import { displayWorkspaceName, hasWorkspaceMembership } from "@/lib/display"
import { getErrorMessage } from "@/lib/errors"
import type { AppNotification } from "@/lib/notifications"
import { TOKEN_KEY, WORKSPACE_KEY } from "@/lib/storage"

type SessionContextValue = {
  token: string | null
  me: MeResponse | null
  workspaces: Workspace[]
  teams: Team[]
  selectedWorkspaceId: string | null
  mustChangePassword: boolean
  isSessionLoading: boolean
  isSessionRestored: boolean
  isTeamsLoading: boolean
  sessionError: string | null
  notification: AppNotification | null
  workspaceNotice: WorkspaceCreateResponse | null
  currentWorkspace: Workspace | null
  workspaceOptions: Workspace[]
  passwordDialogOpen: boolean
  login: (token: string, mustChangePassword: boolean) => void
  logout: () => void
  notify: (kind: AppNotification["kind"], message: string) => void
  dismissNotification: () => void
  openPasswordDialog: () => void
  closePasswordDialog: () => void
  selectWorkspace: (workspaceId: string) => void
  clearSelectedWorkspace: () => void
  workspaceCreated: (payload: WorkspaceCreateResponse) => void
  workspaceUpdated: (workspace: Workspace) => void
  workspaceDeleted: (workspaceId: string) => void
  teamCreated: (team: Team) => void
  teamUpdated: (team: Team) => void
  teamDeleted: (teamId: string) => void
  passwordChanged: () => Promise<void>
}

const SessionContext = React.createContext<SessionContextValue | undefined>(
  undefined
)

export function SessionProvider({ children }: { children: React.ReactNode }) {
  const { t } = useLanguage()
  const [token, setToken] = React.useState<string | null>(null)
  const [mustChangePassword, setMustChangePassword] = React.useState(false)
  const [isPasswordDialogOpen, setIsPasswordDialogOpen] = React.useState(false)
  const [me, setMe] = React.useState<MeResponse | null>(null)
  const [workspaces, setWorkspaces] = React.useState<Workspace[]>([])
  const [teams, setTeams] = React.useState<Team[]>([])
  const [selectedWorkspaceId, setSelectedWorkspaceId] = React.useState<
    string | null
  >(null)
  const [workspaceNotice, setWorkspaceNotice] =
    React.useState<WorkspaceCreateResponse | null>(null)
  const [isSessionLoading, setIsSessionLoading] = React.useState(false)
  const [isSessionRestored, setIsSessionRestored] = React.useState(false)
  const [isTeamsLoading, setIsTeamsLoading] = React.useState(false)
  const [sessionError, setSessionError] = React.useState<string | null>(null)
  const [notification, setNotification] =
    React.useState<AppNotification | null>(null)

  // Hydration-safe restore: localStorage is only readable on the client, so
  // the initial render (server and client alike) starts signed out and the
  // stored token is picked up after mount.
  React.useEffect(() => {
    const storedToken = localStorage.getItem(TOKEN_KEY)
    if (storedToken) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setIsSessionLoading(true)
      setToken(storedToken)
    }
    setIsSessionRestored(true)
  }, [])


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

        const message = getErrorMessage(error, t)
        setSessionError(message)
        notify("error", message)
      } finally {
        setIsSessionLoading(false)
      }
    },
    [logout, notify, t]
  )

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
    if (isSessionLoading || !token || !selectedWorkspaceId || mustChangePassword) {
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
          notify("error", getErrorMessage(error, t))
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
  }, [
    token,
    selectedWorkspaceId,
    mustChangePassword,
    isSessionLoading,
    notify,
    t,
  ])

  function handleLogin(nextToken: string, nextMustChangePassword: boolean) {
    localStorage.setItem(TOKEN_KEY, nextToken)
    setSessionError(null)
    setIsSessionLoading(true)
    setToken(nextToken)
    setMustChangePassword(nextMustChangePassword)
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
    setIsTeamsLoading(true)
    setSelectedWorkspaceId(workspaceId)
    setWorkspaceNotice(null)
  }

  function clearSelectedWorkspace() {
    localStorage.removeItem(WORKSPACE_KEY)
    setTeams([])
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

  const currentWorkspace = React.useMemo(
    () =>
      workspaces.find((workspace) => workspace.id === selectedWorkspaceId) ??
      null,
    [workspaces, selectedWorkspaceId]
  )

  const workspaceOptions = React.useMemo(
    () =>
      workspaces.filter(
        (workspace) =>
          workspace.status === "active" && hasWorkspaceMembership(me, workspace.id)
      ),
    [workspaces, me]
  )

  const value: SessionContextValue = {
    token,
    me,
    workspaces,
    teams,
    selectedWorkspaceId,
    mustChangePassword,
    isSessionLoading,
    isSessionRestored,
    isTeamsLoading,
    sessionError,
    notification,
    workspaceNotice,
    currentWorkspace,
    workspaceOptions,
    passwordDialogOpen: isPasswordDialogOpen,
    login: handleLogin,
    logout,
    notify,
    dismissNotification: () => setNotification(null),
    openPasswordDialog: () => setIsPasswordDialogOpen(true),
    closePasswordDialog: () => setIsPasswordDialogOpen(false),
    selectWorkspace: handleSelectWorkspace,
    clearSelectedWorkspace,
    workspaceCreated: handleWorkspaceCreated,
    workspaceUpdated: handleWorkspaceUpdated,
    workspaceDeleted: handleWorkspaceDeleted,
    teamCreated: handleTeamCreated,
    teamUpdated: handleTeamUpdated,
    teamDeleted: handleTeamDeleted,
    passwordChanged: handlePasswordChanged,
  }

  return (
    <SessionContext.Provider value={value}>
      {children}
    </SessionContext.Provider>
  )
}

export const useSession = () => {
  const context = React.useContext(SessionContext)

  if (context === undefined) {
    throw new Error("useSession must be used within a SessionProvider")
  }

  return context
}

export function useCurrentWorkspaceName() {
  const { t } = useLanguage()
  const { currentWorkspace } = useSession()

  if (!currentWorkspace) {
    return t("未选择工作空间")
  }

  return displayWorkspaceName(currentWorkspace, t)
}
