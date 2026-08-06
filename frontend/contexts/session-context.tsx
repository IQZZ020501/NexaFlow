"use client"

import * as React from "react"

import { useLanguage } from "@/contexts/language-provider"
import { ApiError } from "@/lib/api-client"
import {
  getMe,
  logout as endSession,
  refreshAccessToken,
  type MeResponse,
  type User,
} from "@/lib/api/auth"
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
import { LEGACY_TOKEN_KEY, WORKSPACE_KEY } from "@/lib/storage"

const ACCESS_TOKEN_REFRESH_EARLY_SECONDS = 60
const REFRESH_RETRY_MILLISECONDS = 60_000

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
  login: (token: string, mustChangePassword: boolean, expiresIn: number) => void
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
  userUpdated: (user: User) => void
  passwordChanged: () => Promise<void>
}

const SessionContext = React.createContext<SessionContextValue | undefined>(
  undefined
)

export function replaceSessionUser(me: MeResponse | null, user: User) {
  return me?.user.id === user.id ? { ...me, user } : me
}

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
  const [refreshAt, setRefreshAt] = React.useState<number | null>(null)

  const notify = React.useCallback(
    (kind: AppNotification["kind"], message: string) => {
      setNotification({ id: Date.now(), kind, message })
    },
    []
  )

  const clearSession = React.useCallback(() => {
    localStorage.removeItem(LEGACY_TOKEN_KEY)
    localStorage.removeItem(WORKSPACE_KEY)
    setToken(null)
    setRefreshAt(null)
    setMustChangePassword(false)
    setIsPasswordDialogOpen(false)
    setMe(null)
    setWorkspaces([])
    setTeams([])
    setSelectedWorkspaceId(null)
    setWorkspaceNotice(null)
    setSessionError(null)
  }, [])

  const applyAccessToken = React.useCallback(
    (nextToken: string, nextMustChangePassword: boolean, expiresIn: number) => {
      setSessionError(null)
      setIsSessionLoading(true)
      setToken(nextToken)
      setMustChangePassword(nextMustChangePassword)
      setRefreshAt(
        Date.now() +
          Math.max(expiresIn - ACCESS_TOKEN_REFRESH_EARLY_SECONDS, 1) * 1000
      )
    },
    []
  )

  const renewAccessToken = React.useCallback(async () => {
    const payload = await refreshAccessToken()
    applyAccessToken(
      payload.access_token,
      payload.must_change_password,
      payload.expires_in
    )
  }, [applyAccessToken])

  const logout = React.useCallback(() => {
    void endSession().catch(() => undefined)
    clearSession()
  }, [clearSession])

  React.useEffect(() => {
    let isCurrent = true
    let restoredToken = false
    localStorage.removeItem(LEGACY_TOKEN_KEY)
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setIsSessionLoading(true)

    refreshAccessToken()
      .then((payload) => {
        if (!isCurrent) {
          return
        }
        restoredToken = true
        applyAccessToken(
          payload.access_token,
          payload.must_change_password,
          payload.expires_in
        )
      })
      .catch((error: unknown) => {
        if (
          isCurrent &&
          !(error instanceof ApiError && error.status === 401)
        ) {
          const message = getErrorMessage(error, t)
          setSessionError(message)
          notify("error", message)
        }
      })
      .finally(() => {
        if (isCurrent) {
          setIsSessionRestored(true)
          if (!restoredToken) {
            setIsSessionLoading(false)
          }
        }
      })

    return () => {
      isCurrent = false
    }
  }, [applyAccessToken, notify, t])

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
          try {
            await renewAccessToken()
          } catch {
            clearSession()
          }
          return
        }

        const message = getErrorMessage(error, t)
        setSessionError(message)
        notify("error", message)
      } finally {
        setIsSessionLoading(false)
      }
    },
    [clearSession, notify, renewAccessToken, t]
  )

  React.useEffect(() => {
    if (!token) {
      return
    }

    // eslint-disable-next-line react-hooks/set-state-in-effect
    void loadSession(token)
  }, [token, loadSession])

  React.useEffect(() => {
    if (!token || refreshAt === null) {
      return
    }

    const timer = window.setTimeout(() => {
      void renewAccessToken().catch((error: unknown) => {
        if (error instanceof ApiError && error.status === 401) {
          clearSession()
          return
        }

        setRefreshAt(Date.now() + REFRESH_RETRY_MILLISECONDS)
        notify("error", getErrorMessage(error, t))
      })
    }, Math.max(refreshAt - Date.now(), 0))

    return () => window.clearTimeout(timer)
  }, [clearSession, notify, refreshAt, renewAccessToken, t, token])

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

  function handleLogin(
    nextToken: string,
    nextMustChangePassword: boolean,
    expiresIn: number
  ) {
    applyAccessToken(nextToken, nextMustChangePassword, expiresIn)
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

  function handleUserUpdated(user: User) {
    setMe((current) => replaceSessionUser(current, user))
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
    userUpdated: handleUserUpdated,
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
