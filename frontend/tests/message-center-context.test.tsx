/* @jsxImportSource react */
import { afterEach, describe, expect, mock, test } from "bun:test"

import {
  MessageCenterProvider,
  useMessageCenter,
} from "@/contexts/message-center-context"
import {
  cleanup,
  mockUseSession,
  renderPage,
  screen,
  waitFor,
} from "./helpers/dom"

let unreadRequests = 0

mockUseSession()
mock.module("@/lib/api/messages", () => ({
  listMessages: async () => ({ items: [], total: 0 }),
  getUnreadMessageCount: async () => {
    unreadRequests += 1
    if (unreadRequests === 1) {
      return {
        count: 1,
        next_expiration_at: new Date(Date.now() + 10).toISOString(),
      }
    }
    return { count: 0, next_expiration_at: null }
  },
  markAllMessagesRead: async () => undefined,
  markMessageRead: async () => undefined,
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
  const { unreadCount } = useMessageCenter()
  return <span>{unreadCount}</span>
}

afterEach(() => {
  cleanup()
  unreadRequests = 0
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
  })
})
