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

const messageCenter = {
  messages: [message],
  unreadCount: 1,
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
    return { items: [message], total: listMessageTotal }
  },
}))

afterEach(() => {
  cleanup()
  pushCalls.length = 0
  markReadCalls.length = 0
  listMessageCalls.length = 0
  listMessageTotal = 1
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
})
