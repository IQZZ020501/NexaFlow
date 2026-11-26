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
 * Captures the initial browser route once on mount without keeping the provider
 * subscribed to every subsequent route change.
 */
function SessionBootstrapObserver({
  onCapture,
}: {
  onCapture: (pathname: string) => void
}) {
  const pathname = usePathname()

  React.useEffect(() => {
    onCapture(pathname)
  }, [onCapture, pathname])

  return null
}

/**
 * Watches route changes only while a workspace switch is queued for `/app/apps`.
 */
function PendingWorkspaceObserver({
  onArriveAtApps,
}: {
  onArriveAtApps: () => void
}) {
  const pathname = usePathname()

  React.useEffect(() => {
    if (pathname === "/app/apps") {
      onArriveAtApps()
    }
  }, [onArriveAtApps, pathname])

  return null
}

/**
 * Provides authentication state, session lifecycle management, workspace and team data, and session operations to descendant components.
 *
 * @param children - The components rendered within the session context
 */
export function SessionProvider({ children }: { children: React.ReactNode }) {
  const { t } = useLanguage()
  const tRef = React.useRef(t)
  const [bootstrapCaptured, setBootstrapCaptured] = React.useState(false)
  const [token, setToken] = React.useState<string | null>(null)
  const [sessionReloadSeq, setSessionReloadSeq] = React.useState(0)
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
  const tokenRef = React.useRef<string | null>(null)
  const meRef = React.useRef<MeResponse | null>(null)
  const bootstrapStartedRef = React.useRef(false)
  const lastReloadSeqRef = React.useRef(0)
  const isMountedRef = React.useRef(true)

  React.useEffect(() => {
    isMountedRef.current = true
    return () => {
      isMountedRef.current = false
    }
  }, [])

  React.useEffect(() => {
    tRef.current = t
  }, [t])

  const notify = React.useCallback(
    (kind: AppNotification["kind"], message: string) => {
      setNotification({ id: Date.now(), kind, message })
    },
    []
  )

  const dismissNotification = React.useCallback(() => {
    setNotification(null)
  }, [])

  const openPasswordDialog = React.useCallback(() => {
    setIsPasswordDialogOpen(true)
  }, [])

  const closePasswordDialog = React.useCallback(() => {
    setIsPasswordDialogOpen(false)
  }, [])

  const applyWorkspaceSelection = React.useCallback((workspaceId: string) => {
    localStorage.setItem(WORKSPACE_KEY, workspaceId)
    setTeams([])
    setIsTeamsLoading(true)
    setSelectedWorkspaceId(workspaceId)
  }, [])

  const clearSession = React.useCallback(() => {
    localStorage.removeItem(LEGACY_TOKEN_KEY)
    localStorage.removeItem(WORKSPACE_KEY)
    tokenRef.current = null
    meRef.current = null
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
    (
      nextToken: string,
      nextMustChangePassword: boolean,
      expiresIn: number,
      options?: { silent?: boolean }
    ) => {
      const shouldSkipReload =
        Boolean(options?.silent) &&
        meRef.current !== null &&
        !nextMustChangePassword
      localStorage.removeItem(LOGGED_OUT_KEY)
      tokenRef.current = nextToken
      setSessionError(null)
      if (!shouldSkipReload) {
        setIsSessionLoading(true)
        setSessionReloadSeq((current) => current + 1)
      }
      setToken(nextToken)
      setMustChangePassword(nextMustChangePassword)
      setRefreshAt(
        Date.now() +
          Math.max(expiresIn - ACCESS_TOKEN_REFRESH_EARLY_SECONDS, 1) * 1000
      )
    },
    []
  )

  const renewAccessToken = React.useCallback(
    async (options?: { silent?: boolean }) => {
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
        payload.expires_in,
        options
      )
      return true
    },
    [applyAccessToken]
  )

  const logout = React.useCallback(() => {
    localStorage.setItem(LOGGED_OUT_KEY, "1")
    void endSession().catch(() => undefined)
    clearSession()
    notify("success", tRef.current("已退出登录"))
  }, [clearSession, notify])

  const startBootstrapRestore = React.useCallback(
    (initialPathname: string) => {
      if (bootstrapStartedRef.current) {
        return
      }
      bootstrapStartedRef.current = true
      setBootstrapCaptured(true)

      let restoredToken = false
      localStorage.removeItem(LEGACY_TOKEN_KEY)
      if (initialPathname === "/auth/complete") {
        localStorage.removeItem(LOGGED_OUT_KEY)
        const workspaceId = new URLSearchParams(window.location.search).get(
          "workspace"
        )
        if (workspaceId && workspaceId.length <= 36) {
          localStorage.setItem(WORKSPACE_KEY, workspaceId)
        }
      }
      // Login is anonymous; probing an HttpOnly cookie here only creates expected 401 noise.
      if (
        initialPathname.startsWith("/login") ||
        localStorage.getItem(LOGGED_OUT_KEY)
      ) {
        setIsSessionRestored(true)
        return
      }
      setIsSessionLoading(true)

      refreshAccessToken()
        .then((payload) => {
          if (
            !isMountedRef.current ||
            localStorage.getItem(LOGGED_OUT_KEY)
          ) {
            return
          }
          restoredToken = true
          applyAccessToken(
            payload.access_token,
            payload.must_change_password,
            payload.expires_in
          )
          if (initialPathname === "/auth/complete") {
            notify("success", tRef.current("登录成功"))
          }
        })
        .catch((error: unknown) => {
          if (
            isMountedRef.current &&
            !(error instanceof ApiError && error.status === 401)
          ) {
            const message = getErrorMessage(error, tRef.current)
            setSessionError(message)
            notify("error", message)
          }
        })
        .finally(() => {
          if (isMountedRef.current) {
            setIsSessionRestored(true)
            if (!restoredToken) {
              setIsSessionLoading(false)
            }
          }
        })
    },
    [applyAccessToken, notify]
  )

  const loadSession = React.useCallback(
    async (nextToken: string) => {
      try {
        const [nextMe, maybeWorkspaces] = await Promise.all([
          getMe(nextToken),
          listWorkspaces(nextToken).catch((error: unknown) => {
            if (error instanceof ApiError && error.status === 403) {
              return null
            }
            throw error
          }),
        ])
        meRef.current = nextMe
        setMe(nextMe)
        setMustChangePassword(nextMe.user.must_change_password)
        setSessionError(null)

        if (nextMe.user.must_change_password) {
          setWorkspaces([])
          setTeams([])
          setIsTeamsLoading(false)
          return
        }

        const nextWorkspaces =
          maybeWorkspaces ?? (await listWorkspaces(nextToken))
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
            const renewed = await renewAccessToken({ silent: false })
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
    const currentToken = tokenRef.current
    if (!currentToken || sessionReloadSeq === lastReloadSeqRef.current) {
      return
    }
    lastReloadSeqRef.current = sessionReloadSeq
    void loadSession(currentToken)
  }, [sessionReloadSeq, loadSession])

  React.useEffect(() => {
    if (!token || refreshAt === null) {
      return
    }

    const timer = window.setTimeout(() => {
      void renewAccessToken({ silent: true }).catch((error: unknown) => {
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
    const activeToken = tokenRef.current
    if (
      isSessionLoading ||
      !activeToken ||
      !selectedWorkspaceId ||
      mustChangePassword
    ) {
      return
    }

    let isCurrent = true

    listTeams(activeToken, selectedWorkspaceId)
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
    sessionReloadSeq,
    selectedWorkspaceId,
    mustChangePassword,
    isSessionLoading,
    notify,
  ])

  const completePendingWorkspaceSwitch = React.useCallback(() => {
    if (!pendingWorkspaceId) {
      return
    }

    const nextWorkspace = workspaces.find(
      (workspace) =>
        workspace.id === pendingWorkspaceId &&
        workspace.status === "active" &&
        hasWorkspaceMembership(me, workspace.id)
    )
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
  }, [applyWorkspaceSelection, me, notify, pendingWorkspaceId, workspaces])

  const handleLogin = React.useCallback(
    (nextToken: string, nextMustChangePassword: boolean, expiresIn: number) => {
      applyAccessToken(nextToken, nextMustChangePassword, expiresIn)
      notify("success", tRef.current("登录成功"))
    },
    [applyAccessToken, notify]
  )

  const handleSelectWorkspace = React.useCallback(
    (workspaceId: string) => {
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
    },
    [applyWorkspaceSelection, me, selectedWorkspaceId, workspaces]
  )

  const handleSwitchWorkspace = React.useCallback(
    (workspaceId: string) => {
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
    },
    [me, selectedWorkspaceId, workspaces]
  )

  const clearSelectedWorkspace = React.useCallback(() => {
    localStorage.removeItem(WORKSPACE_KEY)
    setTeams([])
    setIsTeamsLoading(false)
    setSelectedWorkspaceId(null)
  }, [])

  const handleWorkspaceCreated = React.useCallback(
    (payload: WorkspaceCreateResponse) => {
      setWorkspaces((current) => [...current, payload.workspace])
      setMe((current) => addCreatedWorkspaceMembership(current, payload))
    },
    []
  )

  const handleWorkspaceUpdated = React.useCallback(
    (workspace: Workspace) => {
      const nextWorkspaces = workspaces.map((item) =>
        item.id === workspace.id ? workspace : item
      )
      setWorkspaces(nextWorkspaces)

      if (
        workspace.id === selectedWorkspaceId &&
        workspace.status !== "active"
      ) {
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
    },
    [
      clearSelectedWorkspace,
      handleSelectWorkspace,
      me,
      selectedWorkspaceId,
      workspaces,
    ]
  )

  const handleWorkspaceDeleted = React.useCallback(
    (workspaceId: string) => {
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
    },
    [
      clearSelectedWorkspace,
      handleSelectWorkspace,
      me,
      selectedWorkspaceId,
      workspaces,
    ]
  )

  const handleTeamCreated = React.useCallback(
    (team: Team, adminUserId?: string) => {
      setTeams((current) => [...current, team])
      if (adminUserId) {
        setMe((current) => addCreatedTeamMembership(current, team, adminUserId))
      }
    },
    []
  )

  const handleTeamUpdated = React.useCallback((team: Team) => {
    setTeams((current) =>
      current.map((item) => (item.id === team.id ? team : item))
    )
  }, [])

  const handleTeamDeleted = React.useCallback((teamId: string) => {
    setTeams((current) => current.filter((item) => item.id !== teamId))
  }, [])

  const handleUserUpdated = React.useCallback((user: User) => {
    setMe((current) => replaceSessionUser(current, user))
  }, [])

  const handlePasswordChanged = React.useCallback(async () => {
    setIsSessionLoading(true)
    setSessionError(null)
    setMustChangePassword(false)
    setIsPasswordDialogOpen(false)
    if (tokenRef.current) {
      await loadSession(tokenRef.current)
    }
    notify("success", tRef.current("密码已修改"))
  }, [loadSession, notify])

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

  const value: SessionContextValue = React.useMemo(
    () => ({
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
      dismissNotification,
      openPasswordDialog,
      closePasswordDialog,
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
    }),
    [
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
      isPasswordDialogOpen,
      handleLogin,
      logout,
      notify,
      dismissNotification,
      openPasswordDialog,
      closePasswordDialog,
      handleSelectWorkspace,
      handleSwitchWorkspace,
      clearSelectedWorkspace,
      handleWorkspaceCreated,
      handleWorkspaceUpdated,
      handleWorkspaceDeleted,
      handleTeamCreated,
      handleTeamUpdated,
      handleTeamDeleted,
      handleUserUpdated,
      handlePasswordChanged,
    ]
  )

  return (
    <SessionContext.Provider value={value}>
      {!bootstrapCaptured ? (
        <SessionBootstrapObserver onCapture={startBootstrapRestore} />
      ) : null}
      {pendingWorkspaceId ? (
        <PendingWorkspaceObserver
          onArriveAtApps={completePendingWorkspaceSwitch}
        />
      ) : null}
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
 * Reads the session context when a provider is present, so components that can
 * render on their own (for example the theme settings panel) still mount.
 */
export const useOptionalSession = () => React.useContext(SessionContext)

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
