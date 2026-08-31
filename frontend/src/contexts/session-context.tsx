"use client"

import * as React from "react"
import { usePathname } from "next/navigation"

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
import { LEGACY_TOKEN_KEY, LOGGED_OUT_KEY, WORKSPACE_KEY } from "@/lib/storage"

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
  switchWorkspace: (workspaceId: string) => void
  clearSelectedWorkspace: () => void
  workspaceCreated: (payload: WorkspaceCreateResponse) => void
  workspaceUpdated: (workspace: Workspace) => void
  workspaceDeleted: (workspaceId: string) => void
  teamCreated: (team: Team, adminUserId?: string) => void
  teamUpdated: (team: Team) => void
  teamDeleted: (teamId: string) => void
  userUpdated: (user: User) => void
  passwordChanged: () => Promise<void>
}

const SessionContext = React.createContext<SessionContextValue | undefined>(
  undefined
)

/**
 * Replaces the session user when the supplied user belongs to the current session.
 *
 * @param me - The current session data, or `null` when no session exists
 * @param user - The user data to apply
 * @returns The updated session data when user IDs match; otherwise, the original session data
 */
export function replaceSessionUser(me: MeResponse | null, user: User) {
  return me?.user.id === user.id ? { ...me, user } : me
}

/**
 * Adds an administrator membership for a newly created workspace when the current user created it.
 *
 * @param me - The current user and their workspace memberships
 * @param payload - The newly created workspace and its administrator
 * @returns The updated user data, or `me` when no membership is added
 */
export function addCreatedWorkspaceMembership(
  me: MeResponse | null,
  payload: WorkspaceCreateResponse
) {
  if (
    !me ||
    me.user.id !== payload.admin_user.id ||
    me.memberships.some(
      (membership) => membership.workspace_id === payload.workspace.id
    )
  ) {
    return me
  }

  return {
    ...me,
    memberships: [
      ...me.memberships,
      { workspace_id: payload.workspace.id, role: "admin" },
    ],
  }
}

/**
 * Adds a newly created team to the administrator's team memberships.
 *
 * @param me - The current session user data, or `null`
 * @param team - The newly created team
 * @param adminUserId - The user ID designated as the team's administrator
 * @returns Session user data with the team added when applicable, otherwise the original value
 */
export function addCreatedTeamMembership(
  me: MeResponse | null,
  team: Team,
  adminUserId: string
) {
  if (!me || me.user.id !== adminUserId) {
    return me
  }

  if (me.user.teams.some((item) => item.id === team.id)) {
    return me
  }

  return {
    ...me,
    user: {
      ...me.user,
      teams: [
        ...me.user.teams,
        {
          id: team.id,
          workspace_id: team.workspace_id,
          name: team.name,
          is_default: team.is_default,
          role: "admin",
        },
      ],
    },
  }
}

/**
 * Selects the initial active workspace accessible to the user.
 *
 * @param me - The current user's session data
 * @param workspaces - The available workspaces
 * @param storedWorkspaceId - The previously selected workspace ID, if available
 * @returns The stored workspace ID when eligible, otherwise the first eligible active workspace ID, or `null` when none is available
 */
export function getInitialWorkspaceId(
  me: MeResponse,
  workspaces: Workspace[],
  storedWorkspaceId: string | null
) {
  const activeWorkspaces = workspaces.filter(
    (workspace) => workspace.status === "active"
  )

  return (
    activeWorkspaces.find(
      (workspace) =>
        workspace.id === storedWorkspaceId &&
        hasWorkspaceMembership(me, workspace.id)
    )?.id ??
    activeWorkspaces.find((workspace) =>
      hasWorkspaceMembership(me, workspace.id)
    )?.id ??
    null
  )
}

/**
 * Provides authentication state, session lifecycle management, workspace and team data, and session operations to descendant components.
 *
 * @param children - The components rendered within the session context
 */
export function SessionProvider({ children }: { children: React.ReactNode }) {
  const { t } = useLanguage()
  const pathname = usePathname()
  const initialPathnameRef = React.useRef(pathname)
  const tRef = React.useRef(t)
  const [token, setToken] = React.useState<string | null>(null)
  const [mustChangePassword, setMustChangePassword] = React.useState(false)
  const [isPasswordDialogOpen, setIsPasswordDialogOpen] = React.useState(false)
  const [me, setMe] = React.useState<MeResponse | null>(null)
  const [workspaces, setWorkspaces] = React.useState<Workspace[]>([])
  const [teams, setTeams] = React.useState<Team[]>([])
  const [selectedWorkspaceId, setSelectedWorkspaceId] = React.useState<
    string | null
  >(null)
  const [pendingWorkspaceId, setPendingWorkspaceId] = React.useState<
    string | null
  >(null)
  const [isSessionLoading, setIsSessionLoading] = React.useState(false)
  const [isSessionRestored, setIsSessionRestored] = React.useState(false)
  const [isTeamsLoading, setIsTeamsLoading] = React.useState(false)
  const [sessionError, setSessionError] = React.useState<string | null>(null)
  const [notification, setNotification] =
    React.useState<AppNotification | null>(null)
  const [refreshAt, setRefreshAt] = React.useState<number | null>(null)

  React.useEffect(() => {
    tRef.current = t
  }, [t])

  const notify = React.useCallback(
    (kind: AppNotification["kind"], message: string) => {
      setNotification({ id: Date.now(), kind, message })
    },
    []
  )

  const applyWorkspaceSelection = React.useCallback((workspaceId: string) => {
    localStorage.setItem(WORKSPACE_KEY, workspaceId)
    setTeams([])
    setIsTeamsLoading(true)
    setSelectedWorkspaceId(workspaceId)
  }, [])

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
    setPendingWorkspaceId(null)
    setSessionError(null)
  }, [])

  const applyAccessToken = React.useCallback(
    (nextToken: string, nextMustChangePassword: boolean, expiresIn: number) => {
      localStorage.removeItem(LOGGED_OUT_KEY)
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
    if (localStorage.getItem(LOGGED_OUT_KEY)) {
      return false
    }

    const payload = await refreshAccessToken()
    if (localStorage.getItem(LOGGED_OUT_KEY)) {
      return false
    }

    applyAccessToken(
      payload.access_token,
      payload.must_change_password,
      payload.expires_in
    )
    return true
  }, [applyAccessToken])

  const logout = React.useCallback(() => {
    localStorage.setItem(LOGGED_OUT_KEY, "1")
    void endSession().catch(() => undefined)
    clearSession()
  }, [clearSession])

  React.useEffect(() => {
    let isCurrent = true
    let restoredToken = false
    localStorage.removeItem(LEGACY_TOKEN_KEY)
    // Login is anonymous; probing an HttpOnly cookie here only creates expected 401 noise.
    if (
      initialPathnameRef.current === "/login" ||
      localStorage.getItem(LOGGED_OUT_KEY)
    ) {
      setIsSessionRestored(true)
      return
    }
    setIsSessionLoading(true)

    refreshAccessToken()
      .then((payload) => {
        if (!isCurrent || localStorage.getItem(LOGGED_OUT_KEY)) {
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
          const message = getErrorMessage(error, tRef.current)
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
  }, [applyAccessToken, notify])

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
        const nextWorkspaceId = getInitialWorkspaceId(
          nextMe,
          nextWorkspaces,
          storedWorkspaceId
        )

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
            const renewed = await renewAccessToken()
            if (!renewed) {
              clearSession()
            }
          } catch {
            clearSession()
          }
          return
        }

        const message = getErrorMessage(error, tRef.current)
        setSessionError(message)
        notify("error", message)
      } finally {
        setIsSessionLoading(false)
      }
    },
    [clearSession, notify, renewAccessToken]
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
        notify("error", getErrorMessage(error, tRef.current))
      })
    }, Math.max(refreshAt - Date.now(), 0))

    return () => window.clearTimeout(timer)
  }, [clearSession, notify, refreshAt, renewAccessToken, token])

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
          notify("error", getErrorMessage(error, tRef.current))
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
  ])

  React.useEffect(() => {
    if (!pendingWorkspaceId || pathname !== "/app/apps") {
      return
    }

    const nextWorkspace = workspaces.find(
      (workspace) =>
        workspace.id === pendingWorkspaceId &&
        workspace.status === "active" &&
        hasWorkspaceMembership(me, workspace.id)
    )
    // eslint-disable-next-line react-hooks/set-state-in-effect -- complete the switch only after leaving the old resource route
    setPendingWorkspaceId(null)
    if (!nextWorkspace) {
      return
    }

    applyWorkspaceSelection(nextWorkspace.id)
    notify(
      "success",
      tRef.current("已切换到 {workspace}", {
        workspace: displayWorkspaceName(nextWorkspace, tRef.current),
      })
    )
  }, [
    applyWorkspaceSelection,
    me,
    notify,
    pathname,
    pendingWorkspaceId,
    workspaces,
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

    applyWorkspaceSelection(workspaceId)
  }

  function handleSwitchWorkspace(workspaceId: string) {
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
    setPendingWorkspaceId(workspaceId)
  }

  function clearSelectedWorkspace() {
    localStorage.removeItem(WORKSPACE_KEY)
    setTeams([])
    setIsTeamsLoading(false)
    setSelectedWorkspaceId(null)
  }

  function handleWorkspaceCreated(payload: WorkspaceCreateResponse) {
    setWorkspaces((current) => [...current, payload.workspace])
    setMe((current) => addCreatedWorkspaceMembership(current, payload))
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

  function handleTeamCreated(team: Team, adminUserId?: string) {
    setTeams((current) => [...current, team])
    if (adminUserId) {
      setMe((current) => addCreatedTeamMembership(current, team, adminUserId))
    }
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
    switchWorkspace: handleSwitchWorkspace,
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

/**
 * Provides the localized name of the selected workspace.
 *
 * @returns The localized workspace name, or a localized message when no workspace is selected
 */
export function useCurrentWorkspaceName() {
  const { t } = useLanguage()
  const { currentWorkspace } = useSession()

  if (!currentWorkspace) {
    return t("未选择工作空间")
  }

  return displayWorkspaceName(currentWorkspace, t)
}
