import type { WorkspaceAnalytics } from "@/lib/api/analytics"

type DistributionItem = { key: string; count: number }

export type AnalyticsKeyMetrics = {
  averageTokens: number | null
  consoleRunsPerUser: number | null
  failedCancelledRuns: number
  externalCallShare: number | null
}

export function distributionTotal(items: DistributionItem[] | undefined) {
  return (items ?? []).reduce((total, item) => total + Math.max(0, item.count), 0)
}

export function distributionCount(
  items: DistributionItem[] | undefined,
  key: string
) {
  return Math.max(0, items?.find((item) => item.key === key)?.count ?? 0)
}

export function deriveAnalyticsKeyMetrics(
  data: Pick<WorkspaceAnalytics, "summary" | "distributions">
): AnalyticsKeyMetrics {
  const runs = data.summary.runs.value
  const activeUsers = data.summary.active_users.value
  const sourceTotal = distributionTotal(data.distributions.access_sources)
  const terminalFailureCount =
    distributionCount(data.distributions.statuses, "failed") +
    distributionCount(data.distributions.statuses, "cancelled")
  const externalRuns =
    distributionCount(data.distributions.access_sources, "public") +
    distributionCount(data.distributions.access_sources, "api")

  return {
    averageTokens: runs > 0 ? data.summary.tokens.total / runs : null,
    consoleRunsPerUser:
      activeUsers > 0
        ? distributionCount(data.distributions.access_sources, "console") /
          activeUsers
        : null,
    failedCancelledRuns: terminalFailureCount,
    externalCallShare: sourceTotal > 0 ? externalRuns / sourceTotal : null,
  }
}

export function formatAnalyticsHour(hour: number) {
  return `${String(Math.max(0, Math.min(23, hour))).padStart(2, "0")}:00`
}
