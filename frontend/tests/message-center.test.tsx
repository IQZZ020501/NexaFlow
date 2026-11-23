/* @jsxImportSource react */
import { afterEach, describe, expect, mock, test } from "bun:test"

import {
  MessageCenter,
  MessagesPage,
} from "@/components/messages/message-center"
import type { MessageItem } from "@/lib/api/messages"
import {
  cleanup,
  fireEvent,
  mockNextNavigation,
  mockUseSession,
  renderPage,
  screen,
  waitFor,
  within,
} from "./helpers/dom"

const pushCalls: string[] = []
const markReadCalls: string[] = []
const listMessageCalls: Array<{ limit?: number; offset?: number }> = []
let listMessageTotal = 1

const message: MessageItem = {
  id: "announcement-1",
  kind: "announcement",
  scope_type: "global",
  workspace_id: null,
  title: "系统维护公告",
  body: "今晚十点维护系统。\n\n**预计持续 30 分钟。**",
  severity: "warning",
  pinned: true,
  published_at: "2026-09-07T15:15:00Z",
  expires_at: null,
  is_read: false,
  read_at: null,
  created_at: "2026-09-07T15:00:00Z",
}

const notificationMessage: MessageItem = {
  id: "notif-1",
  kind: "notification",
  scope_type: "personal",
  workspace_id: "ws-1",
  automation_id: "auto-9",
  execution_id: "exec-42",
  run_id: "run-7",
  event_type: "awaiting_approval",
  automation_name: "日报助手",
  target_app_id: "app-1",
  target_app_type: "agent",
  trigger_source: "schedule",
  metadata: {},
  title: "自动化任务等待审批：日报助手",
  body: "触发来源：Schedule；等待工具调用确认。",
  severity: "warning",
  pinned: false,
  published_at: "2026-09-07T16:00:00Z",
  expires_at: null,
  is_read: false,
  read_at: null,
  created_at: "2026-09-07T16:00:00Z",
}

let activeMessages: MessageItem[] = [message]

const messageCenter = {
  get messages() {
    return activeMessages
  },
  get unreadCount() {
    return activeMessages.filter((item) => !item.is_read).length
  },
  refreshVersion: 0,
  isLoading: false,
  error: null,
  refresh: async () => undefined,
  markRead: async (messageId: string) => {
    markReadCalls.push(messageId)
  },
  markAllRead: async () => undefined,
}

mockNextNavigation({ push: (href) => pushCalls.push(href) })
mockUseSession()
mock.module("@/contexts/message-center-context", () => ({
  useMessageCenter: () => messageCenter,
  useOptionalMessageCenter: () => messageCenter,
}))
mock.module("@/lib/api/messages", () => ({
  listMessages: async (
    _token: string,
    _workspaceId: string | null,
    options: { limit?: number; offset?: number } = {}
  ) => {
    listMessageCalls.push(options)
    return { items: activeMessages, total: listMessageTotal }
  },
}))

afterEach(() => {
  cleanup()
  pushCalls.length = 0
  markReadCalls.length = 0
  listMessageCalls.length = 0
  listMessageTotal = 1
  activeMessages = [message]
})

describe("MessageCenter", () => {
  test("opens a floating message detail instead of navigating", async () => {
    renderPage(<MessageCenter />)

    fireEvent.pointerDown(screen.getByLabelText("打开消息中心"))
    const menu = await screen.findByRole("menu")
    expect(within(menu).queryByText("预计持续 30 分钟。")).toBeNull()
    expect(
      within(menu).getByText("未读消息").classList.contains("sr-only")
    ).toBe(true)
    fireEvent.click(within(menu).getByText("系统维护公告"))

    const dialog = await screen.findByRole("dialog")
    expect(within(dialog).getByRole("heading").textContent).toBe("系统维护公告")
    expect(within(dialog).getByText("预计持续 30 分钟。")).toBeTruthy()
    expect(within(dialog).getByText("全局公告")).toBeTruthy()
    expect(within(dialog).getByText("警告")).toBeTruthy()
    expect(pushCalls).toEqual([])
    await waitFor(() => expect(markReadCalls).toEqual(["announcement-1"]))

    fireEvent.click(within(dialog).getByRole("button", { name: "关闭" }))
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull())
  })

  test("keeps the view-all entry as page navigation", async () => {
    renderPage(<MessageCenter />)

    fireEvent.pointerDown(screen.getByLabelText("打开消息中心"))
    const menu = await screen.findByRole("menu")
    fireEvent.click(within(menu).getByText("查看全部消息"))

    expect(pushCalls).toEqual(["/app/messages"])
  })

  test("shows only message titles on the full page and opens the detail dialog", async () => {
    renderPage(<MessagesPage />)

    expect(screen.queryByText("预计持续 30 分钟。")).toBeNull()
    fireEvent.click(await screen.findByRole("button", { name: /系统维护公告/ }))

    const dialog = await screen.findByRole("dialog")
    expect(within(dialog).getByText("预计持续 30 分钟。")).toBeTruthy()
  })

  test("pages through every message reported by the API", async () => {
    listMessageTotal = 21
    renderPage(<MessagesPage />)

    await screen.findByRole("button", { name: /系统维护公告/ })
    fireEvent.click(screen.getByRole("button", { name: "下一页" }))

    await waitFor(() =>
      expect(listMessageCalls).toContainEqual({ limit: 20, offset: 20 })
    )
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "2" }).getAttribute("aria-current")
      ).toBe("page")
    )
  })

  test("navigates to the automation execution detail when clicking a task notification", async () => {
    activeMessages = [notificationMessage]
    renderPage(<MessageCenter />)

    fireEvent.pointerDown(screen.getByLabelText("打开消息中心"))
    const menu = await screen.findByRole("menu")
    expect(within(menu).queryByText(notificationMessage.body)).toBeNull()
    fireEvent.click(within(menu).getByText(notificationMessage.title))

    expect(pushCalls).toEqual(["/app/automations/auto-9?execution=exec-42"])
    expect(screen.queryByRole("dialog")).toBeNull()
    await waitFor(() => expect(markReadCalls).toEqual(["notif-1"]))
  })

  test("navigates from full messages page on task notification click", async () => {
    activeMessages = [notificationMessage]
    renderPage(<MessagesPage />)

    fireEvent.click(
      await screen.findByRole("button", {
        name: /自动化任务等待审批：日报助手/,
      })
    )

    expect(pushCalls).toEqual(["/app/automations/auto-9?execution=exec-42"])
    expect(screen.queryByRole("dialog")).toBeNull()
    await waitFor(() => expect(markReadCalls).toEqual(["notif-1"]))
  })
})
