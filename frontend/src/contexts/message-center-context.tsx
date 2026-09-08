"use client"

import * as React from "react"

import {
  getUnreadMessageCount,
  listMessages,
  markAllMessagesRead,
  markMessageRead,
  observeMessageStream,
  type MessageItem,
} from "@/lib/api/messages"
import { ApiError } from "@/lib/api-client"
import { useSession } from "@/contexts/session-context"

type MessageCenterContextValue = {
  messages: MessageItem[]
  unreadCount: number
  isLoading: boolean
  error: ApiError | Error | null
  refresh: () => Promise<void>
  markRead: (messageId: string) => Promise<void>
  markAllRead: () => Promise<void>
}

const MessageCenterContext = React.createContext<
  MessageCenterContextValue | undefined
>(undefined)

export function MessageCenterProvider({
  children,
}: {
  children: React.ReactNode
}) {
  const { token, selectedWorkspaceId, mustChangePassword } = useSession()
  const [messages, setMessages] = React.useState<MessageItem[]>([])
  const [unreadCount, setUnreadCount] = React.useState(0)
  const [isLoading, setIsLoading] = React.useState(false)
  const [error, setError] = React.useState<ApiError | Error | null>(null)
  const requestId = React.useRef(0)

  const refresh = React.useCallback(async () => {
    if (!token || mustChangePassword) {
      requestId.current += 1
      setMessages([])
      setUnreadCount(0)
      setError(null)
      setIsLoading(false)
      return
    }
    const currentRequestId = requestId.current + 1
    requestId.current = currentRequestId
    setIsLoading(true)
    try {
      const [messagePage, unread] = await Promise.all([
        listMessages(token, selectedWorkspaceId),
        getUnreadMessageCount(token, selectedWorkspaceId),
      ])
      if (currentRequestId === requestId.current) {
        setMessages(messagePage.items)
        setUnreadCount(unread.count)
        setError(null)
      }
    } catch (nextError) {
      if (currentRequestId === requestId.current) {
        setError(
          nextError instanceof Error ? nextError : new Error(String(nextError))
        )
      }
    } finally {
      if (currentRequestId === requestId.current) setIsLoading(false)
    }
  }, [mustChangePassword, selectedWorkspaceId, token])

  React.useEffect(() => {
    const timer = window.setTimeout(() => {
      void refresh()
    }, 0)
    return () => window.clearTimeout(timer)
  }, [refresh])

  React.useEffect(() => {
    if (!token || mustChangePassword) return
    const controller = new AbortController()
    void observeMessageStream(
      token,
      selectedWorkspaceId,
      controller.signal,
      () => {
        void refresh()
      }
    ).catch((streamError: unknown) => {
      if (!controller.signal.aborted) {
        setError(
          streamError instanceof Error
            ? streamError
            : new Error(String(streamError))
        )
      }
    })
    return () => controller.abort()
  }, [mustChangePassword, refresh, selectedWorkspaceId, token])

  const markRead = React.useCallback(
    async (messageId: string) => {
      if (!token) return
      const current = messages.find((message) => message.id === messageId)
      if (!current || current.is_read) return
      setMessages((items) =>
        items.map((message) =>
          message.id === messageId
            ? { ...message, is_read: true, read_at: new Date().toISOString() }
            : message
        )
      )
      setUnreadCount((count) => Math.max(0, count - 1))
      try {
        await markMessageRead(token, messageId, selectedWorkspaceId)
      } catch (nextError) {
        void refresh()
        throw nextError
      }
    },
    [messages, refresh, selectedWorkspaceId, token]
  )

  const markAllRead = React.useCallback(async () => {
    if (!token || unreadCount === 0) return
    setMessages((items) =>
      items.map((message) =>
        message.is_read
          ? message
          : { ...message, is_read: true, read_at: new Date().toISOString() }
      )
    )
    setUnreadCount(0)
    try {
      await markAllMessagesRead(token, selectedWorkspaceId)
    } catch (nextError) {
      void refresh()
      throw nextError
    }
  }, [refresh, selectedWorkspaceId, token, unreadCount])

  const value = React.useMemo(
    () => ({
      messages,
      unreadCount,
      isLoading,
      error,
      refresh,
      markRead,
      markAllRead,
    }),
    [error, isLoading, markAllRead, markRead, messages, refresh, unreadCount]
  )

  return (
    <MessageCenterContext.Provider value={value}>
      {children}
    </MessageCenterContext.Provider>
  )
}

export function useMessageCenter() {
  const context = useOptionalMessageCenter()
  if (!context) {
    throw new Error(
      "useMessageCenter must be used within MessageCenterProvider"
    )
  }
  return context
}

export function useOptionalMessageCenter() {
  return React.useContext(MessageCenterContext)
}
