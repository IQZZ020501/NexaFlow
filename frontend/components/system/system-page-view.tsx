import * as React from "react"
import { useLanguage } from "@/contexts/language-provider"
import type {
  AuditLog,
  MeResponse,
  Team,
  User,
  Workspace,
  WorkspaceCreateResponse,
  WorkspaceMember,
} from "@/lib/api/system"
import { cn } from "@/lib/utils"
import type { SystemTabKey } from "@/app/routing"
import {
  CreateTeamDialog,
  CreateWorkspaceDialog,
  EditTeamDialog,
  EditWorkspaceDialog,
} from "@/components/system/dialogs/scope-dialogs"
import {
  CreateUserDialog,
  EditUserDialog,
  UserPasswordDialog,
} from "@/components/system/dialogs/user-dialogs"
import { AuditPanel } from "@/components/system/panels/audit-panel"
import { GlobalUsersPanel } from "@/components/system/panels/global-users-panel"
import { TeamsPanel } from "@/components/system/panels/teams-panel"
import { WorkspacesPanel } from "@/components/system/panels/workspaces-panel"
import { WorkspaceUsersPanel } from "@/components/system/panels/workspace-users-panel"
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
  canCreateWorkspace: boolean
  onSelectWorkspace: (workspaceId: string) => void
  setIsWorkspaceDialogOpen: React.Dispatch<React.SetStateAction<boolean>>
  handleOpenEditWorkspace: (workspace: Workspace) => void
  handleArchiveWorkspace: (workspace: Workspace) => void | Promise<void>
  handleDeleteWorkspace: (workspace: Workspace) => void | Promise<void>
  selectedWorkspace: Workspace | null
  teams: Team[]
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
  isWorkspaceMembersLoading: boolean
  auditLogs: AuditLog[]
  isAuditLoading: boolean
  workspaceEditForm: ScopeEditForm | null
  setWorkspaceEditForm: React.Dispatch<
    React.SetStateAction<ScopeEditForm | null>
  >
  isSavingWorkspace: boolean
  handleUpdateWorkspace: React.FormEventHandler<HTMLFormElement>
  teamEditForm: ScopeEditForm | null
  setTeamEditForm: React.Dispatch<React.SetStateAction<ScopeEditForm | null>>
  isSavingTeam: boolean
  handleUpdateTeam: React.FormEventHandler<HTMLFormElement>
  isUserCreateDialogOpen: boolean
  setIsUserCreateDialogOpen: React.Dispatch<React.SetStateAction<boolean>>
  userCreateForm: UserCreateForm
  setUserCreateForm: React.Dispatch<React.SetStateAction<UserCreateForm>>
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
  canCreateWorkspace,
  onSelectWorkspace,
  setIsWorkspaceDialogOpen,
  handleOpenEditWorkspace,
  handleArchiveWorkspace,
  handleDeleteWorkspace,
  selectedWorkspace,
  teams,
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
  isWorkspaceMembersLoading,
  auditLogs,
  isAuditLoading,
  workspaceEditForm,
  setWorkspaceEditForm,
  isSavingWorkspace,
  handleUpdateWorkspace,
  teamEditForm,
  setTeamEditForm,
  isSavingTeam,
  handleUpdateTeam,
  isUserCreateDialogOpen,
  setIsUserCreateDialogOpen,
  userCreateForm,
  setUserCreateForm,
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
            isWorkspaceMembersLoading={isWorkspaceMembersLoading}
            locale={locale}
            handleOpenCreateUser={handleOpenCreateUser}
          />
        ) : null}

        {activeSystemTab === "audit" && me.user.is_global_admin ? (
          <AuditPanel
            auditLogs={auditLogs}
            isAuditLoading={isAuditLoading}
            locale={locale}
          />
        ) : null}
      </div>

      <EditWorkspaceDialog
        workspaceEditForm={workspaceEditForm}
        setWorkspaceEditForm={setWorkspaceEditForm}
        isSavingWorkspace={isSavingWorkspace}
        handleUpdateWorkspace={handleUpdateWorkspace}
      />
      <EditTeamDialog
        teamEditForm={teamEditForm}
        setTeamEditForm={setTeamEditForm}
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
        isChangingUserPassword={isChangingUserPassword}
        handleChangeUserPassword={handleChangeUserPassword}
      />
      <CreateWorkspaceDialog
        isWorkspaceDialogOpen={isWorkspaceDialogOpen}
        setIsWorkspaceDialogOpen={setIsWorkspaceDialogOpen}
        workspaceForm={workspaceForm}
        setWorkspaceForm={setWorkspaceForm}
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
        isCreatingTeam={isCreatingTeam}
        handleCreateTeam={handleCreateTeam}
      />
    </div>
  )
}
