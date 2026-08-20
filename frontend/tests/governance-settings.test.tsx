/* @jsxImportSource react */
import { afterEach, beforeEach, describe, expect, test } from "bun:test"
import { act } from "@testing-library/react"

import { SystemGovernancePage } from "@/components/system/system-governance-page"
import type { MeResponse } from "@/lib/api/auth"
import type { SystemLog } from "@/lib/api/system"
import {
  cleanup,
  fireEvent,
  jsonResponse,
  makeSession,
  mockNextLink,
  mockNextNavigation,
  mockUseSession,
  renderPage,
  resetFetch,
  screen,
  waitFor,
  withFetch,
  within,
} from "./helpers/dom"

const notifications: Array<[string, string]> = []
const replaced: string[] = []
const session = makeSession({
  notify: (kind: string, message: string) =>
    notifications.push([kind, message]),
})
mockUseSession(session)
mockNextNavigation({
  pathname: "/system/governance",
  replace: (href: string) => replaced.push(href),
})
mockNextLink()

const sessionState = session as unknown as {
  me: MeResponse | null
  workspaces: typeof session.workspaces
}
const adminMe = session.me as MeResponse
const defaultWorkspaces = session.workspaces

const inventory = {
  workspace_id: "ws-1",
  members_total: 12,
  members_active: 10,
  teams_total: 3,
  agents_total: 5,
  knowledge_bases_total: 2,
  models_total: 4,
  tools_total: 9,
  workflows_total: 7,
  active_runs: 3,
  failed_runs_24h: 1,
  failed_tasks_24h: 2,
}

const governance = {
  workspace_id: "ws-1",
  daily_run_limit: 10,
  monthly_token_limit: 100000,
  alert_threshold_percent: 80,
  retention_days: 30,
  timezone: "Asia/Shanghai",
  updated_at: "2026-08-20T00:00:00Z",
}

const pendingInvitation = {
  id: "inv-1",
  workspace_id: "ws-1",
  kind: "personal",
  username: "alice",
  email: "alice@example.com",
  name: "Alice",
  role: "member",
  expires_at: "2026-08-27T00:00:00Z",
  accepted_at: null,
  created_at: "2026-08-20T00:00:00Z",
}

const degradedHealth = {
  status: "degraded",
  components: {
    database: { status: "ok", detail: null },
    redis: { status: "error", detail: "timeout" },
    qdrant: { status: "not_configured", detail: null },
    storage: { status: "error", detail: "unavailable" },
    worker: { status: "ok", detail: null },
  },
  pending_tasks: 2,
  failed_logs_24h: 3,
  checked_at: "2026-08-20T12:00:00Z",
}

const logs: SystemLog[] = [
  {
    id: "log-1",
    level: "error",
    event: "request.unhandled_exception",
    message: "lookup timed out",
    path: null,
    method: null,
    status_code: 500,
    user_id: null,
    username: null,
    ip_address: null,
    details: {},
    stack_trace: null,
    created_at: "2026-08-20T12:00:00Z",
  },
  {
    id: "log-2",
    level: "warning",
    event: "workflow.execution_failed",
    message: "",
    path: null,
    method: null,
    status_code: null,
    user_id: null,
    username: null,
    ip_address: null,
    details: {},
    stack_trace: null,
    created_at: "2026-08-20T11:00:00Z",
  },
]

const sessions = [
  {
    id: "sess-1",
    created_at: "2026-08-19T00:00:00Z",
    last_used_at: "2026-08-20T09:00:00Z",
    expires_at: "2026-09-19T00:00:00Z",
    user_agent: "Mozilla/5.0 Chrome/126",
    ip_address: "10.0.0.1",
    is_current: true,
  },
  {
    id: "sess-2",
    created_at: "2026-08-18T00:00:00Z",
    last_used_at: "2026-08-19T09:00:00Z",
    expires_at: "2026-09-18T00:00:00Z",
    user_agent: null,
    ip_address: "10.0.0.2",
    is_current: false,
  },
]

const originalSetInterval = window.setInterval
const originalClearInterval = window.clearInterval
const originalAnchorClick = HTMLAnchorElement.prototype.click
const originalCreateObjectURL = URL.createObjectURL
const originalRevokeObjectURL = URL.revokeObjectURL
const testWindow = window as typeof window & {
  happyDOM: { setURL: (url: string) => void }
}

beforeEach(() => {
  notifications.length = 0
  replaced.length = 0
  sessionState.me = adminMe
  sessionState.workspaces = defaultWorkspaces
  window.setInterval = ((handler: TimerHandler, delay?: number) => {
    if (typeof handler === "function" && delay === 30_000) return 1
    return originalSetInterval(handler, delay)
  }) as typeof window.setInterval
  window.clearInterval = originalClearInterval
  testWindow.happyDOM.setURL("https://nexaflow.example/system/governance")
})

afterEach(() => {
  cleanup()
  resetFetch()
  sessionState.me = adminMe
  sessionState.workspaces = defaultWorkspaces
  window.setInterval = originalSetInterval
  window.clearInterval = originalClearInterval
  HTMLAnchorElement.prototype.click = originalAnchorClick
  URL.createObjectURL = originalCreateObjectURL
  URL.revokeObjectURL = originalRevokeObjectURL
})

function respondToConfirm(label: string) {
  const dialog = screen.getByRole("dialog", { name: "确认操作" })
  fireEvent.click(within(dialog).getByRole("button", { name: label }))
}

describe("workspace governance settings", () => {
  test("loads governance settings and inventory and saves edited limits", async () => {
    let patchBody: unknown = null
    withFetch((url, init) => {
      if (url.endsWith("/governance") && init?.method === "PATCH") {
        patchBody = JSON.parse(String(init.body)) as Record<string, unknown>
        return jsonResponse(governance)
      }
      if (url.endsWith("/inventory")) return jsonResponse(inventory)
      if (url.endsWith("/governance")) return jsonResponse(governance)
      if (url.endsWith("/invitations")) return jsonResponse([])
      throw new Error(`Unexpected request: ${url}`)
    })

    renderPage(<SystemGovernancePage section="governance" />)

    await waitFor(() => expect(screen.getByDisplayValue("10")).toBeTruthy())
    expect(screen.getByDisplayValue("100000")).toBeTruthy()
    expect(screen.getByDisplayValue("80")).toBeTruthy()
    expect(screen.getByDisplayValue("30")).toBeTruthy()
    expect(screen.getByDisplayValue("Asia/Shanghai")).toBeTruthy()
    for (const label of [
      "Agent",
      "知识库",
      "模型",
      "工具",
      "工作流",
      "活跃运行",
      "失败运行（24小时）",
      "失败任务（24小时）",
    ]) {
      expect(screen.getByText(label)).toBeTruthy()
    }
    // "成员" also appears as the selected invite role; "团队" is a nav link.
    expect(screen.getAllByText("成员").length).toBeGreaterThan(0)
    expect(screen.getAllByText("团队").length).toBeGreaterThan(0)
    expect(screen.getByText("12")).toBeTruthy()

    fireEvent.change(screen.getByLabelText("每日运行上限"), {
      target: { value: "25" },
    })
    fireEvent.change(screen.getByLabelText("月度 Token 上限"), {
      target: { value: "" },
    })
    fireEvent.change(screen.getByLabelText("数据保留天数"), {
      target: { value: "" },
    })
    fireEvent.change(screen.getByLabelText("时区"), {
      target: { value: "America/New_York" },
    })
    fireEvent.click(screen.getByRole("button", { name: "保存策略" }))

    await waitFor(() => expect(patchBody).not.toBeNull())
    expect(patchBody).toEqual({
      daily_run_limit: 25,
      monthly_token_limit: null,
      alert_threshold_percent: 80,
      retention_days: null,
      timezone: "America/New_York",
    })
    expect(notifications).toContainEqual(["success", "策略已保存"])
  })

  test("reports an error when saving governance settings fails", async () => {
    withFetch((url, init) => {
      if (url.endsWith("/governance") && init?.method === "PATCH") {
        return jsonResponse({ detail: "policy rejected" }, 422)
      }
      if (url.endsWith("/inventory")) return jsonResponse(inventory)
      if (url.endsWith("/governance")) return jsonResponse(governance)
      if (url.endsWith("/invitations")) return jsonResponse([])
      throw new Error(`Unexpected request: ${url}`)
    })

    renderPage(<SystemGovernancePage section="governance" />)
    await waitFor(() =>
      expect(screen.getByDisplayValue("Asia/Shanghai")).toBeTruthy()
    )
    fireEvent.click(screen.getByRole("button", { name: "保存策略" }))
    await waitFor(() =>
      expect(notifications).toContainEqual(["error", "policy rejected"])
    )
  })

  test("reports an error when governance settings fail to load", async () => {
    withFetch((url) => {
      if (url.endsWith("/inventory")) return jsonResponse(inventory)
      if (url.endsWith("/governance"))
        return jsonResponse({ detail: "boom" }, 500)
      if (url.endsWith("/invitations")) return jsonResponse([])
      throw new Error(`Unexpected request: ${url}`)
    })

    renderPage(<SystemGovernancePage section="governance" />)
    await waitFor(() => expect(notifications).toContainEqual(["error", "boom"]))
  })

  test("creates a personal invitation from a token when no invite_url is returned", async () => {
    let createBody: unknown = null
    withFetch((url, init) => {
      if (url.endsWith("/inventory")) return jsonResponse(inventory)
      if (url.endsWith("/governance")) return jsonResponse(governance)
      if (url.endsWith("/invitations") && init?.method === "POST") {
        createBody = JSON.parse(String(init.body)) as Record<string, unknown>
        return jsonResponse(
          {
            ...pendingInvitation,
            id: "inv-2",
            token: "token-abc",
            invite_url: null,
          },
          201
        )
      }
      if (url.endsWith("/invitations")) return jsonResponse([])
      throw new Error(`Unexpected request: ${url}`)
    })

    renderPage(<SystemGovernancePage section="governance" />)
    fireEvent.change(await screen.findByLabelText("账号"), {
      target: { value: "alice" },
    })
    fireEvent.change(screen.getByLabelText("邮箱"), {
      target: { value: "alice@example.com" },
    })
    fireEvent.change(screen.getByLabelText("姓名"), {
      target: { value: "Alice" },
    })
    fireEvent.click(screen.getByRole("button", { name: "生成邀请链接" }))

    const expectedUrl = `${window.location.origin}/invite/token-abc`
    await waitFor(() =>
      expect(screen.getByDisplayValue(expectedUrl)).toBeTruthy()
    )
    expect(createBody).toEqual({
      kind: "personal",
      username: "alice",
      email: "alice@example.com",
      name: "Alice",
      role: "member",
    })
    expect(notifications).toContainEqual(["success", "邀请已创建"])
    expect(screen.getByText("Alice · alice@example.com")).toBeTruthy()
  })

  test("switches invitation kinds, copies the link, and shows a not-configured hint", async () => {
    const originalClipboard = navigator.clipboard
    let copiedValue = ""
    let rejectCopy = false
    let resolveCopy: (() => void) | null = null
    Object.defineProperty(navigator, "clipboard", {
      value: {
        writeText: (value: string) => {
          copiedValue = value
          if (rejectCopy) return Promise.reject(new Error("denied"))
          return new Promise<void>((resolve) => {
            resolveCopy = resolve
          })
        },
      },
      configurable: true,
    })
    try {
      withFetch((url, init) => {
        if (url.endsWith("/inventory")) return jsonResponse(inventory)
        if (url.endsWith("/governance")) return jsonResponse(governance)
        if (url.endsWith("/invitations") && init?.method === "POST") {
          return jsonResponse(
            {
              ...pendingInvitation,
              id: "inv-3",
              token: "token-xyz",
              invite_url: null,
              email_delivery_status: "not_configured",
            },
            201
          )
        }
        if (url.endsWith("/invitations")) return jsonResponse([])
        throw new Error(`Unexpected request: ${url}`)
      })

      renderPage(<SystemGovernancePage section="governance" />)
      await waitFor(() =>
        expect(screen.getByRole("button", { name: "邀请方式" })).toBeTruthy()
      )
      fireEvent.pointerDown(screen.getByRole("button", { name: "邀请方式" }))
      fireEvent.click(await screen.findByRole("menuitem", { name: "通用邀请" }))
      expect(
        screen.getByText("通用链接在 7 天内可由多人注册，撤销后立即失效")
      ).toBeTruthy()
      expect(screen.queryByLabelText("账号")).toBeNull()

      fireEvent.pointerDown(screen.getByRole("button", { name: "邀请方式" }))
      fireEvent.click(await screen.findByRole("menuitem", { name: "指定成员" }))
      fireEvent.change(await screen.findByLabelText("账号"), {
        target: { value: "alice" },
      })
      fireEvent.change(screen.getByLabelText("邮箱"), {
        target: { value: "alice@example.com" },
      })
      fireEvent.change(screen.getByLabelText("姓名"), {
        target: { value: "Alice" },
      })
      fireEvent.click(screen.getByRole("button", { name: "生成邀请链接" }))

      const expectedUrl = `${window.location.origin}/invite/token-xyz`
      await waitFor(() =>
        expect(screen.getByDisplayValue(expectedUrl)).toBeTruthy()
      )
      expect(
        screen.getByText("邮件服务尚未配置，邀请邮件未发送；你仍可复制邀请链接")
      ).toBeTruthy()
      fireEvent.click(screen.getByRole("button", { name: "复制链接" }))
      await waitFor(() => expect(copiedValue).toBe(expectedUrl))
      expect(notifications).not.toContainEqual(["success", "已复制"])
      await act(async () => {
        resolveCopy?.()
        await Promise.resolve()
      })
      await waitFor(() =>
        expect(notifications).toContainEqual(["success", "已复制"])
      )

      rejectCopy = true
      fireEvent.click(screen.getByRole("button", { name: "复制链接" }))
      await waitFor(() =>
        expect(notifications).toContainEqual(["error", "复制失败"])
      )
    } finally {
      Object.defineProperty(navigator, "clipboard", {
        value: originalClipboard,
        configurable: true,
      })
    }
  })

  test("shows when a personal invitation email is queued", async () => {
    withFetch((url, init) => {
      if (url.endsWith("/inventory")) return jsonResponse(inventory)
      if (url.endsWith("/governance")) return jsonResponse(governance)
      if (url.endsWith("/invitations") && init?.method === "POST") {
        return jsonResponse(
          {
            ...pendingInvitation,
            id: "inv-4",
            token: "token-q",
            invite_url: "/invite/token-q",
            email_delivery_status: "queued",
          },
          201
        )
      }
      if (url.endsWith("/invitations")) return jsonResponse([])
      throw new Error(`Unexpected request: ${url}`)
    })

    renderPage(<SystemGovernancePage section="governance" />)
    fireEvent.change(await screen.findByLabelText("账号"), {
      target: { value: "alice" },
    })
    fireEvent.change(screen.getByLabelText("邮箱"), {
      target: { value: "alice@example.com" },
    })
    fireEvent.change(screen.getByLabelText("姓名"), {
      target: { value: "Alice" },
    })
    fireEvent.click(screen.getByRole("button", { name: "生成邀请链接" }))

    await waitFor(() =>
      expect(screen.getByText("邀请邮件已加入发送队列")).toBeTruthy()
    )
  })

  test("revokes a pending invitation after confirmation", async () => {
    let deleted = 0
    withFetch((url, init) => {
      if (url.endsWith("/inventory")) return jsonResponse(inventory)
      if (url.endsWith("/governance")) return jsonResponse(governance)
      if (url.endsWith("/invitations/inv-1") && init?.method === "DELETE") {
        deleted += 1
        return jsonResponse(null, 204)
      }
      if (url.endsWith("/invitations")) return jsonResponse([pendingInvitation])
      throw new Error(`Unexpected request: ${url}`)
    })

    renderPage(<SystemGovernancePage section="governance" />)
    await waitFor(() =>
      expect(screen.getByText("Alice · alice@example.com")).toBeTruthy()
    )
    fireEvent.click(screen.getByRole("button", { name: "撤销" }))
    respondToConfirm("撤销")

    await waitFor(() => expect(deleted).toBe(1))
    expect(notifications).toContainEqual(["success", "邀请已撤销"])
    await waitFor(() => expect(screen.getByText("已撤销或已接受")).toBeTruthy())
  })

  test("shows an empty state without manageable workspaces", async () => {
    sessionState.me = {
      ...adminMe,
      user: { ...adminMe.user, is_global_admin: false },
    }
    sessionState.workspaces = []
    withFetch(() => {
      throw new Error("Unexpected request")
    })

    renderPage(<SystemGovernancePage section="governance" />)
    expect(await screen.findByText("暂无可管理工作空间")).toBeTruthy()
  })

  test("redirects users without admin access to the apps page", async () => {
    sessionState.me = {
      ...adminMe,
      user: { ...adminMe.user, is_global_admin: false },
      memberships: [{ workspace_id: "ws-1", role: "member" }],
    }
    withFetch(() => {
      throw new Error("Unexpected request")
    })

    renderPage(<SystemGovernancePage section="governance" />)
    await waitFor(() => expect(replaced).toContain("/app/apps"))
    expect(screen.queryByText("工作空间治理")).toBeNull()
  })

  test("redirects workspace administrators from the operations section", async () => {
    sessionState.me = {
      ...adminMe,
      user: { ...adminMe.user, is_global_admin: false },
    }
    withFetch(() => {
      throw new Error("Unexpected request")
    })

    renderPage(<SystemGovernancePage section="operations" />)
    await waitFor(() => expect(replaced).toContain("/system/teams"))
  })

  test("redirects team administrators without workspace management rights from governance", async () => {
    sessionState.me = {
      ...adminMe,
      user: {
        ...adminMe.user,
        is_global_admin: false,
        teams: [
          {
            id: "team-1",
            workspace_id: "ws-1",
            name: "Platform",
            is_default: true,
            role: "admin",
          },
        ],
      },
      memberships: [{ workspace_id: "ws-1", role: "member" }],
    }
    withFetch(() => {
      throw new Error("Unexpected request")
    })

    renderPage(<SystemGovernancePage section="governance" />)
    await waitFor(() => expect(replaced).toContain("/system/teams"))
    expect(await screen.findByText("暂无可管理工作空间")).toBeTruthy()
  })
})

describe("system operation logs", () => {
  test("renders log rows, event filter options, and exports a CSV", async () => {
    let exported = 0
    HTMLAnchorElement.prototype.click = function click() {
      exported += 1
    }
    URL.createObjectURL = () => "blob:mock-logs"
    URL.revokeObjectURL = () => undefined

    withFetch((url) => {
      if (url === "/api/v1/admin/governance/health") {
        return jsonResponse({
          status: "ok",
          components: {
            database: { status: "ok", detail: null },
            redis: { status: "ok", detail: null },
            qdrant: { status: "ok", detail: null },
            storage: { status: "ok", detail: null },
            worker: { status: "ok", detail: null },
          },
          pending_tasks: 0,
          failed_logs_24h: 0,
          checked_at: "2026-08-20T12:00:00Z",
        })
      }
      if (url.startsWith("/api/v1/admin/system-logs")) {
        return jsonResponse(
          url.includes("event=workflow.execution_failed") ? [logs[1]] : logs
        )
      }
      throw new Error(`Unexpected request: ${url}`)
    })

    renderPage(<SystemGovernancePage section="operations" />)

    await waitFor(() =>
      expect(screen.getByText("lookup timed out")).toBeTruthy()
    )
    expect(screen.getAllByText("请求处理异常").length).toBeGreaterThan(0)
    // Row event label plus the empty-message fallback both render it.
    expect(screen.getAllByText("工作流执行失败").length).toBeGreaterThan(0)
    expect(screen.getByText("500")).toBeTruthy()
    expect(screen.getByText("—")).toBeTruthy()
    expect(screen.queryByText("暂无运行日志")).toBeNull()

    const eventSelect = screen.getByRole("button", { name: "筛选事件" })
    fireEvent.pointerDown(eventSelect)
    fireEvent.click(eventSelect)
    fireEvent.click(
      await screen.findByRole("menuitem", { name: "工作流执行失败" })
    )
    await waitFor(() =>
      expect(screen.queryByText("lookup timed out")).toBeNull()
    )

    fireEvent.click(screen.getByRole("button", { name: "导出" }))
    expect(exported).toBe(1)
  })

  test("reports an error when operation logs cannot be loaded", async () => {
    withFetch((url) => {
      if (url === "/api/v1/admin/governance/health") {
        return jsonResponse({
          status: "ok",
          components: {
            database: { status: "ok", detail: null },
            redis: { status: "ok", detail: null },
            qdrant: { status: "ok", detail: null },
            storage: { status: "ok", detail: null },
            worker: { status: "ok", detail: null },
          },
          pending_tasks: 0,
          failed_logs_24h: 0,
          checked_at: "2026-08-20T12:00:00Z",
        })
      }
      if (url.startsWith("/api/v1/admin/system-logs")) {
        return jsonResponse({ detail: "logs offline" }, 503)
      }
      throw new Error(`Unexpected request: ${url}`)
    })

    renderPage(<SystemGovernancePage section="operations" />)
    await waitFor(() =>
      expect(notifications).toContainEqual(["error", "logs offline"])
    )
    expect(await screen.findByText("暂无运行日志")).toBeTruthy()
  })

  test("renders degraded component details and refreshes health on the interval", async () => {
    let intervalHandler: (() => void) | null = null
    let healthFails = true
    window.setInterval = ((handler: TimerHandler, delay?: number) => {
      if (typeof handler === "function" && delay === 30_000) {
        intervalHandler = () => handler()
      }
      return 1
    }) as typeof window.setInterval
    withFetch((url) => {
      if (url === "/api/v1/admin/governance/health") {
        if (healthFails) {
          return jsonResponse({ detail: "health offline" }, 503)
        }
        return jsonResponse(degradedHealth)
      }
      if (url.startsWith("/api/v1/admin/system-logs")) return jsonResponse([])
      throw new Error(`Unexpected request: ${url}`)
    })

    renderPage(<SystemGovernancePage section="operations" />)
    await waitFor(() =>
      expect(notifications).toContainEqual(["error", "health offline"])
    )
    expect(screen.getAllByText("未知").length).toBeGreaterThan(0)

    healthFails = false
    await act(async () => {
      intervalHandler?.()
      await Promise.resolve()
    })

    await waitFor(() => expect(screen.getByText("检查超时")).toBeTruthy())
    expect(screen.getByText("服务不可用")).toBeTruthy()
    expect(screen.getByText("未配置")).toBeTruthy()
    expect(screen.getAllByText("异常").length).toBe(2)
    expect(screen.getAllByText("正常").length).toBe(2)
    expect(screen.getByText("2")).toBeTruthy()
    expect(screen.getByText("3")).toBeTruthy()
  })
})

describe("session security panel", () => {
  test("lets a global administrator manage another user's sessions", async () => {
    const calls: Array<{ method: string; url: string }> = []
    const otherUserSessions = [
      {
        id: "sess-3",
        created_at: "2026-08-18T00:00:00Z",
        last_used_at: "2026-08-20T10:00:00Z",
        expires_at: "2026-09-18T00:00:00Z",
        user_agent: "Safari/17",
        ip_address: "10.0.0.9",
        is_current: false,
      },
    ]
    withFetch((url, init) => {
      const method = init?.method ?? "GET"
      calls.push({ method, url })
      if (url === "/api/v1/admin/users" && method === "GET") {
        return jsonResponse([
          adminMe.user,
          { ...adminMe.user, id: "u-2", username: "other", name: "Other User" },
        ])
      }
      if (url === "/api/v1/admin/users/u-1/sessions" && method === "GET") {
        return jsonResponse(sessions)
      }
      if (url === "/api/v1/admin/users/u-2/sessions" && method === "GET") {
        return jsonResponse(otherUserSessions)
      }
      if (
        url === "/api/v1/admin/users/u-2/sessions/sess-3" &&
        method === "DELETE"
      ) {
        return jsonResponse(null, 204)
      }
      if (url === "/api/v1/admin/users/u-2/sessions" && method === "DELETE") {
        return jsonResponse(null, 204)
      }
      throw new Error(`Unexpected request: ${method} ${url}`)
    })

    renderPage(<SystemGovernancePage section="security" />)
    await waitFor(() => expect(screen.getByText(/Chrome\/126/)).toBeTruthy())
    expect(screen.getByText("当前会话")).toBeTruthy()
    expect(screen.getByText("10.0.0.2")).toBeTruthy()

    const userSelect = screen.getByRole("button", { name: "选择用户" })
    fireEvent.pointerDown(userSelect)
    fireEvent.click(userSelect)
    fireEvent.click(
      await screen.findByRole("menuitem", { name: "Other User (other)" })
    )

    await waitFor(() => expect(screen.getByText("Safari/17")).toBeTruthy())

    fireEvent.click(screen.getByRole("button", { name: "撤销" }))
    respondToConfirm("撤销")
    await waitFor(() =>
      expect(
        calls.some(
          (c) =>
            c.method === "DELETE" &&
            c.url.endsWith("/users/u-2/sessions/sess-3")
        )
      ).toBe(true)
    )
    expect(notifications).toContainEqual(["success", "会话已撤销"])
    await waitFor(() => expect(screen.queryByText("Safari/17")).toBeNull())

    fireEvent.click(screen.getByRole("button", { name: "撤销其他会话" }))
    respondToConfirm("撤销")
    await waitFor(() =>
      expect(
        calls.some(
          (c) =>
            c.method === "DELETE" &&
            c.url === "/api/v1/admin/users/u-2/sessions"
        )
      ).toBe(true)
    )
    await waitFor(() =>
      expect(notifications).toContainEqual(["success", "其他会话已撤销"])
    )

    const refreshButton = screen.getByRole("button", { name: "刷新" })
    fireEvent.click(refreshButton)
    await waitFor(() =>
      expect(
        calls.filter(
          (c) =>
            c.method === "GET" && c.url === "/api/v1/admin/users/u-2/sessions"
        ).length
      ).toBeGreaterThanOrEqual(2)
    )
  })

  test("lets a workspace administrator revoke their own sessions", async () => {
    sessionState.me = {
      ...adminMe,
      user: { ...adminMe.user, is_global_admin: false },
    }
    const calls: Array<{ method: string; url: string }> = []
    withFetch((url, init) => {
      const method = init?.method ?? "GET"
      calls.push({ method, url })
      if (url === "/api/v1/auth/sessions" && method === "GET") {
        return jsonResponse(sessions)
      }
      if (url === "/api/v1/auth/sessions/sess-1" && method === "DELETE") {
        return jsonResponse(null, 204)
      }
      if (url === "/api/v1/auth/sessions/revoke-others" && method === "POST") {
        return jsonResponse(null, 204)
      }
      throw new Error(`Unexpected request: ${method} ${url}`)
    })

    renderPage(<SystemGovernancePage section="security" />)
    await waitFor(() => expect(screen.getByText(/Chrome\/126/)).toBeTruthy())
    expect(screen.queryByRole("button", { name: "选择用户" })).toBeNull()

    fireEvent.click(screen.getAllByRole("button", { name: "撤销" })[0])
    respondToConfirm("撤销")
    await waitFor(() =>
      expect(
        calls.some(
          (c) =>
            c.method === "DELETE" && c.url === "/api/v1/auth/sessions/sess-1"
        )
      ).toBe(true)
    )
    await waitFor(() => expect(screen.queryByText(/Chrome\/126/)).toBeNull())

    fireEvent.click(screen.getByRole("button", { name: "撤销其他会话" }))
    respondToConfirm("撤销")
    await waitFor(() =>
      expect(
        calls.some(
          (c) =>
            c.method === "POST" &&
            c.url === "/api/v1/auth/sessions/revoke-others"
        )
      ).toBe(true)
    )
  })

  test("reports errors while loading and revoking sessions", async () => {
    sessionState.me = {
      ...adminMe,
      user: { ...adminMe.user, is_global_admin: false },
    }
    withFetch((url, init) => {
      const method = init?.method ?? "GET"
      if (url === "/api/v1/auth/sessions" && method === "GET") {
        return jsonResponse([{ ...sessions[0] }])
      }
      if (url === "/api/v1/auth/sessions/sess-1" && method === "DELETE") {
        return jsonResponse({ detail: "revoke failed" }, 500)
      }
      throw new Error(`Unexpected request: ${method} ${url}`)
    })

    renderPage(<SystemGovernancePage section="security" />)
    await waitFor(() => expect(screen.getByText(/Chrome\/126/)).toBeTruthy())
    fireEvent.click(screen.getByRole("button", { name: "撤销" }))
    respondToConfirm("撤销")
    await waitFor(() =>
      expect(notifications).toContainEqual(["error", "revoke failed"])
    )
    expect(screen.getByText(/Chrome\/126/)).toBeTruthy()
  })
})
