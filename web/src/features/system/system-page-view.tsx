import * as React from "react"
import { useLanguage } from "@/components/language-provider"
import type {
  AuditLog,
  MeResponse,
  Team,
  User,
  Workspace,
  WorkspaceCreateResponse,
  WorkspaceMember,
} from "@/lib/api"
import { cn } from "@/lib/utils"
import type { SystemTabKey } from "@/app/routing"
import {
  CreateTeamDialog,
  CreateWorkspaceDialog,
  EditTeamDialog,
  EditWorkspaceDialog,
} from "@/features/system/dialogs/scope-dialogs"
import {
  CreateUserDialog,
  EditUserDialog,
  UserPasswordDialog,
} from "@/features/system/dialogs/user-dialogs"
import { AuditPanel } from "@/features/system/panels/audit-panel"
import { GlobalUsersPanel } from "@/features/system/panels/global-users-panel"
import { TeamsPanel } from "@/features/system/panels/teams-panel"
import { WorkspacesPanel } from "@/features/system/panels/workspaces-panel"
import { WorkspaceUsersPanel } from "@/features/system/panels/workspace-users-panel"
import type {
  ScopeEditForm,
  TeamForm,
  UserCreateForm,
  UserForm,
  UserPasswordForm,
  UserRoleFilter,
  UserStatusFilter,
  WorkspaceForm,
} from "@/features/system/types"

type SystemTab = {
  key: SystemTabKey
  label: string
  icon: React.ElementType
}

type SystemPageViewProps = {
  activeSystemTab: SystemTabKey
  systemTabs: SystemTab[]
  onSystemTabChange: (tab: SystemTabKey) => void
  me: MeResponse
  workspaces: Workspace[]
  selectedWorkspaceId: string | null
  workspaceError: string | null
  canCreateWorkspace: boolean
  onSelectWorkspace: (workspaceId: string) => void
  setIsWorkspaceDialogOpen: React.Dispatch<React.SetStateAction<boolean>>
  handleOpenEditWorkspace: (workspace: Workspace) => void
  handleArchiveWorkspace: (workspace: Workspace) => void | Promise<void>
  handleDeleteWorkspace: (workspace: Workspace) => void | Promise<void>
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
  users: User[]
  filteredUsers: User[]
  isUsersLoading: boolean
  userSearch: string
  setUserSearch: React.Dispatch<React.SetStateAction<string>>
  userStatusFilter: UserStatusFilter
  setUserStatusFilter: React.Dispatch<React.SetStateAction<UserStatusFilter>>
  userRoleFilter: UserRoleFilter
  setUserRoleFilter: React.Dispatch<React.SetStateAction<UserRoleFilter>>
  userWorkspaceFilter: string
  setUserWorkspaceFilter: React.Dispatch<React.SetStateAction<string>>
  locale: string
  handleOpenCreateUser: () => void
  handleToggleUser: (user: User) => void | Promise<void>
  handleOpenEditUser: (user: User) => void
  handleOpenUserPasswordDialog: (user: User) => void
  handleDeleteUser: (user: User) => void | Promise<void>
  workspaceMembers: WorkspaceMember[]
  workspaceMembersError: string | null
  isWorkspaceMembersLoading: boolean
  auditLogs: AuditLog[]
  auditError: string | null
  isAuditLoading: boolean
  workspaceEditForm: ScopeEditForm | null
  setWorkspaceEditForm: React.Dispatch<
    React.SetStateAction<ScopeEditForm | null>
  >
  setWorkspaceError: React.Dispatch<React.SetStateAction<string | null>>
  isSavingWorkspace: boolean
  handleUpdateWorkspace: React.FormEventHandler<HTMLFormElement>
  teamEditForm: ScopeEditForm | null
  setTeamEditForm: React.Dispatch<React.SetStateAction<ScopeEditForm | null>>
  teamError: string | null
  setTeamError: React.Dispatch<React.SetStateAction<string | null>>
  isSavingTeam: boolean
  handleUpdateTeam: React.FormEventHandler<HTMLFormElement>
  isUserCreateDialogOpen: boolean
  setIsUserCreateDialogOpen: React.Dispatch<React.SetStateAction<boolean>>
  userCreateForm: UserCreateForm
  setUserCreateForm: React.Dispatch<React.SetStateAction<UserCreateForm>>
  userCreateError: string | null
  setUserCreateError: React.Dispatch<React.SetStateAction<string | null>>
  userCreateWorkspace: Workspace | null
  userCreateTeams: Team[]
  isUserCreateTeamsLoading: boolean
  activeWorkspaces: Workspace[]
  isCreatingUser: boolean
  handleCreateUser: React.FormEventHandler<HTMLFormElement>
  handleUserCreateWorkspaceChange: (workspaceId: string) => void
  userForm: UserForm | null
  setUserForm: React.Dispatch<React.SetStateAction<UserForm | null>>
  isSavingUser: boolean
  handleUpdateUser: React.FormEventHandler<HTMLFormElement>
  userPasswordForm: UserPasswordForm | null
  setUserPasswordForm: React.Dispatch<
    React.SetStateAction<UserPasswordForm | null>
  >
  userPasswordError: string | null
  setUserPasswordError: React.Dispatch<React.SetStateAction<string | null>>
  isChangingUserPassword: boolean
  handleChangeUserPassword: React.FormEventHandler<HTMLFormElement>
  isWorkspaceDialogOpen: boolean
  workspaceForm: WorkspaceForm
  setWorkspaceForm: React.Dispatch<React.SetStateAction<WorkspaceForm>>
  workspaceNotice: WorkspaceCreateResponse | null
  isCreatingWorkspace: boolean
  handleCreateWorkspace: React.FormEventHandler<HTMLFormElement>
  isTeamDialogOpen: boolean
  setIsTeamDialogOpen: React.Dispatch<React.SetStateAction<boolean>>
  teamWorkspace: Workspace | null
  manageableWorkspaces: Workspace[]
  teamForm: TeamForm
  setTeamForm: React.Dispatch<React.SetStateAction<TeamForm>>
  isCreatingTeam: boolean
  handleCreateTeam: React.FormEventHandler<HTMLFormElement>
}

export function SystemPageView({
  activeSystemTab,
  systemTabs,
  onSystemTabChange,
  me,
  workspaces,
  selectedWorkspaceId,
  workspaceError,
  canCreateWorkspace,
  onSelectWorkspace,
  setIsWorkspaceDialogOpen,
  handleOpenEditWorkspace,
  handleArchiveWorkspace,
  handleDeleteWorkspace,
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
  users,
  filteredUsers,
  isUsersLoading,
  userSearch,
  setUserSearch,
  userStatusFilter,
  setUserStatusFilter,
  userRoleFilter,
  setUserRoleFilter,
  userWorkspaceFilter,
  setUserWorkspaceFilter,
  locale,
  handleOpenCreateUser,
  handleToggleUser,
  handleOpenEditUser,
  handleOpenUserPasswordDialog,
  handleDeleteUser,
  workspaceMembers,
  workspaceMembersError,
  isWorkspaceMembersLoading,
  auditLogs,
  auditError,
  isAuditLoading,
  workspaceEditForm,
  setWorkspaceEditForm,
  setWorkspaceError,
  isSavingWorkspace,
  handleUpdateWorkspace,
  teamEditForm,
  setTeamEditForm,
  teamError,
  setTeamError,
  isSavingTeam,
  handleUpdateTeam,
  isUserCreateDialogOpen,
  setIsUserCreateDialogOpen,
  userCreateForm,
  setUserCreateForm,
  userCreateError,
  setUserCreateError,
  userCreateWorkspace,
  userCreateTeams,
  isUserCreateTeamsLoading,
  activeWorkspaces,
  isCreatingUser,
  handleCreateUser,
  handleUserCreateWorkspaceChange,
  userForm,
  setUserForm,
  isSavingUser,
  handleUpdateUser,
  userPasswordForm,
  setUserPasswordForm,
  userPasswordError,
  setUserPasswordError,
  isChangingUserPassword,
  handleChangeUserPassword,
  isWorkspaceDialogOpen,
  workspaceForm,
  setWorkspaceForm,
  workspaceNotice,
  isCreatingWorkspace,
  handleCreateWorkspace,
  isTeamDialogOpen,
  setIsTeamDialogOpen,
  teamWorkspace,
  manageableWorkspaces,
  teamForm,
  setTeamForm,
  isCreatingTeam,
  handleCreateTeam,
}: SystemPageViewProps) {
  const { t } = useLanguage()

  return (
    <div className="grid min-w-0 gap-4 lg:h-[calc(100svh-9.25rem)] lg:grid-cols-[240px_minmax(0,1fr)]">
      <aside className="lg:sticky lg:top-20 lg:h-full lg:self-start">
        <div
          role="tablist"
          aria-label={t("系统管理")}
          className="flex gap-1 overflow-x-auto rounded-lg border bg-background p-1 shadow-sm lg:h-full lg:flex-col lg:overflow-visible"
        >
          {systemTabs.map((tab) => {
            const Icon = tab.icon
            const isActive = activeSystemTab === tab.key

            return (
              <button
                key={tab.key}
                id={`system-tab-${tab.key}`}
                type="button"
                role="tab"
                aria-selected={isActive}
                aria-controls={`system-panel-${tab.key}`}
                className={cn(
                  "flex min-w-32 items-center justify-between gap-3 rounded-md px-3 py-1.5 text-left text-sm font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground lg:min-w-0",
                  isActive &&
                    "bg-foreground text-background shadow-sm hover:bg-foreground hover:text-background"
                )}
                onClick={() => onSystemTabChange(tab.key)}
              >
                <span className="flex min-w-0 items-center gap-2">
                  <Icon className="size-4 shrink-0" />
                  <span>{tab.label}</span>
                </span>
              </button>
            )
          })}
        </div>
      </aside>

      <div className="min-w-0 lg:h-full lg:overflow-hidden">
        {activeSystemTab === "workspaces" ? (
          <WorkspacesPanel
            me={me}
            workspaces={workspaces}
            selectedWorkspaceId={selectedWorkspaceId}
            workspaceError={workspaceError}
            canCreateWorkspace={canCreateWorkspace}
            onSelectWorkspace={onSelectWorkspace}
            onOpenCreateWorkspace={() => setIsWorkspaceDialogOpen(true)}
            handleOpenEditWorkspace={handleOpenEditWorkspace}
            handleArchiveWorkspace={handleArchiveWorkspace}
            handleDeleteWorkspace={handleDeleteWorkspace}
          />
        ) : null}

        {activeSystemTab === "teams" ? (
          <TeamsPanel
            selectedWorkspace={selectedWorkspace}
            teams={teams}
            teamsError={teamsError}
            isTeamsLoading={isTeamsLoading}
            canCreateTeam={canCreateTeam}
            canManageWorkspace={canManageWorkspace}
            handleOpenCreateTeam={handleOpenCreateTeam}
            handleOpenEditTeam={handleOpenEditTeam}
            handleArchiveTeam={handleArchiveTeam}
            handleDeleteTeam={handleDeleteTeam}
          />
        ) : null}

        {activeSystemTab === "users" && me.user.is_global_admin ? (
          <GlobalUsersPanel
            me={me}
            users={users}
            filteredUsers={filteredUsers}
            workspaces={workspaces}
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
          />
        ) : null}

        {activeSystemTab === "users" &&
        !me.user.is_global_admin &&
        canManageWorkspace ? (
          <WorkspaceUsersPanel
            selectedWorkspace={selectedWorkspace}
            selectedWorkspaceId={selectedWorkspaceId}
            workspaceMembers={workspaceMembers}
            workspaceMembersError={workspaceMembersError}
            isWorkspaceMembersLoading={isWorkspaceMembersLoading}
            locale={locale}
            handleOpenCreateUser={handleOpenCreateUser}
          />
        ) : null}

        {activeSystemTab === "audit" && me.user.is_global_admin ? (
          <AuditPanel
            auditLogs={auditLogs}
            auditError={auditError}
            isAuditLoading={isAuditLoading}
            locale={locale}
          />
        ) : null}
      </div>

      <EditWorkspaceDialog
        workspaceEditForm={workspaceEditForm}
        setWorkspaceEditForm={setWorkspaceEditForm}
        workspaceError={workspaceError}
        setWorkspaceError={setWorkspaceError}
        isSavingWorkspace={isSavingWorkspace}
        handleUpdateWorkspace={handleUpdateWorkspace}
      />
      <EditTeamDialog
        teamEditForm={teamEditForm}
        setTeamEditForm={setTeamEditForm}
        teamError={teamError}
        setTeamError={setTeamError}
        selectedWorkspace={selectedWorkspace}
        selectedWorkspaceId={selectedWorkspaceId}
        isSavingTeam={isSavingTeam}
        handleUpdateTeam={handleUpdateTeam}
      />
      <CreateUserDialog
        isUserCreateDialogOpen={isUserCreateDialogOpen}
        setIsUserCreateDialogOpen={setIsUserCreateDialogOpen}
        userCreateForm={userCreateForm}
        setUserCreateForm={setUserCreateForm}
        userCreateError={userCreateError}
        setUserCreateError={setUserCreateError}
        userCreateWorkspace={userCreateWorkspace}
        userCreateTeams={userCreateTeams}
        isUserCreateTeamsLoading={isUserCreateTeamsLoading}
        activeWorkspaces={activeWorkspaces}
        me={me}
        selectedWorkspaceId={selectedWorkspaceId}
        isCreatingUser={isCreatingUser}
        handleCreateUser={handleCreateUser}
        handleUserCreateWorkspaceChange={handleUserCreateWorkspaceChange}
      />
      <EditUserDialog
        userForm={userForm}
        setUserForm={setUserForm}
        me={me}
        isSavingUser={isSavingUser}
        handleUpdateUser={handleUpdateUser}
      />
      <UserPasswordDialog
        userPasswordForm={userPasswordForm}
        setUserPasswordForm={setUserPasswordForm}
        userPasswordError={userPasswordError}
        setUserPasswordError={setUserPasswordError}
        isChangingUserPassword={isChangingUserPassword}
        handleChangeUserPassword={handleChangeUserPassword}
      />
      <CreateWorkspaceDialog
        isWorkspaceDialogOpen={isWorkspaceDialogOpen}
        setIsWorkspaceDialogOpen={setIsWorkspaceDialogOpen}
        workspaceForm={workspaceForm}
        setWorkspaceForm={setWorkspaceForm}
        workspaceError={workspaceError}
        workspaceNotice={workspaceNotice}
        isCreatingWorkspace={isCreatingWorkspace}
        handleCreateWorkspace={handleCreateWorkspace}
      />
      <CreateTeamDialog
        isTeamDialogOpen={isTeamDialogOpen}
        setIsTeamDialogOpen={setIsTeamDialogOpen}
        teamWorkspace={teamWorkspace}
        manageableWorkspaces={manageableWorkspaces}
        teamForm={teamForm}
        setTeamForm={setTeamForm}
        teamError={teamError}
        isCreatingTeam={isCreatingTeam}
        handleCreateTeam={handleCreateTeam}
      />
    </div>
  )
}
