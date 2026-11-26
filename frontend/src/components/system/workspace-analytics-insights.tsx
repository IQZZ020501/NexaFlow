import * as React from "react"
import {
  BotIcon,
  Building2Icon,
  MessageCircleQuestionIcon,
  WorkflowIcon,
} from "lucide-react"
import { Label, Pie, PieChart } from "recharts"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import {
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from "@/components/ui/chart"
import { useLanguage } from "@/contexts/language-provider"
import type { TFunction, TranslationKey } from "@/i18n"
import type { WorkspaceAnalytics } from "@/lib/api/analytics"
import { formatTokenCount } from "@/lib/display"
import {
  distributionTotal,
  formatAnalyticsNumber as formatNumber,
} from "@/components/system/workspace-analytics-metrics"

type DistributionKind = "type" | "source" | "status"
type DistributionItem = { key: string; count: number }

const TYPE_COLORS: Record<string, string> = {
  agent: "oklch(0.62 0.16 255)",
  workflow: "oklch(0.64 0.16 295)",
}

const SOURCE_COLORS: Record<string, string> = {
  console: "oklch(0.62 0.16 255)",
  public: "oklch(0.66 0.14 175)",
  api: "oklch(0.72 0.15 70)",
  automation: "oklch(0.64 0.16 295)",
}

const STATUS_COLORS: Record<string, string> = {
  succeeded: "oklch(0.66 0.16 155)",
  failed: "oklch(0.64 0.19 22)",
  awaiting_approval: "oklch(0.75 0.15 75)",
  awaiting_input: "oklch(0.72 0.14 95)",
  awaiting_child: "oklch(0.70 0.13 55)",
  running: "oklch(0.62 0.16 255)",
  planning: "oklch(0.64 0.15 225)",
  planned: "oklch(0.65 0.13 200)",
  queued: "oklch(0.64 0.16 295)",
  cancelled: "oklch(0.65 0.02 255)",
}

const FALLBACK_COLORS = [
  "oklch(0.62 0.16 255)",
  "oklch(0.66 0.14 175)",
  "oklch(0.64 0.16 295)",
  "oklch(0.75 0.15 75)",
  "oklch(0.66 0.16 155)",
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

/**
 * Formats a number according to the specified locale.
 *
 * @param value - The number to format
 * @param locale - The locale used for formatting
 * @returns The locale-formatted number
 */
/**
 * Formats a fractional value as a localized percentage.
 *
 * @param value - The fractional value, or `null` when unavailable
 * @param locale - The locale used for formatting
 * @returns The localized percentage with up to one decimal place, or an em dash when `value` is `null`
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
 * Resolves a localized label for a distribution item.
 *
 * @param key - The distribution item identifier
 * @param kind - The distribution category
 * @returns The localized label, or the original key when no status label is defined
 */
function distributionLabel(key: string, kind: DistributionKind, t: TFunction) {
  if (kind === "type") return key === "workflow" ? t("工作流") : t("Agent")
  if (kind === "source") {
    if (key === "automation") return t("自动化")
    if (key === "public") return t("公开访问")
    if (key === "api") return t("API")
    return t("控制台")
  }
  const label = STATUS_LABELS[key]
  return label ? t(label) : key
}

/**
 * Identifies the distribution item with the highest count.
 *
 * @param items - The distribution items to compare
 * @returns The item with the highest count, or `null` when the collection is empty
 */
function dominantItem(items: DistributionItem[]) {
  return items.reduce<DistributionItem | null>(
    (current, item) =>
      current === null || item.count > current.count ? item : current,
    null
  )
}

/**
 * Selects the palette color for a distribution item.
 *
 * @param kind - The distribution category, such as type, source, or status
 * @param key - The item's category key
 * @param index - The item's position, used to select a fallback status color
 * @returns The color assigned to the distribution item
 */
function itemColor(kind: DistributionKind, key: string, index: number) {
  if (kind === "type") {
    return TYPE_COLORS[key] ?? FALLBACK_COLORS[index % FALLBACK_COLORS.length]
  }
  if (kind === "source") {
    return SOURCE_COLORS[key] ?? FALLBACK_COLORS[index % FALLBACK_COLORS.length]
  }
  return STATUS_COLORS[key] ?? FALLBACK_COLORS[index % FALLBACK_COLORS.length]
}

/**
 * Renders a donut chart with localized labels, percentages, and a summary value for distribution data.
 *
 * @param items - Distribution categories and their counts
 * @param kind - Distribution category type used for labels and colors
 * @param locale - Locale used to format numbers and percentages
 */
function DonutChart({
  items,
  kind,
  locale,
}: {
  items: DistributionItem[]
  kind: DistributionKind
  locale: string
}) {
  const { t } = useLanguage()
  const total = distributionTotal(items)
  const dominant = dominantItem(items)
  const successCount =
    items.find((item) => item.key === "succeeded")?.count ?? 0
  const centerItem = kind === "status" ? null : dominant
  const centerLabel =
    kind === "status"
      ? t("成功率")
      : centerItem
        ? distributionLabel(centerItem.key, kind, t)
        : t("暂无数据")
  const centerValue =
    total && (kind === "status" || centerItem)
      ? `${Math.round(
          ((kind === "status" ? successCount : (centerItem?.count ?? 0)) /
            total) *
            100
        )}%`
      : "—"

  const chartData = items.map((item, index) => ({
    key: item.key,
    count: item.count,
    fill: itemColor(kind, item.key, index),
  }))

  const chartConfig = Object.fromEntries(
    items.map((item, index) => [
      item.key,
      {
        label: distributionLabel(item.key, kind, t),
        color: itemColor(kind, item.key, index),
      },
    ])
  ) satisfies ChartConfig

  return (
    <div className="grid min-w-0 grid-cols-[6rem_minmax(0,1fr)] items-center gap-4">
      {items.length ? (
        <ChartContainer
          config={chartConfig}
          className="aspect-square size-24 shrink-0"
        >
          <PieChart accessibilityLayer>
            <ChartTooltip
              cursor={false}
              content={
                <ChartTooltipContent
                  hideLabel
                  formatter={(value, name, item) => {
                    const label =
                      chartConfig[String(name)]?.label ?? String(name ?? "")
                    const count = Number(value ?? 0)
                    return (
                      <div className="flex flex-1 items-center justify-between gap-4 leading-none">
                        <span className="flex items-center gap-1.5 text-muted-foreground">
                          <span
                            className="h-2.5 w-2.5 shrink-0 rounded-[2px]"
                            style={{
                              backgroundColor: item.payload?.fill ?? item.color,
                            }}
                          />
                          {label}
                        </span>
                        <span className="font-mono font-medium text-foreground tabular-nums">
                          {formatNumber(count, locale)} (
                          {formatPercent(total ? count / total : null, locale)})
                        </span>
                      </div>
                    )
                  }}
                />
              }
            />
            <Pie
              data={chartData}
              dataKey="count"
              nameKey="key"
              innerRadius={30}
              outerRadius={42}
              paddingAngle={items.length > 1 ? 1.5 : 0}
              stroke="var(--card)"
              strokeWidth={2}
              isAnimationActive={false}
            >
              <Label
                content={({ viewBox }) => {
                  if (viewBox && "cx" in viewBox && "cy" in viewBox) {
                    return (
                      <text
                        x={viewBox.cx}
                        y={viewBox.cy}
                        textAnchor="middle"
                        dominantBaseline="middle"
                      >
                        <tspan
                          x={viewBox.cx}
                          y={(viewBox.cy ?? 0) - 4}
                          className="fill-foreground text-sm font-semibold tabular-nums"
                        >
                          {centerValue}
                        </tspan>
                        <tspan
                          x={viewBox.cx}
                          y={(viewBox.cy ?? 0) + 10}
                          className="fill-muted-foreground text-[10px]"
                        >
                          {centerLabel}
                        </tspan>
                      </text>
                    )
                  }
                  return <g />
                }}
              />
            </Pie>
          </PieChart>
        </ChartContainer>
      ) : (
        <div className="flex size-24 shrink-0 items-center justify-center rounded-full border-2 border-dashed border-muted text-xs text-muted-foreground">
          {t("暂无数据")}
        </div>
      )}
      <ul className="min-w-0 space-y-0.5 text-xs">
        {items.length ? (
          items.map((item, index) => {
            const label = distributionLabel(item.key, kind, t)
            return (
              <li
                key={item.key}
                className="flex min-w-0 items-center justify-between gap-3 rounded-md px-2 py-1 transition-colors hover:bg-muted/50"
              >
                <span className="flex min-w-0 items-center gap-2">
                  <span
                    aria-hidden="true"
                    className="size-2.5 shrink-0 rounded-[3px]"
                    style={{
                      backgroundColor: itemColor(kind, item.key, index),
                    }}
                  />
                  <span className="truncate" title={label}>
                    {label}
                  </span>
                </span>
                <span className="flex shrink-0 items-center gap-2 tabular-nums">
                  <span className="font-medium text-foreground">
                    {formatNumber(item.count, locale)}
                  </span>
                  <span className="w-11 text-right text-muted-foreground">
                    {formatPercent(total ? item.count / total : null, locale)}
                  </span>
                </span>
              </li>
            )
          })
        ) : (
          <li className="py-1 text-muted-foreground">{t("暂无数据")}</li>
        )}
      </ul>
    </div>
  )
}

/**
 * Displays run distributions by type, access source, and status.
 *
 * @param data - Distribution data for run types, access sources, and statuses
 * @param locale - Locale used to format chart labels and values
 */
export function RunDistributionPanel({
  data,
  locale,
}: {
  data: WorkspaceAnalytics["distributions"]
  locale: string
}) {
  const { t } = useLanguage()
  return (
    <Card className="min-w-0 gap-0 overflow-hidden rounded-xl py-0 shadow-xs">
      <CardHeader className="border-b px-6 py-4">
        <CardTitle>{t("运行分布")}</CardTitle>
        <CardDescription>{t("按类型、来源和状态查看运行构成")}</CardDescription>
      </CardHeader>
      <CardContent className="grid min-w-0 divide-y px-0 lg:grid-cols-3 lg:divide-x lg:divide-y-0">
        <section className="min-w-0 px-5 py-3.5">
          <h3 className="mb-2.5 text-sm font-medium">{t("运行类型")}</h3>
          <DonutChart items={data.run_types} kind="type" locale={locale} />
        </section>
        <section className="min-w-0 px-5 py-3.5">
          <h3 className="mb-2.5 text-sm font-medium">{t("访问来源")}</h3>
          <DonutChart
            items={data.access_sources}
            kind="source"
            locale={locale}
          />
        </section>
        <section className="min-w-0 px-5 py-3.5">
          <h3 className="mb-2.5 text-sm font-medium">{t("运行状态")}</h3>
          <DonutChart items={data.statuses} kind="status" locale={locale} />
        </section>
      </CardContent>
    </Card>
  )
}

type RankingView = "applications" | "users" | "teams"

/**
 * Displays usage rankings for applications and workflows, users, or teams.
 *
 * @param data - Ranking data for each available view
 * @param locale - Locale used to format counts, token totals, and percentages
 */
export function AnalyticsRankingPanel({
  data,
  locale,
}: {
  data: WorkspaceAnalytics["rankings"]
  locale: string
}) {
  const { t } = useLanguage()
  const [view, setView] = React.useState<RankingView>("applications")
  const options: Array<{ value: RankingView; label: string }> = [
    { value: "applications", label: t("应用 / 工作流") },
    { value: "users", label: t("用户") },
    { value: "teams", label: t("团队") },
  ]

  return (
    <Card className="min-w-0 gap-4 rounded-xl py-5 shadow-xs">
      <CardHeader className="gap-3 px-5">
        <CardTitle>{t("使用排行")}</CardTitle>
        <div
          className="flex max-w-full gap-1 overflow-x-auto pb-1"
          role="group"
          aria-label={t("使用排行")}
        >
          {options.map((option) => (
            <Button
              key={option.value}
              size="sm"
              variant={view === option.value ? "secondary" : "outline"}
              aria-pressed={view === option.value}
              onClick={() => setView(option.value)}
            >
              {option.label}
            </Button>
          ))}
        </div>
      </CardHeader>
      <CardContent className="min-w-0 px-5">
        {view === "applications" ? (
          <div className="space-y-3">
            {data.applications.map((item, index) => (
              <div
                key={item.application_id}
                className="grid min-w-0 gap-1 rounded-lg border px-3 py-2 text-sm sm:grid-cols-[2rem_minmax(0,1fr)_auto_auto_auto] sm:items-center sm:gap-3"
              >
                <span className="text-muted-foreground">{index + 1}</span>
                <span className="flex min-w-0 items-center gap-2 font-medium">
                  {item.app_type === "workflow" ? (
                    <WorkflowIcon
                      aria-hidden="true"
                      className="size-4 shrink-0 text-muted-foreground"
                    />
                  ) : (
                    <BotIcon
                      aria-hidden="true"
                      className="size-4 shrink-0 text-muted-foreground"
                    />
                  )}
                  <span className="truncate">{item.name}</span>
                </span>
                <span className="text-muted-foreground">
                  {t("运行 {runs} 次", {
                    runs: formatNumber(item.run_count, locale),
                  })}
                </span>
                <span className="tabular-nums">
                  {t("Tokens {tokens}", {
                    tokens: formatTokenCount(item.total_tokens),
                  })}
                </span>
                <span className="text-muted-foreground tabular-nums">
                  {formatPercent(item.success_rate, locale)}
                </span>
              </div>
            ))}
            <div className="flex flex-col gap-1 rounded-lg border bg-muted/30 px-3 py-2 text-sm sm:flex-row sm:items-center sm:justify-between">
              <span>{t("公开/API 调用")}</span>
              <span className="text-muted-foreground">
                {t("运行 {runs} 次，Tokens {tokens}", {
                  runs: formatNumber(data.anonymous.run_count, locale),
                  tokens: formatTokenCount(data.anonymous.total_tokens),
                })}
              </span>
            </div>
          </div>
        ) : view === "users" ? (
          <div className="space-y-3">
            {data.users.map((item, index) => (
              <div
                key={item.user_id}
                className="grid min-w-0 gap-1 rounded-lg border px-3 py-2 text-sm sm:grid-cols-[2rem_minmax(0,1fr)_auto_auto] sm:items-center sm:gap-3"
              >
                <span className="text-muted-foreground">{index + 1}</span>
                <span className="truncate font-medium">{item.name}</span>
                <span className="text-muted-foreground">
                  {t("运行 {runs} 次", {
                    runs: formatNumber(item.run_count, locale),
                  })}
                </span>
                <span className="tabular-nums">
                  {t("Tokens {tokens}", {
                    tokens: formatTokenCount(item.total_tokens),
                  })}
                </span>
              </div>
            ))}
          </div>
        ) : (
          <div className="space-y-3">
            {data.teams.length ? (
              data.teams.map((item, index) => (
                <div
                  key={item.team_id}
                  className="grid min-w-0 gap-1 rounded-lg border px-3 py-2 text-sm sm:grid-cols-[2rem_minmax(0,1fr)_auto_auto] sm:items-center sm:gap-3"
                >
                  <span className="text-muted-foreground">{index + 1}</span>
                  <span className="flex min-w-0 items-center gap-2 font-medium">
                    <Building2Icon
                      aria-hidden="true"
                      className="size-4 shrink-0 text-muted-foreground"
                    />
                    <span className="truncate">{item.name}</span>
                  </span>
                  <span className="text-muted-foreground">
                    {t("单日最高 {runs}", {
                      runs: formatNumber(item.peak_daily_runs, locale),
                    })}
                  </span>
                  <span className="tabular-nums">
                    {t("运行 {runs} 次", {
                      runs: formatNumber(item.run_count, locale),
                    })}
                  </span>
                </div>
              ))
            ) : (
              <p className="text-sm text-muted-foreground">
                {t("暂无团队使用数据")}
              </p>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  )
}

/**
 * Displays frequently asked workspace questions with occurrence counts.
 *
 * @param items - Questions that meet the reporting threshold
 * @param locale - Locale used to format counts
 */
export function FrequentQuestionsPanel({
  items,
  locale,
}: {
  items: WorkspaceAnalytics["frequent_questions"]
  locale: string
}) {
  const { t } = useLanguage()
  const [visibleCount, setVisibleCount] = React.useState(10)
  const visibleItems = items.slice(0, visibleCount)

  return (
    <Card className="min-w-0 gap-4 rounded-xl py-5 shadow-xs">
      <CardHeader className="gap-1 px-5">
        <CardTitle className="flex items-center gap-2">
          <MessageCircleQuestionIcon aria-hidden="true" className="size-4" />
          {t("高频问题")}
        </CardTitle>
        <CardDescription>
          {t("仅展示当前工作空间内出现至少 3 次的问题")}
        </CardDescription>
      </CardHeader>
      <CardContent
        role="region"
        aria-label={t("高频问题")}
        className="max-h-[37.5rem] min-w-0 overflow-y-auto overscroll-contain px-5 max-sm:max-h-[60svh]"
        onScroll={(event) => {
          const target = event.currentTarget
          if (
            visibleCount < items.length &&
            target.scrollTop + target.clientHeight >= target.scrollHeight - 24
          ) {
            setVisibleCount((count) => Math.min(count + 10, items.length))
          }
        }}
      >
        {visibleItems.length ? (
          <div className="space-y-2.5">
            {visibleItems.map((item) => (
              <div
                key={item.question}
                className="flex min-w-0 items-center justify-between gap-3 rounded-lg border bg-muted/15 px-3.5 py-2.5 text-sm transition-colors hover:bg-muted/35"
              >
                <p className="min-w-0 flex-1 truncate" title={item.question}>
                  {item.question}
                </p>
                <Badge
                  variant="secondary"
                  className="min-w-7 shrink-0 justify-center px-2 py-0.5 font-semibold tabular-nums"
                >
                  {formatNumber(item.count, locale)}
                </Badge>
              </div>
            ))}
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">
            {t("暂无达到阈值的高频问题")}
          </p>
        )}
      </CardContent>
    </Card>
  )
}
