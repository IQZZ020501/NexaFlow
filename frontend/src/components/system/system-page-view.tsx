import * as React from "react"
import Link from "next/link"
import {
  ActivityIcon,
  BookOpenIcon,
  ChevronDownIcon,
  KeyRoundIcon,
  MailIcon,
  ShieldCheckIcon,
  SparklesIcon,
  BoxesIcon,
  WrenchIcon,
} from "lucide-react"
import { useLanguage } from "@/contexts/language-provider"
import type {
  AuditLog,
  MeResponse,
  Team,
  User,
  Workspace,
  WorkspaceMember,
} from "@/lib/api/system"
import { cn } from "@/lib/utils"
import type { SystemTab } from "./system-shell"
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
import { TeamMembersDialog } from "@/components/system/dialogs/team-members-dialog"
import { WorkspaceMembersDialog } from "@/components/system/dialogs/workspace-members-dialog"
import { AuditPanel } from "@/components/system/panels/audit-panel"
import { GlobalUsersPanel } from "@/components/system/panels/global-users-panel"
import { TeamsPanel } from "@/components/system/panels/teams-panel"
import { WorkspacesPanel } from "@/components/system/panels/workspaces-panel"
import { WorkspaceUsersPanel } from "@/components/system/panels/workspace-users-panel"
import {
  ResourcePermissionsPage,
  type ResourcePermissionPageType,
} from "@/components/system/resource-permissions-page"
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

type SystemTabItem = {
  key: SystemTab
  label: string
  icon: React.ElementType
}

type SystemPageViewProps = {
  activeSystemTab: SystemTab
  systemTabs: SystemTabItem[]
  onSystemTabChange: (tab: SystemTab) => void
  resourcePermissionType: ResourcePermissionPageType
  onResourcePermissionTypeChange: (
    type: ResourcePermissionPageType
  ) => void
  me: MeResponse
  workspaces: Workspace[]
  selectedWorkspaceId: string | null
  canCreateWorkspace: boolean
  onSelectWorkspace: (workspaceId: string) => void
  setIsWorkspaceDialogOpen: React.Dispatch<React.SetStateAction<boolean>>
  handleOpenCreateWorkspace: () => void
  handleOpenWorkspaceMembers: (workspace: Workspace) => void
  handleOpenEditWorkspace: (workspace: Workspace) => void
  handleArchiveWorkspace: (workspace: Workspace) => void | Promise<void>
  handleDeleteWorkspace: (workspace: Workspace) => void | Promise<void>
  selectedWorkspace: Workspace | null
  teams: Team[]
  isTeamsLoading: boolean
  canCreateTeam: boolean
  canManageWorkspace: boolean
  canManageTeamMembers: (team: Team) => boolean
  handleOpenCreateTeam: () => void
  handleOpenTeamMembers: (team: Team) => void
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
  auditSearch?: string
  setAuditSearch?: (value: string) => void
  auditAction?: string
  setAuditAction?: (value: string) => void
  onRefresh?: () => void
  hasMore?: boolean
  total?: number
  page?: number
  pageSize?: import("@/components/system/pagination-footer").SystemPageSize
  onPageChange?: (page: number) => void
  onPageSizeChange?: (pageSize: import("@/components/system/pagination-footer").SystemPageSize) => void
  workspaceScope?: string | null
  /** Loads every matching audit log for the CSV export. */
  loadAll?: () => Promise<AuditLog[]>
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
  canManageGlobalAdmin: boolean
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
  teamAdminCandidates: WorkspaceMember[]
  isTeamAdminCandidatesLoading: boolean
  handleTeamWorkspaceChange: (workspaceId: string) => void
  workspaceMembersDialogProps: React.ComponentProps<
    typeof WorkspaceMembersDialog
  >
  teamMembersDialogProps: React.ComponentProps<typeof TeamMembersDialog>
}

/**
 * Renders the system-management interface with permission-aware navigation, panels, and dialogs.
 *
 * @returns The system-management interface.
 */
export function SystemPageView({
  activeSystemTab,
  systemTabs,
  onSystemTabChange,
  resourcePermissionType,
  onResourcePermissionTypeChange,
  me,
  workspaces,
  selectedWorkspaceId,
  canCreateWorkspace,
  onSelectWorkspace,
  setIsWorkspaceDialogOpen,
  handleOpenCreateWorkspace,
  handleOpenWorkspaceMembers,
  handleOpenEditWorkspace,
  handleArchiveWorkspace,
  handleDeleteWorkspace,
  selectedWorkspace,
  teams,
  isTeamsLoading,
  canCreateTeam,
  canManageWorkspace,
  canManageTeamMembers,
  handleOpenCreateTeam,
  handleOpenTeamMembers,
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
  auditSearch = "",
  setAuditSearch = () => undefined,
  auditAction = "",
  setAuditAction = () => undefined,
  onRefresh = () => undefined,
  hasMore = false,
  total,
  page = 1,
  pageSize = 20,
  onPageChange = () => undefined,
  onPageSizeChange = () => undefined,
  workspaceScope = null,
  loadAll,
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
  canManageGlobalAdmin,
  isSavingUser,
  handleUpdateUser,
  userPasswordForm,
  setUserPasswordForm,
  isChangingUserPassword,
  handleChangeUserPassword,
  isWorkspaceDialogOpen,
  workspaceForm,
  setWorkspaceForm,
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
  teamAdminCandidates,
  isTeamAdminCandidatesLoading,
  handleTeamWorkspaceChange,
  workspaceMembersDialogProps,
  teamMembersDialogProps,
}: SystemPageViewProps) {
  const { t } = useLanguage()

  return (
    <div className="grid min-w-0 gap-4 lg:h-[calc(100svh-9.25rem)] lg:min-h-0 lg:grid-cols-[240px_minmax(0,1fr)]">
      <aside className="min-w-0 lg:sticky lg:top-20 lg:h-full lg:self-start">
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
          <div className="my-1 border-t" />
          {canManageSelectedWorkspace(me, selectedWorkspaceId) ? (
            <details className="group" open={activeSystemTab === "permissions"}>
              <summary
                className={cn(
                  "flex min-w-32 cursor-pointer list-none items-center justify-between gap-2 rounded-md px-3 py-1.5 text-left text-sm font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground lg:min-w-0 [&::-webkit-details-marker]:hidden",
                  activeSystemTab === "permissions" &&
                    "bg-foreground text-background hover:bg-foreground hover:text-background"
                )}
              >
                <span className="flex min-w-0 items-center gap-2">
                  <BoxesIcon className="size-4 shrink-0" />
                  <span>{t("资源授权")}</span>
                </span>
                <ChevronDownIcon className="size-4 shrink-0 transition-transform group-open:rotate-180" />
              </summary>
              <div className="mt-1 space-y-0.5 border-l pl-3 lg:ml-3">
                <button
                  type="button"
                  onClick={() => {
                    onResourcePermissionTypeChange("apps")
                    onSystemTabChange("permissions")
                  }}
                  className={cn(
                    "flex w-full items-center justify-start gap-2 rounded-md px-3 py-2 text-sm text-muted-foreground transition-colors hover:bg-muted hover:text-foreground",
                    activeSystemTab === "permissions" &&
                      resourcePermissionType === "apps" &&
                      "bg-primary/10 text-primary"
                  )}
                >
                  <SparklesIcon className="size-4 shrink-0" />
                  <span>{t("应用")}</span>
                </button>
                <button
                  type="button"
                  onClick={() => {
                    onResourcePermissionTypeChange("knowledge")
                    onSystemTabChange("permissions")
                  }}
                  className={cn(
                    "flex w-full items-center justify-start gap-2 rounded-md px-3 py-2 text-sm text-muted-foreground transition-colors hover:bg-muted hover:text-foreground",
                    activeSystemTab === "permissions" &&
                      resourcePermissionType === "knowledge" &&
                      "bg-primary/10 text-primary"
                  )}
                >
                  <BookOpenIcon className="size-4 shrink-0" />
                  <span>{t("知识库")}</span>
                </button>
                <button
                  type="button"
                  onClick={() => {
                    onResourcePermissionTypeChange("tools")
                    onSystemTabChange("permissions")
                  }}
                  className={cn(
                    "flex w-full items-center justify-start gap-2 rounded-md px-3 py-2 text-sm text-muted-foreground transition-colors hover:bg-muted hover:text-foreground",
                    activeSystemTab === "permissions" &&
                      resourcePermissionType === "tools" &&
                      "bg-primary/10 text-primary"
                  )}
                >
                  <WrenchIcon className="size-4 shrink-0" />
                  <span>{t("工具")}</span>
                </button>
              </div>
            </details>
          ) : null}
          {me.user.is_global_admin ? (
            <Link
              href="/system/operations"
              className="flex min-w-32 items-center gap-2 rounded-md px-3 py-1.5 text-left text-sm font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground lg:min-w-0"
            >
              <ActivityIcon className="size-4 shrink-0" />
              <span>{t("系统运行")}</span>
            </Link>
          ) : null}
          {me.user.is_global_admin ? (
            <Link
              href="/system/email"
              className="flex min-w-32 items-center gap-2 rounded-md px-3 py-1.5 text-left text-sm font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground lg:min-w-0"
            >
              <MailIcon className="size-4 shrink-0" />
              <span>{t("SMTP 邮件")}</span>
            </Link>
          ) : null}
          {canManageAnyWorkspace(me, selectedWorkspaceId) ? (
            <Link
              href="/system/governance"
              className="flex min-w-32 items-center gap-2 rounded-md px-3 py-1.5 text-left text-sm font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground lg:min-w-0"
            >
              <ShieldCheckIcon className="size-4 shrink-0" />
              <span>{t("工作空间治理")}</span>
            </Link>
          ) : null}
          <Link
            href="/system/security"
            className="flex min-w-32 items-center gap-2 rounded-md px-3 py-1.5 text-left text-sm font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground lg:min-w-0"
          >
            <KeyRoundIcon className="size-4 shrink-0" />
            <span>{t("会话安全")}</span>
          </Link>
        </div>
      </aside>

      <div className="min-w-0 lg:h-full lg:min-h-0 lg:overflow-hidden">
        {activeSystemTab === "permissions" ? (
          <ResourcePermissionsPage type={resourcePermissionType} />
        ) : null}

        {activeSystemTab === "workspaces" ? (
          <WorkspacesPanel
            me={me}
            workspaces={workspaces}
            selectedWorkspaceId={selectedWorkspaceId}
            canCreateWorkspace={canCreateWorkspace}
            onSelectWorkspace={onSelectWorkspace}
            onOpenCreateWorkspace={handleOpenCreateWorkspace}
            handleOpenWorkspaceMembers={handleOpenWorkspaceMembers}
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
            canManageTeamMembers={canManageTeamMembers}
            handleOpenCreateTeam={handleOpenCreateTeam}
            handleOpenTeamMembers={handleOpenTeamMembers}
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
            handleOpenWorkspaceMembers={() => {
              if (selectedWorkspace) {
                handleOpenWorkspaceMembers(selectedWorkspace)
              }
            }}
          />
        ) : null}

        {activeSystemTab === "audit" && (me.user.is_global_admin || canManageWorkspace) ? (
          <AuditPanel
            auditLogs={auditLogs}
            isAuditLoading={isAuditLoading}
            locale={locale}
            auditSearch={auditSearch}
            setAuditSearch={setAuditSearch}
            auditAction={auditAction}
            setAuditAction={setAuditAction}
            onRefresh={onRefresh}
            hasMore={hasMore}
            total={total}
            page={page}
            pageSize={pageSize}
            onPageChange={onPageChange}
            onPageSizeChange={onPageSizeChange}
            workspaceScope={workspaceScope}
            loadAll={loadAll}
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
        canManageGlobalAdmin={canManageGlobalAdmin}
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
        users={users}
        isUsersLoading={isUsersLoading}
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
        teamAdminCandidates={teamAdminCandidates}
        isTeamAdminCandidatesLoading={isTeamAdminCandidatesLoading}
        handleTeamWorkspaceChange={handleTeamWorkspaceChange}
      />
      <WorkspaceMembersDialog {...workspaceMembersDialogProps} />
      <TeamMembersDialog {...teamMembersDialogProps} />
    </div>
  )
}

/**
 * Determines whether the current user can manage the selected workspace or any workspace.
 *
 * @param me - The current user's profile and workspace memberships
 * @param workspaceId - The selected workspace identifier, or `null` when no workspace is selected
 * @returns `true` if the user is a global administrator, administers the selected workspace, or administers any workspace, `false` otherwise.
 */
function canManageAnyWorkspace(me: MeResponse, workspaceId: string | null) {
  return Boolean(
    me.user.is_global_admin ||
      me.memberships.some(
        (membership) =>
          membership.workspace_id === workspaceId && membership.role === "admin"
      ) ||
      me.memberships.some((membership) => membership.role === "admin")
  )
}

function canManageSelectedWorkspace(
  me: MeResponse,
  workspaceId: string | null
) {
  return Boolean(
    me.user.is_global_admin ||
      me.memberships.some(
        (membership) =>
          membership.workspace_id === workspaceId && membership.role === "admin"
      )
  )
}
