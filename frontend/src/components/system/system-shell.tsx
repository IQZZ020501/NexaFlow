import * as React from "react"
import {
  Building2Icon,
  HistoryIcon,
  UserCogIcon,
  UsersIcon,
} from "lucide-react"
import { useRouter } from "next/navigation"
import { useLanguage } from "@/contexts/language-provider"
import { useSession } from "@/contexts/session-context"
import { useConfirmDialog } from "@/components/app/confirm-dialog"
import {
  addTeamMember,
  addWorkspaceMember,
  changeUserPassword,
  createTeam,
  createUser,
  createWorkspace,
  createWorkspaceUser,
  deleteTeam,
  deleteUser,
  deleteWorkspace,
  listAuditLogs,
  listWorkspaceAuditLogs,
  listTeamMembers,
  listWorkspaceMembers,
  listTeams,
  listUsers,
  removeTeamMember,
  removeWorkspaceMember,
  updateTeam,
  updateTeamMember,
  updateUser,
  updateWorkspace,
  updateWorkspaceMember,
} from "@/lib/api/system"
import type {
  AuditLog,
  AuditFilters,
  MeResponse,
  Team,
  TeamMember,
  User,
  Workspace,
  WorkspaceCreateResponse,
  WorkspaceMember,
} from "@/lib/api/system"
import { languageLocales } from "@/i18n"
import {
  displayTeamName,
  displayWorkspaceName,
  getMembershipRole,
} from "@/lib/display"
import { getErrorMessage } from "@/lib/errors"
import type { AppNotification } from "@/lib/notifications"
import { getNewPasswordError } from "@/lib/password"
import { SystemPageView } from "@/components/system/system-page-view"
import type {
  ScopeEditForm,
  TeamForm,
  UserCreateForm,
  UserForm,
  UserPasswordForm,
  UserRoleFilter,
  UserStatusFilter,
  WorkspaceForm,
} from "@/lib/api/system"
import {
  canManageTeamMembers,
  getUserRoleKey,
} from "@/components/system/system-utils"

export type SystemTab = "workspaces" | "teams" | "users" | "audit"

/**
 * Renders the system administration interface for the active tab when the current user has access.
 *
 * Redirects unauthorized users to an appropriate application or system page and renders nothing when the session is unavailable.
 *
 * @param activeTab - The system administration tab to display
 */
export function SystemShell({ activeTab }: { activeTab: SystemTab }) {
  const session = useSession()
  const router = useRouter()

  const canAccessSystem = Boolean(
    session.me &&
    (session.me.user.is_global_admin ||
      session.me.user.workspaces.some(
        (workspace) => workspace.role === "admin"
      ) ||
      session.me.user.teams.some((team) => team.role === "admin"))
  )
  const canAccessUsers = Boolean(
    session.me?.user.is_global_admin ||
      getMembershipRole(session.me, session.selectedWorkspaceId) === "admin"
  )

  React.useEffect(() => {
    if (!session.me) {
      return
    }

    if (!canAccessSystem) {
      router.replace("/app/apps")
      return
    }

    if (
      (activeTab === "users" &&
        !session.isSessionLoading &&
        !canAccessUsers) ||
      (activeTab === "audit" &&
        !session.me?.user.is_global_admin &&
        getMembershipRole(session.me, session.selectedWorkspaceId) !== "admin")
    ) {
      router.replace("/system/teams")
    }
  }, [
    activeTab,
    canAccessSystem,
    canAccessUsers,
    router,
    session.isSessionLoading,
    session.me,
    session.selectedWorkspaceId,
  ])

  if (!session.me || !session.token || !canAccessSystem) {
    return null
  }

  return (
    <SystemPageContent
      activeTab={activeTab}
      me={session.me}
      token={session.token}
      workspaces={session.workspaces}
      teams={session.teams}
      selectedWorkspaceId={session.selectedWorkspaceId}
      isTeamsLoading={session.isTeamsLoading}
      onSelectWorkspace={session.selectWorkspace}
      onSystemTabChange={(tab) => router.push(`/system/${tab}`)}
      onWorkspaceCreated={session.workspaceCreated}
      onWorkspaceUpdated={session.workspaceUpdated}
      onWorkspaceDeleted={session.workspaceDeleted}
      onTeamCreated={session.teamCreated}
      onTeamUpdated={session.teamUpdated}
      onTeamDeleted={session.teamDeleted}
      onUserUpdated={session.userUpdated}
      onNotify={session.notify}
    />
  )
}

/**
 * Renders the system administration page and coordinates workspace, team, user, membership, and audit-log management.
 *
 * @param me - The authenticated user's profile and permissions
 * @param selectedWorkspaceId - The currently selected workspace
 * @param activeTab - The active system administration tab
 * @param onNotify - Callback for displaying operation notifications
 */
function SystemPageContent({
  me,
  token,
  workspaces,
  teams,
  selectedWorkspaceId,
  isTeamsLoading,
  activeTab,
  onSelectWorkspace,
  onSystemTabChange,
  onWorkspaceCreated,
  onWorkspaceUpdated,
  onWorkspaceDeleted,
  onTeamCreated,
  onTeamUpdated,
  onTeamDeleted,
  onUserUpdated,
  onNotify,
}: {
  me: MeResponse
  token: string
  workspaces: Workspace[]
  teams: Team[]
  selectedWorkspaceId: string | null
  isTeamsLoading: boolean
  activeTab: SystemTab
  onSelectWorkspace: (workspaceId: string) => void
  onSystemTabChange: (tab: SystemTab) => void
  onWorkspaceCreated: (payload: WorkspaceCreateResponse) => void
  onWorkspaceUpdated: (workspace: Workspace) => void
  onWorkspaceDeleted: (workspaceId: string) => void
  onTeamCreated: (team: Team, adminUserId?: string) => void
  onTeamUpdated: (team: Team) => void
  onTeamDeleted: (teamId: string) => void
  onUserUpdated: (user: User) => void
  onNotify: (kind: AppNotification["kind"], message: string) => void
}) {
  const { language, t } = useLanguage()
  const [confirmAction, confirmDialog] = useConfirmDialog()
  const locale = languageLocales[language]
  const [workspaceForm, setWorkspaceForm] = React.useState<WorkspaceForm>({
    name: "",
    description: "",
    adminUserId: "",
  })
  const [teamForm, setTeamForm] = React.useState<TeamForm>({
    workspaceId: "",
    name: "",
    description: "",
    adminUserId: "",
  })
  const [workspaceEditForm, setWorkspaceEditForm] =
    React.useState<ScopeEditForm | null>(null)
  const [teamEditForm, setTeamEditForm] = React.useState<ScopeEditForm | null>(
    null
  )
  const [userCreateForm, setUserCreateForm] = React.useState<UserCreateForm>({
    username: "",
    email: "",
    name: "",
    workspaceId: selectedWorkspaceId ?? "",
    teamIds: [],
    isGlobalAdmin: false,
  })
  const [users, setUsers] = React.useState<User[]>([])
  const [workspaceMembers, setWorkspaceMembers] = React.useState<
    WorkspaceMember[]
  >([])
  const [workspaceMembersDialogWorkspace, setWorkspaceMembersDialogWorkspace] =
    React.useState<Workspace | null>(null)
  const [teamMembersDialogTeam, setTeamMembersDialogTeam] =
    React.useState<Team | null>(null)
  const [teamMembers, setTeamMembers] = React.useState<TeamMember[]>([])
  const [teamMemberCandidates, setTeamMemberCandidates] = React.useState<
    WorkspaceMember[]
  >([])
  const [auditLogs, setAuditLogs] = React.useState<AuditLog[]>([])
  const [auditSearch, setAuditSearch] = React.useState("")
  const [debouncedAuditSearch, setDebouncedAuditSearch] = React.useState("")
  const [auditAction, setAuditAction] = React.useState("")
  const [auditOffset, setAuditOffset] = React.useState(0)
  const [auditHasMore, setAuditHasMore] = React.useState(false)
  const [userForm, setUserForm] = React.useState<UserForm | null>(null)
  const [userPasswordForm, setUserPasswordForm] =
    React.useState<UserPasswordForm | null>(null)
  const [userSearch, setUserSearch] = React.useState("")
  const [userStatusFilter, setUserStatusFilter] =
    React.useState<UserStatusFilter>("all")
  const [userRoleFilter, setUserRoleFilter] =
    React.useState<UserRoleFilter>("all")
  const [userWorkspaceFilter, setUserWorkspaceFilter] = React.useState("all")
  const [userCreateTeams, setUserCreateTeams] = React.useState<Team[]>([])
  const [teamAdminCandidates, setTeamAdminCandidates] = React.useState<
    WorkspaceMember[]
  >([])
  const [isTeamAdminCandidatesLoading, setIsTeamAdminCandidatesLoading] =
    React.useState(false)
  const [isCreatingWorkspace, setIsCreatingWorkspace] = React.useState(false)
  const [isSavingWorkspace, setIsSavingWorkspace] = React.useState(false)
  const [isCreatingTeam, setIsCreatingTeam] = React.useState(false)
  const [isSavingTeam, setIsSavingTeam] = React.useState(false)
  const [isCreatingUser, setIsCreatingUser] = React.useState(false)
  const [isUserCreateTeamsLoading, setIsUserCreateTeamsLoading] =
    React.useState(false)
  const [isUsersLoading, setIsUsersLoading] = React.useState(false)
  const [isWorkspaceMembersLoading, setIsWorkspaceMembersLoading] =
    React.useState(false)
  const [isWorkspaceMembersMutating, setIsWorkspaceMembersMutating] =
    React.useState(false)
  const [isTeamMembersLoading, setIsTeamMembersLoading] = React.useState(false)
  const [isTeamMembersMutating, setIsTeamMembersMutating] =
    React.useState(false)
  const [isAuditLoading, setIsAuditLoading] = React.useState(false)
  const [isSavingUser, setIsSavingUser] = React.useState(false)
  const [isChangingUserPassword, setIsChangingUserPassword] =
    React.useState(false)
  const [isWorkspaceDialogOpen, setIsWorkspaceDialogOpen] =
    React.useState(false)
  const [isTeamDialogOpen, setIsTeamDialogOpen] = React.useState(false)
  const [isUserCreateDialogOpen, setIsUserCreateDialogOpen] =
    React.useState(false)
  const userCreateTeamsRequestId = React.useRef(0)
  const teamAdminCandidatesRequestId = React.useRef(0)
  const workspaceMembersRequestId = React.useRef(0)
  const teamMembersRequestId = React.useRef(0)
  const auditRequestId = React.useRef(0)

  React.useEffect(() => {
    const timer = window.setTimeout(() => {
      setDebouncedAuditSearch(auditSearch)
    }, 300)
    return () => window.clearTimeout(timer)
  }, [auditSearch])

  const selectedWorkspace =
    workspaces.find((workspace) => workspace.id === selectedWorkspaceId) ?? null
  const activeWorkspaces = workspaces.filter(
    (workspace) => workspace.status === "active"
  )
  const userCreateWorkspace =
    activeWorkspaces.find(
      (workspace) => workspace.id === userCreateForm.workspaceId
    ) ?? null
  const manageableWorkspaces = activeWorkspaces.filter(
    (workspace) =>
      me.user.is_global_admin ||
      getMembershipRole(me, workspace.id) === "admin"
  )
  const teamWorkspace =
    manageableWorkspaces.find(
      (workspace) => workspace.id === teamForm.workspaceId
    ) ?? null
  const selectedRole = getMembershipRole(me, selectedWorkspaceId)
  const canManageWorkspace = selectedRole === "admin"
  const canManageUsers = me.user.is_global_admin || canManageWorkspace
  const canManageTeamAdmins =
    getMembershipRole(me, teamMembersDialogTeam?.workspace_id ?? null) ===
    "admin"
  const canCreateTeam = manageableWorkspaces.length > 0
  const canCreateWorkspace = me.user.is_global_admin
  const reportError = React.useCallback(
    (error: unknown) => {
      const message = getErrorMessage(error, t)
      onNotify("error", message)
      return message
    },
    [onNotify, t]
  )
  const systemTabs: {
    key: SystemTab
    label: string
    icon: React.ElementType
  }[] = [
    {
      key: "workspaces",
      label: t("工作空间"),
      icon: Building2Icon,
    },
    {
      key: "teams",
      label: t("团队"),
      icon: UsersIcon,
    },
    ...(canManageUsers
      ? [
          {
            key: "users" as const,
            label: t("用户管理"),
            icon: UserCogIcon,
          },
        ]
      : []),
    ...(me.user.is_global_admin || canManageWorkspace
      ? [
          {
            key: "audit" as const,
            label: t("审计日志"),
            icon: HistoryIcon,
          },
        ]
      : []),
  ]

  const loadUsers = React.useCallback(async () => {
    setIsUsersLoading(true)

    try {
      setUsers(await listUsers(token))
    } catch (error) {
      setUsers([])
      reportError(error)
    } finally {
      setIsUsersLoading(false)
    }
  }, [reportError, token])

  const loadWorkspaceMembers = React.useCallback(
    async (workspaceId: string) => {
      const requestId = workspaceMembersRequestId.current + 1
      workspaceMembersRequestId.current = requestId
      setWorkspaceMembers([])
      setIsWorkspaceMembersLoading(true)

      try {
        const members = await listWorkspaceMembers(token, workspaceId)
        if (requestId === workspaceMembersRequestId.current) {
          setWorkspaceMembers(members)
        }
      } catch (error) {
        if (requestId === workspaceMembersRequestId.current) {
          setWorkspaceMembers([])
          reportError(error)
        }
      } finally {
        if (requestId === workspaceMembersRequestId.current) {
          setIsWorkspaceMembersLoading(false)
        }
      }
    },
    [reportError, token]
  )

  const loadTeamMembers = React.useCallback(
    async (team: Team) => {
      const requestId = teamMembersRequestId.current + 1
      teamMembersRequestId.current = requestId
      setTeamMembers([])
      setTeamMemberCandidates([])
      setIsTeamMembersLoading(true)

      try {
        const [members, candidates] = await Promise.all([
          listTeamMembers(token, team.workspace_id, team.id),
          listWorkspaceMembers(token, team.workspace_id),
        ])
        if (requestId === teamMembersRequestId.current) {
          setTeamMembers(members)
          setTeamMemberCandidates(candidates)
        }
      } catch (error) {
        if (requestId === teamMembersRequestId.current) {
          setTeamMembers([])
          setTeamMemberCandidates([])
          reportError(error)
        }
      } finally {
        if (requestId === teamMembersRequestId.current) {
          setIsTeamMembersLoading(false)
        }
      }
    },
    [reportError, token]
  )

  const loadAuditLogs = React.useCallback(async (offset: number) => {
    const requestId = auditRequestId.current + 1
    auditRequestId.current = requestId
    setIsAuditLoading(true)

    try {
      const filters: AuditFilters = {
        limit: 100,
        offset,
        search: debouncedAuditSearch || undefined,
        action: auditAction || undefined,
      }
      const nextLogs = me.user.is_global_admin
        ? await listAuditLogs(token, filters)
        : selectedWorkspaceId
          ? await listWorkspaceAuditLogs(token, selectedWorkspaceId, filters)
          : []
      if (requestId !== auditRequestId.current) return
      setAuditLogs((current) => (offset ? [...current, ...nextLogs] : nextLogs))
      setAuditHasMore(nextLogs.length === 100)
    } catch (error) {
      if (requestId !== auditRequestId.current) return
      setAuditLogs([])
      reportError(error)
    } finally {
      if (requestId === auditRequestId.current) {
        setIsAuditLoading(false)
      }
    }
  }, [auditAction, debouncedAuditSearch, me.user.is_global_admin, reportError, selectedWorkspaceId, token])

  const loadUserCreateTeams = React.useCallback(
    async (workspaceId: string) => {
      const requestId = userCreateTeamsRequestId.current + 1
      userCreateTeamsRequestId.current = requestId
      setUserCreateTeams([])
      setIsUserCreateTeamsLoading(true)

      try {
        const nextTeams = await listTeams(token, workspaceId)
        if (requestId === userCreateTeamsRequestId.current) {
          setUserCreateTeams(nextTeams)
        }
      } catch (error) {
        if (requestId === userCreateTeamsRequestId.current) {
          reportError(error)
        }
      } finally {
        if (requestId === userCreateTeamsRequestId.current) {
          setIsUserCreateTeamsLoading(false)
        }
      }
    },
    [reportError, token]
  )

  const loadTeamAdminCandidates = React.useCallback(
    async (workspaceId: string) => {
      const requestId = teamAdminCandidatesRequestId.current + 1
      teamAdminCandidatesRequestId.current = requestId
      setTeamAdminCandidates([])
      setIsTeamAdminCandidatesLoading(true)

      try {
        const members = await listWorkspaceMembers(token, workspaceId)
        if (requestId === teamAdminCandidatesRequestId.current) {
          setTeamAdminCandidates(members)
        }
      } catch (error) {
        if (requestId === teamAdminCandidatesRequestId.current) {
          setTeamAdminCandidates([])
          reportError(error)
        }
      } finally {
        if (requestId === teamAdminCandidatesRequestId.current) {
          setIsTeamAdminCandidatesLoading(false)
        }
      }
    },
    [reportError, token]
  )

  React.useEffect(() => {
    if (activeTab !== "users" || !canManageUsers) {
      return
    }

    if (!me.user.is_global_admin) {
      if (selectedWorkspaceId && canManageWorkspace) {
        // eslint-disable-next-line react-hooks/set-state-in-effect
        void loadWorkspaceMembers(selectedWorkspaceId)
      }
      return
    }

    void loadUsers()
  }, [
    activeTab,
    canManageUsers,
    canManageWorkspace,
    loadUsers,
    loadWorkspaceMembers,
    me.user.is_global_admin,
    selectedWorkspaceId,
  ])

  React.useEffect(() => {
    if (
      activeTab !== "audit" ||
      (!me.user.is_global_admin &&
        getMembershipRole(me, selectedWorkspaceId) !== "admin")
    ) {
      return
    }

    // eslint-disable-next-line react-hooks/set-state-in-effect
    setAuditOffset(0)
    void loadAuditLogs(0)
  }, [activeTab, loadAuditLogs, me, me.user.is_global_admin, selectedWorkspaceId])

  const filteredUsers = React.useMemo(() => {
    const query = userSearch.trim().toLowerCase()

    return users.filter((user) => {
      if (
        query &&
        ![user.name, user.username, user.email]
          .join(" ")
          .toLowerCase()
          .includes(query)
      ) {
        return false
      }

      if (userStatusFilter === "active" && !user.is_active) {
        return false
      }

      if (userStatusFilter === "inactive" && user.is_active) {
        return false
      }

      if (userRoleFilter !== "all" && getUserRoleKey(user) !== userRoleFilter) {
        return false
      }

      if (
        userWorkspaceFilter !== "all" &&
        !user.workspaces.some(
          (workspace) => workspace.id === userWorkspaceFilter
        )
      ) {
        return false
      }

      return true
    })
  }, [userRoleFilter, userSearch, userStatusFilter, userWorkspaceFilter, users])

  function updateUserInList(user: User) {
    setUsers((current) =>
      current.map((item) => (item.id === user.id ? user : item))
    )
    onUserUpdated(user)
  }

  function handleOpenCreateWorkspace() {
    setWorkspaceForm({ name: "", description: "", adminUserId: "" })
    setIsWorkspaceDialogOpen(true)
    void loadUsers()
  }

  function handleOpenWorkspaceMembers(workspace: Workspace) {
    setWorkspaceMembersDialogWorkspace(workspace)
    void loadWorkspaceMembers(workspace.id)
    if (me.user.is_global_admin) {
      void loadUsers()
    }
  }

  function handleOpenCreateUser() {
    const workspaceId = me.user.is_global_admin
      ? (activeWorkspaces.find(
          (workspace) => workspace.id === selectedWorkspaceId
        )?.id ?? "")
      : (selectedWorkspaceId ?? "")
    setUserCreateForm({
      username: "",
      email: "",
      name: "",
      workspaceId,
      teamIds: [],
      isGlobalAdmin: false,
    })
    setIsUserCreateDialogOpen(true)
    if (me.user.is_global_admin && workspaceId) {
      void loadUserCreateTeams(workspaceId)
    } else {
      userCreateTeamsRequestId.current += 1
      setUserCreateTeams([])
      setIsUserCreateTeamsLoading(false)
    }
  }

  function handleUserCreateWorkspaceChange(workspaceId: string) {
    setUserCreateForm((current) => ({
      ...current,
      workspaceId,
      teamIds: [],
    }))
    if (workspaceId) {
      void loadUserCreateTeams(workspaceId)
    } else {
      userCreateTeamsRequestId.current += 1
      setUserCreateTeams([])
      setIsUserCreateTeamsLoading(false)
    }
  }

  function handleOpenCreateTeam() {
    const workspaceId =
      manageableWorkspaces.find(
        (workspace) => workspace.id === selectedWorkspaceId
      )?.id ??
      manageableWorkspaces[0]?.id ??
      ""

    setTeamForm({ workspaceId, name: "", description: "", adminUserId: "" })
    setIsTeamDialogOpen(true)
    if (workspaceId) {
      void loadTeamAdminCandidates(workspaceId)
    } else {
      teamAdminCandidatesRequestId.current += 1
      setTeamAdminCandidates([])
      setIsTeamAdminCandidatesLoading(false)
    }
  }

  function handleOpenTeamMembers(team: Team) {
    setTeamMembersDialogTeam(team)
    void loadTeamMembers(team)
  }

  function handleTeamWorkspaceChange(workspaceId: string) {
    setTeamForm((current) => ({
      ...current,
      workspaceId,
      adminUserId: "",
    }))
    if (workspaceId) {
      void loadTeamAdminCandidates(workspaceId)
    } else {
      teamAdminCandidatesRequestId.current += 1
      setTeamAdminCandidates([])
      setIsTeamAdminCandidatesLoading(false)
    }
  }

  async function handleCreateWorkspace(
    event: React.FormEvent<HTMLFormElement>
  ) {
    event.preventDefault()

    if (!workspaceForm.adminUserId) {
      onNotify("error", t("请选择负责人"))
      return
    }

    setIsCreatingWorkspace(true)

    try {
      const payload = await createWorkspace(token, {
        name: workspaceForm.name,
        description: workspaceForm.description,
        admin_user_id: workspaceForm.adminUserId,
      })
      setWorkspaceForm({ name: "", description: "", adminUserId: "" })
      onWorkspaceCreated(payload)
      setIsWorkspaceDialogOpen(false)
      onNotify("success", t("工作空间已新建"))
    } catch (error) {
      reportError(error)
    } finally {
      setIsCreatingWorkspace(false)
    }
  }

  async function handleCreateTeam(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()

    if (!teamForm.workspaceId || !teamForm.adminUserId) {
      onNotify("error", t("请选择团队管理员"))
      return
    }

    setIsCreatingTeam(true)

    try {
      const team = await createTeam(token, teamForm.workspaceId, {
        name: teamForm.name,
        description: teamForm.description,
        admin_user_id: teamForm.adminUserId,
      })
      setTeamForm({
        workspaceId: "",
        name: "",
        description: "",
        adminUserId: "",
      })
      onTeamCreated(team, teamForm.adminUserId)
      if (team.workspace_id !== selectedWorkspaceId) {
        onSelectWorkspace(team.workspace_id)
      }
      setIsTeamDialogOpen(false)
      onNotify("success", t("团队已新建"))
    } catch (error) {
      reportError(error)
    } finally {
      setIsCreatingTeam(false)
    }
  }

  function handleOpenEditWorkspace(workspace: Workspace) {
    setWorkspaceEditForm({
      id: workspace.id,
      name: workspace.name,
      description: workspace.description,
    })
  }

  async function handleUpdateWorkspace(
    event: React.FormEvent<HTMLFormElement>
  ) {
    event.preventDefault()

    if (!workspaceEditForm) {
      return
    }

    setIsSavingWorkspace(true)

    try {
      const workspace = await updateWorkspace(token, workspaceEditForm.id, {
        name: workspaceEditForm.name,
        description: workspaceEditForm.description,
      })
      onWorkspaceUpdated(workspace)
      setWorkspaceEditForm(null)
      onNotify("success", t("工作空间已更新"))
    } catch (error) {
      reportError(error)
    } finally {
      setIsSavingWorkspace(false)
    }
  }

  async function handleArchiveWorkspace(workspace: Workspace) {
    const nextStatus = workspace.status === "active" ? "archived" : "active"
    const actionLabel = nextStatus === "archived" ? t("归档") : t("恢复")

    if (
      !(await confirmAction({
        description: t("{action} {name}？", {
          action: actionLabel,
          name: displayWorkspaceName(workspace, t),
        }),
        confirmLabel: actionLabel,
      }))
    ) {
      return
    }

    try {
      onWorkspaceUpdated(
        await updateWorkspace(token, workspace.id, { status: nextStatus })
      )
      onNotify(
        "success",
        nextStatus === "archived" ? t("工作空间已归档") : t("工作空间已恢复")
      )
    } catch (error) {
      reportError(error)
    }
  }

  async function handleDeleteWorkspace(workspace: Workspace) {
    if (
      !(await confirmAction({
        description: t("永久删除 {name}？此操作不可恢复。", {
          name: displayWorkspaceName(workspace, t),
        }),
        confirmLabel: t("删除"),
        destructive: true,
      }))
    ) {
      return
    }

    try {
      await deleteWorkspace(token, workspace.id)
      onWorkspaceDeleted(workspace.id)
      onNotify("success", t("工作空间已删除"))
    } catch (error) {
      reportError(error)
    }
  }

  function handleOpenEditTeam(team: Team) {
    setTeamEditForm({
      id: team.id,
      name: team.name,
      description: team.description,
    })
  }

  async function handleUpdateTeam(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()

    if (!teamEditForm || !selectedWorkspaceId) {
      return
    }

    setIsSavingTeam(true)

    try {
      const team = await updateTeam(
        token,
        selectedWorkspaceId,
        teamEditForm.id,
        {
          name: teamEditForm.name,
          description: teamEditForm.description,
        }
      )
      onTeamUpdated(team)
      setTeamEditForm(null)
      onNotify("success", t("团队已更新"))
    } catch (error) {
      reportError(error)
    } finally {
      setIsSavingTeam(false)
    }
  }

  async function handleArchiveTeam(team: Team) {
    if (!selectedWorkspaceId) {
      return
    }

    const nextStatus = team.status === "active" ? "archived" : "active"
    const actionLabel = nextStatus === "archived" ? t("归档") : t("恢复")

    if (
      !(await confirmAction({
        description: t("{action} {name}？", {
          action: actionLabel,
          name: displayTeamName(team, t),
        }),
        confirmLabel: actionLabel,
      }))
    ) {
      return
    }

    try {
      onTeamUpdated(
        await updateTeam(token, selectedWorkspaceId, team.id, {
          status: nextStatus,
        })
      )
      onNotify(
        "success",
        nextStatus === "archived" ? t("团队已归档") : t("团队已恢复")
      )
    } catch (error) {
      reportError(error)
    }
  }

  async function handleDeleteTeam(team: Team) {
    if (!selectedWorkspaceId) {
      return
    }

    if (
      !(await confirmAction({
        description: t("永久删除 {name}？此操作不可恢复。", {
          name: displayTeamName(team, t),
        }),
        confirmLabel: t("删除"),
        destructive: true,
      }))
    ) {
      return
    }

    try {
      await deleteTeam(token, selectedWorkspaceId, team.id)
      onTeamDeleted(team.id)
      onNotify("success", t("团队已删除"))
    } catch (error) {
      reportError(error)
    }
  }

  async function handleAddWorkspaceMember(userId: string, role: string) {
    const workspace = workspaceMembersDialogWorkspace
    if (!workspace) {
      return
    }

    setIsWorkspaceMembersMutating(true)
    try {
      const member = await addWorkspaceMember(token, workspace.id, {
        user_id: userId,
        role,
      })
      setWorkspaceMembers((current) => [...current, member])
      onNotify("success", t("工作空间成员已添加"))
    } catch (error) {
      reportError(error)
    } finally {
      setIsWorkspaceMembersMutating(false)
    }
  }

  async function handleUpdateWorkspaceMember(userId: string, role: string) {
    const workspace = workspaceMembersDialogWorkspace
    if (!workspace) {
      return
    }

    setIsWorkspaceMembersMutating(true)
    try {
      const member = await updateWorkspaceMember(token, workspace.id, userId, {
        role,
      })
      setWorkspaceMembers((current) =>
        current.map((item) => (item.user.id === userId ? member : item))
      )
      onNotify("success", t("工作空间成员已更新"))
    } catch (error) {
      reportError(error)
    } finally {
      setIsWorkspaceMembersMutating(false)
    }
  }

  async function handleRemoveWorkspaceMember(userId: string) {
    const workspace = workspaceMembersDialogWorkspace
    if (!workspace) {
      return
    }

    const member = workspaceMembers.find((item) => item.user.id === userId)
    if (
      member &&
      !(await confirmAction({
        description: t("移除 {name}？", {
          name: member.user.name,
        }),
        confirmLabel: t("移除"),
        destructive: true,
      }))
    ) {
      return
    }

    setIsWorkspaceMembersMutating(true)
    try {
      await removeWorkspaceMember(token, workspace.id, userId)
      setWorkspaceMembers((current) =>
        current.filter((item) => item.user.id !== userId)
      )
      onNotify("success", t("工作空间成员已移除"))
    } catch (error) {
      reportError(error)
    } finally {
      setIsWorkspaceMembersMutating(false)
    }
  }

  async function handleAddTeamMember(userId: string, role: string) {
    const team = teamMembersDialogTeam
    if (!team) {
      return
    }

    setIsTeamMembersMutating(true)
    try {
      const member = await addTeamMember(token, team.workspace_id, team.id, {
        user_id: userId,
        role,
      })
      setTeamMembers((current) => [...current, member])
      onNotify("success", t("团队成员已添加"))
    } catch (error) {
      reportError(error)
    } finally {
      setIsTeamMembersMutating(false)
    }
  }

  async function handleUpdateTeamMember(userId: string, role: string) {
    const team = teamMembersDialogTeam
    if (!team) {
      return
    }

    setIsTeamMembersMutating(true)
    try {
      const member = await updateTeamMember(
        token,
        team.workspace_id,
        team.id,
        userId,
        { role }
      )
      setTeamMembers((current) =>
        current.map((item) => (item.user.id === userId ? member : item))
      )
      onNotify("success", t("团队成员已更新"))
    } catch (error) {
      reportError(error)
    } finally {
      setIsTeamMembersMutating(false)
    }
  }

  async function handleRemoveTeamMember(userId: string) {
    const team = teamMembersDialogTeam
    if (!team) {
      return
    }

    const member = teamMembers.find((item) => item.user.id === userId)
    if (
      member &&
      !(await confirmAction({
        description: t("移除 {name}？", {
          name: member.user.name,
        }),
        confirmLabel: t("移除"),
        destructive: true,
      }))
    ) {
      return
    }

    setIsTeamMembersMutating(true)
    try {
      await removeTeamMember(token, team.workspace_id, team.id, userId)
      setTeamMembers((current) =>
        current.filter((item) => item.user.id !== userId)
      )
      onNotify("success", t("团队成员已移除"))
    } catch (error) {
      reportError(error)
    } finally {
      setIsTeamMembersMutating(false)
    }
  }

  async function handleCreateUser(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()

    if (!me.user.is_global_admin && !selectedWorkspaceId) {
      onNotify("error", t("请选择工作空间"))
      return
    }

    setIsCreatingUser(true)

    try {
      const payload = me.user.is_global_admin
        ? await createUser(token, {
            username: userCreateForm.username,
            email: userCreateForm.email,
            name: userCreateForm.name,
            is_global_admin: userCreateForm.isGlobalAdmin,
            workspace_id: userCreateForm.workspaceId || null,
            team_ids: userCreateForm.teamIds,
          })
        : await createWorkspaceUser(token, selectedWorkspaceId!, {
            username: userCreateForm.username,
            email: userCreateForm.email,
            name: userCreateForm.name,
          })
      if (me.user.is_global_admin) {
        setUsers((current) => [...current, payload.user])
      } else {
        setWorkspaceMembers((current) => [
          ...current,
          { user: payload.user, role: "member" },
        ])
      }
      setIsUserCreateDialogOpen(false)
      setUserCreateForm({
        username: "",
        email: "",
        name: "",
        workspaceId: "",
        teamIds: [],
        isGlobalAdmin: false,
      })
      setUserCreateTeams([])
      onNotify(
        "success",
        t("用户已新建，初始密码：{password}", {
          password: payload.initial_password,
        })
      )
    } catch (error) {
      reportError(error)
    } finally {
      setIsCreatingUser(false)
    }
  }

  async function handleToggleUser(user: User) {
    try {
      updateUserInList(
        await updateUser(token, user.id, { is_active: !user.is_active })
      )
      onNotify("success", user.is_active ? t("用户已停用") : t("用户已启用"))
    } catch (error) {
      reportError(error)
    }
  }

  function handleOpenEditUser(user: User) {
    setUserForm({
      id: user.id,
      username: user.username,
      email: user.email,
      name: user.name,
      isGlobalAdmin: user.is_global_admin,
    })
  }

  async function handleUpdateUser(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()

    if (!userForm) {
      return
    }

    const currentUser = users.find((user) => user.id === userForm.id)
    if (
      currentUser &&
      currentUser.is_global_admin !== userForm.isGlobalAdmin &&
      !(await confirmAction({
        description: t(
          userForm.isGlobalAdmin
            ? "授予 {name} 全局管理员权限？"
            : "撤销 {name} 全局管理员权限？",
          { name: currentUser.name }
        ),
        confirmLabel: t("确认"),
      }))
    ) {
      return
    }

    setIsSavingUser(true)

    try {
      const user = await updateUser(token, userForm.id, {
        username: userForm.username,
        email: userForm.email,
        name: userForm.name,
        is_global_admin: userForm.isGlobalAdmin,
      })
      updateUserInList(user)
      setUserForm(null)
      onNotify("success", t("用户已更新"))
    } catch (error) {
      reportError(error)
    } finally {
      setIsSavingUser(false)
    }
  }

  function handleOpenUserPasswordDialog(user: User) {
    setUserPasswordForm({
      user,
      newPassword: "",
      confirmPassword: "",
    })
  }

  async function handleChangeUserPassword(
    event: React.FormEvent<HTMLFormElement>
  ) {
    event.preventDefault()

    if (!userPasswordForm) {
      return
    }

    const passwordError = getNewPasswordError(
      userPasswordForm.newPassword,
      userPasswordForm.confirmPassword,
      t
    )
    if (passwordError) {
      onNotify("error", passwordError)
      return
    }

    setIsChangingUserPassword(true)
    try {
      const user = await changeUserPassword(
        token,
        userPasswordForm.user.id,
        userPasswordForm.newPassword
      )
      updateUserInList(user)
      setUserPasswordForm(null)
      onNotify(
        "success",
        t("{name} 的密码已修改", { name: userPasswordForm.user.name })
      )
    } catch (error) {
      reportError(error)
    } finally {
      setIsChangingUserPassword(false)
    }
  }

  async function handleDeleteUser(user: User) {
    if (
      !(await confirmAction({
        description: t("永久删除 {name}？此操作不可恢复。", {
          name: user.name,
        }),
        confirmLabel: t("删除"),
        destructive: true,
      }))
    ) {
      return
    }

    try {
      await deleteUser(token, user.id)
      setUsers((current) => current.filter((item) => item.id !== user.id))
      onNotify("success", t("用户已删除"))
    } catch (error) {
      reportError(error)
    }
  }

  return (
    <>
      <SystemPageView
      activeSystemTab={activeTab}
      systemTabs={systemTabs}
      onSystemTabChange={onSystemTabChange}
      me={me}
      workspaces={workspaces}
      selectedWorkspaceId={selectedWorkspaceId}
      canCreateWorkspace={canCreateWorkspace}
      onSelectWorkspace={onSelectWorkspace}
      setIsWorkspaceDialogOpen={setIsWorkspaceDialogOpen}
      handleOpenCreateWorkspace={handleOpenCreateWorkspace}
      handleOpenWorkspaceMembers={handleOpenWorkspaceMembers}
      handleOpenEditWorkspace={handleOpenEditWorkspace}
      handleArchiveWorkspace={handleArchiveWorkspace}
      handleDeleteWorkspace={handleDeleteWorkspace}
      selectedWorkspace={selectedWorkspace}
      teams={teams}
      isTeamsLoading={isTeamsLoading}
      canCreateTeam={canCreateTeam}
      canManageWorkspace={canManageWorkspace}
      canManageTeamMembers={(team) => canManageTeamMembers(me, team)}
      handleOpenCreateTeam={handleOpenCreateTeam}
      handleOpenTeamMembers={handleOpenTeamMembers}
      handleOpenEditTeam={handleOpenEditTeam}
      handleArchiveTeam={handleArchiveTeam}
      handleDeleteTeam={handleDeleteTeam}
      users={users}
      filteredUsers={filteredUsers}
      isUsersLoading={isUsersLoading}
      userSearch={userSearch}
      setUserSearch={setUserSearch}
      userStatusFilter={userStatusFilter}
      setUserStatusFilter={setUserStatusFilter}
      userRoleFilter={userRoleFilter}
      setUserRoleFilter={setUserRoleFilter}
      userWorkspaceFilter={userWorkspaceFilter}
      setUserWorkspaceFilter={setUserWorkspaceFilter}
      locale={locale}
      handleOpenCreateUser={handleOpenCreateUser}
      handleToggleUser={handleToggleUser}
      handleOpenEditUser={handleOpenEditUser}
      handleOpenUserPasswordDialog={handleOpenUserPasswordDialog}
      handleDeleteUser={handleDeleteUser}
      workspaceMembers={workspaceMembers}
      isWorkspaceMembersLoading={isWorkspaceMembersLoading}
      auditLogs={auditLogs}
      isAuditLoading={isAuditLoading}
      auditSearch={auditSearch}
      setAuditSearch={(value) => {
        setAuditSearch(value)
        setAuditOffset(0)
      }}
      auditAction={auditAction}
      setAuditAction={(value) => {
        setAuditAction(value)
        setAuditOffset(0)
      }}
      onRefresh={() => {
        setAuditOffset(0)
        void loadAuditLogs(0)
      }}
      onLoadMore={() => {
        const nextOffset = auditOffset + 100
        setAuditOffset(nextOffset)
        void loadAuditLogs(nextOffset)
      }}
      hasMore={auditHasMore}
      workspaceScope={me.user.is_global_admin ? null : selectedWorkspace?.name ?? null}
      workspaceEditForm={workspaceEditForm}
      setWorkspaceEditForm={setWorkspaceEditForm}
      isSavingWorkspace={isSavingWorkspace}
      handleUpdateWorkspace={handleUpdateWorkspace}
      teamEditForm={teamEditForm}
      setTeamEditForm={setTeamEditForm}
      isSavingTeam={isSavingTeam}
      handleUpdateTeam={handleUpdateTeam}
      isUserCreateDialogOpen={isUserCreateDialogOpen}
      setIsUserCreateDialogOpen={setIsUserCreateDialogOpen}
      userCreateForm={userCreateForm}
      setUserCreateForm={setUserCreateForm}
      userCreateWorkspace={userCreateWorkspace}
      userCreateTeams={userCreateTeams}
      isUserCreateTeamsLoading={isUserCreateTeamsLoading}
      activeWorkspaces={activeWorkspaces}
      isCreatingUser={isCreatingUser}
      handleCreateUser={handleCreateUser}
      handleUserCreateWorkspaceChange={handleUserCreateWorkspaceChange}
      userForm={userForm}
      setUserForm={setUserForm}
      canManageGlobalAdmin={me.user.is_global_admin}
      isSavingUser={isSavingUser}
      handleUpdateUser={handleUpdateUser}
      userPasswordForm={userPasswordForm}
      setUserPasswordForm={setUserPasswordForm}
      isChangingUserPassword={isChangingUserPassword}
      handleChangeUserPassword={handleChangeUserPassword}
      isWorkspaceDialogOpen={isWorkspaceDialogOpen}
      workspaceForm={workspaceForm}
      setWorkspaceForm={setWorkspaceForm}
      isCreatingWorkspace={isCreatingWorkspace}
      handleCreateWorkspace={handleCreateWorkspace}
      isTeamDialogOpen={isTeamDialogOpen}
      setIsTeamDialogOpen={setIsTeamDialogOpen}
      teamWorkspace={teamWorkspace}
      manageableWorkspaces={manageableWorkspaces}
      teamForm={teamForm}
      setTeamForm={setTeamForm}
      isCreatingTeam={isCreatingTeam}
      handleCreateTeam={handleCreateTeam}
      teamAdminCandidates={teamAdminCandidates}
      isTeamAdminCandidatesLoading={isTeamAdminCandidatesLoading}
      handleTeamWorkspaceChange={handleTeamWorkspaceChange}
      workspaceMembersDialogProps={{
        workspace: workspaceMembersDialogWorkspace,
        setWorkspace: setWorkspaceMembersDialogWorkspace,
        members: workspaceMembers,
        users: me.user.is_global_admin ? users : [],
        isLoading: isWorkspaceMembersLoading,
        isCandidatesLoading: isUsersLoading,
        isMutating: isWorkspaceMembersMutating,
        canAddMembers: me.user.is_global_admin,
        canManageAdmins: me.user.is_global_admin,
        onAddMember: handleAddWorkspaceMember,
        onUpdateMemberRole: handleUpdateWorkspaceMember,
        onRemoveMember: handleRemoveWorkspaceMember,
      }}
      teamMembersDialogProps={{
        team: teamMembersDialogTeam,
        setTeam: setTeamMembersDialogTeam,
        members: teamMembers,
        workspaceMembers: teamMemberCandidates,
        isLoading: isTeamMembersLoading,
        isMutating: isTeamMembersMutating,
        canManageTeamAdmins,
        onAddMember: handleAddTeamMember,
        onUpdateMemberRole: handleUpdateTeamMember,
        onRemoveMember: handleRemoveTeamMember,
      }}
      />
      {confirmDialog}
    </>
  )
}
