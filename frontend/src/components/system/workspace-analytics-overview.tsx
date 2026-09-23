import * as React from "react"
import {
  ActivityIcon,
  ArrowDownRightIcon,
  ArrowUpRightIcon,
  BarChart3Icon,
  CheckCircle2Icon,
  MinusIcon,
  UsersIcon,
} from "lucide-react"

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { useLanguage } from "@/contexts/language-provider"
import type { WorkspaceAnalytics } from "@/lib/api/analytics"
import {
  deriveAnalyticsKeyMetrics,
  formatAnalyticsNumber as formatNumber,
} from "@/components/system/workspace-analytics-metrics"
import { formatTokenCount } from "@/lib/display"
import { cn } from "@/lib/utils"

const TONE_TILE = {
  sky: "bg-sky-500/10 text-sky-700 dark:text-sky-400",
  violet: "bg-violet-500/10 text-violet-700 dark:text-violet-400",
  emerald: "bg-emerald-500/10 text-emerald-700 dark:text-emerald-400",
  amber: "bg-amber-500/10 text-amber-700 dark:text-amber-400",
} as const

/**
 * Formats a number with up to one decimal place according to the specified locale.
 *
 * @param value - The number to format
 * @param locale - The locale used for formatting
 * @returns The localized number string
 */
function formatDecimal(value: number, locale: string) {
  return new Intl.NumberFormat(locale, {
    maximumFractionDigits: 1,
  }).format(value)
}

/**
 * Formats a nullable ratio as a localized percentage.
 *
 * @param value - The ratio to format, or `null` when the value is unavailable
 * @param locale - The locale used for formatting
 * @returns The localized percentage, or `"—"` when `value` is `null`
 */
function formatPercent(value: number | null, locale: string) {
  return value === null
    ? "—"
    : new Intl.NumberFormat(locale, {
        style: "percent",
        maximumFractionDigits: 1,
      }).format(value)
}

/**
 * Displays a localized period-over-period percentage comparison.
 *
 * @param value - The percentage change, or `null` when no comparable data is available
 * @returns The localized comparison chip
 */
function Comparison({ value }: { value: number | null }) {
  const { t } = useLanguage()
  if (value === null) {
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-muted px-2 py-0.5 text-muted-foreground">
        {t("上期无可比数据")}
      </span>
    )
  }
  const formatted = `${value > 0 ? "+" : ""}${value.toFixed(1)}`
  const Icon =
    value > 0 ? ArrowUpRightIcon : value < 0 ? ArrowDownRightIcon : MinusIcon
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full px-2 py-0.5 font-medium tabular-nums",
        value > 0
          ? "bg-emerald-500/10 text-emerald-700 dark:text-emerald-400"
          : value < 0
            ? "bg-destructive/10 text-destructive"
            : "bg-muted text-muted-foreground"
      )}
    >
      <Icon aria-hidden="true" className="size-3 shrink-0" />
      {t("较上期 {value}%", { value: formatted })}
    </span>
  )
}

/**
 * Renders a headline metric with a tinted icon, value, trend chip, and supporting detail.
 *
 * @param icon - Icon component displayed in the metric tile
 * @param tone - Accent used by the icon tile
 * @param label - Metric label
 * @param value - Formatted metric value
 * @param comparison - Period-over-period change displayed beside the value
 * @param detail - Supporting text rendered beneath the value
 */
export function CoreMetricCard({
  icon: Icon,
  tone = "sky",
  label,
  value,
  comparison,
  detail,
}: {
  icon: React.ComponentType<{ className?: string }>
  tone?: keyof typeof TONE_TILE
  label: string
  value: string
  comparison?: number | null
  detail?: string
}) {
  return (
    <Card className="min-w-0 gap-3 rounded-xl py-4 shadow-xs">
      <CardContent className="flex flex-col gap-3 px-4">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="truncate text-sm text-muted-foreground">{label}</p>
            <p className="mt-1 truncate text-2xl font-semibold tracking-tight tabular-nums">
              {value}
            </p>
          </div>
          <span
            aria-hidden="true"
            className={cn(
              "flex size-9 shrink-0 items-center justify-center rounded-lg",
              TONE_TILE[tone]
            )}
          >
            <Icon className="size-4" />
          </span>
        </div>
        <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 text-xs">
          {comparison !== undefined ? <Comparison value={comparison} /> : null}
          {detail ? (
            <span
              className="min-w-0 truncate text-muted-foreground"
              title={detail}
            >
              {detail}
            </span>
          ) : null}
        </div>
      </CardContent>
    </Card>
  )
}

/**
 * Renders a compact metric with optional supporting detail or period comparison.
 *
 * @param label - Metric label
 * @param value - Formatted metric value
 * @param detail - Supporting text displayed beneath the metric value
 * @param comparison - Period-over-period change displayed when `detail` is not provided
 */
function KeyMetric({
  label,
  value,
  detail,
  comparison,
}: {
  label: string
  value: string
  detail?: React.ReactNode
  comparison?: number | null
}) {
  return (
    <div className="min-w-0 rounded-lg border bg-muted/20 p-3">
      <p className="truncate text-xs text-muted-foreground">{label}</p>
      <p className="mt-1 truncate text-base font-semibold tabular-nums">
        {value}
      </p>
      {detail || comparison !== undefined ? (
        <p className="mt-1 truncate text-xs text-muted-foreground">
          {detail ?? <Comparison value={comparison ?? null} />}
        </p>
      ) : null}
    </div>
  )
}

/**
 * Renders a localized panel of workspace key metrics.
 *
 * @param data - Workspace analytics data used to calculate and display the metrics
 * @param locale - Locale used to format metric values
 * @returns The rendered key metrics panel
 */
export function AnalyticsKeyMetricsPanel({
  data,
  locale,
}: {
  data: WorkspaceAnalytics
  locale: string
}) {
  const { t } = useLanguage()
  const derived = deriveAnalyticsKeyMetrics(data)
  const averageDuration = data.summary.average_duration_ms.value

  return (
    <Card className="min-w-0 gap-4 rounded-xl py-5 shadow-xs">
      <CardHeader className="px-5">
        <CardTitle>{t("关键指标")}</CardTitle>
        <p className="text-sm text-muted-foreground">
          {t("成员、效率与调用概览")}
        </p>
      </CardHeader>
      <CardContent className="grid min-w-0 grid-cols-2 gap-3 px-5 md:grid-cols-4 xl:grid-cols-7">
        <KeyMetric
          label={t("工作空间成员")}
          value={t("{active} / {total}", {
            active: formatNumber(data.summary.members.active, locale),
            total: formatNumber(data.summary.members.total, locale),
          })}
          detail={t("启用人数 / 总人数")}
        />
        <KeyMetric
          label={t("启用团队")}
          value={formatNumber(data.summary.active_teams, locale)}
        />
        <KeyMetric
          label={t("平均运行耗时")}
          value={
            averageDuration === null
              ? "—"
              : t("{value} 秒", {
                  value: formatDecimal(averageDuration / 1000, locale),
                })
          }
          comparison={data.summary.average_duration_ms.change_percent}
        />
        <KeyMetric
          label={t("单次平均 Token")}
          value={
            derived.averageTokens === null
              ? "—"
              : formatTokenCount(derived.averageTokens)
          }
          detail={
            data.summary.tokens.unreported_runs ||
            data.summary.tokens.unreported_graph_builds
              ? t("存在用量缺报")
              : undefined
          }
        />
        <KeyMetric
          label={t("人均控制台运行")}
          value={
            derived.consoleRunsPerUser === null
              ? "—"
              : formatDecimal(derived.consoleRunsPerUser, locale)
          }
        />
        <KeyMetric
          label={t("失败 / 取消运行")}
          value={formatNumber(derived.failedCancelledRuns, locale)}
        />
        <KeyMetric
          label={t("外部调用占比")}
          value={formatPercent(derived.externalCallShare, locale)}
        />
      </CardContent>
    </Card>
  )
}

/**
 * Renders the workspace analytics overview with primary metrics and supporting key metrics.
 *
 * @param data - Workspace analytics data used to populate the metrics.
 * @param locale - Locale used to format numeric and percentage values.
 * @returns The rendered workspace analytics overview.
 */
export function WorkspaceAnalyticsOverview({
  data,
  locale,
}: {
  data: WorkspaceAnalytics
  locale: string
}) {
  const { t } = useLanguage()
  const derived = deriveAnalyticsKeyMetrics(data)

  return (
    <>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <CoreMetricCard
          icon={UsersIcon}
          tone="sky"
          label={t("活跃用户")}
          value={formatNumber(data.summary.active_users.value, locale)}
          comparison={data.summary.active_users.change_percent}
          detail={t("启用成员 {active} / {total}", {
            active: formatNumber(data.summary.members.active, locale),
            total: formatNumber(data.summary.members.total, locale),
          })}
        />
        <CoreMetricCard
          icon={BarChart3Icon}
          tone="violet"
          label={t("运行次数")}
          value={formatNumber(data.summary.runs.value, locale)}
          comparison={data.summary.runs.change_percent}
          detail={t("公开与 API 运行 {runs} 次", {
            runs: formatNumber(data.rankings.anonymous.run_count, locale),
          })}
        />
        <CoreMetricCard
          icon={ActivityIcon}
          tone="amber"
          label={t("Token 消耗")}
          value={formatTokenCount(data.summary.tokens.total)}
          comparison={data.summary.tokens.change_percent}
          detail={t("输入 {input} · 输出 {output}", {
            input: formatTokenCount(data.summary.tokens.input),
            output: formatTokenCount(data.summary.tokens.output),
          })}
        />
        <CoreMetricCard
          icon={CheckCircle2Icon}
          tone="emerald"
          label={t("运行成功率")}
          value={formatPercent(data.summary.success_rate.value, locale)}
          comparison={data.summary.success_rate.change_percent}
          detail={t("失败与取消 {value} 次", {
            value: formatNumber(derived.failedCancelledRuns, locale),
          })}
        />
      </div>

      <AnalyticsKeyMetricsPanel data={data} locale={locale} />
    </>
  )
}

export { Comparison }
