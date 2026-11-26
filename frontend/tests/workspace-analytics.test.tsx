/* @jsxImportSource react */
import { afterEach, beforeEach, describe, expect, mock, spyOn, test } from "bun:test"

import { TopBar } from "@/components/app/top-bar"
import {
  WorkspaceAnalyticsPage,
  formatTrendValue,
  getPresetAnalyticsRange,
} from "@/components/system/workspace-analytics-page"
import { ChartContainer, ChartTooltipContent } from "@/components/ui/chart"
import { formatAnalyticsHour } from "@/components/system/workspace-analytics-metrics"
import type { MeResponse } from "@/lib/api/auth"
import type { WorkspaceAnalytics } from "@/lib/api/analytics"
import type { Workspace } from "@/lib/api/system"
import { deriveAnalyticsKeyMetrics } from "@/components/system/workspace-analytics-metrics"
import { formatTokenCount } from "@/lib/display"
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
const switchWorkspaceCalls: string[] = []
const session = makeSession({
  selectWorkspace: (workspaceId: string) =>
    selectWorkspaceCalls.push(workspaceId),
  switchWorkspace: (workspaceId: string) =>
    switchWorkspaceCalls.push(workspaceId),
})
const sessionState = session as unknown as {
  me: MeResponse | null
  token: string | null
  workspaces: Workspace[]
  workspaceOptions: Workspace[]
  selectedWorkspaceId: string | null
  selectWorkspace: (workspaceId: string) => void
  switchWorkspace: (workspaceId: string) => void
}

mockUseSession(session)
mockNextNavigation({
  pathname: "/system/analytics",
  replace: (href) => replaceCalls.push(href),
})
mockNextImage()
mockNextLink()
mock.module("@/contexts/theme-provider", () => ({
  useTheme: () => ({
    theme: "system",
    setTheme: () => undefined,
    palette: "neutral",
    setPalette: () => undefined,
  }),
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
      application_total: 280,
      total: 320,
      unreported_runs: 1,
      previous_total: 60,
      change_percent: 433.3,
    },
    success_rate: { value: 0.5, previous_value: 1, change_percent: -50 },
    average_duration_ms: {
      value: 12500,
      previous_value: 10000,
      change_percent: 25,
    },
  },
  inventory: {
    applications: {
      total: 3,
      agents: 2,
      workflows: 1,
      published: 1,
      active: 3,
    },
    knowledge: { bases: 2, documents: 12, chunks: 340 },
    tools: { total: 7, mcp: 3, builtin: 4, active: 6 },
    models: 5,
  },
  tool_usage: {
    calls: { value: 42, previous_value: 30, change_percent: 40 },
    failed: 4,
    success_rate: { value: 0.9, previous_value: 0.8, change_percent: 12.5 },
    approval_required: 6,
    top_tools: [
      {
        tool_id: "tool-1",
        name: "tavily_search",
        kind: "mcp",
        calls: 20,
        failed: 2,
        success_rate: 0.9,
      },
      {
        tool_id: "tool-2",
        name: "current_time",
        kind: "builtin",
        calls: 12,
        failed: 0,
        success_rate: 1,
      },
    ],
  },
  trends: [
    {
      date: "2026-08-01",
      runs: 1,
      input_tokens: 100,
      output_tokens: 50,
      application_tokens: 150,
      total_tokens: 150,
    },
    {
      date: "2026-08-02",
      runs: 3,
      input_tokens: 40,
      output_tokens: 25,
      application_tokens: 130,
      total_tokens: 170,
    },
  ],
  hourly_runs: Array.from({ length: 24 }, (_, hour) => ({
    hour,
    runs: hour === 0 ? 3 : hour === 23 ? 1 : 0,
  })),
  member_trends: [
    {
      user_id: "u-1",
      name: "NexaFlow Admin",
      total_runs: 20,
      total_tokens: 150,
      daily: [
        { date: "2026-08-01", runs: 8, total_tokens: 60 },
        { date: "2026-08-02", runs: 12, total_tokens: 90 },
      ],
    },
    ...Array.from({ length: 11 }, (_, idx) => {
      const rank = idx + 2
      const runs = 19 - idx
      const tokens = rank === 6 ? 950 : rank === 2 ? 400 : 300 - rank * 10
      return {
        user_id: `u-${rank}`,
        name: `Member ${rank}`,
        total_runs: runs,
        total_tokens: tokens,
        daily: [
          {
            date: "2026-08-01",
            runs: Math.floor(runs / 2),
            total_tokens: Math.floor(tokens / 2),
          },
          {
            date: "2026-08-02",
            runs: runs - Math.floor(runs / 2),
            total_tokens: tokens - Math.floor(tokens / 2),
          },
        ],
      }
    }),
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
    timezone: "Asia/Shanghai",
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
  sessionState.switchWorkspace = (workspaceId) =>
    switchWorkspaceCalls.push(workspaceId)
}

beforeEach(() => {
  handler = () => jsonResponse(analytics)
  requests = []
  replaceCalls.length = 0
  selectWorkspaceCalls.length = 0
  switchWorkspaceCalls.length = 0
  restoreGlobalAdminSession()
  installFetch()
})

afterEach(() => cleanup())

describe("workspace analytics", () => {
  test("renders the dashboard and keeps every section on one scoped request", async () => {
    renderPage(<WorkspaceAnalyticsPage />)

    await waitFor(() => expect(screen.getByText("Support Agent")).toBeTruthy())
    const tokenCard = screen
      .getAllByText("Token 消耗")[0]
      .closest<HTMLElement>("[data-slot='card']")!
    expect(within(tokenCard).getByText("320")).toBeTruthy()
    expect(within(tokenCard).getByText("输入 140 · 输出 75")).toBeTruthy()
    expect(within(tokenCard).getByText("较上期 +433.3%")).toBeTruthy()

    // Resource scale and tool usage are part of the dashboard.
    const inventoryCard = screen
      .getByText("资产概览")
      .closest<HTMLElement>("[data-slot='card']")!
    expect(
      within(inventoryCard).getByText("Agent 2 · 工作流 1 · 已发布 1")
    ).toBeTruthy()
    expect(within(inventoryCard).getByText("文档 12 · 片段 340")).toBeTruthy()
    expect(within(inventoryCard).getByText("MCP 3 · 内置 4")).toBeTruthy()
    expect(
      within(inventoryCard).getByText(/每个 MCP 服务计为一个工具/)
    ).toBeTruthy()

    const toolUsageCard = screen
      .getByText("工具调用")
      .closest<HTMLElement>("[data-slot='card']")!
    expect(within(toolUsageCard).getByText("42")).toBeTruthy()
    expect(within(toolUsageCard).getByText("上期 30 次")).toBeTruthy()
    expect(within(toolUsageCard).getByText("90.0%")).toBeTruthy()
    expect(within(toolUsageCard).getByText("失败 4 次")).toBeTruthy()
    expect(within(toolUsageCard).queryByText("调用最多的工具")).toBeNull()
    expect(within(toolUsageCard).queryByText("tavily_search")).toBeNull()
    // Average run duration renders in seconds instead of milliseconds.
    expect(screen.getByText("12.5 秒")).toBeTruthy()
    expect(screen.queryByText(/毫秒/)).toBeNull()
    expect(screen.getByText("公开/API 调用")).toBeTruthy()
    const frequentQuestion = screen.getByText("How do I deploy?")
    expect(frequentQuestion).toBeTruthy()
    expect(frequentQuestion.className).toContain("truncate")
    expect(frequentQuestion.getAttribute("title")).toBe("How do I deploy?")
    expect(screen.getByText("时段活跃曲线")).toBeTruthy()
    expect(screen.getByText("按自然日统计顶层运行")).toBeTruthy()
    expect(document.querySelectorAll("[data-slot='chart']")).toHaveLength(7)
    expect(screen.queryByText(/统计时区/)).toBeNull()
    expect(
      screen.getByText("使用排行").closest<HTMLElement>("[data-slot='card']")
        ?.parentElement?.className
    ).toContain("xl:grid-cols-2")
    const statusSection = screen.getByText("运行状态").closest("section")!
    const succeededRow = within(statusSection)
      .getByText("运行成功")
      .closest("li")!
    expect(within(succeededRow).getByText("2")).toBeTruthy()
    expect(within(succeededRow).getByText("50%")).toBeTruthy()
    fireEvent.click(screen.getByRole("button", { name: "团队" }))
    expect(screen.getByText("Analytics Team")).toBeTruthy()
    expect(screen.getByText("单日最高 3")).toBeTruthy()
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

    fireEvent.click(screen.getByLabelText("选择统计周期"))
    fireEvent.click(
      within(
        await screen.findByRole("dialog", { name: "选择统计周期" })
      ).getByRole("button", {
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

    fireEvent.click(screen.getByLabelText("选择统计周期"))
    fireEvent.click(
      within(
        await screen.findByRole("dialog", { name: "选择统计周期" })
      ).getByRole("button", {
        name: "自定义",
      })
    )
    const calendar = await screen.findByRole("dialog", { name: "自定义" })
    expect(calendar.querySelector("input[type='date']")).toBeNull()
    const dates = within(calendar)
      .getAllByRole("button")
      .filter(
        (button) => button.dataset.date && button.dataset.outside !== "true"
      )
    const from = dates[0].dataset.date!
    const to = dates[6].dataset.date!
    fireEvent.click(dates[0])
    fireEvent.click(dates[6])
    fireEvent.click(within(calendar).getByRole("button", { name: "确认" }))
    await waitFor(() => expect(requests).toHaveLength(3))
    url = new URL(requests[2], "http://app.local")
    expect(url.searchParams.get("from")).toBe(from)
    const expectedExclusiveTo = new Date(`${to}T00:00:00Z`)
    expectedExclusiveTo.setUTCDate(expectedExclusiveTo.getUTCDate() + 1)
    expect(url.searchParams.get("to")).toBe(
      expectedExclusiveTo.toISOString().slice(0, 10)
    )
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
      expect(screen.getByText("服务暂时不可用，请稍后重试")).toBeTruthy()
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
          tokens: {
            ...analytics.summary.tokens,
            application_total: 0,
            total: 0,
          },
        },
      })
    renderPage(<WorkspaceAnalyticsPage />)
    await waitFor(() =>
      expect(screen.getByText("所选范围内暂无运行数据")).toBeTruthy()
    )
    // Workspace scale stays visible without activity; run-based panels do not.
    expect(screen.getByText("资产概览")).toBeTruthy()
    expect(screen.getByText("工具调用")).toBeTruthy()
    expect(screen.queryByText("运行分布")).toBeNull()
    expect(screen.queryByText("时段活跃曲线")).toBeNull()
  })

  test("renders token consumption with K/M/B units", async () => {
    handler = () =>
      jsonResponse({
        ...analytics,
        summary: {
          ...analytics.summary,
          runs: { value: 100, previous_value: 80, change_percent: 25 },
          tokens: {
            ...analytics.summary.tokens,
            application_total: 2_500_000,
            total: 1_234_567,
          },
        },
        rankings: {
          ...analytics.rankings,
          applications: [
            {
              ...analytics.rankings.applications[0],
              total_tokens: 2_500_000_000,
            },
          ],
          users: [{ ...analytics.rankings.users[0], total_tokens: 12_340 }],
          anonymous: { run_count: 2, total_tokens: 250_000 },
        },
      })
    renderPage(<WorkspaceAnalyticsPage />)

    await waitFor(() => expect(screen.getByText("Support Agent")).toBeTruthy())
    const tokenCard = screen
      .getAllByText("Token 消耗")[0]
      .closest<HTMLElement>("[data-slot='card']")!
    expect(within(tokenCard).getByText("1.23M")).toBeTruthy()
    // Ranking rows reuse the same units for applications, users and匿名调用.
    expect(screen.getByText("Tokens 2.5B")).toBeTruthy()
    expect(screen.getByText("运行 2 次，Tokens 250K")).toBeTruthy()
    // The per-run average keeps the same units (2,500,000 / 100 runs).
    expect(screen.getByText("25K")).toBeTruthy()

    fireEvent.click(screen.getByRole("button", { name: "用户" }))
    expect(await screen.findByText("Tokens 12.3K")).toBeTruthy()
  })

  test("formats trend values with token units and plain run counts", () => {
    expect(formatTrendValue(1_234_567, "total_tokens", "zh-CN")).toBe("1.23M")
    expect(formatTrendValue(1_234, "total_tokens", "en-US")).toBe("1.23K")
    expect(formatTrendValue(1_234, "runs", "en-US")).toBe("1,234")
  })

  test("formats token counts below one thousand without units", () => {
    expect(formatTokenCount(0)).toBe("0")
    expect(formatTokenCount(320)).toBe("320")
    expect(formatTokenCount(1_500)).toBe("1.5K")
    expect(formatTokenCount(12_340)).toBe("12.3K")
    expect(formatTokenCount(123_456)).toBe("123K")
    expect(formatTokenCount(1_234_567)).toBe("1.23M")
    expect(formatTokenCount(2_500_000_000)).toBe("2.5B")
    expect(formatTokenCount(Number.NaN)).toBe("0")
  })

  test("puts the analytics entry in the top navigation for authorized admins", () => {
    renderPage(<TopBar />)
    const link = screen.getByRole("link", { name: "数据大屏" })
    expect(link.getAttribute("href")).toBe("/system/analytics")
    expect(link.closest("nav")).toBeTruthy()
  })

  test("shows system management in an ordinary user's avatar menu", async () => {
    const ordinary = makeSession()
    ordinary.me!.user.is_global_admin = false
    ordinary.me!.user.workspaces = [
      { id: "ws-1", name: "Test Workspace", is_default: false, role: "member" },
    ]
    ordinary.me!.memberships = [{ workspace_id: "ws-1", role: "member" }]
    Object.assign(sessionState, ordinary)

    renderPage(<TopBar />)
    fireEvent.pointerDown(
      screen.getByRole("button", { name: "打开用户菜单" })
    )
    const menu = await screen.findByRole("menu")
    const systemLink = within(menu).getByRole("menuitem", { name: "系统管理" })
    expect(systemLink.getAttribute("href")).toBe("/system/teams")
    expect(within(menu).queryByRole("menuitem", { name: "记忆" })).toBeNull()
  })

  test("provides every navigation entry in the compact menu", async () => {
    renderPage(<TopBar />)
    const menuButton = screen.getByRole("button", { name: "主导航" })
    expect(menuButton.className).toContain("xl:hidden")
    expect(menuButton.className).toContain("sm:inline-flex")
    fireEvent.pointerDown(menuButton)
    const menu = await screen.findByRole("menu")
    for (const name of ["应用", "知识库", "模型", "工具", "数据大屏"]) {
      expect(within(menu).getByRole("menuitem", { name })).toBeTruthy()
    }
  })

  test("returns to the application home after switching workspaces", async () => {
    renderPage(<TopBar />)

    fireEvent.pointerDown(
      screen.getByRole("button", {
        name: "切换工作空间，当前为 Test Workspace",
      })
    )
    fireEvent.click(await screen.findByText("Member Workspace"))

    expect(switchWorkspaceCalls).toEqual(["ws-2"])
    expect(replaceCalls).toEqual(["/app/apps"])
  })

  test("derives key metrics from the correct distributions and handles zero denominators", () => {
    expect(deriveAnalyticsKeyMetrics(analytics)).toEqual({
      averageTokens: 70,
      consoleRunsPerUser: 1,
      failedCancelledRuns: 2,
      externalCallShare: 0.5,
    })

    expect(
      deriveAnalyticsKeyMetrics({
        ...analytics,
        summary: {
          ...analytics.summary,
          runs: { value: 0, previous_value: 0, change_percent: 0 },
          active_users: { value: 0, previous_value: 0, change_percent: 0 },
          tokens: { ...analytics.summary.tokens, total: 0 },
        },
        distributions: {
          run_types: [],
          access_sources: [],
          statuses: [],
        },
      })
    ).toEqual({
      averageTokens: null,
      consoleRunsPerUser: null,
      failedCancelledRuns: 0,
      externalCallShare: null,
    })
  })

  test("switches ranking views and loads frequent questions ten at a time", async () => {
    const longAnalytics: WorkspaceAnalytics = {
      ...analytics,
      frequent_questions: Array.from({ length: 12 }, (_, index) => ({
        question: `Question ${index + 1}`,
        count: index + 3,
        latest_at: `2026-08-${String(index + 1).padStart(2, "0")}T00:00:00Z`,
      })),
    }
    handler = () => jsonResponse(longAnalytics)
    renderPage(<WorkspaceAnalyticsPage />)
    await waitFor(() => expect(screen.getByText("Question 1")).toBeTruthy())
    expect(requests).toHaveLength(1)
    expect(screen.getByText("Question 10")).toBeTruthy()
    expect(screen.queryByText("Question 11")).toBeNull()

    const rankingCard = screen
      .getByText("使用排行")
      .closest<HTMLElement>("[data-slot='card']")!
    fireEvent.click(within(rankingCard).getByRole("button", { name: "用户" }))
    expect(within(rankingCard).getByText("NexaFlow Admin")).toBeTruthy()
    fireEvent.click(within(rankingCard).getByRole("button", { name: "团队" }))
    expect(within(rankingCard).getByText("Analytics Team")).toBeTruthy()
    fireEvent.click(
      within(rankingCard).getByRole("button", { name: "应用 / 工作流" })
    )
    expect(within(rankingCard).getByText("Support Agent")).toBeTruthy()

    const questions = screen.getByRole("region", { name: "高频问题" })
    Object.defineProperty(questions, "scrollHeight", {
      configurable: true,
      value: 1_000,
    })
    Object.defineProperty(questions, "clientHeight", {
      configurable: true,
      value: 400,
    })
    questions.scrollTop = 600
    fireEvent.scroll(questions)
    expect(screen.getByText("Question 11")).toBeTruthy()
    expect(screen.getByText("Question 12")).toBeTruthy()
    expect(requests).toHaveLength(1)
  })

  test("supports Top 5 / 10 / 20 presets, metric switching, and custom member selection", async () => {
    renderPage(<WorkspaceAnalyticsPage />)

    await waitFor(() =>
      expect(screen.getByText("成员每日使用对比")).toBeTruthy()
    )
    const memberCard = screen
      .getByText("成员每日使用对比")
      .closest<HTMLElement>("[data-slot='card']")!

    expect(
      within(memberCard).getByRole("button", { name: "选择成员 (5/12)" })
    ).toBeTruthy()
    expect(within(memberCard).getByText("Member 5")).toBeTruthy()
    expect(within(memberCard).queryByText("Member 6")).toBeNull()

    fireEvent.click(within(memberCard).getByRole("button", { name: "Top 10" }))
    expect(
      within(memberCard).getByRole("button", { name: "选择成员 (10/12)" })
    ).toBeTruthy()
    expect(within(memberCard).getByText("Member 10")).toBeTruthy()
    expect(within(memberCard).queryByText("Member 11")).toBeNull()

    fireEvent.click(within(memberCard).getByRole("button", { name: "Top 20" }))
    expect(
      within(memberCard).getByRole("button", { name: "选择成员 (12/12)" })
    ).toBeTruthy()
    expect(within(memberCard).getByText("Member 12")).toBeTruthy()

    fireEvent.click(within(memberCard).getByRole("button", { name: "Top 5" }))
    expect(
      within(memberCard).getByRole("button", { name: "选择成员 (5/12)" })
    ).toBeTruthy()
    expect(within(memberCard).queryByText("Member 6")).toBeNull()

    fireEvent.click(within(memberCard).getByRole("button", { name: "Token 消耗" }))
    expect(within(memberCard).getByText("950")).toBeTruthy()
    expect(within(memberCard).getByText("400")).toBeTruthy()

    fireEvent.click(within(memberCard).getByRole("button", { name: "运行次数" }))
    fireEvent.pointerDown(
      within(memberCard).getByRole("button", { name: "选择成员 (5/12)" })
    )
    const menu = await screen.findByRole("menu")

    fireEvent.click(within(menu).getByRole("menuitem", { name: /Member 5/ }))
    expect(within(memberCard).getByText("选择成员 (4/12)")).toBeTruthy()

    fireEvent.click(within(menu).getByRole("menuitem", { name: /Member 6/ }))
    expect(within(memberCard).getByText("选择成员 (5/12)")).toBeTruthy()
    expect(within(memberCard).getByText("Member 6")).toBeTruthy()

    fireEvent.click(within(menu).getByRole("menuitem", { name: /Member 12/ }))
    expect(within(memberCard).getByText("选择成员 (6/12)")).toBeTruthy()
    expect(within(memberCard).getByText("Member 12")).toBeTruthy()
  })
})

test("builds preset ranges from the Shanghai calendar date", () => {
  expect(getPresetAnalyticsRange(7, new Date("2026-08-19T12:00:00Z"))).toEqual({
    from: "2026-08-13",
    to: "2026-08-20",
  })
  expect(getPresetAnalyticsRange(7, new Date("2026-08-19T16:30:00Z"))).toEqual({
    from: "2026-08-14",
    to: "2026-08-21",
  })
})

test("formats numeric zero tooltip labels inside ChartContainer", () => {
  function TooltipProbe() {
    return (
      <ChartTooltipContent
        active
        label={0}
        payload={[
          {
            name: "runs",
            dataKey: "runs",
            value: 3,
            color: "var(--primary)",
            payload: { hour: 0, runs: 3 },
            graphicalItemId: "runs",
          },
        ]}
        labelFormatter={(value) => formatAnalyticsHour(Number(value))}
      />
    )
  }

  const bounds = spyOn(
    HTMLElement.prototype,
    "getBoundingClientRect"
  ).mockReturnValue(new DOMRect(0, 0, 320, 200))

  try {
    renderPage(
      <ChartContainer
        config={{ runs: { label: "运行次数", color: "var(--primary)" } }}
      >
        <TooltipProbe />
      </ChartContainer>
    )

    expect(screen.getByText("00:00")).toBeTruthy()
    expect(screen.getByText("运行次数")).toBeTruthy()
    expect(screen.getByText("3")).toBeTruthy()
  } finally {
    bounds.mockRestore()
  }
})
