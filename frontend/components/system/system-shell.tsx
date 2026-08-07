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
import {
  changeUserPassword,
  createTeam,
  createUser,
  createWorkspace,
  createWorkspaceUser,
  deleteTeam,
  deleteUser,
  deleteWorkspace,
  listAuditLogs,
  listWorkspaceMembers,
  listTeams,
  listUsers,
  updateTeam,
  updateUser,
  updateWorkspace,
} from "@/lib/api/system"
import type {
  AuditLog,
  MeResponse,
  Team,
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
import { getUserRoleKey } from "@/components/system/system-utils"

export type SystemTab = "workspaces" | "teams" | "users" | "audit"

export function SystemShell({ activeTab }: { activeTab: SystemTab }) {
  const session = useSession()
  const router = useRouter()

  if (!session.me || !session.token) {
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
  onTeamCreated: (team: Team) => void
  onTeamUpdated: (team: Team) => void
  onTeamDeleted: (teamId: string) => void
  onUserUpdated: (user: User) => void
  onNotify: (kind: AppNotification["kind"], message: string) => void
}) {
  const { language, t } = useLanguage()
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
  })
  const [users, setUsers] = React.useState<User[]>([])
  const [workspaceMembers, setWorkspaceMembers] = React.useState<
    WorkspaceMember[]
  >([])
  const [auditLogs, setAuditLogs] = React.useState<AuditLog[]>([])
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
    ...(me.user.is_global_admin
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
      setIsWorkspaceMembersLoading(true)

      try {
        setWorkspaceMembers(await listWorkspaceMembers(token, workspaceId))
      } catch (error) {
        setWorkspaceMembers([])
        reportError(error)
      } finally {
        setIsWorkspaceMembersLoading(false)
      }
    },
    [reportError, token]
  )

  const loadAuditLogs = React.useCallback(async () => {
    setIsAuditLoading(true)

    try {
      setAuditLogs(await listAuditLogs(token))
    } catch (error) {
      setAuditLogs([])
      reportError(error)
    } finally {
      setIsAuditLoading(false)
    }
  }, [reportError, token])

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
    if (activeTab !== "audit" || !me.user.is_global_admin) {
      return
    }

    // eslint-disable-next-line react-hooks/set-state-in-effect
    void loadAuditLogs()
  }, [activeTab, loadAuditLogs, me.user.is_global_admin])

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
      setTeamForm({ workspaceId: "", name: "", description: "", adminUserId: "" })
      if (team.workspace_id === selectedWorkspaceId) {
        onTeamCreated(team)
      } else {
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
      !window.confirm(
        t("{action} {name}？", {
          action: actionLabel,
          name: displayWorkspaceName(workspace, t),
        })
      )
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
      !window.confirm(
        t("永久删除 {name}？此操作不可恢复。", {
          name: displayWorkspaceName(workspace, t),
        })
      )
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
      !window.confirm(
        t("{action} {name}？", {
          action: actionLabel,
          name: displayTeamName(team, t),
        })
      )
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
      !window.confirm(
        t("永久删除 {name}？此操作不可恢复。", {
          name: displayTeamName(team, t),
        })
      )
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
      })
      setUserCreateTeams([])
      onNotify("success", t("用户已新建"))
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
    })
  }

  async function handleUpdateUser(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()

    if (!userForm) {
      return
    }

    setIsSavingUser(true)

    try {
      const user = await updateUser(token, userForm.id, {
        username: userForm.username,
        email: userForm.email,
        name: userForm.name,
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
      !window.confirm(
        t("永久删除 {name}？此操作不可恢复。", { name: user.name })
      )
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
      handleOpenEditWorkspace={handleOpenEditWorkspace}
      handleArchiveWorkspace={handleArchiveWorkspace}
      handleDeleteWorkspace={handleDeleteWorkspace}
      selectedWorkspace={selectedWorkspace}
      teams={teams}
      isTeamsLoading={isTeamsLoading}
      canCreateTeam={canCreateTeam}
      canManageWorkspace={canManageWorkspace}
      handleOpenCreateTeam={handleOpenCreateTeam}
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
    />
  )
}
