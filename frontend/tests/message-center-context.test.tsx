/* @jsxImportSource react */
import { afterEach, describe, expect, mock, test } from "bun:test"

import {
  MessageCenterProvider,
  useMessageCenter,
} from "@/contexts/message-center-context"
import {
  cleanup,
  fireEvent,
  makeSession,
  mockUseSession,
  renderPage,
  screen,
  waitFor,
} from "./helpers/dom"

let unreadRequests = 0
let expiresSoon = true
let readFails = false
const notifications: Array<[string, string]> = []

mockUseSession(
  makeSession({
    notify: (kind: string, message: string) => {
      notifications.push([kind, message])
    },
  })
)
mock.module("@/lib/api/messages", () => ({
  listMessages: async () => ({ items: [], total: 0 }),
  getUnreadMessageCount: async () => {
    unreadRequests += 1
    if (!expiresSoon) return { count: 1, next_expiration_at: null }
    if (unreadRequests === 1) {
      return {
        count: 1,
        next_expiration_at: new Date(Date.now() + 10).toISOString(),
      }
    }
    return { count: 0, next_expiration_at: null }
  },
  markAllMessagesRead: async () => {
    if (readFails) throw new Error("read update failed")
  },
  markMessageRead: async () => {
    if (readFails) throw new Error("read update failed")
  },
  observeMessageStream: async (
    _token: string,
    _workspaceId: string | null,
    signal: AbortSignal
  ) =>
    await new Promise<void>((resolve) => {
      signal.addEventListener("abort", () => resolve(), { once: true })
    }),
}))

function UnreadCount() {
  const { unreadCount, markRead, markAllRead } = useMessageCenter()
  return (
    <>
      <span>{unreadCount}</span>
      <button onClick={() => void markAllRead().catch(() => undefined)}>
        read-all
      </button>
      <button onClick={() => void markRead("message-1").catch(() => undefined)}>
        read-one
      </button>
    </>
  )
}

afterEach(() => {
  cleanup()
  unreadRequests = 0
  expiresSoon = true
  readFails = false
  notifications.length = 0
})

describe("MessageCenterProvider", () => {
  test("refreshes when the next visible announcement expires", async () => {
    renderPage(
      <MessageCenterProvider>
        <UnreadCount />
      </MessageCenterProvider>
    )

    await screen.findByText("1")
    await waitFor(() => expect(unreadRequests).toBeGreaterThanOrEqual(2), {
      timeout: 1500,
    })
    expect(screen.getByText("0")).toBeTruthy()
    expect(notifications).toEqual([])
  })

  test.each([false, true])(
    "reports bulk read outcome when failure is %s",
    async (fails) => {
      expiresSoon = false
      readFails = fails
      renderPage(
        <MessageCenterProvider>
          <UnreadCount />
        </MessageCenterProvider>
      )
      await screen.findByText("1")
      fireEvent.click(screen.getByText("read-all"))
      await waitFor(() =>
        expect(notifications).toEqual([
          fails
            ? ["error", "read update failed"]
            : ["success", "全部消息已标为已读"],
        ])
      )
      if (!fails) {
        fireEvent.click(screen.getByText("read-all"))
        expect(notifications).toHaveLength(1)
      }
    }
  )

  test("reports failed read updates when opening a message", async () => {
    expiresSoon = false
    readFails = true
    renderPage(
      <MessageCenterProvider>
        <UnreadCount />
      </MessageCenterProvider>
    )
    await screen.findByText("1")
    fireEvent.click(screen.getByText("read-one"))
    await waitFor(() =>
      expect(notifications).toEqual([["error", "read update failed"]])
    )
  })
})
