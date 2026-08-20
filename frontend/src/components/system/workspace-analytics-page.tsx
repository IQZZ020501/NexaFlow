"use client"

import * as React from "react"
import {
  ActivityIcon,
  Building2Icon,
  CalendarDaysIcon,
  ChevronDownIcon,
  LoaderCircleIcon,
  RefreshCwIcon,
  TriangleAlertIcon,
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
import { languageLocales, type TranslationKey } from "@/i18n"
import type { MeResponse } from "@/lib/api/auth"
import {
  getWorkspaceAnalytics,
  type WorkspaceAnalytics,
} from "@/lib/api/analytics"
import type { Workspace } from "@/lib/api/system"
import { displayWorkspaceName, getMembershipRole } from "@/lib/display"
import { getErrorMessage } from "@/lib/errors"
import { canAccessWorkspaceAnalytics } from "@/components/system/system-utils"
import {
  formatAnalyticsHour,
} from "@/components/system/workspace-analytics-metrics"
import { WorkspaceAnalyticsOverview } from "@/components/system/workspace-analytics-overview"
import {
  AnalyticsRankingPanel,
  FrequentQuestionsPanel,
  RunDistributionPanel,
} from "@/components/system/workspace-analytics-insights"

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

/**
 * Formats a date as a UTC calendar date.
 *
 * @param value - The date to format
 * @returns The date in `YYYY-MM-DD` format
 */
function utcDate(value: Date) {
  return value.toISOString().slice(0, 10)
}

/**
 * Shifts a UTC calendar date by the specified number of days.
 *
 * @param value - The date to shift in `YYYY-MM-DD` format
 * @param days - The number of days to add; negative values shift the date earlier
 * @returns The shifted date in `YYYY-MM-DD` format
 */
function shiftUtcDate(value: string, days: number) {
  const date = new Date(`${value}T00:00:00Z`)
  date.setUTCDate(date.getUTCDate() + days)
  return utcDate(date)
}

/**
 * Creates a preset analytics date range ending on the day after the current UTC date.
 *
 * @param days - The number of preceding days to include.
 * @param now - The date used to determine the current UTC day.
 * @returns An analytics range with UTC date strings for the start and exclusive end dates.
 */
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

/**
 * Selects active workspaces that the user can administer for analytics.
 *
 * @param me - The current user's account and workspace membership information
 * @param workspaces - Workspaces to filter
 * @returns The active workspaces accessible to global or workspace administrators
 */
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

/**
 * Formats a number according to the specified locale.
 *
 * @param value - The number to format
 * @param locale - The locale used for formatting
 * @returns The locale-formatted number
 */
function formatNumber(value: number, locale: string) {
  return new Intl.NumberFormat(locale).format(value)
}

/**
 * Formats a number using compact notation for the specified locale.
 *
 * @param value - The number to format
 * @param locale - The locale used for formatting
 * @returns The locale-formatted compact number
 */
function formatCompactNumber(value: number, locale: string) {
  return new Intl.NumberFormat(locale, {
    notation: "compact",
    maximumFractionDigits: 1,
  }).format(value)
}

/**
 * Displays a localized area chart for daily workspace runs or token consumption.
 *
 * @param title - The chart title
 * @param description - The chart description
 * @param data - The daily trend data to visualize
 * @param dataKey - The metric to plot: `runs` or `total_tokens`
 * @param locale - The locale used to format axis and tooltip values
 * @param color - The chart's stroke and gradient color
 */
function TrendChart({
  title,
  description,
  data,
  dataKey,
  locale,
  color,
}: {
  title: string
  description: string
  data: WorkspaceAnalytics["trends"]
  dataKey: "runs" | "total_tokens"
  locale: string
  color: string
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
                <stop offset="0%" stopColor={color} stopOpacity={0.25} />
                <stop offset="100%" stopColor={color} stopOpacity={0.03} />
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
              stroke={color}
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

/**
 * Displays hourly run activity for the selected analytics period.
 *
 * @param data - Hourly run counts to visualize
 * @param locale - Locale used to format chart values
 * @param color - Color used for the chart area and line
 */
function HourlyTrendChart({
  data,
  locale,
  color,
}: {
  data: WorkspaceAnalytics["hourly_runs"]
  locale: string
  color: string
}) {
  const { t } = useLanguage()
  const description = t("所选周期内各小时的运行活跃度")
  return (
    <Card className="min-w-0 gap-4 py-5 shadow-none">
      <CardHeader className="px-5">
        <CardTitle>{t("时段活跃曲线")}</CardTitle>
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
              <linearGradient id="analytics-hourly" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={color} stopOpacity={0.25} />
                <stop offset="100%" stopColor={color} stopOpacity={0.03} />
              </linearGradient>
            </defs>
            <CartesianGrid
              vertical={false}
              stroke="var(--border)"
              strokeDasharray="3 3"
            />
            <XAxis
              dataKey="hour"
              type="number"
              domain={[0, 23]}
              ticks={Array.from({ length: 24 }, (_, hour) => hour)}
              axisLine={false}
              tickLine={false}
              interval={0}
              height={48}
              tickFormatter={(value: number) => formatAnalyticsHour(value)}
              angle={-35}
              textAnchor="end"
              tick={{ fill: "var(--muted-foreground)", fontSize: 9 }}
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
              labelFormatter={(value) => formatAnalyticsHour(Number(value))}
              formatter={(value) => formatNumber(Number(value ?? 0), locale)}
            />
            <Area
              type="monotone"
              dataKey="runs"
              stroke={color}
              strokeWidth={2.5}
              fill="url(#analytics-hourly)"
              isAnimationActive={false}
            />
          </AreaChart>
        </ResponsiveContainer>
      </CardContent>
    </Card>
  )
}

/**
 * Displays workspace usage, activity, and resource-consumption analytics with selectable date ranges.
 *
 * @returns The workspace analytics page.
 */
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
      : t(
          PRESET_OPTIONS.find((option) => option.value === preset)?.label ??
            "最近 30 天"
        )
  const chartVars = {
    "--analytics-hourly": "color-mix(in oklch, var(--primary) 55%, oklch(0.58 0.13 190))",
    "--analytics-runs": "color-mix(in oklch, var(--primary) 55%, oklch(0.58 0.13 245))",
    "--analytics-tokens": "color-mix(in oklch, var(--primary) 55%, oklch(0.58 0.12 300))",
  } as React.CSSProperties

  return (
    <div
      className="mx-auto flex w-full max-w-[1600px] min-w-0 flex-col gap-5"
      style={chartVars}
    >
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
                  <ChevronDownIcon aria-hidden="true" className="size-4 text-muted-foreground" />
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
                    <Building2Icon aria-hidden="true" />
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
                  <ChevronDownIcon aria-hidden="true" className="size-4 text-muted-foreground" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="min-w-44">
                {PRESET_OPTIONS.map((option) => (
                  <DropdownMenuItem
                    key={option.value}
                    onSelect={() => selectPreset(option.value)}
                  >
                    <CalendarDaysIcon aria-hidden="true" />
                    {t(option.label)}
                  </DropdownMenuItem>
                ))}
                <DropdownMenuItem onSelect={() => setPreset("custom")}>
                  <CalendarDaysIcon aria-hidden="true" />
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
            <div className="flex min-w-0 flex-1 flex-col gap-1.5">
              <Label htmlFor="analytics-from">{t("开始日期")}</Label>
              <Input
                id="analytics-from"
                type="date"
                value={customFrom}
                max={customTo}
                onChange={(event) => setCustomFrom(event.target.value)}
              />
            </div>
            <div className="flex min-w-0 flex-1 flex-col gap-1.5">
              <Label htmlFor="analytics-to">{t("结束日期")}</Label>
              <Input
                id="analytics-to"
                type="date"
                value={customTo}
                min={customFrom}
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
            <LoaderCircleIcon aria-hidden="true" className="mr-2 size-4 animate-spin" />
            {t("正在加载")}
          </CardContent>
        </Card>
      ) : error && !data ? (
        <Card className="border-destructive/40 py-12 shadow-none">
          <CardContent className="flex flex-col items-center gap-3 text-center">
            <TriangleAlertIcon aria-hidden="true" className="size-6 text-destructive" />
            <p className="text-sm text-muted-foreground">{error}</p>
            <Button variant="outline" onClick={() => setReloadKey((value) => value + 1)}>
              <RefreshCwIcon data-icon="inline-start" aria-hidden="true" />
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

          <WorkspaceAnalyticsOverview data={data} locale={locale} />

          <p className="text-xs text-muted-foreground">
            {t("统计时区为 {timezone}，结束日期不计入统计区间。", {
              timezone: data.metadata.timezone,
            })}
          </p>

          {data.summary.runs.value === 0 ? (
            <Card className="border-dashed py-14 shadow-none">
              <CardContent className="flex flex-col items-center gap-2 text-center text-sm text-muted-foreground">
                <ActivityIcon aria-hidden="true" className="size-6" />
                {t("所选范围内暂无运行数据")}
              </CardContent>
            </Card>
          ) : (
            <>
              <HourlyTrendChart
                data={data.hourly_runs}
                locale={locale}
                color="var(--analytics-hourly)"
              />
              <div className="grid min-w-0 gap-4 xl:grid-cols-2">
                <TrendChart
                  title={t("每日运行趋势")}
                  description={t("按 UTC 自然日统计顶层运行")}
                  data={data.trends}
                  dataKey="runs"
                  locale={locale}
                  color="var(--analytics-runs)"
                />
                <TrendChart
                  title={t("每日 Token 趋势")}
                  description={t("Workflow 使用工作流级 Token 口径")}
                  data={data.trends}
                  dataKey="total_tokens"
                  locale={locale}
                  color="var(--analytics-tokens)"
                />
              </div>

              <RunDistributionPanel
                data={data.distributions}
                locale={locale}
              />

              <div className="grid min-w-0 gap-4 xl:grid-cols-[3fr_2fr]">
                <AnalyticsRankingPanel data={data.rankings} locale={locale} />
                <FrequentQuestionsPanel
                  items={data.frequent_questions}
                  locale={locale}
                />
              </div>
            </>
          )}
        </div>
      ) : null}
    </div>
  )
}
