"use client"

import * as React from "react"
import {
  ActivityIcon,
  BarChart3Icon,
  CheckIcon,
  LoaderCircleIcon,
  MessageSquareIcon,
  UsersIcon,
} from "lucide-react"
import { Area, AreaChart, XAxis, YAxis } from "recharts"

import { FilterDropdown } from "@/components/app/filter-dropdown"
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
import type { TFunction } from "@/i18n"
import {
  getAgentMonitoring,
  type Agent,
  type AgentMonitoring,
} from "@/lib/api/agents"
import { getErrorMessage } from "@/lib/errors"

type MonitoringPanelProps = {
  agent: Agent
  token: string
  workspaceId: string
  t: TFunction
  notify: (kind: "success" | "error", message: string) => void
}

function MetricCard({
  icon: Icon,
  label,
  value,
  tone,
}: {
  icon: React.ComponentType<{ className?: string }>
  label: string
  value: number
  tone: string
}) {
  return (
    <div className="rounded-lg border bg-background p-4">
      <div className="flex items-center gap-3">
        <span
          className={`flex size-9 items-center justify-center rounded-lg ${tone}`}
        >
          <Icon className="size-4" />
        </span>
        <div className="min-w-0">
          <p className="text-xs text-muted-foreground">{label}</p>
          <p className="mt-1 text-xl font-semibold tabular-nums">
            {value.toLocaleString()}
          </p>
        </div>
      </div>
    </div>
  )
}

export function AgentMonitoringPanel({
  agent,
  token,
  workspaceId,
  t,
  notify,
}: MonitoringPanelProps) {
  const [days, setDays] = React.useState<7 | 30 | 90>(7)
  const [data, setData] = React.useState<AgentMonitoring | null>(null)
  const [loading, setLoading] = React.useState(true)
  React.useEffect(() => {
    let current = true
    getAgentMonitoring(token, workspaceId, agent.id, days)
      .then((response) => {
        if (current) setData(response)
      })
      .catch((error: unknown) => {
        if (current) notify("error", getErrorMessage(error, t))
      })
      .finally(() => {
        if (current) setLoading(false)
      })
    return () => {
      current = false
    }
  }, [agent.id, days, notify, t, token, workspaceId])
  const summary = data?.summary
  const daily = data?.daily ?? []
  const chartConfig = {
    runs: {
      label: t("运行次数"),
      color: "var(--primary)",
    },
  } satisfies ChartConfig
  return (
    <div className="space-y-5 p-4 sm:p-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold">{t("监控统计")}</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            {t(
              agent.app_type === "workflow"
                ? "按时间范围查看工作流的使用与运行情况。"
                : "按时间范围查看 Agent 的使用与运行情况。"
            )}
          </p>
        </div>
        <div className="w-40 shrink-0">
          <FilterDropdown
            ariaLabel={t("统计周期")}
            value={String(days)}
            options={[
              { value: "7", label: t("过去 7 天") },
              { value: "30", label: t("过去 30 天") },
              { value: "90", label: t("过去 90 天") },
            ]}
            onChange={(value) => {
              setLoading(true)
              setDays(Number(value) as 7 | 30 | 90)
            }}
          />
        </div>
      </div>
      {loading || !summary ? (
        <div className="flex min-h-40 items-center justify-center text-sm text-muted-foreground">
          <LoaderCircleIcon className="mr-2 size-4 animate-spin" />
          {t("正在加载")}
        </div>
      ) : (
        <>
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
            <MetricCard
              icon={UsersIcon}
              label={t("活跃用户")}
              value={summary.active_users}
              tone="bg-blue-500/10 text-blue-600"
            />
            <MetricCard
              icon={MessageSquareIcon}
              label={t("对话次数")}
              value={summary.conversations}
              tone="bg-orange-500/10 text-orange-600"
            />
            <MetricCard
              icon={ActivityIcon}
              label={t("运行次数")}
              value={summary.runs}
              tone="bg-emerald-500/10 text-emerald-600"
            />
            <MetricCard
              icon={CheckIcon}
              label={t("成功运行")}
              value={summary.succeeded}
              tone="bg-teal-500/10 text-teal-600"
            />
            <MetricCard
              icon={BarChart3Icon}
              label={t("Tokens 总数")}
              value={summary.total_tokens}
              tone="bg-violet-500/10 text-violet-600"
            />
          </div>
          <Card className="min-w-0 gap-4 rounded-xl py-5 shadow-xs">
            <CardHeader className="px-6">
              <CardTitle>{t("每日运行趋势")}</CardTitle>
              <CardDescription>
                {t("失败 {value} 次", { value: summary.failed })}
              </CardDescription>
            </CardHeader>
            <CardContent className="min-w-0 px-2 sm:px-6">
              <ChartContainer
                config={chartConfig}
                className="aspect-auto h-[300px] w-full"
              >
                <AreaChart
                  data={daily}
                  accessibilityLayer
                  desc={t("每日运行趋势")}
                >
                  <XAxis
                    dataKey="date"
                    fontSize={12}
                    tickLine={false}
                    axisLine={false}
                    minTickGap={24}
                    tickFormatter={(date: string) => date.slice(5)}
                  />
                  <YAxis
                    allowDecimals={false}
                    fontSize={12}
                    tickLine={false}
                    axisLine={false}
                    width={36}
                  />
                  <ChartTooltip content={<ChartTooltipContent />} />
                  <Area
                    type="monotone"
                    dataKey="runs"
                    stroke="var(--color-runs)"
                    fill="var(--color-runs)"
                    fillOpacity={0.15}
                    connectNulls
                  />
                </AreaChart>
              </ChartContainer>
            </CardContent>
          </Card>
        </>
      )}
    </div>
  )
}
