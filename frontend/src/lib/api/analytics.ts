import { request } from "@/lib/api-client"

export type AnalyticsComparison = {
  value: number
  previous_value: number
  change_percent: number | null
}

export type AnalyticsNullableComparison = {
  value: number | null
  previous_value: number | null
  change_percent: number | null
}

export type WorkspaceAnalytics = {
  summary: {
    members: { total: number; active: number }
    active_teams: number
    active_users: AnalyticsComparison
    runs: AnalyticsComparison
    tokens: {
      input: number
      output: number
      application_total: number
      graph_total: number
      total: number
      unreported_runs: number
      unreported_graph_builds: number
      previous_total: number
      change_percent: number | null
    }
    success_rate: AnalyticsNullableComparison
    average_duration_ms: AnalyticsNullableComparison
  }
  trends: Array<{
    date: string
    runs: number
    graph_builds: number
    input_tokens: number
    output_tokens: number
    application_tokens: number
    graph_tokens: number
    total_tokens: number
  }>
  hourly_runs: Array<{
    hour: number
    runs: number
  }>
  distributions: {
    run_types: Array<{ key: string; count: number }>
    access_sources: Array<{ key: string; count: number }>
    statuses: Array<{ key: string; count: number }>
  }
  rankings: {
    users: Array<{
      user_id: string
      name: string
      run_count: number
      total_tokens: number
    }>
    applications: Array<{
      application_id: string
      name: string
      app_type: "agent" | "workflow"
      run_count: number
      total_tokens: number
      success_rate: number | null
    }>
    anonymous: { run_count: number; total_tokens: number }
    teams: Array<{
      team_id: string
      name: string
      peak_daily_runs: number
      run_count: number
    }>
  }
  frequent_questions: Array<{
    question: string
    count: number
    latest_at: string
  }>
  metadata: {
    workspace_id: string
    timezone: "UTC"
    from_date: string
    to_date: string
    previous_from_date: string
    previous_to_date: string
    end_exclusive: true
    generated_at: string
  }
}

export function getWorkspaceAnalytics(
  token: string,
  workspaceId: string,
  range: { from: string; to: string },
  signal?: AbortSignal
) {
  const query = new URLSearchParams({ from: range.from, to: range.to })
  return request<WorkspaceAnalytics>(
    `/api/v1/workspaces/${workspaceId}/analytics?${query}`,
    { token, signal }
  )
}
