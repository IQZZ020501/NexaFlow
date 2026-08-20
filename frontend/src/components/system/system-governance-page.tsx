"use client"

import * as React from "react"
import Link from "next/link"
import { useRouter } from "next/navigation"
import {
  ActivityIcon,
  Building2Icon,
  CheckCircle2Icon,
  ClipboardIcon,
  CopyIcon,
  FileTextIcon,
  HistoryIcon,
  KeyRoundIcon,
  LoaderCircleIcon,
  MailIcon,
  RefreshCwIcon,
  ShieldCheckIcon,
  Trash2Icon,
  UserPlusIcon,
  UsersIcon,
  XCircleIcon,
} from "lucide-react"

import { useLanguage } from "@/contexts/language-provider"
import { useSession } from "@/contexts/session-context"
import { useConfirmDialog } from "@/components/app/confirm-dialog"
import { languageLocales } from "@/i18n"
import {
  createWorkspaceInvitation,
  deleteWorkspaceInvitation,
  getAdminHealth,
  getWorkspaceGovernance,
  getWorkspaceInventory,
  listSessions,
  listSystemLogs,
  listUserSessions,
  listUsers,
  listWorkspaceInvitations,
  revokeAllUserSessions,
  revokeOtherSessions,
  revokeSession,
  revokeUserSession,
  revokeWorkspaceInvitation,
  updateWorkspaceGovernance,
  type AdminHealth,
  type RefreshSession,
  type SystemLog,
  type User,
  type WorkspaceInvitation,
  type WorkspaceInvitationKind,
  type WorkspaceInventory,
} from "@/lib/api/system"
import { Button } from "@/components/ui/button"
import { FilterDropdown } from "@/components/app/filter-dropdown"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Badge } from "@/components/ui/badge"
import { cn } from "@/lib/utils"
import { displayWorkspaceName, formatDateTime } from "@/lib/display"
import { getErrorMessage } from "@/lib/errors"
import { copyText } from "@/lib/clipboard"
import {
  systemLogEventLabel,
  systemLogLevelLabel,
} from "@/lib/constants"
import { SmtpSettingsPage } from "@/components/system/smtp-settings-page"

export type SystemGovernanceSection = "operations" | "governance" | "security" | "email"

type Props = {
  section: SystemGovernanceSection
}

const navItems: Array<{
  href: string
  label: "工作空间" | "团队" | "用户管理" | "审计日志" | "系统运行" | "工作空间治理" | "会话安全" | "SMTP 邮件"
  icon: React.ElementType
}> = [
  { href: "/system/workspaces", label: "工作空间", icon: Building2Icon },
  { href: "/system/teams", label: "团队", icon: UsersIcon },
  { href: "/system/users", label: "用户管理", icon: KeyRoundIcon },
  { href: "/system/audit", label: "审计日志", icon: HistoryIcon },
  { href: "/system/operations", label: "系统运行", icon: ActivityIcon },
  { href: "/system/email", label: "SMTP 邮件", icon: MailIcon },
  { href: "/system/governance", label: "工作空间治理", icon: ShieldCheckIcon },
  { href: "/system/security", label: "会话安全", icon: KeyRoundIcon },
]

/**
 * Renders the system governance section authorized for the current user.
 *
 * Redirects users without access to the application page and restricts operations
 * and workspace governance to users with the required administrative permissions.
 *
 * @param section - The governance section to display.
 */
export function SystemGovernancePage({ section }: Props) {
  const session = useSession()
  const router = useRouter()
  const canManageWorkspace = Boolean(
    session.me?.user.is_global_admin ||
      session.me?.memberships.some((membership) => membership.role === "admin")
  )
  const canAccess = Boolean(
    session.me &&
      (session.me.user.is_global_admin ||
        session.me.memberships.some((membership) => membership.role === "admin") ||
        session.me.user.teams.some((team) => team.role === "admin"))
  )

  React.useEffect(() => {
    if (!session.me) return
    if (!canAccess) {
      router.replace("/app/apps")
      return
    }
    if ((section === "operations" || section === "email") && !session.me.user.is_global_admin) {
      router.replace("/system/teams")
    }
    if (section === "governance" && !canManageWorkspace) {
      router.replace("/system/teams")
    }
  }, [canAccess, canManageWorkspace, router, section, session.me])

  if (!session.me || !session.token || !canAccess) return null

  return (
    <div className="grid min-w-0 gap-4 lg:grid-cols-[240px_minmax(0,1fr)]">
      <SystemGovernanceNav section={section} me={session.me} />
      <main className="min-w-0">
        {section === "operations" ? <OperationsPanel /> : null}
        {section === "governance" ? <GovernancePanel /> : null}
        {section === "security" ? <SecurityPanel /> : null}
        {section === "email" ? <SmtpSettingsPage /> : null}
      </main>
    </div>
  )
}

/**
 * Renders localized navigation links for the system administration sections available to the current user.
 *
 * @param section - The currently active system administration section
 * @param me - The authenticated user and membership data used to determine visible links
 */
function SystemGovernanceNav({
  section,
  me,
}: {
  section: SystemGovernanceSection
  me: NonNullable<ReturnType<typeof useSession>["me"]>
}) {
  const { t } = useLanguage()
  const canManageUsers = Boolean(
    me.user.is_global_admin || me.memberships.some((membership) => membership.role === "admin")
  )
  const canManageWorkspace = Boolean(
    me.user.is_global_admin || me.memberships.some((membership) => membership.role === "admin")
  )
  const visible = navItems.filter((item) => {
    if (item.href === "/system/users") return canManageUsers
    if (item.href === "/system/audit" || item.href === "/system/operations" || item.href === "/system/email") {
      return me.user.is_global_admin
    }
    if (item.href === "/system/governance") return canManageWorkspace
    return true
  })
  const activeHref = `/system/${section}`
  return (
    <aside className="min-w-0 lg:sticky lg:top-20 lg:self-start">
      <nav
        aria-label={t("系统管理")}
        className="flex gap-1 overflow-x-auto rounded-lg border bg-background p-1 shadow-sm lg:flex-col lg:overflow-visible"
      >
        {visible.map((item) => {
          const Icon = item.icon
          const active = item.href === activeHref
          return (
            <Link
              key={item.href}
              href={item.href}
              className={cn(
                "flex min-w-32 items-center gap-2 rounded-md px-3 py-2 text-sm font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground lg:min-w-0",
                active && "bg-foreground text-background hover:bg-foreground hover:text-background"
              )}
            >
              <Icon className="size-4 shrink-0" />
              <span>{t(item.label)}</span>
            </Link>
          )
        })}
      </nav>
    </aside>
  )
}

/**
 * Provides workspace governance state and localized error reporting for the current session.
 *
 * @returns The session, active workspaces, manageable workspaces, selected workspace, and error reporter
 */
function useGovernanceContext() {
  const { t } = useLanguage()
  const session = useSession()
  const activeWorkspaces = session.workspaces.filter((workspace) => workspace.status === "active")
  const manageableWorkspaces = activeWorkspaces.filter(
    (workspace) =>
      session.me?.user.is_global_admin ||
      session.me?.memberships.some(
        (membership) => membership.workspace_id === workspace.id && membership.role === "admin"
      )
  )
  const selectedWorkspaceId =
    (session.selectedWorkspaceId && manageableWorkspaces.some((item) => item.id === session.selectedWorkspaceId)
      ? session.selectedWorkspaceId
      : manageableWorkspaces[0]?.id) ?? ""
  const selectedWorkspace = manageableWorkspaces.find((item) => item.id === selectedWorkspaceId) ?? null
  const reportError = React.useCallback(
    (error: unknown) => {
      session.notify("error", getErrorMessage(error, t))
    },
    [session, t]
  )
  return {
    session,
    activeWorkspaces,
    manageableWorkspaces,
    selectedWorkspaceId,
    selectedWorkspace,
    reportError,
  }
}

const healthComponents = [
  { name: "database", label: "数据库" },
  { name: "redis", label: "Redis" },
  { name: "qdrant", label: "向量数据库" },
  { name: "storage", label: "文件存储" },
  { name: "worker", label: "后台 Worker" },
] as const

/**
 * Displays system health metrics and filtered operation logs for administrators.
 *
 * @returns The operations dashboard with health status, log filters, and CSV export controls.
 */
function OperationsPanel() {
  const { t, language } = useLanguage()
  const { session, reportError } = useGovernanceContext()
  const [health, setHealth] = React.useState<AdminHealth | null>(null)
  const [logs, setLogs] = React.useState<SystemLog[]>([])
  const [level, setLevel] = React.useState("")
  const [event, setEvent] = React.useState("")
  const [search, setSearch] = React.useState("")
  const [loading, setLoading] = React.useState(true)
  const healthRequestRef = React.useRef(0)

  const loadHealth = React.useCallback(async (reportFailure: boolean) => {
    if (!session.token) return
    const requestId = ++healthRequestRef.current
    try {
      const nextHealth = await getAdminHealth(session.token)
      if (requestId === healthRequestRef.current) setHealth(nextHealth)
    } catch (error) {
      if (requestId !== healthRequestRef.current) return
      setHealth(null)
      if (reportFailure) reportError(error)
    }
  }, [reportError, session.token])

  const loadLogs = React.useCallback(async () => {
    if (!session.token) return
    try {
      setLogs(
        await listSystemLogs(session.token, {
          limit: 100,
          level: level || undefined,
          event: event || undefined,
          search: search || undefined,
        })
      )
    } catch (error) {
      reportError(error)
    }
  }, [event, level, reportError, search, session.token])

  const load = React.useCallback(async () => {
    setLoading(true)
    try {
      await Promise.all([loadHealth(true), loadLogs()])
    } finally {
      setLoading(false)
    }
  }, [loadHealth, loadLogs])

  React.useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load()
  }, [load])

  React.useEffect(() => {
    const timer = window.setInterval(() => {
      void loadHealth(false)
    }, 30_000)
    return () => {
      window.clearInterval(timer)
      healthRequestRef.current += 1
    }
  }, [loadHealth])

  function exportLogs() {
    const header = [t("时间"), t("级别"), t("事件"), t("消息"), t("状态")]
    const rows = logs.map((log) => [
      formatDateTime(log.created_at, languageLocales[language]),
      systemLogLevelLabel(log.level, t),
      systemLogEventLabel(log.event, t),
      log.message || systemLogEventLabel(log.event, t),
      String(log.status_code ?? ""),
    ])
    const csv = [header, ...rows]
      .map((row) => row.map((value) => `"${value.replaceAll('"', '""')}"`).join(","))
      .join("\n")
    const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }))
    const anchor = document.createElement("a")
    anchor.href = url
    anchor.download = "nexaflow-system-logs.csv"
    anchor.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div className="grid min-w-0 gap-4">
      <Card>
        <CardHeader className="flex-row items-start justify-between gap-4">
          <div>
            <CardTitle className="flex items-center gap-2"><ActivityIcon className="size-4" />{t("系统运行")}</CardTitle>
            <CardDescription>
              <span className="block">{t("查看服务状态与后台失败记录")}</span>
              <span className="mt-1 block text-xs">
                {t("每 30 秒自动刷新")} · {t("最后检查")}：{health ? formatDateTime(health.checked_at, languageLocales[language]) : t("未知")}
              </span>
            </CardDescription>
          </div>
          <Button variant="outline" size="sm" onClick={() => void load()} disabled={loading}>
            <RefreshCwIcon className={cn("size-4", loading && "animate-spin")} />{t("刷新")}
          </Button>
        </CardHeader>
        <CardContent className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
          {healthComponents.map(({ name, label }) => {
            const component = health?.components[name]
            const componentStatus = component?.status ?? "unknown"
            return (
              <div key={name} className="rounded-lg border bg-muted/20 p-3">
                <div className="text-sm font-medium">{t(label)}</div>
                <Badge
                  variant={componentStatus === "error" ? "destructive" : componentStatus === "ok" ? "secondary" : "outline"}
                  className="mt-2"
                >
                  {componentStatus === "ok" ? t("正常") : componentStatus === "error" ? t("异常") : componentStatus === "not_configured" ? t("未配置") : t("未知")}
                </Badge>
                {componentStatus === "error" ? (
                  <div className="mt-1 text-xs text-muted-foreground">
                    {component?.detail === "timeout" ? t("检查超时") : t("服务不可用")}
                  </div>
                ) : null}
              </div>
            )
          })}
          <div className="rounded-lg border bg-muted/20 p-3"><div className="text-sm font-medium">{t("待处理任务")}</div><div className="mt-2 text-2xl font-semibold">{health?.pending_tasks ?? "—"}</div></div>
          <div className="rounded-lg border bg-muted/20 p-3"><div className="text-sm font-medium">{t("近 24 小时错误")}</div><div className="mt-2 text-2xl font-semibold">{health?.failed_logs_24h ?? "—"}</div></div>
        </CardContent>
      </Card>
      <Card className="min-w-0">
        <CardHeader className="flex-row flex-wrap items-end justify-between gap-3">
          <div><CardTitle>{t("系统运行日志")}</CardTitle><CardDescription>{t("仅系统管理员可见，敏感字段已脱敏")}</CardDescription></div>
          <div className="flex flex-wrap gap-2">
            <Input className="w-48" value={search} onChange={(event) => setSearch(event.target.value)} placeholder={t("搜索日志")} />
            <FilterDropdown
              className="h-9 w-32"
              value={level}
              onChange={setLevel}
              ariaLabel={t("级别")}
              options={[
                { value: "", label: t("全部级别") },
                ...["critical", "error", "warning", "info", "debug"].map((item) => ({
                  value: item,
                  label: systemLogLevelLabel(item, t),
                })),
              ]}
            />
            <FilterDropdown
              className="h-9 w-52"
              value={event}
              onChange={setEvent}
              ariaLabel={t("筛选事件")}
              options={[
                { value: "", label: t("全部事件") },
                ...Array.from(new Set(logs.map((log) => log.event))).map((item) => ({
                  value: item,
                  label: systemLogEventLabel(item, t),
                })),
              ]}
            />
            <Button variant="outline" size="sm" onClick={exportLogs}><FileTextIcon className="size-4" />{t("导出")}</Button>
          </div>
        </CardHeader>
        <CardContent>
          {loading ? <LoaderCircleIcon className="mx-auto my-10 animate-spin" /> : logs.length ? (
            <div className="overflow-auto rounded-lg border"><div className="min-w-[900px] text-sm">
              <div className="grid grid-cols-[170px_90px_220px_minmax(0,1fr)_80px] gap-x-6 border-b bg-muted/40 px-3 py-2 font-medium"><span>{t("时间")}</span><span>{t("级别")}</span><span>{t("事件")}</span><span>{t("消息")}</span><span>{t("状态")}</span></div>
              {logs.map((log) => <div key={log.id} className="grid grid-cols-[170px_90px_220px_minmax(0,1fr)_80px] items-center gap-x-6 border-b px-3 py-3 last:border-b-0"><span className="text-muted-foreground">{formatDateTime(log.created_at, languageLocales[language])}</span><span><Badge variant={log.level === "error" || log.level === "critical" ? "destructive" : "outline"}>{systemLogLevelLabel(log.level, t)}</Badge></span><span className="truncate" title={systemLogEventLabel(log.event, t)}>{systemLogEventLabel(log.event, t)}</span><span className="min-w-0 truncate text-muted-foreground" title={log.message || systemLogEventLabel(log.event, t)}>{log.message || systemLogEventLabel(log.event, t)}</span><span>{log.status_code ?? "—"}</span></div>)}
            </div></div>
          ) : <div className="rounded-lg border border-dashed p-8 text-center text-sm text-muted-foreground">{t("暂无运行日志")}</div>}
        </CardContent>
      </Card>
    </div>
  )
}

/**
 * Manages governance settings, inventory, and invitations for the selected workspace.
 */
function GovernancePanel() {
  const { t, language } = useLanguage()
  const { session, manageableWorkspaces, selectedWorkspaceId, selectedWorkspace, reportError } = useGovernanceContext()
  const [confirmAction, confirmDialog] = useConfirmDialog()
  const [inventory, setInventory] = React.useState<WorkspaceInventory | null>(null)
  const [invitations, setInvitations] = React.useState<WorkspaceInvitation[]>([])
  const [form, setForm] = React.useState({ daily: "", monthly: "", threshold: "80", retention: "", timezone: "UTC" })
  const [invite, setInvite] = React.useState<{
    kind: WorkspaceInvitationKind
    username: string
    email: string
    name: string
    role: string
  }>({ kind: "personal", username: "", email: "", name: "", role: "member" })
  const [inviteResult, setInviteResult] = React.useState<WorkspaceInvitation | null>(null)
  const [loading, setLoading] = React.useState(false)

  const load = React.useCallback(async () => {
    if (!session.token || !selectedWorkspaceId) return
    setLoading(true)
    try {
      const [nextInventory, nextGovernance, nextInvitations] = await Promise.all([
        getWorkspaceInventory(session.token, selectedWorkspaceId),
        getWorkspaceGovernance(session.token, selectedWorkspaceId),
        listWorkspaceInvitations(session.token, selectedWorkspaceId),
      ])
      setInventory(nextInventory); setInvitations(nextInvitations)
      setForm({ daily: nextGovernance.daily_run_limit?.toString() ?? "", monthly: nextGovernance.monthly_token_limit?.toString() ?? "", threshold: nextGovernance.alert_threshold_percent.toString(), retention: nextGovernance.retention_days?.toString() ?? "", timezone: nextGovernance.timezone })
    } catch (error) { reportError(error) } finally { setLoading(false) }
  }, [reportError, selectedWorkspaceId, session.token])

  React.useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load()
  }, [load])

  async function saveGovernance(event: React.FormEvent) {
    event.preventDefault(); if (!session.token || !selectedWorkspaceId) return
    try {
      await updateWorkspaceGovernance(session.token, selectedWorkspaceId, { daily_run_limit: form.daily ? Number(form.daily) : null, monthly_token_limit: form.monthly ? Number(form.monthly) : null, alert_threshold_percent: Number(form.threshold), retention_days: form.retention ? Number(form.retention) : null, timezone: form.timezone })
      session.notify("success", t("策略已保存"))
    } catch (error) { reportError(error) }
  }

  async function createInvite(event: React.FormEvent) {
    event.preventDefault(); if (!session.token || !selectedWorkspaceId) return
    try {
      const created = await createWorkspaceInvitation(
        session.token,
        selectedWorkspaceId,
        invite.kind === "generic"
          ? { kind: "generic", role: invite.role }
          : invite
      )
      const invitePath = created.invite_url ?? (
        created.token
          ? `/invite/${created.token}${created.kind === "generic" ? "?mode=generic" : ""}`
          : null
      )
      const result = {
        ...created,
        invite_url: invitePath ? new URL(invitePath, window.location.origin).href : null,
      }
      setInviteResult(result)
      setInvitations((current) => [result, ...current])
      setInvite((current) => ({ ...current, username: "", email: "", name: "" }))
      session.notify("success", t("邀请已创建"))
    } catch (error) { reportError(error) }
  }

  async function revokeInvite(id: string) {
    if (!session.token || !selectedWorkspaceId) return
    if (!(await confirmAction({
      description: t("确认撤销邀请"),
      confirmLabel: t("撤销"),
      destructive: true,
    }))) return
    try { await revokeWorkspaceInvitation(session.token, selectedWorkspaceId, id); setInvitations((current) => current.map((item) => item.id === id ? { ...item, accepted_at: new Date().toISOString() } : item)); session.notify("success", t("邀请已撤销")) } catch (error) { reportError(error) }
  }

  async function deleteInvite(id: string) {
    if (!session.token || !selectedWorkspaceId) return
    if (!(await confirmAction({
      description: t("确认删除邀请"),
      confirmLabel: t("删除"),
      destructive: true,
    }))) return
    try {
      await deleteWorkspaceInvitation(session.token, selectedWorkspaceId, id)
      setInvitations((current) => current.filter((item) => item.id !== id))
      setInviteResult((current) => current?.id === id ? null : current)
      session.notify("success", t("邀请已删除"))
    } catch (error) { reportError(error) }
  }

  async function copyInviteLink() {
    try {
      await copyText(inviteResult?.invite_url ?? inviteResult?.token ?? "")
      session.notify("success", t("已复制"))
    } catch {
      session.notify("error", t("复制失败"))
    }
  }

  if (!selectedWorkspace) return <EmptyState text={t("暂无可管理工作空间")} />
  const dateLocale = language === "en" ? "en-US" : language === "zh-Hant" ? "zh-TW" : "zh-CN"
  const cards: Array<[string, number]> = inventory ? [["成员", inventory.members_total], ["团队", inventory.teams_total], ["Agent", inventory.agents_total], ["知识库", inventory.knowledge_bases_total], ["模型", inventory.models_total], ["工具", inventory.tools_total], ["工作流", inventory.workflows_total], ["活跃运行", inventory.active_runs], ["失败运行（24小时）", inventory.failed_runs_24h], ["失败任务（24小时）", inventory.failed_tasks_24h]] : []
  return <div className="grid min-w-0 gap-4">
    {confirmDialog}
    <Card><CardHeader className="flex-row flex-wrap items-end justify-between gap-3"><div><CardTitle className="flex items-center gap-2"><ShieldCheckIcon className="size-4" />{t("工作空间治理")}</CardTitle><CardDescription>{t("系统管理员可治理全部工作空间，工作空间管理员可治理本空间团队与策略")}</CardDescription></div><div className="flex items-center gap-2"><label className="text-sm text-muted-foreground">{t("工作空间")}</label><FilterDropdown className="h-9 w-56" value={selectedWorkspaceId} onChange={session.selectWorkspace} ariaLabel={t("选择工作空间")} options={manageableWorkspaces.map((workspace) => ({ value: workspace.id, label: displayWorkspaceName(workspace, t) }))} /><Button variant="outline" size="sm" onClick={() => void load()} disabled={loading}><RefreshCwIcon className={cn("size-4", loading && "animate-spin")} /></Button></div></CardHeader><CardContent className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">{cards.map(([label, value]) => <div key={label} className="rounded-lg border bg-muted/20 p-3"><div className="text-xs text-muted-foreground">{t(label as never)}</div><div className="mt-1 text-2xl font-semibold">{value}</div></div>)}</CardContent></Card>
    <div className="grid gap-4 xl:grid-cols-2">
      <Card><CardHeader><CardTitle>{t("配额策略")}</CardTitle><CardDescription>{t("先限制运行规模，再根据用量告警调整")}</CardDescription></CardHeader><CardContent><form className="grid gap-3" onSubmit={saveGovernance}><Field label={t("每日运行上限")} value={form.daily} onChange={(value) => setForm((current) => ({ ...current, daily: value }))} placeholder={t("不限制")} type="number" /><Field label={t("月度 Token 上限")} value={form.monthly} onChange={(value) => setForm((current) => ({ ...current, monthly: value }))} placeholder={t("不限制")} type="number" /><Field label={t("告警阈值（百分比）")} value={form.threshold} onChange={(value) => setForm((current) => ({ ...current, threshold: value }))} type="number" /><Field label={t("数据保留天数")} value={form.retention} onChange={(value) => setForm((current) => ({ ...current, retention: value }))} placeholder={t("不限制")} type="number" /><Field label={t("时区")} value={form.timezone} onChange={(value) => setForm((current) => ({ ...current, timezone: value }))} /><div className="flex justify-end"><Button type="submit"><ClipboardIcon className="size-4" />{t("保存策略")}</Button></div></form></CardContent></Card>
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2"><UserPlusIcon className="size-4" />{t("工作空间邀请")}</CardTitle>
        <CardDescription>{t("指定成员链接仅可领取一次；通用链接 7 天内可重复使用")}</CardDescription>
      </CardHeader>
      <CardContent>
        <form className="grid gap-3" onSubmit={createInvite}>
          <div className="grid gap-3 sm:grid-cols-2">
            <label className="grid gap-1 text-sm">
              <span>{t("邀请方式")}</span>
              <FilterDropdown
                className="h-9 w-full"
                value={invite.kind}
                onChange={(kind) => setInvite((current) => ({
                  ...current,
                  kind: kind as WorkspaceInvitationKind,
                  role: kind === "generic" ? "member" : current.role,
                }))}
                ariaLabel={t("邀请方式")}
                options={[
                  { value: "personal", label: t("指定成员") },
                  { value: "generic", label: t("通用邀请") },
                ]}
              />
            </label>
            <label className="grid gap-1 text-sm">
              <span>{t("角色")}</span>
              <FilterDropdown className="h-9 w-full" value={invite.role} onChange={(role) => setInvite((current) => ({ ...current, role }))} ariaLabel={t("角色")} options={[{ value: "member", label: t("成员") }, ...(invite.kind === "personal" && session.me?.user.is_global_admin ? [{ value: "admin", label: t("工作空间管理员") }] : [])]} />
            </label>
            {invite.kind === "personal" ? (
              <>
                <Field label={t("账号")} value={invite.username} onChange={(value) => setInvite((current) => ({ ...current, username: value }))} required />
                <Field label={t("邮箱")} value={invite.email} onChange={(value) => setInvite((current) => ({ ...current, email: value }))} required type="email" />
                <Field label={t("姓名")} value={invite.name} onChange={(value) => setInvite((current) => ({ ...current, name: value }))} required />
              </>
            ) : (
              <p className="text-sm text-muted-foreground sm:col-span-2">{t("通用链接在 7 天内可由多人注册，撤销后立即失效")}</p>
            )}
          </div>
          <div className="flex justify-end"><Button type="submit"><UserPlusIcon className="size-4" />{t("生成邀请链接")}</Button></div>
        </form>
        {inviteResult?.token ? (
          <div className="mt-4 rounded-lg border bg-muted/20 p-3">
            <div className="mb-2 text-sm font-medium">{t("邀请链接")}</div>
            <div className="flex gap-2">
              <Input
                readOnly
                value={inviteResult.invite_url ?? inviteResult.token}
              />
              <Button
                type="button"
                variant="outline"
                size="icon"
                aria-label={t("复制链接")}
                onClick={() => void copyInviteLink()}
              >
                <CopyIcon className="size-4" />
              </Button>
            </div>
            {inviteResult.kind === "personal" &&
            inviteResult.email_delivery_status === "queued" ? (
              <p
                className="mt-2 text-xs text-emerald-700 dark:text-emerald-400"
                role="status"
              >
                {t("邀请邮件已加入发送队列")}
              </p>
            ) : null}
            {inviteResult.kind === "personal" &&
            inviteResult.email_delivery_status === "not_configured" ? (
              <p
                className="mt-2 text-xs text-amber-700 dark:text-amber-400"
                role="status"
              >
                {t("邮件服务尚未配置，邀请邮件未发送；你仍可复制邀请链接")}
              </p>
            ) : null}
          </div>
        ) : null}
        <div className="mt-4 grid gap-2">
          {invitations.map((item) => (
            <div key={item.id} className="flex flex-wrap items-center justify-between gap-2 rounded-lg border p-3 text-sm">
              <div>
                <div className="font-medium">{item.kind === "generic" ? t("通用邀请") : `${item.name} · ${item.email}`}</div>
                <div className="text-xs text-muted-foreground">{t(item.role === "admin" ? "工作空间管理员" : "成员")} · {formatDateTime(item.expires_at, dateLocale)}</div>
              </div>
              <div className="flex items-center gap-2">
                {item.accepted_at ? (
                  <Badge variant="secondary">{t("已撤销或已接受")}</Badge>
                ) : (
                  <Button type="button" variant="outline" size="sm" onClick={() => void revokeInvite(item.id)}>{t("撤销")}</Button>
                )}
                <Button type="button" variant="outline" size="sm" onClick={() => void deleteInvite(item.id)}>
                  <Trash2Icon className="size-4" />
                  {t("删除")}
                </Button>
              </div>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
    </div>
  </div>
}

/**
 * Displays the current user's active sessions and allows administrators to revoke them.
 *
 * Global administrators can inspect and manage sessions for other users.
 */
function SecurityPanel() {
  const { t, language } = useLanguage()
  const { session, reportError } = useGovernanceContext()
  const [confirmAction, confirmDialog] = useConfirmDialog()
  const [sessions, setSessions] = React.useState<RefreshSession[]>([])
  const [users, setUsers] = React.useState<User[]>([])
  const [targetUserId, setTargetUserId] = React.useState(session.me?.user.id ?? "")
  const [loading, setLoading] = React.useState(true)
  const isGlobal = Boolean(session.me?.user.is_global_admin)
  const currentUserId = session.me?.user.id ?? ""
  const dateLocale = language === "en" ? "en-US" : language === "zh-Hant" ? "zh-TW" : "zh-CN"

  const load = React.useCallback(async () => {
    if (!session.token) return
    setLoading(true)
    try {
      if (isGlobal) {
        const [nextUsers, nextSessions] = await Promise.all([listUsers(session.token), listUserSessions(session.token, targetUserId || currentUserId)])
        setUsers(nextUsers); setSessions(nextSessions)
      } else setSessions(await listSessions(session.token))
    } catch (error) { reportError(error) } finally { setLoading(false) }
  }, [currentUserId, isGlobal, reportError, session.token, targetUserId])

  React.useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load()
  }, [load])

  async function revoke(item: RefreshSession) {
    if (!session.token) return
    if (!(await confirmAction({
      description: t("确认撤销会话"),
      confirmLabel: t("撤销"),
      destructive: true,
    }))) return
    try { if (isGlobal && targetUserId !== session.me?.user.id) await revokeUserSession(session.token, targetUserId, item.id); else await revokeSession(session.token, item.id); setSessions((current) => current.filter((candidate) => candidate.id !== item.id)); session.notify("success", t("会话已撤销")) } catch (error) { reportError(error) }
  }

  async function revokeAll() {
    if (!session.token) return
    if (!(await confirmAction({
      description: t("确认撤销其他会话"),
      confirmLabel: t("撤销"),
      destructive: true,
    }))) return
    try { if (isGlobal && targetUserId !== session.me?.user.id) await revokeAllUserSessions(session.token, targetUserId); else await revokeOtherSessions(session.token); await load(); session.notify("success", t("其他会话已撤销")) } catch (error) { reportError(error) }
  }

  return <><Card><CardHeader className="flex-row flex-wrap items-end justify-between gap-3"><div><CardTitle className="flex items-center gap-2"><KeyRoundIcon className="size-4" />{t("会话安全")}</CardTitle><CardDescription>{t("查看登录设备并及时撤销异常会话")}</CardDescription></div><div className="flex flex-wrap gap-2">{isGlobal ? <FilterDropdown className="h-9 w-56" value={targetUserId} onChange={setTargetUserId} ariaLabel={t("选择用户")} options={users.map((user) => ({ value: user.id, label: `${user.name} (${user.username})` }))} /> : null}<Button variant="outline" size="sm" onClick={() => void revokeAll()} disabled={loading}><XCircleIcon className="size-4" />{t("撤销其他会话")}</Button><Button variant="outline" size="icon" onClick={() => void load()} disabled={loading} aria-label={t("刷新")}><RefreshCwIcon className={cn("size-4", loading && "animate-spin")} /></Button></div></CardHeader><CardContent>{loading ? <LoaderCircleIcon className="mx-auto my-10 animate-spin" /> : sessions.length ? <div className="grid gap-2">{sessions.map((item) => <div key={item.id} className="flex flex-wrap items-center justify-between gap-3 rounded-lg border p-3"><div className="flex min-w-0 items-center gap-3"><div className="flex size-9 items-center justify-center rounded-full bg-muted"><KeyRoundIcon className="size-4" /></div><div className="min-w-0"><div className="truncate text-sm font-medium" title={item.user_agent || item.ip_address || t("未知设备")}>{item.user_agent || item.ip_address || t("未知设备")}</div><div className="text-xs text-muted-foreground">{item.user_agent ? item.ip_address || "—" : "—"} · {t("最近使用")} {formatDateTime(item.last_used_at, dateLocale)}</div></div></div><div className="flex items-center gap-2">{item.is_current ? <Badge><CheckCircle2Icon className="mr-1 size-3" />{t("当前会话")}</Badge> : null}<Button variant="destructive" size="sm" onClick={() => void revoke(item)}>{t("撤销")}</Button></div></div>)}</div> : <div className="rounded-lg border border-dashed p-8 text-center text-sm text-muted-foreground">{t("暂无会话")}</div>}</CardContent></Card>{confirmDialog}</>
}

/**
 * Renders a labeled controlled input field.
 *
 * @param label - The text displayed above the input
 * @param value - The input's current value
 * @param onChange - Called with the updated input value
 * @param placeholder - Optional placeholder text
 * @param type - The input type
 * @param required - Whether the input requires a value
 */
function Field({
  label,
  value,
  onChange,
  placeholder,
  type = "text",
  required,
}: {
  label: string
  value: string
  onChange: (value: string) => void
  placeholder?: string
  type?: string
  required?: boolean
}) {
  return <label className="grid gap-1 text-sm"><span>{label}</span><Input type={type} value={value} placeholder={placeholder} required={required} onChange={(event) => onChange(event.target.value)} /></label>
}

/**
 * Renders a centered message for an empty content area.
 *
 * @param text - The message to display
 */
function EmptyState({ text }: { text: string }) {
  return <div className="rounded-lg border border-dashed p-10 text-center text-sm text-muted-foreground">{text}</div>
}
