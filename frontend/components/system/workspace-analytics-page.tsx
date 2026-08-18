"use client"

import * as React from "react"
import {
  ActivityIcon,
  BarChart3Icon,
  BotIcon,
  Building2Icon,
  CalendarDaysIcon,
  CheckCircle2Icon,
  ChevronDownIcon,
  Clock3Icon,
  LoaderCircleIcon,
  MessageCircleQuestionIcon,
  RefreshCwIcon,
  TriangleAlertIcon,
  UsersIcon,
  WorkflowIcon,
} from "lucide-react"
import { useRouter } from "next/navigation"
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts"

import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { useLanguage } from "@/contexts/language-provider"
import { useSession } from "@/contexts/session-context"
import { languageLocales, type TFunction, type TranslationKey } from "@/i18n"
import type { MeResponse } from "@/lib/api/auth"
import {
  getWorkspaceAnalytics,
  type WorkspaceAnalytics,
} from "@/lib/api/analytics"
import type { Workspace } from "@/lib/api/system"
import { displayWorkspaceName, getMembershipRole } from "@/lib/display"
import { getErrorMessage } from "@/lib/errors"
import { cn } from "@/lib/utils"
import { canAccessWorkspaceAnalytics } from "@/components/system/system-utils"

type AnalyticsRange = { from: string; to: string }
type RangePreset = 7 | 30 | 90 | "custom"

const PRESET_OPTIONS: Array<{
  value: Exclude<RangePreset, "custom">
  label: TranslationKey
}> = [
  { value: 7, label: "最近 7 天" },
  { value: 30, label: "最近 30 天" },
  { value: 90, label: "最近 90 天" },
]

const STATUS_LABELS: Record<string, TranslationKey> = {
  queued: "排队中",
  planning: "规划中",
  planned: "已规划",
  running: "运行中",
  awaiting_approval: "等待审批",
  awaiting_input: "等待输入",
  awaiting_child: "等待子运行",
  succeeded: "运行成功",
  failed: "运行失败",
  cancelled: "已取消",
}

function utcDate(value: Date) {
  return value.toISOString().slice(0, 10)
}

function shiftUtcDate(value: string, days: number) {
  const date = new Date(`${value}T00:00:00Z`)
  date.setUTCDate(date.getUTCDate() + days)
  return utcDate(date)
}

export function getPresetAnalyticsRange(
  days: 7 | 30 | 90,
  now = new Date()
): AnalyticsRange {
  const today = new Date(
    Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate())
  )
  const to = new Date(today)
  to.setUTCDate(to.getUTCDate() + 1)
  const from = new Date(to)
  from.setUTCDate(from.getUTCDate() - days)
  return { from: utcDate(from), to: utcDate(to) }
}

export function getAnalyticsWorkspaceOptions(
  me: MeResponse,
  workspaces: Workspace[]
) {
  return workspaces.filter(
    (workspace) =>
      workspace.status === "active" &&
      (me.user.is_global_admin ||
        getMembershipRole(me, workspace.id) === "admin")
  )
}

function formatNumber(value: number, locale: string) {
  return new Intl.NumberFormat(locale).format(value)
}

function formatCompactNumber(value: number, locale: string) {
  return new Intl.NumberFormat(locale, {
    notation: "compact",
    maximumFractionDigits: 1,
  }).format(value)
}

function formatPercent(value: number | null, locale: string) {
  return value === null
    ? "—"
    : new Intl.NumberFormat(locale, {
        style: "percent",
        maximumFractionDigits: 1,
      }).format(value)
}

function formatDateTime(value: string, locale: string) {
  return new Intl.DateTimeFormat(locale, {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: "UTC",
  }).format(new Date(value))
}

function distributionLabel(
  key: string,
  kind: "type" | "source" | "status",
  t: TFunction
) {
  if (kind === "type") return key === "workflow" ? t("工作流") : t("Agent")
  if (kind === "source") {
    if (key === "public") return t("公开访问")
    if (key === "api") return t("API")
    return t("控制台")
  }
  const label = STATUS_LABELS[key]
  return label ? t(label) : key
}

function Comparison({ value, t }: { value: number | null; t: TFunction }) {
  if (value === null) {
    return <span>{t("上期无可比数据")}</span>
  }
  const formatted = `${value > 0 ? "+" : ""}${value.toFixed(1)}`
  return <span>{t("较上期 {value}%", { value: formatted })}</span>
}

function MetricCard({
  icon: Icon,
  label,
  value,
  detail,
  comparison,
  className,
}: {
  icon: React.ComponentType<{ className?: string }>
  label: string
  value: string
  detail?: React.ReactNode
  comparison?: number | null
  className?: string
}) {
  const { t } = useLanguage()
  return (
    <Card className={cn("gap-3 py-4 shadow-none", className)}>
      <CardContent className="flex h-full flex-col gap-3 px-4">
        <div className="flex items-center justify-between gap-3 text-muted-foreground">
          <span className="text-sm font-medium">{label}</span>
          <span className="rounded-lg bg-primary/10 p-2 text-primary">
            <Icon className="size-4" />
          </span>
        </div>
        <strong className="text-2xl font-semibold tracking-tight">{value}</strong>
        <div className="mt-auto text-xs text-muted-foreground">
          {detail ??
            (comparison !== undefined ? (
              <Comparison value={comparison} t={t} />
            ) : null)}
        </div>
      </CardContent>
    </Card>
  )
}

function TrendChart({
  title,
  description,
  data,
  dataKey,
  locale,
}: {
  title: string
  description: string
  data: WorkspaceAnalytics["trends"]
  dataKey: "runs" | "total_tokens"
  locale: string
}) {
  return (
    <Card className="min-w-0 gap-4 py-5 shadow-none">
      <CardHeader className="px-5">
        <CardTitle>{title}</CardTitle>
        <CardDescription>{description}</CardDescription>
      </CardHeader>
      <CardContent className="h-64 min-w-0 px-2 sm:px-5">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart
            data={data}
            accessibilityLayer
            desc={description}
            margin={{ top: 8, right: 12, left: 0, bottom: 0 }}
          >
            <defs>
              <linearGradient id={`analytics-${dataKey}`} x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="var(--primary)" stopOpacity={0.22} />
                <stop offset="100%" stopColor="var(--primary)" stopOpacity={0.02} />
              </linearGradient>
            </defs>
            <CartesianGrid
              vertical={false}
              stroke="var(--border)"
              strokeDasharray="3 3"
            />
            <XAxis
              dataKey="date"
              axisLine={false}
              tickLine={false}
              minTickGap={28}
              tickFormatter={(value: string) => value.slice(5)}
              tick={{ fill: "var(--muted-foreground)", fontSize: 11 }}
            />
            <YAxis
              allowDecimals={false}
              axisLine={false}
              tickLine={false}
              width={46}
              tickFormatter={(value: number) =>
                formatCompactNumber(Number(value), locale)
              }
              tick={{ fill: "var(--muted-foreground)", fontSize: 11 }}
            />
            <Tooltip
              cursor={{
                stroke: "var(--muted-foreground)",
                strokeDasharray: "4 4",
                strokeOpacity: 0.5,
              }}
              contentStyle={{
                borderRadius: "var(--radius)",
                borderColor: "var(--border)",
                backgroundColor: "var(--popover)",
                color: "var(--popover-foreground)",
              }}
              formatter={(value) => formatNumber(Number(value ?? 0), locale)}
            />
            <Area
              type="monotone"
              dataKey={dataKey}
              stroke="var(--primary)"
              strokeWidth={2.5}
              fill={`url(#analytics-${dataKey})`}
              isAnimationActive={false}
            />
          </AreaChart>
        </ResponsiveContainer>
      </CardContent>
    </Card>
  )
}

function DistributionCard({
  title,
  items,
  kind,
}: {
  title: string
  items: Array<{ key: string; count: number }>
  kind: "type" | "source" | "status"
}) {
  const { t } = useLanguage()
  const total = items.reduce((sum, item) => sum + item.count, 0)
  return (
    <Card className="gap-4 py-5 shadow-none">
      <CardHeader className="px-5">
        <CardTitle>{title}</CardTitle>
      </CardHeader>
      <CardContent className="px-5">
        {items.length ? (
          <ul className="space-y-4">
            {items.map((item) => {
              const percent = total ? (item.count / total) * 100 : 0
              return (
                <li key={item.key} className="space-y-1.5">
                  <div className="flex items-center justify-between gap-3 text-sm">
                    <span>{distributionLabel(item.key, kind, t)}</span>
                    <span className="tabular-nums text-muted-foreground">
                      {item.count}
                    </span>
                  </div>
                  <div className="h-2 overflow-hidden rounded-full bg-muted">
                    <div
                      className="h-full rounded-full bg-primary"
                      style={{ width: `${percent}%` }}
                    />
                  </div>
                </li>
              )
            })}
          </ul>
        ) : (
          <p className="text-sm text-muted-foreground">{t("暂无数据")}</p>
        )}
      </CardContent>
    </Card>
  )
}

export function WorkspaceAnalyticsPage() {
  const router = useRouter()
  const session = useSession()
  const { language, t } = useLanguage()
  const locale = languageLocales[language]
  const [preset, setPreset] = React.useState<RangePreset>(30)
  const [range, setRange] = React.useState<AnalyticsRange>(() =>
    getPresetAnalyticsRange(30)
  )
  const [customFrom, setCustomFrom] = React.useState(range.from)
  const [customTo, setCustomTo] = React.useState(() => shiftUtcDate(range.to, -1))
  const [data, setData] = React.useState<WorkspaceAnalytics | null>(null)
  const [error, setError] = React.useState<string | null>(null)
  const [loading, setLoading] = React.useState(false)
  const [reloadKey, setReloadKey] = React.useState(0)

  const canAccess = Boolean(
    session.me && canAccessWorkspaceAnalytics(session.me)
  )
  const workspaceOptions = React.useMemo(
    () =>
      session.me
        ? getAnalyticsWorkspaceOptions(session.me, session.workspaces)
        : [],
    [session.me, session.workspaces]
  )
  const workspaceId =
    workspaceOptions.find(
      (workspace) => workspace.id === session.selectedWorkspaceId
    )?.id ?? workspaceOptions[0]?.id ?? null
  const selectedWorkspace =
    workspaceOptions.find((workspace) => workspace.id === workspaceId) ?? null

  React.useEffect(() => {
    if (session.me && !canAccess) router.replace("/app/apps")
  }, [canAccess, router, session.me])

  React.useEffect(() => {
    if (!canAccess || !session.token || !workspaceId) return
    let current = true
    const controller = new AbortController()
    // Clear the previous tenant's data before starting the next scoped request.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setData(null)
    setError(null)
    setLoading(true)
    getWorkspaceAnalytics(
      session.token,
      workspaceId,
      range,
      controller.signal
    )
      .then((payload) => {
        if (current) setData(payload)
      })
      .catch((loadError: unknown) => {
        if (
          current &&
          !(loadError instanceof DOMException && loadError.name === "AbortError")
        ) {
          setError(getErrorMessage(loadError, t))
        }
      })
      .finally(() => {
        if (current) setLoading(false)
      })
    return () => {
      current = false
      controller.abort()
    }
  }, [canAccess, range, reloadKey, session.token, t, workspaceId])

  if (!session.me || !canAccess) return null

  const selectPreset = (days: 7 | 30 | 90) => {
    const nextRange = getPresetAnalyticsRange(days)
    setPreset(days)
    setRange(nextRange)
    setCustomFrom(nextRange.from)
    setCustomTo(shiftUtcDate(nextRange.to, -1))
  }
  const customRangeValid = Boolean(
    customFrom && customTo && customFrom <= customTo
  )
  const applyCustomRange = () => {
    if (!customRangeValid) return
    setRange({ from: customFrom, to: shiftUtcDate(customTo, 1) })
  }
  const presetLabel =
    preset === "custom"
      ? t("自定义")
      : t(PRESET_OPTIONS.find((option) => option.value === preset)?.label ?? "最近 30 天")

  return (
    <div className="mx-auto flex w-full max-w-[1600px] min-w-0 flex-col gap-5">
      <div className="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
        <div className="space-y-1">
          <h1 className="text-2xl font-semibold tracking-tight">{t("数据大屏")}</h1>
          <p className="text-sm text-muted-foreground">
            {t("按工作空间查看使用规模、活跃度与资源消耗。")}
          </p>
        </div>
        <div className="flex min-w-0 flex-wrap items-center gap-x-4 gap-y-3">
          <div className="flex w-full min-w-0 items-center gap-2 sm:w-auto">
            <Label className="shrink-0">{t("工作空间")}</Label>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button
                  variant="outline"
                  className="min-w-0 flex-1 justify-between sm:w-auto sm:max-w-80 sm:flex-none"
                  aria-label={t("选择统计工作空间")}
                >
                  <span className="truncate">
                    {selectedWorkspace
                      ? displayWorkspaceName(selectedWorkspace, t)
                      : t("暂无工作空间")}
                  </span>
                  <ChevronDownIcon className="size-4 text-muted-foreground" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="min-w-64">
                <DropdownMenuLabel>{t("工作空间")}</DropdownMenuLabel>
                <DropdownMenuSeparator />
                {workspaceOptions.map((workspace) => (
                  <DropdownMenuItem
                    key={workspace.id}
                    onSelect={() => session.selectWorkspace(workspace.id)}
                  >
                    <Building2Icon />
                    <span className="truncate">
                      {displayWorkspaceName(workspace, t)}
                    </span>
                  </DropdownMenuItem>
                ))}
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
          <div className="flex w-full min-w-0 items-center gap-2 sm:w-auto">
            <Label className="shrink-0">{t("统计周期")}</Label>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button
                  variant="outline"
                  className="min-w-0 flex-1 justify-between sm:w-auto sm:flex-none"
                  aria-label={t("选择统计周期")}
                >
                  <span>{presetLabel}</span>
                  <ChevronDownIcon className="size-4 text-muted-foreground" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="min-w-44">
                {PRESET_OPTIONS.map((option) => (
                  <DropdownMenuItem
                    key={option.value}
                    onSelect={() => selectPreset(option.value)}
                  >
                    <CalendarDaysIcon />
                    {t(option.label)}
                  </DropdownMenuItem>
                ))}
                <DropdownMenuItem onSelect={() => setPreset("custom")}>
                  <CalendarDaysIcon />
                  {t("自定义")}
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </div>
      </div>

      {preset === "custom" ? (
        <Card className="gap-4 py-4 shadow-none">
          <CardContent className="flex flex-col gap-3 px-4 sm:flex-row sm:items-end">
            <div className="flex-1 space-y-1.5">
              <Label htmlFor="analytics-from">{t("开始日期")}</Label>
              <Input
                id="analytics-from"
                type="date"
                value={customFrom}
                max={customTo || undefined}
                onChange={(event) => setCustomFrom(event.target.value)}
              />
            </div>
            <div className="flex-1 space-y-1.5">
              <Label htmlFor="analytics-to">{t("结束日期")}</Label>
              <Input
                id="analytics-to"
                type="date"
                value={customTo}
                min={customFrom || undefined}
                aria-invalid={!customRangeValid}
                onChange={(event) => setCustomTo(event.target.value)}
              />
            </div>
            <Button disabled={!customRangeValid} onClick={applyCustomRange}>
              {t("确认")}
            </Button>
          </CardContent>
        </Card>
      ) : null}

      {!workspaceId ? (
        <Card className="border-dashed py-12 shadow-none">
          <CardContent className="text-center text-sm text-muted-foreground">
            {t("暂无可查看的数据工作空间")}
          </CardContent>
        </Card>
      ) : loading && !data ? (
        <Card className="py-16 shadow-none">
          <CardContent className="flex items-center justify-center text-sm text-muted-foreground">
            <LoaderCircleIcon className="mr-2 size-4 animate-spin" />
            {t("正在加载")}
          </CardContent>
        </Card>
      ) : error && !data ? (
        <Card className="border-destructive/40 py-12 shadow-none">
          <CardContent className="flex flex-col items-center gap-3 text-center">
            <TriangleAlertIcon className="size-6 text-destructive" />
            <p className="text-sm text-muted-foreground">{error}</p>
            <Button variant="outline" onClick={() => setReloadKey((value) => value + 1)}>
              <RefreshCwIcon data-icon="inline-start" />
              {t("重试")}
            </Button>
          </CardContent>
        </Card>
      ) : data ? (
        <div className="flex min-w-0 flex-col gap-5" aria-busy={loading}>
          {error ? (
            <div className="flex items-center justify-between gap-3 rounded-lg border border-destructive/30 bg-destructive/5 px-4 py-3 text-sm">
              <span>{error}</span>
              <Button
                size="sm"
                variant="outline"
                onClick={() => setReloadKey((value) => value + 1)}
              >
                {t("重试")}
              </Button>
            </div>
          ) : null}

          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-12">
            <MetricCard
              className="xl:col-span-3"
              icon={UsersIcon}
              label={t("工作空间成员")}
              value={formatNumber(data.summary.members.total, locale)}
              detail={t("启用 {active} / 总计 {total}", {
                active: formatNumber(data.summary.members.active, locale),
                total: formatNumber(data.summary.members.total, locale),
              })}
            />
            <MetricCard
              className="xl:col-span-3"
              icon={Building2Icon}
              label={t("启用团队")}
              value={formatNumber(data.summary.active_teams, locale)}
            />
            <MetricCard
              className="xl:col-span-3"
              icon={ActivityIcon}
              label={t("活跃用户")}
              value={formatNumber(data.summary.active_users.value, locale)}
              comparison={data.summary.active_users.change_percent}
            />
            <MetricCard
              className="xl:col-span-3"
              icon={BarChart3Icon}
              label={t("运行次数")}
              value={formatNumber(data.summary.runs.value, locale)}
              comparison={data.summary.runs.change_percent}
            />
            <MetricCard
              className="xl:col-span-4"
              icon={BotIcon}
              label={t("Token 消耗")}
              value={formatNumber(data.summary.tokens.total, locale)}
              detail={
                <div className="space-y-1">
                  <p>
                    {t("输入 {input} / 输出 {output}", {
                      input: formatNumber(data.summary.tokens.input, locale),
                      output: formatNumber(data.summary.tokens.output, locale),
                    })}
                  </p>
                  <p>
                    <Comparison
                      value={data.summary.tokens.change_percent}
                      t={t}
                    />
                  </p>
                  {data.summary.tokens.unreported_runs ? (
                    <p className="text-amber-600 dark:text-amber-400">
                      {t("{value} 次运行的用量未完整上报", {
                        value: data.summary.tokens.unreported_runs,
                      })}
                    </p>
                  ) : null}
                </div>
              }
            />
            <MetricCard
              className="xl:col-span-4"
              icon={CheckCircle2Icon}
              label={t("运行成功率")}
              value={formatPercent(data.summary.success_rate.value, locale)}
              comparison={data.summary.success_rate.change_percent}
            />
            <MetricCard
              className="xl:col-span-4"
              icon={Clock3Icon}
              label={t("平均运行耗时")}
              value={
                data.summary.average_duration_ms.value === null
                  ? "—"
                  : t("{value} 毫秒", {
                      value: formatNumber(
                        Math.round(data.summary.average_duration_ms.value),
                        locale
                      ),
                    })
              }
              comparison={data.summary.average_duration_ms.change_percent}
            />
          </div>

          <p className="text-xs text-muted-foreground">
            {t("统计时区为 {timezone}，结束日期不计入统计区间。", {
              timezone: data.metadata.timezone,
            })}
          </p>

          {data.summary.runs.value === 0 ? (
            <Card className="border-dashed py-14 shadow-none">
              <CardContent className="flex flex-col items-center gap-2 text-center text-sm text-muted-foreground">
                <ActivityIcon className="size-6" />
                {t("所选范围内暂无运行数据")}
              </CardContent>
            </Card>
          ) : (
            <>
              <div className="grid min-w-0 gap-4 xl:grid-cols-2">
                <TrendChart
                  title={t("每日运行趋势")}
                  description={t("按 UTC 自然日统计顶层运行")}
                  data={data.trends}
                  dataKey="runs"
                  locale={locale}
                />
                <TrendChart
                  title={t("每日 Token 趋势")}
                  description={t("Workflow 使用工作流级 Token 口径")}
                  data={data.trends}
                  dataKey="total_tokens"
                  locale={locale}
                />
              </div>

              <div className="grid gap-4 lg:grid-cols-3">
                <DistributionCard
                  title={t("运行类型分布")}
                  items={data.distributions.run_types}
                  kind="type"
                />
                <DistributionCard
                  title={t("访问来源分布")}
                  items={data.distributions.access_sources}
                  kind="source"
                />
                <DistributionCard
                  title={t("运行状态分布")}
                  items={data.distributions.statuses}
                  kind="status"
                />
              </div>

              <div className="grid min-w-0 gap-4 xl:grid-cols-2">
                <Card className="min-w-0 gap-4 py-5 shadow-none">
                  <CardHeader className="px-5">
                    <CardTitle>{t("用户 Token 消耗 Top 10")}</CardTitle>
                  </CardHeader>
                  <CardContent className="min-w-0 px-5">
                    <div className="overflow-x-auto">
                      <table className="w-full min-w-[520px] text-sm">
                        <thead className="text-left text-muted-foreground">
                          <tr className="border-b">
                            <th className="pb-3 font-medium">{t("排名")}</th>
                            <th className="pb-3 font-medium">{t("用户")}</th>
                            <th className="pb-3 text-right font-medium">{t("运行次数")}</th>
                            <th className="pb-3 text-right font-medium">{t("Tokens 总数")}</th>
                          </tr>
                        </thead>
                        <tbody>
                          {data.rankings.users.map((item, index) => (
                            <tr key={item.user_id} className="border-b last:border-0">
                              <td className="py-3 text-muted-foreground">{index + 1}</td>
                              <td className="py-3 font-medium">{item.name}</td>
                              <td className="py-3 text-right tabular-nums">
                                {formatNumber(item.run_count, locale)}
                              </td>
                              <td className="py-3 text-right tabular-nums">
                                {formatNumber(item.total_tokens, locale)}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                    <div className="mt-4 flex flex-col gap-1 rounded-lg border bg-muted/30 px-3 py-2 text-sm sm:flex-row sm:items-center sm:justify-between">
                      <span>{t("公开/API 调用")}</span>
                      <span className="text-muted-foreground">
                        {t("运行 {runs} 次，Tokens {tokens}", {
                          runs: formatNumber(data.rankings.anonymous.run_count, locale),
                          tokens: formatNumber(
                            data.rankings.anonymous.total_tokens,
                            locale
                          ),
                        })}
                      </span>
                    </div>
                  </CardContent>
                </Card>

                <Card className="min-w-0 gap-4 py-5 shadow-none">
                  <CardHeader className="px-5">
                    <CardTitle>{t("应用 / 工作流 Token 消耗 Top 10")}</CardTitle>
                  </CardHeader>
                  <CardContent className="min-w-0 px-5">
                    <div className="overflow-x-auto">
                      <table className="w-full min-w-[620px] text-sm">
                        <thead className="text-left text-muted-foreground">
                          <tr className="border-b">
                            <th className="pb-3 font-medium">{t("排名")}</th>
                            <th className="pb-3 font-medium">{t("应用")}</th>
                            <th className="pb-3 text-right font-medium">{t("运行次数")}</th>
                            <th className="pb-3 text-right font-medium">{t("Tokens 总数")}</th>
                            <th className="pb-3 text-right font-medium">{t("成功率")}</th>
                          </tr>
                        </thead>
                        <tbody>
                          {data.rankings.applications.map((item, index) => (
                            <tr
                              key={item.application_id}
                              className="border-b last:border-0"
                            >
                              <td className="py-3 text-muted-foreground">{index + 1}</td>
                              <td className="py-3">
                                <span className="flex items-center gap-2 font-medium">
                                  {item.app_type === "workflow" ? (
                                    <WorkflowIcon className="size-4 text-muted-foreground" />
                                  ) : (
                                    <BotIcon className="size-4 text-muted-foreground" />
                                  )}
                                  {item.name}
                                </span>
                              </td>
                              <td className="py-3 text-right tabular-nums">
                                {formatNumber(item.run_count, locale)}
                              </td>
                              <td className="py-3 text-right tabular-nums">
                                {formatNumber(item.total_tokens, locale)}
                              </td>
                              <td className="py-3 text-right tabular-nums">
                                {formatPercent(item.success_rate, locale)}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </CardContent>
                </Card>
              </div>

              <div className="grid min-w-0 gap-4 xl:grid-cols-2">
                <Card className="min-w-0 gap-4 py-5 shadow-none">
                  <CardHeader className="px-5">
                    <CardTitle className="flex items-center gap-2">
                      <Building2Icon className="size-4" />
                      {t("团队活跃度 Top 10")}
                    </CardTitle>
                    <CardDescription>
                      {t("按成员所属团队统计，展示单日最高运行次数")}
                    </CardDescription>
                  </CardHeader>
                  <CardContent className="px-5">
                    {data.rankings.teams.length ? (
                      <div className="overflow-x-auto">
                        <table className="w-full min-w-[480px] text-sm">
                          <thead className="text-left text-muted-foreground">
                            <tr className="border-b">
                              <th className="pb-3 font-medium">{t("排名")}</th>
                              <th className="pb-3 font-medium">{t("团队")}</th>
                              <th className="pb-3 text-right font-medium">
                                {t("单日最高")}
                              </th>
                              <th className="pb-3 text-right font-medium">
                                {t("运行次数")}
                              </th>
                            </tr>
                          </thead>
                          <tbody>
                            {data.rankings.teams.map((item, index) => (
                              <tr key={item.team_id} className="border-b last:border-0">
                                <td className="py-3 text-muted-foreground">
                                  {index + 1}
                                </td>
                                <td className="py-3 font-medium">{item.name}</td>
                                <td className="py-3 text-right tabular-nums">
                                  {formatNumber(item.peak_daily_runs, locale)}
                                </td>
                                <td className="py-3 text-right tabular-nums">
                                  {formatNumber(item.run_count, locale)}
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    ) : (
                      <p className="text-sm text-muted-foreground">
                        {t("暂无团队使用数据")}
                      </p>
                    )}
                  </CardContent>
                </Card>

                <Card className="min-w-0 gap-4 py-5 shadow-none">
                  <CardHeader className="px-5">
                    <CardTitle className="flex items-center gap-2">
                      <MessageCircleQuestionIcon className="size-4" />
                      {t("高频问题")}
                    </CardTitle>
                    <CardDescription>
                      {t("仅展示当前工作空间内出现至少 3 次的问题")}
                    </CardDescription>
                  </CardHeader>
                  <CardContent className="px-5">
                    {data.frequent_questions.length ? (
                      <div className="overflow-x-auto">
                        <table className="w-full min-w-[620px] text-sm">
                          <thead className="text-left text-muted-foreground">
                            <tr className="border-b">
                              <th className="pb-3 font-medium">{t("问题")}</th>
                              <th className="pb-3 text-right font-medium">{t("出现次数")}</th>
                              <th className="pb-3 text-right font-medium">{t("最近出现")}</th>
                            </tr>
                          </thead>
                          <tbody>
                            {data.frequent_questions.map((item) => (
                              <tr key={item.question} className="border-b last:border-0">
                                <td className="max-w-3xl py-3 pr-4">{item.question}</td>
                                <td className="py-3 text-right tabular-nums">
                                  {formatNumber(item.count, locale)}
                                </td>
                                <td className="whitespace-nowrap py-3 text-right text-muted-foreground">
                                  {formatDateTime(item.latest_at, locale)}
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    ) : (
                      <p className="text-sm text-muted-foreground">
                        {t("暂无达到阈值的高频问题")}
                      </p>
                    )}
                  </CardContent>
                </Card>
              </div>
            </>
          )}
        </div>
      ) : null}
    </div>
  )
}
