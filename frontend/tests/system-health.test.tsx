/* @jsxImportSource react */
import { afterEach, beforeEach, describe, expect, test } from "bun:test"
import { act } from "@testing-library/react"

import { SystemGovernancePage } from "@/components/system/system-governance-page"
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
  setFetch,
  waitFor,
  withFetch,
  within,
} from "./helpers/dom"

const notifications: Array<[string, string]> = []
const session = makeSession({
  notify: (kind: string, message: string) => notifications.push([kind, message]),
})
mockUseSession(session)
mockNextNavigation({ pathname: "/system/operations" })
mockNextLink()

const originalSetInterval = window.setInterval
const originalClearInterval = window.clearInterval
let intervalHandler: (() => void) | null = null
let intervalDelay = 0

const health = {
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
  pending_graph_tasks: 4,
  failed_graph_tasks_24h: 1,
  pending_graph_profile_repairs: 2,
  checked_at: "2026-08-20T12:00:00Z",
}

function healthCard(label: string) {
  const card = screen.getByText(label).parentElement
  if (!card) throw new Error(`Missing health card: ${label}`)
  return within(card)
}

beforeEach(() => {
  notifications.length = 0
  intervalHandler = null
  intervalDelay = 0
  window.setInterval = ((handler: TimerHandler, delay?: number) => {
    if (typeof handler === "function" && delay === 30_000) {
      intervalHandler = () => handler()
      intervalDelay = delay
    }
    return 1
  }) as typeof window.setInterval
  window.clearInterval = (() => undefined) as typeof window.clearInterval
})

afterEach(() => {
  cleanup()
  resetFetch()
  window.setInterval = originalSetInterval
  window.clearInterval = originalClearInterval
})

describe("system health", () => {
  test("renders live component states and refreshes health every 30 seconds", async () => {
    let healthRequests = 0
    withFetch((url) => {
      if (url === "/api/v1/admin/governance/health") {
        healthRequests += 1
        return jsonResponse(health)
      }
      if (url.startsWith("/api/v1/admin/system-logs")) return jsonResponse([])
      throw new Error(`Unexpected request: ${url}`)
    })

    renderPage(<SystemGovernancePage section="operations" />)

    await waitFor(() => expect(healthCard("Redis").getByText("异常")).toBeTruthy())
    expect(healthCard("数据库").getByText("正常")).toBeTruthy()
    expect(healthCard("向量数据库").getByText("未配置")).toBeTruthy()
    expect(healthCard("文件存储").getByText("服务不可用")).toBeTruthy()
    expect(healthCard("后台 Worker").getByText("正常")).toBeTruthy()
    expect(healthCard("图谱任务").getByText("4")).toBeTruthy()
    expect(healthCard("待清理知识页").getByText("2")).toBeTruthy()
    expect(healthCard("Redis").getByText("检查超时")).toBeTruthy()
    expect(screen.getByText(/最后检查：/)).toBeTruthy()
    expect(screen.getByText(/每 30 秒自动刷新/)).toBeTruthy()
    expect(intervalDelay).toBe(30_000)

    await act(async () => {
      intervalHandler?.()
      await Promise.resolve()
    })
    await waitFor(() => expect(healthRequests).toBe(2))
  })

  test("clears stale health when a refresh cannot reach the endpoint", async () => {
    withFetch((url) => {
      if (url === "/api/v1/admin/governance/health") return jsonResponse(health)
      if (url.startsWith("/api/v1/admin/system-logs")) return jsonResponse([])
      throw new Error(`Unexpected request: ${url}`)
    })
    renderPage(<SystemGovernancePage section="operations" />)
    await waitFor(() => expect(healthCard("数据库").getByText("正常")).toBeTruthy())

    setFetch((url) => {
      if (url === "/api/v1/admin/governance/health") {
        return jsonResponse({ detail: "unavailable" }, 503)
      }
      if (url.startsWith("/api/v1/admin/system-logs")) return jsonResponse([])
      throw new Error(`Unexpected request: ${url}`)
    })
    fireEvent.click(screen.getByRole("button", { name: "刷新" }))

    await waitFor(() => expect(healthCard("数据库").getByText("未知")).toBeTruthy())
    for (const label of ["Redis", "向量数据库", "文件存储", "后台 Worker"]) {
      expect(healthCard(label).getByText("未知")).toBeTruthy()
    }
    expect(notifications.length).toBe(1)
  })

  test("ignores an older health result after a newer refresh fails", async () => {
    let healthRequests = 0
    let resolveOlderHealth: ((response: Response) => void) | null = null
    withFetch((url) => {
      if (url === "/api/v1/admin/governance/health") {
        healthRequests += 1
        if (healthRequests === 1) return jsonResponse(health)
        if (healthRequests === 2) {
          return new Promise<Response>((resolve) => {
            resolveOlderHealth = resolve
          })
        }
        return jsonResponse({ detail: "unavailable" }, 503)
      }
      if (url.startsWith("/api/v1/admin/system-logs")) return jsonResponse([])
      throw new Error(`Unexpected request: ${url}`)
    })

    renderPage(<SystemGovernancePage section="operations" />)
    await waitFor(() => expect(healthCard("数据库").getByText("正常")).toBeTruthy())

    await act(async () => {
      intervalHandler?.()
      await Promise.resolve()
    })
    await waitFor(() => expect(healthRequests).toBe(2))

    fireEvent.click(screen.getByRole("button", { name: "刷新" }))
    await waitFor(() => expect(healthRequests).toBe(3))
    await waitFor(() => expect(healthCard("数据库").getByText("未知")).toBeTruthy())
    expect(notifications).toContainEqual(["error", "unavailable"])

    await act(async () => {
      resolveOlderHealth?.(jsonResponse(health))
      await Promise.resolve()
    })
    await waitFor(() => expect(healthCard("数据库").getByText("未知")).toBeTruthy())
  })
})
