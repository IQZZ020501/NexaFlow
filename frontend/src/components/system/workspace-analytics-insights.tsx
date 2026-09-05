import * as React from "react"
import {
  BotIcon,
  Building2Icon,
  MessageCircleQuestionIcon,
  WorkflowIcon,
} from "lucide-react"
import {
  Cell,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  type TooltipContentProps,
} from "recharts"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { useLanguage } from "@/contexts/language-provider"
import type { TFunction, TranslationKey } from "@/i18n"
import type { WorkspaceAnalytics } from "@/lib/api/analytics"
import { APP_TIME_ZONE } from "@/lib/display"
import {
  distributionTotal,
} from "@/components/system/workspace-analytics-metrics"

type DistributionKind = "type" | "source" | "status"
type DistributionItem = { key: string; count: number }

const COLORS = {
  type: [
    "color-mix(in oklch, var(--primary) 65%, oklch(0.62 0.14 245))",
    "color-mix(in oklch, var(--primary) 65%, oklch(0.62 0.12 300))",
  ],
  source: [
    "color-mix(in oklch, var(--primary) 55%, oklch(0.62 0.13 185))",
    "color-mix(in oklch, var(--primary) 55%, oklch(0.68 0.13 65))",
    "var(--muted-foreground)",
  ],
  status: [
    "color-mix(in oklch, var(--primary) 45%, oklch(0.62 0.13 145))",
    "var(--destructive)",
    "var(--muted-foreground)",
  ],
} satisfies Record<DistributionKind, string[]>

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
function formatNumber(value: number, locale: string) {
  return new Intl.NumberFormat(locale).format(value)
}

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
 * Formats a date-time value for the specified locale.
 *
 * @param value - The date-time value to format
 * @param locale - The locale used for date and time formatting
 * @returns The localized date and time string
 */
function formatDateTime(value: string, locale: string) {
  return new Intl.DateTimeFormat(locale, {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: APP_TIME_ZONE,
  }).format(new Date(value))
}

/**
 * Resolves a localized label for a distribution item.
 *
 * @param key - The distribution item identifier
 * @param kind - The distribution category
 * @returns The localized label, or the original key when no status label is defined
 */
function distributionLabel(
  key: string,
  kind: DistributionKind,
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
    return key === "workflow" ? COLORS.type[1] : COLORS.type[0]
  }
  if (kind === "source") {
    if (key === "api") return COLORS.source[1]
    if (key === "public") return COLORS.source[2]
    return COLORS.source[0]
  }
  if (key === "failed") return COLORS.status[1]
  if (key === "cancelled") return COLORS.status[2]
  if (key === "succeeded") return COLORS.status[0]
  return COLORS.status[index % COLORS.status.length]
}

function DistributionTooltip({
  active,
  payload,
  items,
  kind,
  locale,
}: Pick<TooltipContentProps, "active" | "payload"> & {
  items: DistributionItem[]
  kind: DistributionKind
  locale: string
}) {
  const { t } = useLanguage()
  const item = payload[0]?.payload as DistributionItem | undefined
  if (!active || !item) return null
  const total = distributionTotal(items)
  const index = items.findIndex((candidate) => candidate.key === item.key)

  return (
    <div className="flex items-center gap-2 whitespace-nowrap rounded-md border bg-popover px-2.5 py-1.5 text-xs text-popover-foreground shadow-lg">
      <span
        aria-hidden="true"
        className="size-2 rounded-full"
        style={{ backgroundColor: itemColor(kind, item.key, index) }}
      />
      <span className="font-medium">{distributionLabel(item.key, kind, t)}</span>
      <span className="tabular-nums">{formatNumber(item.count, locale)}</span>
      <span className="tabular-nums text-muted-foreground">
        {formatPercent(total ? item.count / total : null, locale)}
      </span>
    </div>
  )
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
  const successCount = items.find((item) => item.key === "succeeded")?.count ?? 0
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
          ((kind === "status" ? successCount : centerItem?.count ?? 0) / total) *
            100
        )}%`
      : "—"

  return (
    <div className="grid min-w-0 grid-cols-[7rem_minmax(0,1fr)] items-center gap-4">
      <div className="relative size-28 shrink-0">
        {items.length ? (
          <ResponsiveContainer width="100%" height="100%">
            <PieChart accessibilityLayer>
              <Pie
                data={items}
                dataKey="count"
                nameKey="key"
                rootTabIndex={-1}
                className="outline-none"
                innerRadius="66%"
                outerRadius="90%"
                paddingAngle={items.length > 1 ? 3 : 0}
                cornerRadius={3}
                stroke="var(--card)"
                strokeWidth={2}
                isAnimationActive={false}
              >
                {items.map((item, index) => (
                  <Cell
                    key={item.key}
                    fill={itemColor(kind, item.key, index)}
                  />
                ))}
              </Pie>
              <Tooltip
                allowEscapeViewBox={{ x: false, y: true }}
                cursor={false}
                offset={10}
                reverseDirection={{ x: false, y: false }}
                wrapperStyle={{
                  outline: "none",
                  pointerEvents: "none",
                  zIndex: 20,
                }}
                content={({ active, payload }) => (
                  <DistributionTooltip
                    active={active}
                    payload={payload}
                    items={items}
                    kind={kind}
                    locale={locale}
                  />
                )}
              />
            </PieChart>
          </ResponsiveContainer>
        ) : null}
        <div className="pointer-events-none absolute inset-0 grid place-items-center">
          <strong className="text-xl font-semibold leading-none tabular-nums">
            {centerValue}
          </strong>
          <span className="absolute left-1/2 top-1/2 mt-3 flex h-6 w-20 -translate-x-1/2 items-start justify-center text-center text-[10px] leading-3 text-muted-foreground">
            {centerLabel}
          </span>
        </div>
      </div>
      <ul className="min-w-0 divide-y text-xs">
        {items.length ? (
          items.map((item, index) => {
            const label = distributionLabel(item.key, kind, t)
            return (
              <li
                key={item.key}
                className="flex min-w-0 items-center justify-between gap-3 py-2 first:pt-0 last:pb-0"
              >
                <span className="flex min-w-0 items-center gap-2">
                  <span
                    aria-hidden="true"
                    className="size-2 shrink-0 rounded-full"
                    style={{ backgroundColor: itemColor(kind, item.key, index) }}
                  />
                  <span className="truncate" title={label}>
                    {label}
                  </span>
                </span>
                <span className="flex shrink-0 items-center gap-2 tabular-nums">
                  <span className="font-medium text-foreground">
                    {formatNumber(item.count, locale)}
                  </span>
                  <span className="w-10 text-right text-muted-foreground">
                    {formatPercent(total ? item.count / total : null, locale)}
                  </span>
                </span>
              </li>
            )
          })
        ) : (
          <li className="text-muted-foreground">{t("暂无数据")}</li>
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
    <Card className="min-w-0 gap-0 py-0 shadow-none">
      <CardHeader className="border-b px-5 py-5">
        <CardTitle>{t("运行分布")}</CardTitle>
        <CardDescription>{t("按类型、来源和状态查看运行构成")}</CardDescription>
      </CardHeader>
      <CardContent className="grid min-w-0 divide-y px-0 lg:grid-cols-3 lg:divide-x lg:divide-y-0">
        <section className="min-w-0 px-5 py-4">
          <h3 className="mb-4 text-sm font-medium">{t("运行类型")}</h3>
          <DonutChart items={data.run_types} kind="type" locale={locale} />
        </section>
        <section className="min-w-0 px-5 py-4">
          <h3 className="mb-4 text-sm font-medium">{t("访问来源")}</h3>
          <DonutChart items={data.access_sources} kind="source" locale={locale} />
        </section>
        <section className="min-w-0 px-5 py-4">
          <h3 className="mb-4 text-sm font-medium">{t("运行状态")}</h3>
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
    <Card className="min-w-0 gap-4 py-5 shadow-none">
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
                    <WorkflowIcon aria-hidden="true" className="size-4 shrink-0 text-muted-foreground" />
                  ) : (
                    <BotIcon aria-hidden="true" className="size-4 shrink-0 text-muted-foreground" />
                  )}
                  <span className="truncate">{item.name}</span>
                </span>
                <span className="text-muted-foreground">
                  {t("运行 {runs} 次", { runs: formatNumber(item.run_count, locale) })}
                </span>
                <span className="tabular-nums">
                  {t("Tokens {tokens}", {
                    tokens: formatNumber(item.total_tokens, locale),
                  })}
                </span>
                <span className="tabular-nums text-muted-foreground">
                  {formatPercent(item.success_rate, locale)}
                </span>
              </div>
            ))}
            <div className="flex flex-col gap-1 rounded-lg border bg-muted/30 px-3 py-2 text-sm sm:flex-row sm:items-center sm:justify-between">
              <span>{t("公开/API 调用")}</span>
              <span className="text-muted-foreground">
                {t("运行 {runs} 次，Tokens {tokens}", {
                  runs: formatNumber(data.anonymous.run_count, locale),
                  tokens: formatNumber(data.anonymous.total_tokens, locale),
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
                  {t("运行 {runs} 次", { runs: formatNumber(item.run_count, locale) })}
                </span>
                <span className="tabular-nums">
                  {t("Tokens {tokens}", {
                    tokens: formatNumber(item.total_tokens, locale),
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
                    <Building2Icon aria-hidden="true" className="size-4 shrink-0 text-muted-foreground" />
                    <span className="truncate">{item.name}</span>
                  </span>
                  <span className="text-muted-foreground">
                    {t("单日最高 {runs}", {
                      runs: formatNumber(item.peak_daily_runs, locale),
                    })}
                  </span>
                  <span className="tabular-nums">
                    {t("运行 {runs} 次", { runs: formatNumber(item.run_count, locale) })}
                  </span>
                </div>
              ))
            ) : (
              <p className="text-sm text-muted-foreground">{t("暂无团队使用数据")}</p>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  )
}

/**
 * Displays frequently asked workspace questions with occurrence counts and latest occurrence times.
 *
 * @param items - Questions that meet the reporting threshold
 * @param locale - Locale used to format counts and timestamps
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
    <Card className="min-w-0 gap-4 py-5 shadow-none">
      <CardHeader className="gap-1 px-5">
        <CardTitle className="flex items-center gap-2">
          <MessageCircleQuestionIcon aria-hidden="true" className="size-4" />
          {t("高频问题")}
        </CardTitle>
        <CardDescription>{t("仅展示当前工作空间内出现至少 3 次的问题")}</CardDescription>
      </CardHeader>
      <CardContent
        role="region"
        aria-label={t("高频问题")}
        className="max-h-[37.5rem] min-w-0 overflow-y-auto px-5"
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
          <div className="space-y-2">
            {visibleItems.map((item) => (
              <div
                key={item.question}
                className="flex min-w-0 flex-col gap-2 rounded-lg border px-3 py-2 text-sm sm:flex-row sm:items-start sm:justify-between"
              >
                <p className="min-w-0 whitespace-normal break-words">{item.question}</p>
                <div className="flex shrink-0 items-center gap-2 sm:flex-col sm:items-end sm:gap-1">
                  <Badge variant="secondary">{formatNumber(item.count, locale)}</Badge>
                  <time className="text-xs text-muted-foreground">
                    {formatDateTime(item.latest_at, locale)}
                  </time>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">{t("暂无达到阈值的高频问题")}</p>
        )}
      </CardContent>
    </Card>
  )
}
