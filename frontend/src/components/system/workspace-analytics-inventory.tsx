"use client"

import * as React from "react"
import {
  ActivityIcon,
  BoxesIcon,
  DatabaseIcon,
  PuzzleIcon,
  ShieldAlertIcon,
  WrenchIcon,
} from "lucide-react"

import { Badge } from "@/components/ui/badge"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { useLanguage } from "@/contexts/language-provider"
import type { TranslationKey } from "@/i18n"
import type { WorkspaceAnalytics } from "@/lib/api/analytics"
import { formatAnalyticsNumber } from "@/components/system/workspace-analytics-metrics"
import { cn } from "@/lib/utils"

const TONE_TILE = {
  primary: "bg-primary/10 text-primary",
  sky: "bg-sky-500/10 text-sky-700 dark:text-sky-400",
  violet: "bg-violet-500/10 text-violet-700 dark:text-violet-400",
  emerald: "bg-emerald-500/10 text-emerald-700 dark:text-emerald-400",
  amber: "bg-amber-500/10 text-amber-700 dark:text-amber-400",
} as const

const TOOL_KIND_LABELS: Record<string, TranslationKey> = {
  builtin: "内置工具",
  mcp: "MCP 工具",
  python: "Python",
}

/**
 * Renders one compact statistic with an optional icon and supporting detail.
 *
 * @param icon - Optional icon displayed in a tinted tile
 * @param tone - Accent used by the icon tile
 * @param label - Statistic label
 * @param value - Formatted statistic value
 * @param detail - Supporting text rendered beneath the value
 */
function StatTile({
  icon: Icon,
  tone = "primary",
  label,
  value,
  detail,
}: {
  icon?: React.ComponentType<{ className?: string }>
  tone?: keyof typeof TONE_TILE
  label: string
  value: string
  detail?: string
}) {
  return (
    <div className="flex min-w-0 items-start gap-3 rounded-lg border bg-muted/20 p-3">
      {Icon ? (
        <span
          aria-hidden="true"
          className={cn(
            "flex size-8 shrink-0 items-center justify-center rounded-lg",
            TONE_TILE[tone]
          )}
        >
          <Icon className="size-4" />
        </span>
      ) : null}
      <div className="min-w-0">
        <p className="truncate text-xs text-muted-foreground">{label}</p>
        <p className="mt-0.5 text-lg font-semibold tabular-nums">{value}</p>
        {detail ? (
          <p
            className="mt-0.5 truncate text-xs text-muted-foreground"
            title={detail}
          >
            {detail}
          </p>
        ) : null}
      </div>
    </div>
  )
}

/**
 * Displays workspace resource scale: applications, knowledge, tools, and models.
 *
 * @param inventory - Workspace resource counts
 * @param locale - Locale used to format counts
 */
export function AnalyticsInventoryPanel({
  inventory,
  locale,
}: {
  inventory: WorkspaceAnalytics["inventory"]
  locale: string
}) {
  const { t } = useLanguage()
  const count = (value: number) => formatAnalyticsNumber(value, locale)

  return (
    <Card className="min-w-0 gap-4 rounded-xl py-5 shadow-xs">
      <CardHeader className="px-5">
        <CardTitle>{t("资产概览")}</CardTitle>
        <CardDescription>
          {t("工作空间内的应用、知识、工具与模型规模")}
        </CardDescription>
      </CardHeader>
      <CardContent className="grid min-w-0 grid-cols-1 gap-3 px-5 sm:grid-cols-2 lg:grid-cols-4">
        <StatTile
          icon={BoxesIcon}
          tone="violet"
          label={t("应用")}
          value={count(inventory.applications.total)}
          detail={t(
            "Agent {agents} · 工作流 {workflows} · 已发布 {published}",
            {
              agents: count(inventory.applications.agents),
              workflows: count(inventory.applications.workflows),
              published: count(inventory.applications.published),
            }
          )}
        />
        <StatTile
          icon={DatabaseIcon}
          tone="emerald"
          label={t("知识库")}
          value={count(inventory.knowledge.bases)}
          detail={t("文档 {documents} · 片段 {chunks}", {
            documents: count(inventory.knowledge.documents),
            chunks: count(inventory.knowledge.chunks),
          })}
        />
        <StatTile
          icon={WrenchIcon}
          tone="amber"
          label={t("工具")}
          value={count(inventory.tools.total)}
          detail={t("MCP {mcp} · Python {python} · 内置 {builtin}", {
            mcp: count(inventory.tools.mcp),
            python: count(inventory.tools.python),
            builtin: count(inventory.tools.builtin),
          })}
        />
        <StatTile
          icon={PuzzleIcon}
          tone="sky"
          label={t("模型")}
          value={count(inventory.models)}
        />
      </CardContent>
    </Card>
  )
}

/**
 * Displays tool invocation volume, success rate, approvals, and the busiest tools.
 *
 * @param usage - Tool usage statistics for the selected period
 * @param locale - Locale used to format counts and percentages
 */
export function AnalyticsToolUsagePanel({
  usage,
  locale,
}: {
  usage: WorkspaceAnalytics["tool_usage"]
  locale: string
}) {
  const { t } = useLanguage()
  const count = (value: number) => formatAnalyticsNumber(value, locale)
  const formatRate = (value: number | null) =>
    value === null ? "—" : `${(value * 100).toFixed(1)}%`
  const busiest = usage.top_tools[0]?.calls ?? 0

  return (
    <Card className="min-w-0 gap-4 rounded-xl py-5 shadow-xs">
      <CardHeader className="px-5">
        <CardTitle>{t("工具调用")}</CardTitle>
        <CardDescription>
          {t("所选周期内的工具执行情况与调用最多的工具")}
        </CardDescription>
      </CardHeader>
      <CardContent className="flex min-w-0 flex-col gap-4 px-5">
        <div className="grid min-w-0 grid-cols-1 gap-3 sm:grid-cols-3">
          <StatTile
            icon={WrenchIcon}
            tone="amber"
            label={t("调用次数")}
            value={count(usage.calls.value)}
            detail={t("上期 {value} 次", {
              value: count(usage.calls.previous_value),
            })}
          />
          <StatTile
            icon={ActivityIcon}
            tone="emerald"
            label={t("调用成功率")}
            value={formatRate(usage.success_rate.value)}
            detail={t("失败 {failed} 次", { failed: count(usage.failed) })}
          />
          <StatTile
            icon={ShieldAlertIcon}
            tone="violet"
            label={t("需审批调用")}
            value={count(usage.approval_required)}
          />
        </div>
        <div className="min-w-0">
          <h3 className="mb-2 flex items-center gap-2 text-sm font-medium">
            {t("调用最多的工具")}
            <Badge variant="secondary">{count(usage.top_tools.length)}</Badge>
          </h3>
          {usage.top_tools.length ? (
            <ul className="min-w-0 space-y-2">
              {usage.top_tools.map((tool) => {
                const kindLabel = TOOL_KIND_LABELS[tool.kind]
                return (
                  <li
                    key={tool.tool_id}
                    className="flex min-w-0 items-center justify-between gap-3 rounded-lg border px-3 py-2 text-sm"
                  >
                    <span className="flex min-w-0 items-center gap-2">
                      <span className="truncate font-medium" title={tool.name}>
                        {tool.name || t("未知工具")}
                      </span>
                      {kindLabel ? (
                        <Badge variant="outline">{t(kindLabel)}</Badge>
                      ) : null}
                    </span>
                    <span className="flex shrink-0 items-center gap-3 tabular-nums">
                      <span
                        aria-hidden="true"
                        className="hidden h-1.5 w-24 overflow-hidden rounded-full bg-muted sm:block"
                      >
                        <span
                          className="block h-full rounded-full bg-primary/70"
                          style={{
                            width: `${busiest ? Math.max(6, Math.round((tool.calls / busiest) * 100)) : 0}%`,
                          }}
                        />
                      </span>
                      <span className="w-10 text-right">
                        {count(tool.calls)}
                      </span>
                      <span className="w-12 text-right text-muted-foreground">
                        {tool.success_rate === null
                          ? "—"
                          : `${Math.round(tool.success_rate * 100)}%`}
                      </span>
                    </span>
                  </li>
                )
              })}
            </ul>
          ) : (
            <p className="rounded-lg border border-dashed px-3 py-6 text-center text-sm text-muted-foreground">
              {t("所选范围内暂无工具调用")}
            </p>
          )}
        </div>
      </CardContent>
    </Card>
  )
}
