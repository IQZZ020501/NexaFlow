import * as React from "react"
import {
  ActivityIcon,
  BarChart3Icon,
  CheckCircle2Icon,
  UsersIcon,
} from "lucide-react"

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { useLanguage } from "@/contexts/language-provider"
import type { WorkspaceAnalytics } from "@/lib/api/analytics"
import {
  deriveAnalyticsKeyMetrics,
} from "@/components/system/workspace-analytics-metrics"

/**
 * Formats a number according to locale-specific conventions.
 *
 * @param value - The number to format
 * @param locale - The locale to use for formatting
 * @returns The localized number string
 */
function formatNumber(value: number, locale: string) {
  return new Intl.NumberFormat(locale).format(value)
}

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
 * @returns The localized comparison text or no-comparable-data message
 */
function Comparison({
  value,
}: {
  value: number | null
}) {
  const { t } = useLanguage()
  if (value === null) return <span>{t("上期无可比数据")}</span>
  const formatted = `${value > 0 ? "+" : ""}${value.toFixed(1)}`
  return <span>{t("较上期 {value}%", { value: formatted })}</span>
}

/**
 * Renders a metric card with an icon, label, value, and optional supporting content.
 *
 * @param icon - Icon component displayed beside the metric
 * @param label - Metric label
 * @param value - Formatted metric value
 * @param detail - Supporting content displayed beneath the value.
 * @param comparison - Period-over-period change displayed when `detail` is not provided.
 */
export function CoreMetricCard({
  icon: Icon,
  label,
  value,
  detail,
  comparison,
}: {
  icon: React.ComponentType<{ className?: string }>
  label: string
  value: string
  detail?: React.ReactNode
  comparison?: number | null
}) {
  return (
    <Card className="min-h-28 gap-2 py-4 shadow-none">
      <CardContent className="flex h-full flex-col gap-2 px-4">
        <div className="flex items-center justify-between gap-3 text-muted-foreground">
          <span className="text-sm font-medium">{label}</span>
          <span className="rounded-lg bg-muted p-2 text-muted-foreground">
            <Icon aria-hidden="true" className="size-4" />
          </span>
        </div>
        <strong className="text-2xl font-semibold tracking-tight">{value}</strong>
        <div className="mt-auto text-xs text-muted-foreground">
          {detail ??
            (comparison !== undefined ? <Comparison value={comparison} /> : null)}
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
 * @param detail - Supporting content displayed beneath the metric value
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
    <div className="min-w-0 border-b pb-3 last:border-b-0 last:pb-0 md:border-b-0 md:border-r md:pr-4 md:last:border-r-0 md:last:pr-0 xl:border-r xl:pb-0">
      <p className="truncate text-xs text-muted-foreground">{label}</p>
      <p className="mt-1 truncate text-base font-semibold tabular-nums">{value}</p>
      {detail || comparison !== undefined ? (
        <p className="mt-1 text-xs text-muted-foreground">
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
    <Card className="gap-4 py-5 shadow-none">
      <CardHeader className="px-5">
        <CardTitle>{t("关键指标")}</CardTitle>
        <p className="text-sm text-muted-foreground">
          {t("成员、效率与调用概览")}
        </p>
      </CardHeader>
      <CardContent className="grid grid-cols-2 gap-x-4 gap-y-4 px-5 md:grid-cols-4 xl:grid-cols-7">
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
              : t("{value} 毫秒", {
                  value: formatNumber(Math.round(averageDuration), locale),
                })
          }
          comparison={data.summary.average_duration_ms.change_percent}
        />
        <KeyMetric
          label={t("单次平均 Token")}
          value={
            derived.averageTokens === null
              ? "—"
              : formatDecimal(derived.averageTokens, locale)
          }
          detail={
            data.summary.tokens.unreported_runs
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

  return (
    <>
      <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
        <CoreMetricCard
          icon={UsersIcon}
          label={t("活跃用户")}
          value={formatNumber(data.summary.active_users.value, locale)}
          comparison={data.summary.active_users.change_percent}
        />
        <CoreMetricCard
          icon={BarChart3Icon}
          label={t("运行次数")}
          value={formatNumber(data.summary.runs.value, locale)}
          comparison={data.summary.runs.change_percent}
        />
        <CoreMetricCard
          icon={ActivityIcon}
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
                <Comparison value={data.summary.tokens.change_percent} />
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
        <CoreMetricCard
          icon={CheckCircle2Icon}
          label={t("运行成功率")}
          value={formatPercent(data.summary.success_rate.value, locale)}
          comparison={data.summary.success_rate.change_percent}
        />
      </div>

      <AnalyticsKeyMetricsPanel data={data} locale={locale} />
    </>
  )
}

export { Comparison }
