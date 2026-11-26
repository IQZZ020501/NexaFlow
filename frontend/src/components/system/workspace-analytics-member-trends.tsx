"use client"

import * as React from "react"
import { CheckIcon, ChevronDownIcon, UsersIcon } from "lucide-react"
import { Area, AreaChart, XAxis, YAxis } from "recharts"

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
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { useLanguage } from "@/contexts/language-provider"
import type { WorkspaceAnalytics } from "@/lib/api/analytics"
import { formatTokenCount } from "@/lib/display"
import { cn } from "@/lib/utils"

type MemberTrendMetric = "runs" | "total_tokens"

const TOP_PRESETS = [5, 10, 20] as const
type TopPreset = (typeof TOP_PRESETS)[number]

const MAX_SELECTED_MEMBERS = 20
const PRIMARY_SERIES_STYLES = [
  { color: "var(--primary)", fillOpacity: 0.14 },
  {
    color: "color-mix(in oklch, var(--primary) 72%, var(--background))",
    fillOpacity: 0.1,
  },
  {
    color: "color-mix(in oklch, var(--primary) 54%, var(--background))",
    fillOpacity: 0.07,
  },
  {
    color: "color-mix(in oklch, var(--primary) 40%, var(--background))",
    fillOpacity: 0.05,
  },
  {
    color: "color-mix(in oklch, var(--primary) 28%, var(--background))",
    fillOpacity: 0.03,
  },
] as const
const EXTENDED_SERIES_HUES = [255, 175, 295, 70, 15, 210, 145, 330] as const

function getMemberSeriesStyle(index: number) {
  if (index < PRIMARY_SERIES_STYLES.length) {
    return PRIMARY_SERIES_STYLES[index]
  }
  const hue =
    EXTENDED_SERIES_HUES[(index - PRIMARY_SERIES_STYLES.length) % EXTENDED_SERIES_HUES.length]
  return {
    color: `color-mix(in oklch, var(--primary) 42%, oklch(0.62 0.09 ${hue}))`,
    fillOpacity: 0.02,
  }
}

function sortByMetric(
  series: WorkspaceAnalytics["member_trends"],
  metric: MemberTrendMetric
) {
  return [...series].sort((a, b) =>
    metric === "total_tokens"
      ? b.total_tokens - a.total_tokens || b.total_runs - a.total_runs
      : b.total_runs - a.total_runs || b.total_tokens - a.total_tokens
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

/**
 * Displays a multi-series daily usage comparison across workspace members
 * with Top 5 / 10 / 20 presets and custom member filtering.
 *
 * @param series - Per-member daily usage series ordered by activity
 * @param locale - Locale used to format numbers in axes, tooltips, and menus
 */
export const MemberComparisonChart = React.memo(function MemberComparisonChart({
  series,
  locale,
}: {
  series: WorkspaceAnalytics["member_trends"]
  locale: string
}) {
  const { t } = useLanguage()
  const [metric, setMetric] = React.useState<MemberTrendMetric>("runs")
  const [activePreset, setActivePreset] = React.useState<TopPreset | null>(5)
  const [selectedIds, setSelectedIds] = React.useState<string[]>(() =>
    sortByMetric(series, "runs")
      .slice(0, 5)
      .map((member) => member.user_id)
  )

  const sortedSeries = React.useMemo(
    () => sortByMetric(series, metric),
    [metric, series]
  )

  const selectedSet = React.useMemo(() => new Set(selectedIds), [selectedIds])
  const selectedMembers = React.useMemo(
    () => sortedSeries.filter((member) => selectedSet.has(member.user_id)),
    [selectedSet, sortedSeries]
  )
  const maxSelectable = Math.min(MAX_SELECTED_MEMBERS, series.length)

  const formatMetricValue = React.useCallback(
    (value: number) =>
      metric === "total_tokens"
        ? formatTokenCount(value)
        : formatNumber(value, locale),
    [locale, metric]
  )

  const formatAxisValue = (value: number) =>
    metric === "total_tokens"
      ? formatTokenCount(value)
      : formatCompactNumber(value, locale)

  const handleMetricChange = (nextMetric: MemberTrendMetric) => {
    setMetric(nextMetric)
    if (activePreset !== null) {
      setSelectedIds(
        sortByMetric(series, nextMetric)
          .slice(0, activePreset)
          .map((member) => member.user_id)
      )
    }
  }

  const applyPreset = (limit: TopPreset) => {
    setActivePreset(limit)
    setSelectedIds(
      sortedSeries.slice(0, limit).map((member) => member.user_id)
    )
  }

  const toggleMember = (userId: string) => {
    setActivePreset(null)
    setSelectedIds((current) => {
      if (current.includes(userId)) {
        return current.length > 1
          ? current.filter((id) => id !== userId)
          : current
      }
      if (current.length >= MAX_SELECTED_MEMBERS) {
        return current
      }
      return [...current, userId]
    })
  }

  const memberAssignments = React.useMemo(
    () =>
      selectedMembers.map((member, index) => {
        const style = getMemberSeriesStyle(index)
        return {
          member,
          key: `m${index}`,
          color: style.color,
          fillOpacity: style.fillOpacity,
        }
      }),
    [selectedMembers]
  )

  const assignmentByUserId = React.useMemo(
    () =>
      new Map(
        memberAssignments.map((assignment) => [
          assignment.member.user_id,
          assignment,
        ])
      ),
    [memberAssignments]
  )

  const chartConfig = React.useMemo(
    () =>
      Object.fromEntries(
        memberAssignments.map((assignment) => [
          assignment.key,
          {
            label: assignment.member.name,
            color: assignment.color,
          },
        ])
      ) satisfies ChartConfig,
    [memberAssignments]
  )

  const chartData = React.useMemo(() => {
    const templateDays = selectedMembers[0]?.daily ?? []
    return templateDays.map((dayPoint, dayIndex) => {
      const row: Record<string, string | number> = { date: dayPoint.date }
      for (const assignment of memberAssignments) {
        row[assignment.key] =
          assignment.member.daily[dayIndex]?.[metric] ?? 0
      }
      return row
    })
  }, [memberAssignments, metric, selectedMembers])

  const description = t(
    "对比工作空间成员按自然日的运行次数与 Token 消耗（支持 Top 5 / 10 / 20）"
  )

  return (
    <Card className="min-w-0 gap-4 rounded-xl py-5 shadow-xs">
      <CardHeader className="flex flex-col gap-3 px-6 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0 space-y-1">
          <CardTitle>{t("成员每日使用对比")}</CardTitle>
          <CardDescription>{description}</CardDescription>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <div
            className="inline-flex items-center rounded-lg bg-muted p-0.5"
            role="group"
            aria-label={t("指标切换")}
          >
            <button
              type="button"
              aria-pressed={metric === "runs"}
              onClick={() => handleMetricChange("runs")}
              className={cn(
                "cursor-pointer rounded-md px-2.5 py-1 text-xs font-medium transition-colors",
                metric === "runs"
                  ? "bg-background text-foreground shadow-xs"
                  : "text-muted-foreground hover:text-foreground"
              )}
            >
              {t("运行次数")}
            </button>
            <button
              type="button"
              aria-pressed={metric === "total_tokens"}
              onClick={() => handleMetricChange("total_tokens")}
              className={cn(
                "cursor-pointer rounded-md px-2.5 py-1 text-xs font-medium transition-colors",
                metric === "total_tokens"
                  ? "bg-background text-foreground shadow-xs"
                  : "text-muted-foreground hover:text-foreground"
              )}
            >
              {t("Token 消耗")}
            </button>
          </div>
          {series.length > 0 ? (
            <>
              <div
                className="inline-flex items-center rounded-lg bg-muted p-0.5"
                role="group"
                aria-label={t("展示人数")}
              >
                {TOP_PRESETS.map((limit) => (
                  <button
                    key={limit}
                    type="button"
                    aria-pressed={activePreset === limit}
                    onClick={() => applyPreset(limit)}
                    className={cn(
                      "cursor-pointer rounded-md px-2.5 py-1 text-xs font-medium transition-colors",
                      activePreset === limit
                        ? "bg-background text-foreground shadow-xs"
                        : "text-muted-foreground hover:text-foreground"
                    )}
                  >
                    {`Top ${limit}`}
                  </button>
                ))}
              </div>
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button
                    size="sm"
                    variant="outline"
                    aria-label={t("选择成员 ({count}/{max})", {
                      count: selectedMembers.length,
                      max: maxSelectable,
                    })}
                  >
                    <UsersIcon aria-hidden="true" className="size-4" />
                    <span>
                      {t("选择成员 ({count}/{max})", {
                        count: selectedMembers.length,
                        max: maxSelectable,
                      })}
                    </span>
                    <ChevronDownIcon
                      aria-hidden="true"
                      className="size-4 text-muted-foreground"
                    />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent
                  align="end"
                  className="max-h-72 w-64 overflow-y-auto"
                >
                  <DropdownMenuLabel>{t("成员每日使用对比")}</DropdownMenuLabel>
                  <DropdownMenuSeparator />
                  {sortedSeries.map((member) => {
                    const assignment = assignmentByUserId.get(member.user_id)
                    const isSelected = Boolean(assignment)
                    const isDisabled =
                      !isSelected && selectedIds.length >= MAX_SELECTED_MEMBERS
                    const totalValue =
                      metric === "total_tokens"
                        ? member.total_tokens
                        : member.total_runs
                    return (
                      <DropdownMenuItem
                        key={member.user_id}
                        disabled={isDisabled}
                        onSelect={(event) => {
                          event.preventDefault()
                          toggleMember(member.user_id)
                        }}
                        className="flex items-center justify-between gap-2"
                      >
                        <span className="flex min-w-0 items-center gap-2">
                          <span
                            aria-hidden="true"
                            className="flex size-4 shrink-0 items-center justify-center rounded-[4px] border border-input"
                          >
                            {isSelected ? (
                              <CheckIcon className="size-3" />
                            ) : null}
                          </span>
                          <span
                            aria-hidden="true"
                            className="size-2 shrink-0 rounded-[2px]"
                            style={{
                              backgroundColor:
                                assignment?.color ?? "var(--muted-foreground)",
                              opacity: isSelected ? 1 : 0.35,
                            }}
                          />
                          <span className="truncate">{member.name}</span>
                        </span>
                        <span className="shrink-0 text-xs text-muted-foreground tabular-nums">
                          {formatMetricValue(totalValue)}
                        </span>
                      </DropdownMenuItem>
                    )
                  })}
                </DropdownMenuContent>
              </DropdownMenu>
            </>
          ) : null}
        </div>
      </CardHeader>
      <CardContent className="min-w-0 px-2 sm:px-6">
        {selectedMembers.length === 0 ? (
          <p className="py-12 text-center text-sm text-muted-foreground">
            {t("所选范围内暂无成员使用数据")}
          </p>
        ) : (
          <>
            <ChartContainer
              config={chartConfig}
              className="aspect-auto h-[300px] w-full"
            >
              <AreaChart
                data={chartData}
                accessibilityLayer
                desc={t("成员每日使用对比")}
              >
                <XAxis
                  dataKey="date"
                  fontSize={12}
                  tickLine={false}
                  axisLine={false}
                  minTickGap={28}
                  tickFormatter={(value: string) => value.slice(5)}
                />
                <YAxis
                  allowDecimals={false}
                  fontSize={12}
                  tickLine={false}
                  axisLine={false}
                  width={46}
                  tickFormatter={(value: number) =>
                    formatAxisValue(Number(value))
                  }
                />
                <ChartTooltip
                  itemSorter={(item) => -Number(item.value ?? 0)}
                  content={
                    <ChartTooltipContent
                      formatter={(value, name, item) => {
                        const key = String(name ?? "")
                        const memberLabel = chartConfig[key]?.label ?? key
                        return (
                          <div className="flex flex-1 items-center justify-between gap-4 leading-none">
                            <span className="flex items-center gap-1.5 text-muted-foreground">
                              <span
                                className="h-2.5 w-2.5 shrink-0 rounded-[2px]"
                                style={{ backgroundColor: item.color }}
                              />
                              {memberLabel}
                            </span>
                            <span className="font-mono font-medium text-foreground tabular-nums">
                              {formatMetricValue(Number(value ?? 0))}
                            </span>
                          </div>
                        )
                      }}
                    />
                  }
                />
                {memberAssignments.map((assignment) => (
                  <Area
                    key={assignment.key}
                    type="monotone"
                    dataKey={assignment.key}
                    stroke={`var(--color-${assignment.key})`}
                    fill={`var(--color-${assignment.key})`}
                    fillOpacity={assignment.fillOpacity}
                    isAnimationActive={false}
                  />
                ))}
              </AreaChart>
            </ChartContainer>
            <div className="mt-3 flex max-h-24 flex-wrap items-center justify-center gap-x-5 gap-y-1.5 overflow-y-auto text-xs">
              {memberAssignments.map((assignment) => {
                const totalValue =
                  metric === "total_tokens"
                    ? assignment.member.total_tokens
                    : assignment.member.total_runs
                return (
                  <div
                    key={assignment.member.user_id}
                    className="flex items-center gap-1.5"
                  >
                    <span
                      aria-hidden="true"
                      className="h-2 w-2 shrink-0 rounded-[2px]"
                      style={{ backgroundColor: assignment.color }}
                    />
                    <span className="max-w-36 truncate font-medium">
                      {assignment.member.name}
                    </span>
                    <span className="text-muted-foreground tabular-nums">
                      {formatMetricValue(totalValue)}
                    </span>
                  </div>
                )
              })}
            </div>
          </>
        )}
      </CardContent>
    </Card>
  )
})
