import * as React from "react"
import {
  ArchiveIcon,
  ChevronDownIcon,
  CircleCheckIcon,
  CircleOffIcon,
  Building2Icon,
  HistoryIcon,
  LanguagesIcon,
  LockIcon,
  LoaderCircleIcon,
  LogOutIcon,
  MonitorIcon,
  MoonIcon,
  PencilIcon,
  PlusIcon,
  RotateCcwIcon,
  SearchIcon,
  SettingsIcon,
  SunIcon,
  Trash2Icon,
  UserCogIcon,
  UsersIcon,
  XIcon,
} from "lucide-react"

import { Avatar, AvatarFallback } from "@/components/ui/avatar"
import { useLanguage } from "@/components/language-provider"
import { useTheme } from "@/components/theme-provider"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import {
  Field,
  FieldDescription,
  FieldGroup,
  FieldLabel,
} from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import {
  ApiError,
  changePassword,
  changeUserPassword,
  createTeam,
  createUser,
  createWorkspaceUser,
  createWorkspace,
  deleteTeam,
  deleteUser,
  deleteWorkspace,
  getMe,
  listAuditLogs,
  listWorkspaceMembers,
  listTeams,
  listUsers,
  listWorkspaces,
  login,
  type AuditLog,
  type MeResponse,
  type Team,
  type User,
  type Workspace,
  type WorkspaceCreateResponse,
  type WorkspaceMember,
  updateTeam,
  updateUser,
  updateWorkspace,
} from "@/lib/api"
import { isEventFromDropdownMenu } from "@/lib/dom"
import {
  getPages,
  type FeaturePageConfig,
  type PageKey,
} from "@/lib/pages"
import {
  languageLocales,
  languageOptions,
  type TFunction,
  type TranslationKey,
} from "@/lib/i18n"
import { cn } from "@/lib/utils"

const TOKEN_KEY = "nexaflow.accessToken"
const WORKSPACE_KEY = "nexaflow.workspaceId"
const DEFAULT_USER_PASSWORD = "NexaFlow@123"
const STATUS_LABEL_KEYS: Record<string, TranslationKey> = {
  active: "已启用",
  archived: "已归档",
}
const AUDIT_DETAIL_LABEL_KEYS: Record<string, TranslationKey> = {
  email: "邮箱",
  is_active: "启用状态",
  is_global_admin: "全局管理员",
  name: "名称",
  slug: "标识",
  status: "状态",
  team_ids: "团队 ID",
  username: "用户名",
  workspace_id: "工作空间 ID",
}
const AUDIT_ACTION_LABEL_KEYS: Record<string, TranslationKey> = {
  "workspace.create": "新建工作空间",
  "workspace.update": "更新工作空间",
  "workspace.archive": "归档工作空间",
  "workspace.restore": "恢复工作空间",
  "workspace.delete": "删除工作空间",
  "team.create": "新建团队",
  "team.update": "更新团队",
  "team.archive": "归档团队",
  "team.restore": "恢复团队",
  "team.delete": "删除团队",
  "user.create": "新建用户",
  "user.update": "更新用户",
  "user.reset_password": "修改密码",
  "user.change_password": "修改密码",
  "user.deactivate": "停用用户",
  "user.delete": "删除用户",
}
type ThemePreference = "system" | "light" | "dark"
const themeOptions: Array<{
  value: ThemePreference
  labelKey: TranslationKey
  icon: typeof MonitorIcon
}> = [
  { value: "system", labelKey: "跟随系统", icon: MonitorIcon },
  { value: "light", labelKey: "白色", icon: SunIcon },
  { value: "dark", labelKey: "暗色", icon: MoonIcon },
]
type SystemTabKey = "workspaces" | "teams" | "users" | "audit"

type AppRoute = {
  page: PageKey
  systemTab: SystemTabKey
}

const PAGE_PATHS: Record<PageKey, string> = {
  apps: "/apps",
  knowledge: "/knowledge",
  models: "/models",
  tools: "/tools",
  system: "/system/workspaces",
}

const SYSTEM_TAB_PATHS: Record<SystemTabKey, string> = {
  workspaces: "/system/workspaces",
  teams: "/system/teams",
  users: "/system/users",
  audit: "/system/audit",
}

function routeFromPath(pathname = window.location.pathname): AppRoute {
  const path = pathname.replace(/\/+$/, "") || "/"

  switch (path) {
    case "/":
    case "/apps":
      return { page: "apps", systemTab: "workspaces" }
    case "/knowledge":
      return { page: "knowledge", systemTab: "workspaces" }
    case "/models":
      return { page: "models", systemTab: "workspaces" }
    case "/tools":
      return { page: "tools", systemTab: "workspaces" }
    case "/system":
    case "/system/workspaces":
      return { page: "system", systemTab: "workspaces" }
    case "/system/teams":
      return { page: "system", systemTab: "teams" }
    case "/system/users":
      return { page: "system", systemTab: "users" }
    case "/system/audit":
      return { page: "system", systemTab: "audit" }
    case "/system/account":
      return { page: "system", systemTab: "workspaces" }
    default:
      return { page: "apps", systemTab: "workspaces" }
  }
}

function pathForRoute(route: AppRoute) {
  if (route.page === "system") {
    return SYSTEM_TAB_PATHS[route.systemTab]
  }

  return PAGE_PATHS[route.page]
}

type LoginForm = {
  username: string
  password: string
}

type ChangePasswordForm = {
  currentPassword: string
  newPassword: string
  confirmPassword: string
}

type UserPasswordForm = {
  user: User
  newPassword: string
  confirmPassword: string
}

type WorkspaceForm = {
  name: string
  slug: string
  adminUsername: string
  adminEmail: string
  adminName: string
}

type TeamForm = {
  workspaceId: string
  name: string
  slug: string
}

type ScopeEditForm = {
  id: string
  name: string
  slug: string
}

type UserCreateForm = {
  username: string
  email: string
  name: string
  isGlobalAdmin: boolean
  workspaceId: string
  teamIds: string[]
}

type UserForm = {
  id: string
  username: string
  email: string
  name: string
  isGlobalAdmin: boolean
}

type UserStatusFilter = "all" | "active" | "inactive"
type UserRoleFilter = "all" | "global_admin" | "workspace_admin" | "team_admin" | "member"
type FilterDropdownOption = {
  value: string
  label: string
}
type AppNotification = {
  id: number
  kind: "success" | "error"
  message: string
}

function getErrorMessage(error: unknown, t: TFunction) {
  if (error instanceof ApiError) {
    return error.message
  }

  if (error instanceof Error) {
    return error.message
  }

  return t("请求失败")
}

function getNewPasswordError(
  newPassword: string,
  confirmPassword: string,
  t: TFunction
) {
  if (newPassword !== confirmPassword) {
    return t("两次输入的新密码不一致")
  }

  if (newPassword.length < 6 || !/[A-Z]/.test(newPassword)) {
    return t("密码至少 6 位，并且包含一个大写字母")
  }

  return null
}

function initials(name: string) {
  const value = name.trim() || "NexaFlow"
  return value.slice(0, 2).toUpperCase()
}

function formatDateTime(value: string, locale: string) {
  return new Intl.DateTimeFormat(locale, {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(new Date(value))
}

type DefaultNamedScope = {
  name: string
  is_default: boolean
}

function displayWorkspaceName(workspace: DefaultNamedScope, t: TFunction) {
  if (workspace.is_default && workspace.name === "Default Workspace") {
    return t("默认工作空间")
  }

  return workspace.name
}

function displayTeamName(team: DefaultNamedScope, t: TFunction) {
  if (team.is_default && team.name === "Default Team") {
    return t("默认团队")
  }

  return team.name
}

function hasWorkspaceMembership(me: MeResponse | null, workspaceId: string) {
  return Boolean(
    me?.memberships.some((membership) => membership.workspace_id === workspaceId)
  )
}

function formatUserWorkspaces(user: User, t: TFunction) {
  if (!user.workspaces.length) {
    return "-"
  }

  return user.workspaces
    .map((workspace) => displayWorkspaceName(workspace, t))
    .join(t("列表分隔符"))
}

function formatUserTeams(user: User, t: TFunction) {
  if (!user.teams.length) {
    return "-"
  }

  return user.teams
    .map((team) => displayTeamName(team, t))
    .join(t("列表分隔符"))
}

function getUserRoleLabel(user: User, t: TFunction) {
  if (user.is_global_admin) {
    return t("全局管理员")
  }

  if (user.workspaces.some((workspace) => workspace.role === "admin")) {
    return t("工作空间管理员")
  }

  if (user.teams.some((team) => team.role === "admin")) {
    return t("团队管理员")
  }

  return t("普通用户")
}

function getUserRoleKey(user: User): UserRoleFilter {
  if (user.is_global_admin) {
    return "global_admin"
  }

  if (user.workspaces.some((workspace) => workspace.role === "admin")) {
    return "workspace_admin"
  }

  if (user.teams.some((team) => team.role === "admin")) {
    return "team_admin"
  }

  return "member"
}

function getUserRoleClass(user: User) {
  const role = getUserRoleKey(user)

  if (role === "global_admin" || role === "workspace_admin") {
    return "border-amber-300/60 bg-amber-100 text-amber-700 dark:border-amber-500/40 dark:bg-amber-500/10 dark:text-amber-300"
  }

  if (role === "team_admin") {
    return "border-red-300/60 bg-red-100 text-red-600 dark:border-red-500/40 dark:bg-red-500/10 dark:text-red-300"
  }

  return "border-border bg-muted text-muted-foreground"
}

function displaySlug(slug: string, isDefault: boolean, t: TFunction) {
  if (isDefault && slug === "default") {
    return t("默认")
  }

  return slug
}

function formatAuditDetails(details: Record<string, unknown>, t: TFunction) {
  const entries = Object.entries(details).filter(
    ([, value]) => value !== null && value !== undefined && value !== ""
  )
  if (!entries.length) {
    return "-"
  }

  return entries
    .map(([key, value]) => {
      const labelKey = AUDIT_DETAIL_LABEL_KEYS[key]
      const label = labelKey ? t(labelKey) : key
      return `${label}: ${formatAuditDetailValue(key, value, t)}`
    })
    .join(t("详情分隔符"))
}

function formatAuditDetailValue(
  key: string,
  value: unknown,
  t: TFunction
): string {
  if (Array.isArray(value)) {
    return value
      .map((item) => formatAuditDetailValue(key, item, t))
      .join(t("列表分隔符"))
  }

  if (typeof value === "boolean") {
    return value ? t("是") : t("否")
  }

  if (key === "status" && typeof value === "string") {
    const labelKey = STATUS_LABEL_KEYS[value]
    return labelKey ? t(labelKey) : value
  }

  return String(value)
}

function getMembershipRole(me: MeResponse | null, workspaceId: string | null) {
  if (!me || !workspaceId) {
    return null
  }

  return (
    me.memberships.find((membership) => membership.workspace_id === workspaceId)
      ?.role ?? null
  )
}

function FilterDropdown({
  ariaLabel,
  value,
  options,
  onChange,
}: {
  ariaLabel: string
  value: string
  options: FilterDropdownOption[]
  onChange: (value: string) => void
}) {
  const selectedOption = options.find((option) => option.value === value)

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          className="flex h-8 w-full items-center justify-between gap-2 rounded-lg border bg-background px-2 text-sm"
          aria-label={ariaLabel}
        >
          <span className="truncate">{selectedOption?.label ?? value}</span>
          <ChevronDownIcon className="size-4 shrink-0 text-muted-foreground" />
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent
        align="start"
        className="min-w-[var(--radix-dropdown-menu-trigger-width)]"
      >
        <DropdownMenuGroup>
          {options.map((option) => (
            <DropdownMenuItem
              key={option.value}
              onSelect={() => onChange(option.value)}
              className="justify-between"
            >
              <span className="truncate">{option.label}</span>
              {option.value === value ? (
                <CircleCheckIcon className="text-primary" />
              ) : null}
            </DropdownMenuItem>
          ))}
        </DropdownMenuGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

function OperationNotification({
  notification,
  onDismiss,
}: {
  notification: AppNotification | null
  onDismiss: () => void
}) {
  const { t } = useLanguage()

  if (!notification) {
    return null
  }

  const Icon = notification.kind === "success" ? CircleCheckIcon : CircleOffIcon

  return (
    <div
      className="fixed left-1/2 top-4 z-50 w-[calc(100%-2rem)] max-w-sm -translate-x-1/2"
      role={notification.kind === "error" ? "alert" : "status"}
      aria-live={notification.kind === "error" ? "assertive" : "polite"}
    >
      <div
        className={cn(
          "flex items-center gap-3 rounded-lg border bg-background px-3 py-2 text-sm shadow-lg",
          notification.kind === "success"
            ? "border-emerald-300 text-emerald-700 dark:border-emerald-500/50 dark:text-emerald-300"
            : "border-destructive/50 text-destructive"
        )}
      >
        <Icon className="size-4 shrink-0" />
        <span className="min-w-0 flex-1 truncate">{notification.message}</span>
        <Button
          type="button"
          variant="ghost"
          size="icon-sm"
          onClick={onDismiss}
          aria-label={t("关闭提示")}
        >
          <XIcon />
        </Button>
      </div>
    </div>
  )
}

function LoginScreen({
  onLogin,
}: {
  onLogin: (token: string, mustChangePassword: boolean) => void
}) {
  const { t } = useLanguage()
  const [form, setForm] = React.useState<LoginForm>({
    username: "",
    password: "",
  })
  const [error, setError] = React.useState<string | null>(null)
  const [isSubmitting, setIsSubmitting] = React.useState(false)

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError(null)
    setIsSubmitting(true)

    try {
      const payload = await login(form.username, form.password)
      onLogin(payload.access_token, payload.must_change_password)
    } catch (error) {
      setError(getErrorMessage(error, t))
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <main className="flex min-h-svh items-center justify-center bg-muted/30 p-6">
      <Card className="w-full max-w-sm">
        <CardHeader>
          <CardTitle>NexaFlow</CardTitle>
          <CardDescription>{t("登录到你的工作空间")}</CardDescription>
        </CardHeader>
        <form onSubmit={handleSubmit}>
          <CardContent>
            <FieldGroup>
              <Field>
                <FieldLabel htmlFor="username">{t("用户名")}</FieldLabel>
                <Input
                  id="username"
                  autoComplete="username"
                  value={form.username}
                  onChange={(event) =>
                    setForm((current) => ({
                      ...current,
                      username: event.target.value,
                    }))
                  }
                  required
                />
              </Field>
              <Field>
                <FieldLabel htmlFor="password">{t("密码")}</FieldLabel>
                <Input
                  id="password"
                  type="password"
                  autoComplete="current-password"
                  value={form.password}
                  onChange={(event) =>
                    setForm((current) => ({
                      ...current,
                      password: event.target.value,
                    }))
                  }
                  required
                />
              </Field>
              {error ? (
                <p className="text-sm text-destructive">{error}</p>
              ) : null}
            </FieldGroup>
          </CardContent>
          <CardFooter className="pt-6">
            <Button className="w-full" disabled={isSubmitting}>
              {isSubmitting ? (
                <LoaderCircleIcon data-icon="inline-start" />
              ) : null}
              {t("登录")}
            </Button>
          </CardFooter>
        </form>
      </Card>
    </main>
  )
}

function ChangePasswordDialog({
  open,
  token,
  title,
  description,
  canDismiss = false,
  requireCurrentPassword = false,
  onOpenChange,
  onChanged,
}: {
  open: boolean
  token: string
  title?: string
  description?: string
  canDismiss?: boolean
  requireCurrentPassword?: boolean
  onOpenChange?: (open: boolean) => void
  onChanged: () => void
}) {
  const { t } = useLanguage()
  const [form, setForm] = React.useState<ChangePasswordForm>({
    currentPassword: "",
    newPassword: "",
    confirmPassword: "",
  })
  const [error, setError] = React.useState<string | null>(null)
  const [isSubmitting, setIsSubmitting] = React.useState(false)

  function resetForm() {
    setForm({ currentPassword: "", newPassword: "", confirmPassword: "" })
    setError(null)
  }

  function handleOpenChange(nextOpen: boolean) {
    if (nextOpen || !canDismiss) {
      return
    }

    resetForm()
    onOpenChange?.(false)
  }

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError(null)

    if (requireCurrentPassword && !form.currentPassword) {
      setError(t("请输入当前密码"))
      return
    }

    const passwordError = getNewPasswordError(
      form.newPassword,
      form.confirmPassword,
      t
    )
    if (passwordError) {
      setError(passwordError)
      return
    }

    setIsSubmitting(true)
    try {
      await changePassword(
        token,
        form.newPassword,
        requireCurrentPassword ? form.currentPassword : undefined
      )
      resetForm()
      onChanged()
    } catch (error) {
      setError(getErrorMessage(error, t))
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent
        onEscapeKeyDown={
          canDismiss ? undefined : (event) => event.preventDefault()
        }
        onPointerDownOutside={
          canDismiss ? undefined : (event) => event.preventDefault()
        }
      >
        <DialogHeader>
          <DialogTitle>{title ?? t("修改初始密码")}</DialogTitle>
          <DialogDescription>
            {description ?? t("设置新密码后继续使用 NexaFlow")}
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={handleSubmit}>
          <FieldGroup>
            {requireCurrentPassword ? (
              <Field>
                <FieldLabel htmlFor="currentPassword">
                  {t("当前密码")}
                </FieldLabel>
                <Input
                  id="currentPassword"
                  type="password"
                  autoComplete="current-password"
                  value={form.currentPassword}
                  onChange={(event) =>
                    setForm((current) => ({
                      ...current,
                      currentPassword: event.target.value,
                    }))
                  }
                  required
                />
              </Field>
            ) : null}
            <Field>
              <FieldLabel htmlFor="newPassword">{t("新密码")}</FieldLabel>
              <Input
                id="newPassword"
                type="password"
                autoComplete="new-password"
                minLength={6}
                value={form.newPassword}
                onChange={(event) =>
                  setForm((current) => ({
                    ...current,
                    newPassword: event.target.value,
                  }))
                }
                required
              />
              <FieldDescription>
                {t("至少 6 位，并且包含一个大写字母")}
              </FieldDescription>
            </Field>
            <Field>
              <FieldLabel htmlFor="confirmPassword">
                {t("确认密码")}
              </FieldLabel>
              <Input
                id="confirmPassword"
                type="password"
                autoComplete="new-password"
                minLength={6}
                value={form.confirmPassword}
                onChange={(event) =>
                  setForm((current) => ({
                    ...current,
                    confirmPassword: event.target.value,
                  }))
                }
                required
              />
            </Field>
            {error ? <p className="text-sm text-destructive">{error}</p> : null}
          </FieldGroup>
          <DialogFooter className="pt-4">
            <Button className="w-full" disabled={isSubmitting}>
              {isSubmitting ? (
                <LoaderCircleIcon data-icon="inline-start" />
              ) : null}
              {t("保存")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

function TopBar({
  me,
  activePage,
  featurePages,
  currentWorkspaceName,
  selectedWorkspaceId,
  workspaceOptions,
  onPageChange,
  onSelectWorkspace,
  onChangePassword,
  onLogout,
}: {
  me: MeResponse
  activePage: PageKey
  featurePages: readonly FeaturePageConfig[]
  currentWorkspaceName: string
  selectedWorkspaceId: string | null
  workspaceOptions: Workspace[]
  onPageChange: (page: PageKey) => void
  onSelectWorkspace: (workspaceId: string) => void
  onChangePassword: () => void
  onLogout: () => void
}) {
  const { language, setLanguage, t } = useLanguage()
  const { theme, setTheme } = useTheme()
  const activeThemeOption =
    themeOptions.find((option) => option.value === theme) ?? themeOptions[0]
  const activeThemeLabel = t(activeThemeOption.labelKey)
  const ActiveThemeIcon = activeThemeOption.icon
  const activeLanguageOption =
    languageOptions.find((option) => option.value === language) ??
    languageOptions[0]
  const otherWorkspaces = workspaceOptions.filter(
    (workspace) => workspace.id !== selectedWorkspaceId
  )

  return (
    <header className="sticky top-0 z-10 border-b bg-background/95 backdrop-blur">
      <div className="flex h-14 w-full items-center gap-3 px-4 sm:px-6 lg:px-8">
        <div className="flex min-w-0 shrink-0 items-center gap-2">
          <button
            type="button"
            className="shrink-0 text-left text-base font-semibold"
            onClick={() => onPageChange("apps")}
          >
            NexaFlow
          </button>
          <span className="text-sm text-muted-foreground" aria-hidden="true">
            ｜
          </span>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <button
                type="button"
                className="flex min-w-0 max-w-[32vw] items-center gap-1 rounded-md px-1.5 py-1 text-sm text-muted-foreground hover:bg-muted hover:text-foreground aria-expanded:bg-muted aria-expanded:text-foreground sm:max-w-52"
                title={currentWorkspaceName}
                aria-label={t("切换工作空间，当前为 {workspace}", {
                  workspace: currentWorkspaceName,
                })}
              >
                <span className="truncate">{currentWorkspaceName}</span>
                <ChevronDownIcon className="size-3.5 shrink-0" />
              </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start" className="min-w-56">
              <DropdownMenuLabel>{t("其他工作空间")}</DropdownMenuLabel>
              <DropdownMenuSeparator />
              <DropdownMenuGroup>
                {otherWorkspaces.length ? (
                  otherWorkspaces.map((workspace) => (
                    <DropdownMenuItem
                      key={workspace.id}
                      onSelect={() => onSelectWorkspace(workspace.id)}
                    >
                      <Building2Icon />
                      <span className="truncate">
                        {displayWorkspaceName(workspace, t)}
                      </span>
                    </DropdownMenuItem>
                  ))
                ) : (
                  <DropdownMenuItem disabled>
                    {t("暂无其他工作空间")}
                  </DropdownMenuItem>
                )}
              </DropdownMenuGroup>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
        <nav className="flex min-w-0 flex-1 justify-center gap-2 overflow-x-auto">
          {featurePages.map((page) => {
            const Icon = page.icon
            const isActive = activePage === page.key

            return (
              <Button
                key={page.key}
                type="button"
                variant={isActive ? "secondary" : "ghost"}
                onClick={() => onPageChange(page.key)}
                className="h-10 min-w-28 px-4 text-sm"
              >
                <Icon data-icon="inline-start" />
                <span className="hidden sm:inline">{page.label}</span>
              </Button>
            )
          })}
        </nav>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button
              variant="ghost"
              size="icon-lg"
              className="text-muted-foreground hover:text-foreground aria-expanded:bg-muted aria-expanded:text-foreground"
              aria-label={t("切换语言，当前为 {language}", {
                language: activeLanguageOption.label,
              })}
            >
              <LanguagesIcon className="size-4" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="min-w-40">
            <DropdownMenuLabel>{t("语言")}</DropdownMenuLabel>
            <DropdownMenuSeparator />
            <DropdownMenuGroup>
              {languageOptions.map((option) => (
                <DropdownMenuItem
                  key={option.value}
                  className="justify-between"
                  onSelect={() => setLanguage(option.value)}
                >
                  <span>{option.label}</span>
                  {option.value === language ? (
                    <CircleCheckIcon className="size-3.5 text-primary" />
                  ) : null}
                </DropdownMenuItem>
              ))}
            </DropdownMenuGroup>
          </DropdownMenuContent>
        </DropdownMenu>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button
              variant="ghost"
              size="icon-lg"
              className="text-muted-foreground hover:text-foreground aria-expanded:bg-muted aria-expanded:text-foreground"
              aria-label={t("切换主题，当前为 {theme}", {
                theme: activeThemeLabel,
              })}
            >
              <ActiveThemeIcon className="size-4" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="min-w-40">
            <DropdownMenuLabel>{t("主题")}</DropdownMenuLabel>
            <DropdownMenuSeparator />
            <DropdownMenuGroup>
              {themeOptions.map((option) => {
                const Icon = option.icon
                const isActive = theme === option.value

                return (
                  <DropdownMenuItem
                    key={option.value}
                    className="justify-between"
                    onSelect={() => setTheme(option.value)}
                  >
                    <span className="flex items-center gap-2">
                      <Icon />
                      {t(option.labelKey)}
                    </span>
                    {isActive ? (
                      <CircleCheckIcon className="size-3.5 text-primary" />
                    ) : null}
                  </DropdownMenuItem>
                )
              })}
            </DropdownMenuGroup>
          </DropdownMenuContent>
        </DropdownMenu>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button
              variant="ghost"
              size="icon-lg"
              aria-label={t("打开用户菜单")}
            >
              <Avatar>
                <AvatarFallback>{initials(me.user.name)}</AvatarFallback>
              </Avatar>
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuLabel>
              <div className="flex flex-col gap-1">
                <span>{me.user.name}</span>
                <span className="text-xs font-normal text-muted-foreground">
                  {me.user.username} /{" "}
                  {me.user.is_global_admin ? t("全局管理员") : t("成员")}
                </span>
                <span className="text-xs font-normal text-muted-foreground">
                  {me.user.email}
                </span>
              </div>
            </DropdownMenuLabel>
            <DropdownMenuSeparator />
            <DropdownMenuGroup>
              <DropdownMenuItem onSelect={onChangePassword}>
                <LockIcon />
                {t("修改密码")}
              </DropdownMenuItem>
              <DropdownMenuItem onSelect={() => onPageChange("system")}>
                <SettingsIcon />
                {t("系统管理")}
              </DropdownMenuItem>
              <DropdownMenuItem onSelect={onLogout}>
                <LogOutIcon />
                {t("退出登录")}
              </DropdownMenuItem>
            </DropdownMenuGroup>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </header>
  )
}

function FeaturePage({ page }: { page: FeaturePageConfig }) {
  const { t } = useLanguage()
  const Icon = page.icon
  const [isDialogOpen, setIsDialogOpen] = React.useState(false)

  return (
    <>
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <h1 className="truncate text-2xl font-semibold">{page.label}</h1>
          <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
            {page.description}
          </p>
        </div>
        <Button
          type="button"
          className="shrink-0"
          onClick={() => setIsDialogOpen(true)}
        >
          <PlusIcon data-icon="inline-start" />
          {page.actionLabel}
        </Button>
      </div>

      <div className="rounded-lg border bg-background p-3 shadow-sm">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
          <div className="relative min-w-0 sm:w-[320px]">
            <SearchIcon className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              className="pl-9"
              placeholder={t("搜索{label}...", { label: page.label })}
            />
          </div>
          <Button type="button" variant="outline" className="justify-between">
            {t("最近更新")}
            <ChevronDownIcon data-icon="inline-end" />
          </Button>
        </div>
      </div>

      <div className="rounded-lg border bg-background p-6 shadow-sm">
        <div className="mx-auto flex min-h-[320px] max-w-xl flex-col items-center justify-center gap-4 text-center">
          <span className="flex size-14 items-center justify-center rounded-lg bg-muted">
            <Icon className="size-5 text-muted-foreground" />
          </span>
          <div className="flex flex-col gap-2">
            <p className="text-base font-semibold">{page.emptyTitle}</p>
            <p className="text-sm leading-6 text-muted-foreground">
              {page.emptyDescription}
            </p>
          </div>
          <div className="flex flex-wrap justify-center gap-2">
            <Button type="button" onClick={() => setIsDialogOpen(true)}>
              <PlusIcon data-icon="inline-start" />
              {page.actionLabel}
            </Button>
            <Button type="button" variant="outline">
              {page.secondaryActionLabel}
            </Button>
          </div>
        </div>
      </div>

      <Dialog open={isDialogOpen} onOpenChange={setIsDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{page.actionLabel}</DialogTitle>
            <DialogDescription>{page.dialogDescription}</DialogDescription>
          </DialogHeader>
          <form
            onSubmit={(event) => {
              event.preventDefault()
              setIsDialogOpen(false)
            }}
          >
            <FieldGroup>
              {page.dialogFields.map((field) => (
                <Field key={field.id}>
                  <FieldLabel htmlFor={field.id}>{field.label}</FieldLabel>
                  <Input
                    id={field.id}
                    type={field.type ?? "text"}
                    placeholder={field.placeholder}
                    required
                  />
                </Field>
              ))}
            </FieldGroup>
            <DialogFooter className="pt-5">
              <Button
                type="button"
                variant="outline"
                onClick={() => setIsDialogOpen(false)}
              >
                {t("取消")}
              </Button>
              <Button type="submit">{page.actionLabel}</Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </>
  )
}

function StatusBadge({ status }: { status: string }) {
  const { t } = useLanguage()
  const labelKey = STATUS_LABEL_KEYS[status]

  return (
    <Badge variant={status === "active" ? "secondary" : "outline"}>
      {labelKey ? t(labelKey) : status}
    </Badge>
  )
}

function SystemPage({
  me,
  token,
  workspaces,
  teams,
  selectedWorkspaceId,
  workspaceNotice,
  isTeamsLoading,
  teamsError,
  activeSystemTab,
  onSelectWorkspace,
  onSystemTabChange,
  onWorkspaceCreated,
  onWorkspaceUpdated,
  onWorkspaceDeleted,
  onTeamCreated,
  onTeamUpdated,
  onTeamDeleted,
  onNotify,
}: {
  me: MeResponse
  token: string
  workspaces: Workspace[]
  teams: Team[]
  selectedWorkspaceId: string | null
  workspaceNotice: WorkspaceCreateResponse | null
  isTeamsLoading: boolean
  teamsError: string | null
  activeSystemTab: SystemTabKey
  onSelectWorkspace: (workspaceId: string) => void
  onSystemTabChange: (tab: SystemTabKey) => void
  onWorkspaceCreated: (payload: WorkspaceCreateResponse) => void
  onWorkspaceUpdated: (workspace: Workspace) => void
  onWorkspaceDeleted: (workspaceId: string) => void
  onTeamCreated: (team: Team) => void
  onTeamUpdated: (team: Team) => void
  onTeamDeleted: (teamId: string) => void
  onNotify: (kind: AppNotification["kind"], message: string) => void
}) {
  const { language, t } = useLanguage()
  const locale = languageLocales[language]
  const [workspaceForm, setWorkspaceForm] = React.useState<WorkspaceForm>({
    name: "",
    slug: "",
    adminUsername: "",
    adminEmail: "",
    adminName: "",
  })
  const [teamForm, setTeamForm] = React.useState<TeamForm>({
    workspaceId: "",
    name: "",
    slug: "",
  })
  const [workspaceEditForm, setWorkspaceEditForm] =
    React.useState<ScopeEditForm | null>(null)
  const [teamEditForm, setTeamEditForm] =
    React.useState<ScopeEditForm | null>(null)
  const [userCreateForm, setUserCreateForm] =
    React.useState<UserCreateForm>({
      username: "",
      email: "",
      name: "",
      isGlobalAdmin: false,
      workspaceId: selectedWorkspaceId ?? "",
      teamIds: [],
    })
  const [workspaceError, setWorkspaceError] = React.useState<string | null>(
    null
  )
  const [teamError, setTeamError] = React.useState<string | null>(null)
  const [users, setUsers] = React.useState<User[]>([])
  const [workspaceMembers, setWorkspaceMembers] = React.useState<
    WorkspaceMember[]
  >([])
  const [auditLogs, setAuditLogs] = React.useState<AuditLog[]>([])
  const [auditError, setAuditError] = React.useState<string | null>(null)
  const [workspaceMembersError, setWorkspaceMembersError] = React.useState<
    string | null
  >(null)
  const [userCreateError, setUserCreateError] = React.useState<string | null>(
    null
  )
  const [userForm, setUserForm] = React.useState<UserForm | null>(null)
  const [userPasswordForm, setUserPasswordForm] =
    React.useState<UserPasswordForm | null>(null)
  const [userPasswordError, setUserPasswordError] = React.useState<
    string | null
  >(null)
  const [userSearch, setUserSearch] = React.useState("")
  const [userStatusFilter, setUserStatusFilter] =
    React.useState<UserStatusFilter>("all")
  const [userRoleFilter, setUserRoleFilter] =
    React.useState<UserRoleFilter>("all")
  const [userWorkspaceFilter, setUserWorkspaceFilter] = React.useState("all")
  const [userCreateTeams, setUserCreateTeams] = React.useState<Team[]>([])
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
    (workspace) => getMembershipRole(me, workspace.id) === "admin"
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
    key: SystemTabKey
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
      setWorkspaceMembersError(null)
      setIsWorkspaceMembersLoading(true)

      try {
        setWorkspaceMembers(await listWorkspaceMembers(token, workspaceId))
      } catch (error) {
        setWorkspaceMembers([])
        setWorkspaceMembersError(reportError(error))
      } finally {
        setIsWorkspaceMembersLoading(false)
      }
    },
    [reportError, token]
  )

  const loadAuditLogs = React.useCallback(async () => {
    setAuditError(null)
    setIsAuditLoading(true)

    try {
      setAuditLogs(await listAuditLogs(token))
    } catch (error) {
      setAuditLogs([])
      setAuditError(reportError(error))
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
          setUserCreateError(null)
        }
      } catch (error) {
        if (requestId === userCreateTeamsRequestId.current) {
          setUserCreateError(reportError(error))
        }
      } finally {
        if (requestId === userCreateTeamsRequestId.current) {
          setIsUserCreateTeamsLoading(false)
        }
      }
    },
    [reportError, token]
  )

  React.useEffect(() => {
    if (activeSystemTab !== "users" || !canManageUsers) {
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
    activeSystemTab,
    canManageUsers,
    canManageWorkspace,
    loadUsers,
    loadWorkspaceMembers,
    me.user.is_global_admin,
    selectedWorkspaceId,
  ])

  React.useEffect(() => {
    if (activeSystemTab !== "audit" || !me.user.is_global_admin) {
      return
    }

    // eslint-disable-next-line react-hooks/set-state-in-effect
    void loadAuditLogs()
  }, [activeSystemTab, loadAuditLogs, me.user.is_global_admin])

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
        !user.workspaces.some((workspace) => workspace.id === userWorkspaceFilter)
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
  }

  function handleOpenCreateUser() {
    const workspaceId =
      me.user.is_global_admin
        ? (activeWorkspaces.find(
            (workspace) => workspace.id === selectedWorkspaceId
          )?.id ?? "")
        : (selectedWorkspaceId ?? "")
    setUserCreateForm({
      username: "",
      email: "",
      name: "",
      isGlobalAdmin: false,
      workspaceId,
      teamIds: [],
    })
    setUserCreateError(null)
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
    setUserCreateError(null)
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

    setTeamError(null)
    setTeamForm({ workspaceId, name: "", slug: "" })
    setIsTeamDialogOpen(true)
  }

  async function handleCreateWorkspace(
    event: React.FormEvent<HTMLFormElement>
  ) {
    event.preventDefault()
    setWorkspaceError(null)
    setIsCreatingWorkspace(true)

    try {
      const payload = await createWorkspace(token, {
        name: workspaceForm.name,
        slug: workspaceForm.slug,
        admin: {
          username: workspaceForm.adminUsername,
          email: workspaceForm.adminEmail,
          name: workspaceForm.adminName,
        },
      })
      setWorkspaceForm({
        name: "",
        slug: "",
        adminUsername: "",
        adminEmail: "",
        adminName: "",
      })
      onWorkspaceCreated(payload)
      onNotify("success", t("工作空间已新建"))
    } catch (error) {
      setWorkspaceError(reportError(error))
    } finally {
      setIsCreatingWorkspace(false)
    }
  }

  async function handleCreateTeam(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()

    if (!teamForm.workspaceId) {
      return
    }

    setTeamError(null)
    setIsCreatingTeam(true)

    try {
      const team = await createTeam(token, teamForm.workspaceId, {
        name: teamForm.name,
        slug: teamForm.slug,
      })
      setTeamForm({ workspaceId: "", name: "", slug: "" })
      if (team.workspace_id === selectedWorkspaceId) {
        onTeamCreated(team)
      } else {
        onSelectWorkspace(team.workspace_id)
      }
      setIsTeamDialogOpen(false)
      onNotify("success", t("团队已新建"))
    } catch (error) {
      setTeamError(reportError(error))
    } finally {
      setIsCreatingTeam(false)
    }
  }

  function handleOpenEditWorkspace(workspace: Workspace) {
    setWorkspaceError(null)
    setWorkspaceEditForm({
      id: workspace.id,
      name: workspace.name,
      slug: workspace.slug,
    })
  }

  async function handleUpdateWorkspace(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()

    if (!workspaceEditForm) {
      return
    }

    setWorkspaceError(null)
    setIsSavingWorkspace(true)

    try {
      const workspace = await updateWorkspace(token, workspaceEditForm.id, {
        name: workspaceEditForm.name,
        slug: workspaceEditForm.slug,
      })
      onWorkspaceUpdated(workspace)
      setWorkspaceEditForm(null)
      onNotify("success", t("工作空间已更新"))
    } catch (error) {
      setWorkspaceError(reportError(error))
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

    setWorkspaceError(null)

    try {
      onWorkspaceUpdated(
        await updateWorkspace(token, workspace.id, { status: nextStatus })
      )
      onNotify(
        "success",
        nextStatus === "archived"
          ? t("工作空间已归档")
          : t("工作空间已恢复")
      )
    } catch (error) {
      setWorkspaceError(reportError(error))
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

    setWorkspaceError(null)

    try {
      await deleteWorkspace(token, workspace.id)
      onWorkspaceDeleted(workspace.id)
      onNotify("success", t("工作空间已删除"))
    } catch (error) {
      setWorkspaceError(reportError(error))
    }
  }

  function handleOpenEditTeam(team: Team) {
    setTeamError(null)
    setTeamEditForm({
      id: team.id,
      name: team.name,
      slug: team.slug,
    })
  }

  async function handleUpdateTeam(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()

    if (!teamEditForm || !selectedWorkspaceId) {
      return
    }

    setTeamError(null)
    setIsSavingTeam(true)

    try {
      const team = await updateTeam(token, selectedWorkspaceId, teamEditForm.id, {
        name: teamEditForm.name,
        slug: teamEditForm.slug,
      })
      onTeamUpdated(team)
      setTeamEditForm(null)
      onNotify("success", t("团队已更新"))
    } catch (error) {
      setTeamError(reportError(error))
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

    setTeamError(null)

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
      setTeamError(reportError(error))
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

    setTeamError(null)

    try {
      await deleteTeam(token, selectedWorkspaceId, team.id)
      onTeamDeleted(team.id)
      onNotify("success", t("团队已删除"))
    } catch (error) {
      setTeamError(reportError(error))
    }
  }

  async function handleCreateUser(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setUserCreateError(null)

    if (!me.user.is_global_admin && !selectedWorkspaceId) {
      setUserCreateError(t("请选择工作空间"))
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
        isGlobalAdmin: false,
        workspaceId: "",
        teamIds: [],
      })
      setUserCreateTeams([])
      onNotify("success", t("用户已新建"))
    } catch (error) {
      setUserCreateError(reportError(error))
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
    setUserPasswordError(null)
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

    setUserPasswordError(null)

    const passwordError = getNewPasswordError(
      userPasswordForm.newPassword,
      userPasswordForm.confirmPassword,
      t
    )
    if (passwordError) {
      setUserPasswordError(passwordError)
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
      setUserPasswordError(reportError(error))
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
          <div
            id="system-panel-workspaces"
            role="tabpanel"
            aria-labelledby="system-tab-workspaces"
            className="grid gap-4 lg:h-full lg:overflow-y-auto lg:pr-1"
          >
            <Card className="min-w-0 gap-3 border-border/70 py-4 shadow-sm lg:min-h-full">
              <CardHeader className="flex-row items-start justify-between gap-4 px-4">
                <div className="flex min-w-0 items-start gap-3">
                  <span className="flex size-8 shrink-0 items-center justify-center rounded-lg border bg-background">
                    <Building2Icon className="size-4" />
                  </span>
                  <div className="min-w-0">
                    <CardTitle>{t("工作空间")}</CardTitle>
                    <CardDescription>{t("当前租户范围")}</CardDescription>
                  </div>
                </div>
                {canCreateWorkspace ? (
                  <Button
                    type="button"
                    size="sm"
                    onClick={() => setIsWorkspaceDialogOpen(true)}
                  >
                    <PlusIcon data-icon="inline-start" />
                    {t("新建工作空间")}
                  </Button>
                ) : null}
              </CardHeader>
              <CardContent className="min-w-0 px-4">
                {workspaceError ? (
                  <p className="mb-3 text-sm text-destructive">
                    {workspaceError}
                  </p>
                ) : null}
                {workspaces.length ? (
                  <div className="flex flex-col gap-2">
                    {workspaces.map((workspace) => {
                      const isSelected = workspace.id === selectedWorkspaceId
                      const isArchived = workspace.status === "archived"
                      const workspaceRole = getMembershipRole(me, workspace.id)
                      const canUseThisWorkspace = Boolean(workspaceRole)
                      const canManageThisWorkspace = me.user.is_global_admin

                      return (
                        <div
                          key={workspace.id}
                          className={cn(
                            "flex w-full items-center justify-between gap-3 rounded-lg border bg-background px-4 py-2.5 text-left text-sm shadow-xs transition-colors hover:border-foreground/30 hover:bg-muted/50",
                            isSelected &&
                              "border-foreground bg-muted/60 shadow-sm"
                          )}
                        >
                          <button
                            type="button"
                            className="flex min-w-0 flex-1 flex-col gap-1 text-left disabled:cursor-not-allowed disabled:opacity-60"
                            disabled={isArchived || !canUseThisWorkspace}
                            onClick={() => onSelectWorkspace(workspace.id)}
                            title={
                              canUseThisWorkspace
                                ? t("切换工作空间")
                                : t("仅系统管理，无工作空间权限")
                            }
                          >
                            <span className="truncate font-medium">
                              {displayWorkspaceName(workspace, t)}
                            </span>
                            <span className="truncate text-muted-foreground">
                              {displaySlug(
                                workspace.slug,
                                workspace.is_default,
                                t
                              )}
                            </span>
                          </button>
                          <span className="flex shrink-0 items-center gap-2">
                            {workspace.is_default ? (
                              <Badge variant="outline">{t("默认")}</Badge>
                            ) : null}
                            <StatusBadge status={workspace.status} />
                            {canManageThisWorkspace ? (
                              <>
                                <Button
                                  type="button"
                                  variant="ghost"
                                  size="icon-sm"
                                  onClick={() =>
                                    handleOpenEditWorkspace(workspace)
                                  }
                                  title={t("编辑工作空间")}
                                  aria-label={t("编辑工作空间")}
                                >
                                  <PencilIcon />
                                </Button>
                                <Button
                                  type="button"
                                  variant="ghost"
                                  size="icon-sm"
                                  disabled={workspace.is_default}
                                  onClick={() =>
                                    void handleArchiveWorkspace(workspace)
                                  }
                                  title={
                                    isArchived
                                      ? t("恢复工作空间")
                                      : t("归档工作空间")
                                  }
                                  aria-label={
                                    isArchived
                                      ? t("恢复工作空间")
                                      : t("归档工作空间")
                                  }
                                >
                                  {isArchived ? (
                                    <RotateCcwIcon />
                                  ) : (
                                    <ArchiveIcon />
                                  )}
                                </Button>
                              </>
                            ) : null}
                            {canCreateWorkspace ? (
                              <Button
                                type="button"
                                variant="ghost"
                                size="icon-sm"
                                disabled={workspace.is_default}
                                onClick={() =>
                                  void handleDeleteWorkspace(workspace)
                                }
                                title={t("永久删除工作空间")}
                                aria-label={t("永久删除工作空间")}
                              >
                                <Trash2Icon />
                              </Button>
                            ) : null}
                          </span>
                        </div>
                      )
                    })}
                  </div>
                ) : (
                  <div className="flex min-h-28 items-center justify-center rounded-lg border border-dashed bg-muted/20">
                    <p className="text-sm text-muted-foreground">
                      {t("暂无工作空间")}
                    </p>
                  </div>
                )}
              </CardContent>
            </Card>
          </div>
        ) : null}

        {activeSystemTab === "teams" ? (
          <div
            id="system-panel-teams"
            role="tabpanel"
            aria-labelledby="system-tab-teams"
            className="grid gap-4 lg:h-full lg:overflow-y-auto lg:pr-1"
          >
            <Card className="min-w-0 gap-4 border-border/70 py-5 shadow-sm lg:min-h-full">
              <CardHeader className="flex-row items-start justify-between gap-4 px-5">
                <div className="flex min-w-0 items-start gap-3">
                  <span className="flex size-8 shrink-0 items-center justify-center rounded-lg border bg-background">
                    <UsersIcon className="size-4" />
                  </span>
                  <div className="min-w-0">
                    <CardTitle>{t("团队")}</CardTitle>
                    <CardDescription>
                      {selectedWorkspace
                        ? displayWorkspaceName(selectedWorkspace, t)
                        : t("未选择工作空间")}
                    </CardDescription>
                  </div>
                </div>
                {canCreateTeam ? (
                  <Button
                    type="button"
                    size="sm"
                    onClick={handleOpenCreateTeam}
                  >
                    <PlusIcon data-icon="inline-start" />
                    {t("新建团队")}
                  </Button>
                ) : null}
              </CardHeader>
              <CardContent className="min-w-0 px-5">
                {teamsError ? (
                  <p className="text-sm text-destructive">{teamsError}</p>
                ) : isTeamsLoading ? (
                  <div className="flex min-h-28 items-center justify-center">
                    <LoaderCircleIcon className="animate-spin text-muted-foreground" />
                  </div>
                ) : teams.length ? (
                  <div className="flex flex-col gap-2">
                    {teams.map((team) => {
                      const isArchived = team.status === "archived"

                      return (
                        <div
                          key={team.id}
                          className="flex items-center justify-between gap-3 rounded-lg border bg-background px-4 py-2.5 text-sm shadow-xs"
                        >
                          <span className="flex min-w-0 flex-col gap-1">
                            <span className="truncate font-medium">
                              {displayTeamName(team, t)}
                            </span>
                            <span className="truncate text-muted-foreground">
                              {displaySlug(team.slug, team.is_default, t)}
                            </span>
                          </span>
                          <span className="flex shrink-0 items-center gap-2">
                            {team.is_default ? (
                              <Badge variant="outline">{t("默认")}</Badge>
                            ) : null}
                            <StatusBadge status={team.status} />
                            {canManageWorkspace ? (
                              <>
                                <Button
                                  type="button"
                                  variant="ghost"
                                  size="icon-sm"
                                  onClick={() => handleOpenEditTeam(team)}
                                  title={t("编辑团队")}
                                  aria-label={t("编辑团队")}
                                >
                                  <PencilIcon />
                                </Button>
                                <Button
                                  type="button"
                                  variant="ghost"
                                  size="icon-sm"
                                  disabled={team.is_default}
                                  onClick={() => void handleArchiveTeam(team)}
                                  title={
                                    isArchived ? t("恢复团队") : t("归档团队")
                                  }
                                  aria-label={
                                    isArchived ? t("恢复团队") : t("归档团队")
                                  }
                                >
                                  {isArchived ? (
                                    <RotateCcwIcon />
                                  ) : (
                                    <ArchiveIcon />
                                  )}
                                </Button>
                                <Button
                                  type="button"
                                  variant="ghost"
                                  size="icon-sm"
                                  disabled={team.is_default}
                                  onClick={() => void handleDeleteTeam(team)}
                                  title={t("永久删除团队")}
                                  aria-label={t("永久删除团队")}
                                >
                                  <Trash2Icon />
                                </Button>
                              </>
                            ) : null}
                          </span>
                        </div>
                      )
                    })}
                  </div>
                ) : (
                  <div className="flex min-h-28 items-center justify-center rounded-lg border border-dashed bg-muted/20">
                    <p className="text-sm text-muted-foreground">
                      {t("暂无团队")}
                    </p>
                  </div>
                )}
              </CardContent>
            </Card>
          </div>
        ) : null}

        {activeSystemTab === "users" && me.user.is_global_admin ? (
          <div
            id="system-panel-users"
            role="tabpanel"
            aria-labelledby="system-tab-users"
            className="grid min-w-0 gap-4 lg:h-full lg:overflow-y-auto lg:pr-1"
          >
            <Card className="min-w-0 overflow-hidden gap-3 border-border/70 py-4 shadow-sm lg:min-h-full">
              <CardHeader className="flex-row items-start justify-between gap-4 px-4">
                <div className="flex min-w-0 items-start gap-3">
                  <span className="flex size-8 shrink-0 items-center justify-center rounded-lg border bg-background">
                    <UserCogIcon className="size-4" />
                  </span>
                  <div className="min-w-0">
                    <CardTitle>{t("用户管理")}</CardTitle>
                    <CardDescription>{t("全局账号")}</CardDescription>
                  </div>
                </div>
                <Button type="button" size="sm" onClick={handleOpenCreateUser}>
                  <PlusIcon data-icon="inline-start" />
                  {t("新建用户")}
                </Button>
              </CardHeader>
              <CardContent className="min-w-0 px-4">
                {isUsersLoading ? (
                  <div className="flex min-h-28 items-center justify-center">
                    <LoaderCircleIcon className="animate-spin text-muted-foreground" />
                  </div>
                ) : users.length ? (
                  <div className="grid gap-3">
                    <div className="grid gap-2 lg:grid-cols-[minmax(220px,1fr)_150px_170px_190px]">
                      <div className="relative">
                        <SearchIcon className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" />
                        <Input
                          value={userSearch}
                          onChange={(event) => setUserSearch(event.target.value)}
                          placeholder={t("搜索姓名、账号、邮箱")}
                          className="pl-9"
                        />
                      </div>
                      <FilterDropdown
                        ariaLabel={t("筛选用户状态")}
                        value={userStatusFilter}
                        onChange={(value) =>
                          setUserStatusFilter(value as UserStatusFilter)
                        }
                        options={[
                          { value: "all", label: t("全部状态") },
                          { value: "active", label: t("已启用") },
                          { value: "inactive", label: t("已停用") },
                        ]}
                      />
                      <FilterDropdown
                        ariaLabel={t("筛选用户角色")}
                        value={userRoleFilter}
                        onChange={(value) =>
                          setUserRoleFilter(value as UserRoleFilter)
                        }
                        options={[
                          { value: "all", label: t("全部角色") },
                          { value: "global_admin", label: t("全局管理员") },
                          { value: "workspace_admin", label: t("工作空间管理员") },
                          { value: "team_admin", label: t("团队管理员") },
                          { value: "member", label: t("普通用户") },
                        ]}
                      />
                      <FilterDropdown
                        ariaLabel={t("筛选工作空间")}
                        value={userWorkspaceFilter}
                        onChange={setUserWorkspaceFilter}
                        options={[
                          { value: "all", label: t("全部工作空间") },
                          ...workspaces.map((workspace) => ({
                            value: workspace.id,
                            label: displayWorkspaceName(workspace, t),
                          })),
                        ]}
                      />
                    </div>
                    <div className="min-w-0 overflow-x-auto rounded-lg border bg-background">
                      <div
                        role="table"
                        aria-label={t("用户列表")}
                        className="min-w-[1700px] text-sm"
                      >
                      <div
                        role="row"
                        className="grid grid-cols-[150px_140px_260px_240px_220px_130px_120px_180px_160px] border-b bg-muted/40 px-4 py-3 text-sm font-semibold text-muted-foreground"
                      >
                        <span role="columnheader">{t("用户名")}</span>
                        <span role="columnheader">{t("账号")}</span>
                        <span role="columnheader">{t("邮箱")}</span>
                        <span role="columnheader">{t("所属工作空间")}</span>
                        <span role="columnheader">{t("所属团队")}</span>
                        <span role="columnheader">{t("用户角色")}</span>
                        <span role="columnheader">{t("状态")}</span>
                        <span role="columnheader">{t("创建时间")}</span>
                        <span role="columnheader" className="text-right">
                          {t("操作")}
                        </span>
                      </div>
                      {filteredUsers.map((user, index) => {
                        const workspaceNames = formatUserWorkspaces(user, t)
                        const teamNames = formatUserTeams(user, t)
                        const roleLabel = getUserRoleLabel(user, t)

                        return (
                          <div
                            key={user.id}
                            role="row"
                            className={cn(
                              "grid grid-cols-[150px_140px_260px_240px_220px_130px_120px_180px_160px] items-center border-b px-4 py-4 last:border-b-0 hover:bg-muted/40",
                              index % 2 === 1 && "bg-muted/20"
                            )}
                          >
                            <span
                              role="cell"
                              className="truncate font-medium"
                              title={user.name}
                            >
                              {user.name}
                            </span>
                            <span
                              role="cell"
                              className="truncate text-muted-foreground"
                              title={user.username}
                            >
                              {user.username}
                            </span>
                            <span
                              role="cell"
                              className="truncate text-muted-foreground"
                              title={user.email}
                            >
                              {user.email}
                            </span>
                            <span
                              role="cell"
                              className="truncate"
                              title={workspaceNames}
                            >
                              {workspaceNames}
                            </span>
                            <span
                              role="cell"
                              className="truncate"
                              title={teamNames}
                            >
                              {teamNames}
                            </span>
                            <span role="cell">
                              <span
                                className={cn(
                                  "inline-flex rounded-md border px-2 py-0.5 text-xs font-medium whitespace-nowrap",
                                  getUserRoleClass(user)
                                )}
                              >
                                {roleLabel}
                              </span>
                            </span>
                            <span
                              role="cell"
                              className="flex items-center gap-2 whitespace-nowrap"
                            >
                              {user.is_active ? (
                                <CircleCheckIcon className="size-4 text-green-600" />
                              ) : (
                                <CircleOffIcon className="size-4 text-muted-foreground" />
                              )}
                              <span>
                                {user.is_active ? t("已启用") : t("已停用")}
                              </span>
                            </span>
                            <span
                              role="cell"
                              className="whitespace-nowrap text-muted-foreground"
                            >
                              {formatDateTime(user.created_at, locale)}
                            </span>
                            <span
                              role="cell"
                              className="flex items-center justify-end gap-2 whitespace-nowrap"
                            >
                              <button
                                type="button"
                                className={cn(
                                  "flex h-6 w-11 shrink-0 items-center rounded-full p-0.5 transition-colors",
                                  user.is_active ? "bg-primary" : "bg-muted"
                                )}
                                disabled={user.id === me.user.id}
                                onClick={() => void handleToggleUser(user)}
                                title={
                                  user.id === me.user.id
                                    ? t("不能停用当前账号")
                                    : t("切换用户状态")
                                }
                                aria-label={t("切换用户状态")}
                              >
                                <span
                                  className={cn(
                                    "size-5 rounded-full bg-background shadow-sm transition-transform",
                                    user.is_active && "translate-x-5"
                                  )}
                                />
                              </button>
                              <span className="h-5 w-px bg-border" />
                              <Button
                                type="button"
                                variant="ghost"
                                size="icon-sm"
                                onClick={() => handleOpenEditUser(user)}
                                title={t("编辑用户")}
                                aria-label={t("编辑用户")}
                              >
                                <PencilIcon />
                              </Button>
                              <Button
                                type="button"
                                variant="ghost"
                                size="icon-sm"
                                onClick={() =>
                                  handleOpenUserPasswordDialog(user)
                                }
                                title={t("修改密码")}
                                aria-label={t("修改密码")}
                              >
                                <LockIcon />
                              </Button>
                              <Button
                                type="button"
                                variant="ghost"
                                size="icon-sm"
                                disabled={user.id === me.user.id}
                                onClick={() => void handleDeleteUser(user)}
                                title={
                                  user.id === me.user.id
                                    ? t("不能删除当前账号")
                                    : t("删除用户")
                                }
                                aria-label={t("删除用户")}
                              >
                                <Trash2Icon />
                              </Button>
                            </span>
                          </div>
                        )
                      })}
                      {!filteredUsers.length ? (
                        <div className="px-4 py-8 text-center text-sm text-muted-foreground">
                          {t("没有匹配的用户")}
                        </div>
                      ) : null}
                      </div>
                    </div>
                  </div>
                ) : (
                  <div className="flex min-h-28 items-center justify-center rounded-lg border border-dashed bg-muted/20">
                    <p className="text-sm text-muted-foreground">
                      {t("暂无用户")}
                    </p>
                  </div>
                )}
              </CardContent>
            </Card>
          </div>
        ) : null}

        {activeSystemTab === "users" &&
        !me.user.is_global_admin &&
        canManageWorkspace ? (
          <div
            id="system-panel-users"
            role="tabpanel"
            aria-labelledby="system-tab-users"
            className="grid min-w-0 gap-4 lg:h-full lg:overflow-y-auto lg:pr-1"
          >
            <Card className="min-w-0 overflow-hidden gap-3 border-border/70 py-4 shadow-sm lg:min-h-full">
              <CardHeader className="flex-row items-start justify-between gap-4 px-4">
                <div className="flex min-w-0 items-start gap-3">
                  <span className="flex size-8 shrink-0 items-center justify-center rounded-lg border bg-background">
                    <UserCogIcon className="size-4" />
                  </span>
                  <div className="min-w-0">
                    <CardTitle>{t("用户管理")}</CardTitle>
                    <CardDescription>
                      {selectedWorkspace
                        ? displayWorkspaceName(selectedWorkspace, t)
                        : t("未选择工作空间")}
                    </CardDescription>
                  </div>
                </div>
                <Button
                  type="button"
                  size="sm"
                  disabled={!selectedWorkspaceId}
                  onClick={handleOpenCreateUser}
                >
                  <PlusIcon data-icon="inline-start" />
                  {t("新建用户")}
                </Button>
              </CardHeader>
              <CardContent className="min-w-0 px-4">
                {workspaceMembersError ? (
                  <p className="mb-3 text-sm text-destructive">
                    {workspaceMembersError}
                  </p>
                ) : null}
                {isWorkspaceMembersLoading ? (
                  <div className="flex min-h-28 items-center justify-center">
                    <LoaderCircleIcon className="animate-spin text-muted-foreground" />
                  </div>
                ) : workspaceMembers.length ? (
                  <div className="min-w-0 overflow-x-auto rounded-lg border bg-background">
                    <div
                      role="table"
                      aria-label={t("工作空间用户列表")}
                      className="min-w-[980px] text-sm"
                    >
                      <div
                        role="row"
                        className="grid grid-cols-[160px_150px_280px_120px_120px_150px] border-b bg-muted/40 px-4 py-3 text-sm font-semibold text-muted-foreground"
                      >
                        <span role="columnheader">{t("用户名")}</span>
                        <span role="columnheader">{t("账号")}</span>
                        <span role="columnheader">{t("邮箱")}</span>
                        <span role="columnheader">{t("空间角色")}</span>
                        <span role="columnheader">{t("状态")}</span>
                        <span role="columnheader">{t("创建时间")}</span>
                      </div>
                      {workspaceMembers.map((member, index) => {
                        const roleLabel =
                          member.role === "admin" ? t("管理员") : t("成员")

                        return (
                          <div
                            key={member.user.id}
                            role="row"
                            className={cn(
                              "grid grid-cols-[160px_150px_280px_120px_120px_150px] items-center border-b px-4 py-4 last:border-b-0 hover:bg-muted/40",
                              index % 2 === 1 && "bg-muted/20"
                            )}
                          >
                            <span
                              role="cell"
                              className="truncate font-medium"
                              title={member.user.name}
                            >
                              {member.user.name}
                            </span>
                            <span
                              role="cell"
                              className="truncate text-muted-foreground"
                              title={member.user.username}
                            >
                              {member.user.username}
                            </span>
                            <span
                              role="cell"
                              className="truncate text-muted-foreground"
                              title={member.user.email}
                            >
                              {member.user.email}
                            </span>
                            <span role="cell">
                              <span className="inline-flex rounded-md border border-border bg-muted px-2 py-0.5 text-xs font-medium whitespace-nowrap">
                                {roleLabel}
                              </span>
                            </span>
                            <span
                              role="cell"
                              className="flex items-center gap-2 whitespace-nowrap"
                            >
                              {member.user.is_active ? (
                                <CircleCheckIcon className="size-4 text-green-600" />
                              ) : (
                                <CircleOffIcon className="size-4 text-muted-foreground" />
                              )}
                              <span>
                                {member.user.is_active
                                  ? t("已启用")
                                  : t("已停用")}
                              </span>
                            </span>
                            <span
                              role="cell"
                              className="whitespace-nowrap text-muted-foreground"
                            >
                              {formatDateTime(member.user.created_at, locale)}
                            </span>
                          </div>
                        )
                      })}
                    </div>
                  </div>
                ) : (
                  <div className="flex min-h-28 items-center justify-center rounded-lg border border-dashed bg-muted/20">
                    <p className="text-sm text-muted-foreground">
                      {t("暂无用户")}
                    </p>
                  </div>
                )}
              </CardContent>
            </Card>
          </div>
        ) : null}

        {activeSystemTab === "audit" && me.user.is_global_admin ? (
          <div
            id="system-panel-audit"
            role="tabpanel"
            aria-labelledby="system-tab-audit"
            className="grid min-w-0 gap-4 lg:h-full lg:overflow-y-auto lg:pr-1"
          >
            <Card className="min-w-0 overflow-hidden gap-3 border-border/70 py-4 shadow-sm lg:min-h-full">
              <CardHeader className="flex-row items-start justify-between gap-4 px-4">
                <div className="flex min-w-0 items-start gap-3">
                  <span className="flex size-8 shrink-0 items-center justify-center rounded-lg border bg-background">
                    <HistoryIcon className="size-4" />
                  </span>
                  <div className="min-w-0">
                    <CardTitle>{t("审计日志")}</CardTitle>
                    <CardDescription>{t("系统管理写操作")}</CardDescription>
                  </div>
                </div>
              </CardHeader>
              <CardContent className="min-w-0 px-4">
                {auditError ? (
                  <p className="text-sm text-destructive">{auditError}</p>
                ) : isAuditLoading ? (
                  <div className="flex min-h-28 items-center justify-center">
                    <LoaderCircleIcon className="animate-spin text-muted-foreground" />
                  </div>
                ) : auditLogs.length ? (
                  <div className="min-w-0 overflow-x-auto rounded-lg border bg-background">
                    <div
                      role="table"
                      aria-label={t("审计日志")}
                      className="w-max min-w-[1700px] text-sm"
                    >
                      <div className="grid grid-cols-[180px_150px_160px_220px_minmax(950px,max-content)] border-b bg-muted/40 px-4 py-3 font-semibold text-muted-foreground">
                        <span role="columnheader">{t("时间")}</span>
                        <span role="columnheader">{t("操作者")}</span>
                        <span role="columnheader">{t("动作")}</span>
                        <span role="columnheader">{t("对象")}</span>
                        <span role="columnheader">{t("详情")}</span>
                      </div>
                      {auditLogs.map((log, index) => (
                        <div
                          key={log.id}
                          role="row"
                          className={cn(
                            "grid grid-cols-[180px_150px_160px_220px_minmax(950px,max-content)] items-center border-b px-4 py-4 last:border-b-0 hover:bg-muted/40",
                            index % 2 === 1 && "bg-muted/20"
                          )}
                        >
                          <span className="whitespace-nowrap text-muted-foreground">
                            {formatDateTime(log.created_at, locale)}
                          </span>
                          <span className="truncate" title={log.actor_username}>
                            {log.actor_name}
                          </span>
                          <span>
                            {AUDIT_ACTION_LABEL_KEYS[log.action]
                              ? t(AUDIT_ACTION_LABEL_KEYS[log.action])
                              : log.action}
                          </span>
                          <span className="truncate" title={log.resource_name}>
                            {log.resource_name}
                          </span>
                          <span
                            className="whitespace-nowrap text-muted-foreground"
                            title={formatAuditDetails(log.details, t)}
                          >
                            {formatAuditDetails(log.details, t)}
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>
                ) : (
                  <div className="flex min-h-28 items-center justify-center rounded-lg border border-dashed bg-muted/20">
                    <p className="text-sm text-muted-foreground">
                      {t("暂无审计日志")}
                    </p>
                  </div>
                )}
              </CardContent>
            </Card>
          </div>
        ) : null}

      </div>

      <Dialog
        open={Boolean(workspaceEditForm)}
        onOpenChange={(open) => {
          if (!open) {
            setWorkspaceEditForm(null)
            setWorkspaceError(null)
          }
        }}
      >
        <DialogContent side="right">
          <DialogHeader>
            <DialogTitle>{t("编辑工作空间")}</DialogTitle>
            <DialogDescription>{t("更新名称和标识")}</DialogDescription>
          </DialogHeader>
          {workspaceEditForm ? (
            <form onSubmit={handleUpdateWorkspace}>
              <FieldGroup>
                <Field>
                  <FieldLabel htmlFor="editWorkspaceName">
                    {t("名称")}
                  </FieldLabel>
                  <Input
                    id="editWorkspaceName"
                    value={workspaceEditForm.name}
                    onChange={(event) =>
                      setWorkspaceEditForm((current) =>
                        current
                          ? { ...current, name: event.target.value }
                          : current
                      )
                    }
                    required
                  />
                </Field>
                <Field>
                  <FieldLabel htmlFor="editWorkspaceSlug">
                    {t("标识")}
                  </FieldLabel>
                  <Input
                    id="editWorkspaceSlug"
                    value={workspaceEditForm.slug}
                    onChange={(event) =>
                      setWorkspaceEditForm((current) =>
                        current
                          ? { ...current, slug: event.target.value }
                          : current
                      )
                    }
                    required
                  />
                </Field>
                {workspaceError ? (
                  <p className="text-sm text-destructive">{workspaceError}</p>
                ) : null}
              </FieldGroup>
              <DialogFooter className="pt-5">
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => setWorkspaceEditForm(null)}
                >
                  {t("取消")}
                </Button>
                <Button disabled={isSavingWorkspace}>
                  {isSavingWorkspace ? (
                    <LoaderCircleIcon data-icon="inline-start" />
                  ) : null}
                  {t("保存")}
                </Button>
              </DialogFooter>
            </form>
          ) : null}
        </DialogContent>
      </Dialog>

      <Dialog
        open={Boolean(teamEditForm)}
        onOpenChange={(open) => {
          if (!open) {
            setTeamEditForm(null)
            setTeamError(null)
          }
        }}
      >
        <DialogContent side="right">
          <DialogHeader>
            <DialogTitle>{t("编辑团队")}</DialogTitle>
            <DialogDescription>
              {selectedWorkspace
                ? displayWorkspaceName(selectedWorkspace, t)
                : t("先选择工作空间")}
            </DialogDescription>
          </DialogHeader>
          {teamEditForm ? (
            <form onSubmit={handleUpdateTeam}>
              <FieldGroup>
                <Field>
                  <FieldLabel htmlFor="editTeamName">{t("名称")}</FieldLabel>
                  <Input
                    id="editTeamName"
                    value={teamEditForm.name}
                    onChange={(event) =>
                      setTeamEditForm((current) =>
                        current
                          ? { ...current, name: event.target.value }
                          : current
                      )
                    }
                    required
                  />
                </Field>
                <Field>
                  <FieldLabel htmlFor="editTeamSlug">{t("标识")}</FieldLabel>
                  <Input
                    id="editTeamSlug"
                    value={teamEditForm.slug}
                    onChange={(event) =>
                      setTeamEditForm((current) =>
                        current
                          ? { ...current, slug: event.target.value }
                          : current
                      )
                    }
                    required
                  />
                </Field>
                {teamError ? (
                  <p className="text-sm text-destructive">{teamError}</p>
                ) : null}
              </FieldGroup>
              <DialogFooter className="pt-5">
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => setTeamEditForm(null)}
                >
                  {t("取消")}
                </Button>
                <Button disabled={!selectedWorkspaceId || isSavingTeam}>
                  {isSavingTeam ? (
                    <LoaderCircleIcon data-icon="inline-start" />
                  ) : null}
                  {t("保存")}
                </Button>
              </DialogFooter>
            </form>
          ) : null}
        </DialogContent>
      </Dialog>

      <Dialog
        open={isUserCreateDialogOpen}
        onOpenChange={(open) => {
          setIsUserCreateDialogOpen(open)
          if (!open) {
            setUserCreateError(null)
          }
        }}
      >
        <DialogContent
          side="right"
          onInteractOutside={(event) => {
            if (isEventFromDropdownMenu(event)) {
              event.preventDefault()
            }
          }}
        >
          <DialogHeader>
            <DialogTitle>{t("新建用户")}</DialogTitle>
            <DialogDescription>
              {me.user.is_global_admin
                ? t("创建账号并分配工作空间与团队")
                : t("创建普通账号并加入当前工作空间")}
            </DialogDescription>
          </DialogHeader>
          <form onSubmit={handleCreateUser}>
            <FieldGroup>
              <Field>
                <FieldLabel htmlFor="newUserName">{t("姓名")}</FieldLabel>
                <Input
                  id="newUserName"
                  value={userCreateForm.name}
                  onChange={(event) =>
                    setUserCreateForm((current) => ({
                      ...current,
                      name: event.target.value,
                    }))
                  }
                  required
                />
              </Field>
              <Field>
                <FieldLabel htmlFor="newUserUsername">{t("账号")}</FieldLabel>
                <Input
                  id="newUserUsername"
                  value={userCreateForm.username}
                  onChange={(event) =>
                    setUserCreateForm((current) => ({
                      ...current,
                      username: event.target.value,
                    }))
                  }
                  required
                />
              </Field>
              <Field>
                <FieldLabel htmlFor="newUserEmail">{t("邮箱")}</FieldLabel>
                <Input
                  id="newUserEmail"
                  type="email"
                  value={userCreateForm.email}
                  onChange={(event) =>
                    setUserCreateForm((current) => ({
                      ...current,
                      email: event.target.value,
                    }))
                  }
                  required
                />
              </Field>
              <Field>
                <FieldLabel>{t("默认密码")}</FieldLabel>
                <p className="text-sm font-medium text-foreground">
                  {DEFAULT_USER_PASSWORD}
                </p>
              </Field>
              {me.user.is_global_admin ? (
                <label className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    className="size-4"
                    checked={userCreateForm.isGlobalAdmin}
                    onChange={(event) =>
                      setUserCreateForm((current) => ({
                        ...current,
                        isGlobalAdmin: event.target.checked,
                      }))
                    }
                  />
                  {t("全局管理员")}
                </label>
              ) : null}
              {me.user.is_global_admin ? (
                <Field>
                  <FieldLabel id="newUserWorkspaceLabel">
                    {t("工作空间")}
                  </FieldLabel>
                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <Button
                      id="newUserWorkspace"
                      type="button"
                      variant="outline"
                      className="h-9 w-full justify-between px-3 font-normal"
                      aria-labelledby="newUserWorkspaceLabel newUserWorkspace"
                    >
                      <span
                        className={cn(
                          "min-w-0 flex-1 truncate text-left",
                          !userCreateWorkspace && "text-muted-foreground"
                        )}
                      >
                        {userCreateWorkspace
                          ? displayWorkspaceName(userCreateWorkspace, t)
                          : t("不指定工作空间")}
                      </span>
                      <ChevronDownIcon data-icon="inline-end" />
                    </Button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent
                    align="start"
                    className="w-(--radix-dropdown-menu-trigger-width)"
                  >
                    <DropdownMenuItem
                      onSelect={() => handleUserCreateWorkspaceChange("")}
                    >
                      {t("不指定工作空间")}
                    </DropdownMenuItem>
                    {activeWorkspaces.map((workspace) => (
                      <DropdownMenuItem
                        key={workspace.id}
                        className="justify-between"
                        onSelect={() =>
                          handleUserCreateWorkspaceChange(workspace.id)
                        }
                      >
                        <span className="min-w-0 truncate">
                          {displayWorkspaceName(workspace, t)}
                        </span>
                        {workspace.is_default ? (
                          <Badge variant="outline">{t("默认")}</Badge>
                        ) : null}
                      </DropdownMenuItem>
                    ))}
                  </DropdownMenuContent>
                </DropdownMenu>
                </Field>
              ) : null}
              {me.user.is_global_admin ? (
                <Field>
                  <FieldLabel>{t("团队")}</FieldLabel>
                {!userCreateForm.workspaceId ? (
                  <FieldDescription>
                    {t("选择工作空间后可分配该空间下的团队")}
                  </FieldDescription>
                ) : isUserCreateTeamsLoading ? (
                  <div className="flex h-16 items-center justify-center rounded-lg border border-dashed">
                    <LoaderCircleIcon className="animate-spin text-muted-foreground" />
                  </div>
                ) : userCreateTeams.length ? (
                  <div className="grid gap-2 rounded-lg border p-2">
                    {userCreateTeams.map((team) => (
                      <label
                        key={team.id}
                        className="flex items-center gap-2 rounded-md px-2 py-1.5 text-sm hover:bg-muted"
                      >
                        <input
                          type="checkbox"
                          className="size-4"
                          checked={userCreateForm.teamIds.includes(team.id)}
                          onChange={(event) =>
                            setUserCreateForm((current) => ({
                              ...current,
                              teamIds: event.target.checked
                                ? [...current.teamIds, team.id]
                                : current.teamIds.filter(
                                    (teamId) => teamId !== team.id
                                  ),
                            }))
                          }
                        />
                        <span className="min-w-0 truncate">
                          {displayTeamName(team, t)}
                        </span>
                      </label>
                    ))}
                  </div>
                ) : (
                  <FieldDescription>
                    {t("该工作空间下暂无团队")}
                  </FieldDescription>
                )}
                </Field>
              ) : null}
              {userCreateError ? (
                <p className="text-sm text-destructive">{userCreateError}</p>
              ) : null}
            </FieldGroup>
            <DialogFooter className="pt-5">
              <Button
                type="button"
                variant="outline"
                onClick={() => setIsUserCreateDialogOpen(false)}
              >
                {t("取消")}
              </Button>
              <Button
                disabled={
                  isCreatingUser ||
                  (!me.user.is_global_admin && !selectedWorkspaceId)
                }
              >
                {isCreatingUser ? (
                  <LoaderCircleIcon data-icon="inline-start" />
                ) : (
                  <PlusIcon data-icon="inline-start" />
                )}
                {t("新建")}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      <Dialog
        open={Boolean(userForm)}
        onOpenChange={(open) => !open && setUserForm(null)}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t("编辑用户")}</DialogTitle>
            <DialogDescription>{t("更新账号基础信息")}</DialogDescription>
          </DialogHeader>
          {userForm ? (
            <form onSubmit={handleUpdateUser}>
              <FieldGroup>
                <Field>
                  <FieldLabel htmlFor="userName">{t("姓名")}</FieldLabel>
                  <Input
                    id="userName"
                    value={userForm.name}
                    onChange={(event) =>
                      setUserForm((current) =>
                        current
                          ? { ...current, name: event.target.value }
                          : current
                      )
                    }
                    required
                  />
                </Field>
                <Field>
                  <FieldLabel htmlFor="userUsername">{t("账号")}</FieldLabel>
                  <Input
                    id="userUsername"
                    value={userForm.username}
                    onChange={(event) =>
                      setUserForm((current) =>
                        current
                          ? { ...current, username: event.target.value }
                          : current
                      )
                    }
                    required
                  />
                </Field>
                <Field>
                  <FieldLabel htmlFor="userEmail">{t("邮箱")}</FieldLabel>
                  <Input
                    id="userEmail"
                    type="email"
                    value={userForm.email}
                    onChange={(event) =>
                      setUserForm((current) =>
                        current
                          ? { ...current, email: event.target.value }
                          : current
                      )
                    }
                    required
                  />
                </Field>
                <label className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    className="size-4"
                    checked={userForm.isGlobalAdmin}
                    disabled={userForm.id === me.user.id}
                    onChange={(event) =>
                      setUserForm((current) =>
                        current
                          ? {
                              ...current,
                              isGlobalAdmin: event.target.checked,
                            }
                          : current
                      )
                    }
                  />
                  {t("全局管理员")}
                </label>
              </FieldGroup>
              <DialogFooter className="pt-5">
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => setUserForm(null)}
                >
                  {t("取消")}
                </Button>
                <Button disabled={isSavingUser}>
                  {isSavingUser ? (
                    <LoaderCircleIcon data-icon="inline-start" />
                  ) : null}
                  {t("保存")}
                </Button>
              </DialogFooter>
            </form>
          ) : null}
        </DialogContent>
      </Dialog>

      <Dialog
        open={Boolean(userPasswordForm)}
        onOpenChange={(open) => {
          if (!open) {
            setUserPasswordForm(null)
            setUserPasswordError(null)
          }
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t("修改密码")}</DialogTitle>
            <DialogDescription>
              {userPasswordForm
                ? t("为 {name} 设置新密码", {
                    name: userPasswordForm.user.name,
                  })
                : t("设置新密码")}
            </DialogDescription>
          </DialogHeader>
          {userPasswordForm ? (
            <form onSubmit={handleChangeUserPassword}>
              <FieldGroup>
                <Field>
                  <FieldLabel htmlFor="managedUserNewPassword">
                    {t("新密码")}
                  </FieldLabel>
                  <Input
                    id="managedUserNewPassword"
                    type="password"
                    autoComplete="new-password"
                    minLength={6}
                    value={userPasswordForm.newPassword}
                    onChange={(event) =>
                      setUserPasswordForm((current) =>
                        current
                          ? { ...current, newPassword: event.target.value }
                          : current
                      )
                    }
                    required
                  />
                  <FieldDescription>
                    {t("至少 6 位，并且包含一个大写字母")}
                  </FieldDescription>
                </Field>
                <Field>
                  <FieldLabel htmlFor="managedUserConfirmPassword">
                    {t("确认密码")}
                  </FieldLabel>
                  <Input
                    id="managedUserConfirmPassword"
                    type="password"
                    autoComplete="new-password"
                    minLength={6}
                    value={userPasswordForm.confirmPassword}
                    onChange={(event) =>
                      setUserPasswordForm((current) =>
                        current
                          ? {
                              ...current,
                              confirmPassword: event.target.value,
                            }
                          : current
                      )
                    }
                    required
                  />
                </Field>
                {userPasswordError ? (
                  <p className="text-sm text-destructive">
                    {userPasswordError}
                  </p>
                ) : null}
              </FieldGroup>
              <DialogFooter className="pt-5">
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => setUserPasswordForm(null)}
                >
                  {t("取消")}
                </Button>
                <Button disabled={isChangingUserPassword}>
                  {isChangingUserPassword ? (
                    <LoaderCircleIcon data-icon="inline-start" />
                  ) : null}
                  {t("保存")}
                </Button>
              </DialogFooter>
            </form>
          ) : null}
        </DialogContent>
      </Dialog>

      <Dialog
        open={isWorkspaceDialogOpen}
        onOpenChange={setIsWorkspaceDialogOpen}
      >
        <DialogContent side="right">
          <DialogHeader>
            <DialogTitle>{t("新建工作空间")}</DialogTitle>
            <DialogDescription>{t("创建租户和负责人")}</DialogDescription>
          </DialogHeader>
          <form onSubmit={handleCreateWorkspace}>
            <FieldGroup>
              <Field>
                <FieldLabel htmlFor="workspaceName">{t("名称")}</FieldLabel>
                <Input
                  id="workspaceName"
                  value={workspaceForm.name}
                  onChange={(event) =>
                    setWorkspaceForm((current) => ({
                      ...current,
                      name: event.target.value,
                    }))
                  }
                  required
                />
              </Field>
              <Field>
                <FieldLabel htmlFor="workspaceSlug">{t("标识")}</FieldLabel>
                <Input
                  id="workspaceSlug"
                  value={workspaceForm.slug}
                  onChange={(event) =>
                    setWorkspaceForm((current) => ({
                      ...current,
                      slug: event.target.value,
                    }))
                  }
                  required
                />
              </Field>
              <Field>
                <FieldLabel htmlFor="adminName">
                  {t("负责人姓名")}
                </FieldLabel>
                <Input
                  id="adminName"
                  value={workspaceForm.adminName}
                  onChange={(event) =>
                    setWorkspaceForm((current) => ({
                      ...current,
                      adminName: event.target.value,
                    }))
                  }
                  required
                />
              </Field>
              <Field>
                <FieldLabel htmlFor="adminUsername">
                  {t("负责人账号")}
                </FieldLabel>
                <Input
                  id="adminUsername"
                  value={workspaceForm.adminUsername}
                  onChange={(event) =>
                    setWorkspaceForm((current) => ({
                      ...current,
                      adminUsername: event.target.value,
                    }))
                  }
                  required
                />
              </Field>
              <Field>
                <FieldLabel htmlFor="adminEmail">
                  {t("负责人邮箱")}
                </FieldLabel>
                <Input
                  id="adminEmail"
                  type="email"
                  value={workspaceForm.adminEmail}
                  onChange={(event) =>
                    setWorkspaceForm((current) => ({
                      ...current,
                      adminEmail: event.target.value,
                    }))
                  }
                  required
                />
              </Field>
              {workspaceError ? (
                <p className="text-sm text-destructive">{workspaceError}</p>
              ) : null}
              {workspaceNotice ? (
                <div className="rounded-lg border bg-muted p-3 text-sm">
                  <div className="font-medium">
                    {t("已创建 {name}", {
                      name: workspaceNotice.workspace.name,
                    })}
                  </div>
                  {workspaceNotice.admin_initial_password ? (
                    <div className="mt-1 font-mono text-xs">
                      {workspaceNotice.admin_initial_password}
                    </div>
                  ) : null}
                </div>
              ) : null}
            </FieldGroup>
            <DialogFooter className="pt-5">
              <Button
                type="button"
                variant="outline"
                onClick={() => setIsWorkspaceDialogOpen(false)}
              >
                {t("取消")}
              </Button>
              <Button disabled={isCreatingWorkspace}>
                {isCreatingWorkspace ? (
                  <LoaderCircleIcon data-icon="inline-start" />
                ) : (
                  <PlusIcon data-icon="inline-start" />
                )}
                {t("新建")}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      <Dialog open={isTeamDialogOpen} onOpenChange={setIsTeamDialogOpen}>
        <DialogContent side="right">
          <DialogHeader>
            <DialogTitle>{t("新建团队")}</DialogTitle>
            <DialogDescription>
              {teamWorkspace
                ? displayWorkspaceName(teamWorkspace, t)
                : t("先选择工作空间")}
            </DialogDescription>
          </DialogHeader>
          <form onSubmit={handleCreateTeam}>
            <FieldGroup>
              <Field>
                <FieldLabel id="teamWorkspaceLabel">
                  {t("工作空间")}
                </FieldLabel>
                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <Button
                      id="teamWorkspace"
                      type="button"
                      variant="outline"
                      className="h-9 w-full justify-between px-3 font-normal"
                      disabled={!manageableWorkspaces.length}
                      aria-labelledby="teamWorkspaceLabel teamWorkspace"
                    >
                      <span
                        className={cn(
                          "min-w-0 flex-1 truncate text-left",
                          !teamWorkspace && "text-muted-foreground"
                        )}
                      >
                        {teamWorkspace
                          ? displayWorkspaceName(teamWorkspace, t)
                          : t("选择工作空间")}
                      </span>
                      <ChevronDownIcon data-icon="inline-end" />
                    </Button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent
                    align="start"
                    className="w-(--radix-dropdown-menu-trigger-width)"
                  >
                    <DropdownMenuGroup>
                      {manageableWorkspaces.map((workspace) => (
                        <DropdownMenuItem
                          key={workspace.id}
                          onSelect={() =>
                            setTeamForm((current) => ({
                              ...current,
                              workspaceId: workspace.id,
                            }))
                          }
                          className="justify-between"
                        >
                          <span className="truncate">
                            {displayWorkspaceName(workspace, t)}
                          </span>
                          {workspace.id === teamForm.workspaceId ? (
                            <CircleCheckIcon className="text-primary" />
                          ) : null}
                        </DropdownMenuItem>
                      ))}
                    </DropdownMenuGroup>
                  </DropdownMenuContent>
                </DropdownMenu>
              </Field>
              <Field>
                <FieldLabel htmlFor="teamName">{t("名称")}</FieldLabel>
                <Input
                  id="teamName"
                  value={teamForm.name}
                  onChange={(event) =>
                    setTeamForm((current) => ({
                      ...current,
                      name: event.target.value,
                    }))
                  }
                  required
                />
              </Field>
              <Field>
                <FieldLabel htmlFor="teamSlug">{t("标识")}</FieldLabel>
                <Input
                  id="teamSlug"
                  value={teamForm.slug}
                  onChange={(event) =>
                    setTeamForm((current) => ({
                      ...current,
                      slug: event.target.value,
                    }))
                  }
                  required
                />
              </Field>
              {teamError ? (
                <p className="text-sm text-destructive">{teamError}</p>
              ) : null}
            </FieldGroup>
            <DialogFooter className="pt-5">
              <Button
                type="button"
                variant="outline"
                onClick={() => setIsTeamDialogOpen(false)}
              >
                {t("取消")}
              </Button>
              <Button disabled={!teamForm.workspaceId || isCreatingTeam}>
                {isCreatingTeam ? (
                  <LoaderCircleIcon data-icon="inline-start" />
                ) : (
                  <PlusIcon data-icon="inline-start" />
                )}
                {t("新建")}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  )
}

export function App() {
  const { t } = useLanguage()
  const [token, setToken] = React.useState<string | null>(() =>
    localStorage.getItem(TOKEN_KEY)
  )
  const [mustChangePassword, setMustChangePassword] = React.useState(false)
  const [isPasswordDialogOpen, setIsPasswordDialogOpen] =
    React.useState(false)
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
          )
            ?.id ??
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
        (item) => item.status === "active" && hasWorkspaceMembership(me, item.id)
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
  const isChangePasswordDialogOpen =
    mustChangePassword || isPasswordDialogOpen
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
          <FeaturePage page={activePageConfig ?? featurePages[0]} />
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
