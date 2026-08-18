/* @jsxImportSource react */
import { afterEach, beforeEach, describe, expect, mock, test } from "bun:test"

import { TopBar } from "@/components/app/top-bar"
import {
  WorkspaceAnalyticsPage,
  getPresetAnalyticsRange,
} from "@/components/system/workspace-analytics-page"
import type { MeResponse } from "@/lib/api/auth"
import type { WorkspaceAnalytics } from "@/lib/api/analytics"
import type { Workspace } from "@/lib/api/system"
import {
  cleanup,
  fireEvent,
  jsonResponse,
  makeSession,
  mockNextImage,
  mockNextLink,
  mockNextNavigation,
  mockUseSession,
  renderPage,
  screen,
  waitFor,
  within,
  type FetchHandler,
} from "./helpers/dom"

const replaceCalls: string[] = []
const selectWorkspaceCalls: string[] = []
const session = makeSession({
  selectWorkspace: (workspaceId: string) => selectWorkspaceCalls.push(workspaceId),
})
const sessionState = session as unknown as {
  me: MeResponse | null
  token: string | null
  workspaces: Workspace[]
  workspaceOptions: Workspace[]
  selectedWorkspaceId: string | null
  selectWorkspace: (workspaceId: string) => void
}

mockUseSession(session)
mockNextNavigation({
  pathname: "/system/analytics",
  replace: (href) => replaceCalls.push(href),
})
mockNextImage()
mockNextLink()
mock.module("@/contexts/theme-provider", () => ({
  useTheme: () => ({ theme: "system", setTheme: () => undefined }),
  ThemeProvider: ({ children }: { children: React.ReactNode }) => children,
}))

const secondWorkspace: Workspace = {
  id: "ws-2",
  name: "Member Workspace",
  description: "",
  status: "active",
  is_default: false,
}

const analytics: WorkspaceAnalytics = {
  summary: {
    members: { total: 5, active: 4 },
    active_teams: 1,
    active_users: { value: 2, previous_value: 1, change_percent: 100 },
    runs: { value: 4, previous_value: 1, change_percent: 300 },
    tokens: {
      input: 140,
      output: 75,
      total: 280,
      unreported_runs: 1,
      previous_total: 50,
      change_percent: 460,
    },
    success_rate: { value: 0.5, previous_value: 1, change_percent: -50 },
    average_duration_ms: {
      value: 12500,
      previous_value: 10000,
      change_percent: 25,
    },
  },
  trends: [
    {
      date: "2026-08-01",
      runs: 1,
      input_tokens: 100,
      output_tokens: 50,
      total_tokens: 150,
    },
    {
      date: "2026-08-02",
      runs: 3,
      input_tokens: 40,
      output_tokens: 25,
      total_tokens: 130,
    },
  ],
  distributions: {
    run_types: [
      { key: "agent", count: 3 },
      { key: "workflow", count: 1 },
    ],
    access_sources: [
      { key: "console", count: 2 },
      { key: "public", count: 1 },
      { key: "api", count: 1 },
    ],
    statuses: [
      { key: "succeeded", count: 2 },
      { key: "failed", count: 1 },
      { key: "cancelled", count: 1 },
    ],
  },
  rankings: {
    users: [
      {
        user_id: "u-1",
        name: "NexaFlow Admin",
        run_count: 1,
        total_tokens: 150,
      },
    ],
    applications: [
      {
        application_id: "agent-1",
        name: "Support Agent",
        app_type: "agent",
        run_count: 3,
        total_tokens: 200,
        success_rate: 2 / 3,
      },
      {
        application_id: "workflow-1",
        name: "Release Workflow",
        app_type: "workflow",
        run_count: 1,
        total_tokens: 80,
        success_rate: 0,
      },
    ],
    anonymous: { run_count: 2, total_tokens: 130 },
    teams: [
      {
        team_id: "team-1",
        name: "Analytics Team",
        peak_daily_runs: 3,
        run_count: 7,
      },
    ],
  },
  frequent_questions: [
    {
      question: "How do I deploy?",
      count: 3,
      latest_at: "2026-08-04T00:00:00Z",
    },
  ],
  metadata: {
    workspace_id: "ws-1",
    timezone: "UTC",
    from_date: "2026-08-01",
    to_date: "2026-08-08",
    previous_from_date: "2026-07-25",
    previous_to_date: "2026-08-01",
    end_exclusive: true,
    generated_at: "2026-08-08T00:00:00Z",
  },
}

let handler: FetchHandler = () => jsonResponse(analytics)
let requests: string[] = []

function installFetch() {
  globalThis.fetch = ((input: RequestInfo | URL, init?: RequestInit) => {
    const url =
      typeof input === "string"
        ? input
        : input instanceof URL
          ? input.toString()
          : input.url
    requests.push(url)
    return Promise.resolve(handler(url, init))
  }) as typeof fetch
}

function restoreGlobalAdminSession() {
  const fresh = makeSession()
  sessionState.me = fresh.me
  sessionState.token = fresh.token
  sessionState.workspaces = [fresh.workspaces[0], secondWorkspace]
  sessionState.workspaceOptions = [fresh.workspaces[0], secondWorkspace]
  sessionState.selectedWorkspaceId = "ws-1"
  sessionState.selectWorkspace = (workspaceId) =>
    selectWorkspaceCalls.push(workspaceId)
}

beforeEach(() => {
  handler = () => jsonResponse(analytics)
  requests = []
  replaceCalls.length = 0
  selectWorkspaceCalls.length = 0
  restoreGlobalAdminSession()
  installFetch()
})

afterEach(() => cleanup())

describe("workspace analytics", () => {
  test("renders the dashboard and keeps every section on one scoped request", async () => {
    renderPage(<WorkspaceAnalyticsPage />)

    await waitFor(() => expect(screen.getByText("Support Agent")).toBeTruthy())
    const tokenCard = screen
      .getByText("Token 消耗")
      .closest<HTMLElement>("[data-slot='card']")!
    expect(within(tokenCard).getByText("280")).toBeTruthy()
    expect(within(tokenCard).getByText("1 次运行的用量未完整上报")).toBeTruthy()
    expect(screen.getByText("公开/API 调用")).toBeTruthy()
    expect(screen.getByText("How do I deploy?")).toBeTruthy()
    expect(screen.getByText("Analytics Team")).toBeTruthy()
    expect(screen.getByText("单日最高")).toBeTruthy()
    expect(requests).toHaveLength(1)
    const url = new URL(requests[0], "http://app.local")
    expect(url.pathname).toBe("/api/v1/workspaces/ws-1/analytics")
    const from = Date.parse(`${url.searchParams.get("from")}T00:00:00Z`)
    const to = Date.parse(`${url.searchParams.get("to")}T00:00:00Z`)
    expect((to - from) / 86_400_000).toBe(30)
  })

  test("switches presets and applies a custom closed-open range", async () => {
    renderPage(<WorkspaceAnalyticsPage />)
    await waitFor(() => expect(requests).toHaveLength(1))

    fireEvent.pointerDown(screen.getByLabelText("选择统计周期"))
    fireEvent.click(
      within(await screen.findByRole("menu")).getByRole("menuitem", {
        name: "最近 7 天",
      })
    )
    await waitFor(() => expect(requests).toHaveLength(2))
    let url = new URL(requests[1], "http://app.local")
    expect(
      (Date.parse(`${url.searchParams.get("to")}T00:00:00Z`) -
        Date.parse(`${url.searchParams.get("from")}T00:00:00Z`)) /
        86_400_000
    ).toBe(7)

    fireEvent.pointerDown(screen.getByLabelText("选择统计周期"))
    fireEvent.click(
      within(await screen.findByRole("menu")).getByRole("menuitem", {
        name: "自定义",
      })
    )
    fireEvent.change(screen.getByLabelText("开始日期"), {
      target: { value: "2026-08-01" },
    })
    fireEvent.change(screen.getByLabelText("结束日期"), {
      target: { value: "2026-08-07" },
    })
    fireEvent.click(screen.getByRole("button", { name: "确认" }))
    await waitFor(() => expect(requests).toHaveLength(3))
    url = new URL(requests[2], "http://app.local")
    expect(url.searchParams.get("from")).toBe("2026-08-01")
    expect(url.searchParams.get("to")).toBe("2026-08-08")
  })

  test("shows only workspaces where a non-global user is a workspace admin", async () => {
    const me = sessionState.me!
    me.user.is_global_admin = false
    me.memberships = [
      { workspace_id: "ws-1", role: "admin" },
      { workspace_id: "ws-2", role: "member" },
    ]
    me.user.workspaces = [
      {
        id: "ws-1",
        name: "Test Workspace",
        is_default: false,
        role: "admin",
      },
      {
        id: "ws-2",
        name: "Member Workspace",
        is_default: false,
        role: "member",
      },
    ]
    sessionState.selectedWorkspaceId = "ws-2"

    renderPage(<WorkspaceAnalyticsPage />)
    await waitFor(() => expect(requests).toHaveLength(1))
    expect(requests[0]).toContain("/workspaces/ws-1/analytics")
    fireEvent.pointerDown(screen.getByLabelText("选择统计工作空间"))
    const menu = await screen.findByRole("menu")
    expect(within(menu).getByText("Test Workspace")).toBeTruthy()
    expect(within(menu).queryByText("Member Workspace")).toBeNull()
  })

  test("shows a retry state and an explicit empty state", async () => {
    handler = () => jsonResponse({ detail: "analytics unavailable" }, 500)
    renderPage(<WorkspaceAnalyticsPage />)
    await waitFor(() =>
      expect(screen.getByText("analytics unavailable")).toBeTruthy()
    )
    expect(screen.getByRole("button", { name: "重试" })).toBeTruthy()

    cleanup()
    requests = []
    handler = () =>
      jsonResponse({
        ...analytics,
        summary: {
          ...analytics.summary,
          runs: { value: 0, previous_value: 0, change_percent: 0 },
        },
      })
    renderPage(<WorkspaceAnalyticsPage />)
    await waitFor(() =>
      expect(screen.getByText("所选范围内暂无运行数据")).toBeTruthy()
    )
  })

  test("puts the analytics entry in the top navigation for authorized admins", () => {
    renderPage(<TopBar />)
    const link = screen.getByRole("link", { name: "数据大屏" })
    expect(link.getAttribute("href")).toBe("/system/analytics")
  })
})

test("builds UTC preset ranges with an exclusive end date", () => {
  expect(getPresetAnalyticsRange(7, new Date("2026-08-19T12:00:00Z"))).toEqual({
    from: "2026-08-13",
    to: "2026-08-20",
  })
})
