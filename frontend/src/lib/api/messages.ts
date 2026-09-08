import { apiUrl, request, requestPage, type ApiError } from "@/lib/api-client"

export type MessageSeverity = "info" | "warning" | "critical"

export type MessageItem = {
  id: string
  kind: "announcement"
  scope_type: "global" | "workspace"
  workspace_id: string | null
  title: string
  body: string
  severity: MessageSeverity
  pinned: boolean
  published_at: string
  expires_at: string | null
  is_read: boolean
  read_at: string | null
  created_at: string
}

export type MessageStreamEvent = {
  type:
    "announcement.published" | "announcement.updated" | "announcement.archived"
  message_id: string
  scope_type: "global" | "workspace"
  workspace_id: string | null
}

function workspaceQuery(workspaceId: string | null) {
  return workspaceId ? `?workspace_id=${encodeURIComponent(workspaceId)}` : ""
}

export function listMessages(token: string, workspaceId: string | null) {
  const query = new URLSearchParams({ limit: "50" })
  if (workspaceId) query.set("workspace_id", workspaceId)
  return requestPage<MessageItem>(`/api/v1/messages?${query.toString()}`, {
    token,
  })
}

export function getUnreadMessageCount(
  token: string,
  workspaceId: string | null
) {
  return request<{ count: number }>(
    `/api/v1/messages/unread-count${workspaceQuery(workspaceId)}`,
    { token }
  )
}

export function markMessageRead(
  token: string,
  messageId: string,
  workspaceId: string | null
) {
  return request<void>(
    `/api/v1/messages/${messageId}/read${workspaceQuery(workspaceId)}`,
    { method: "POST", token }
  )
}

export function markAllMessagesRead(token: string, workspaceId: string | null) {
  return request<void>(
    `/api/v1/messages/read-all${workspaceQuery(workspaceId)}`,
    {
      method: "POST",
      token,
    }
  )
}

function streamQuery(
  workspaceId: string | null,
  globalAfter: string | null,
  workspaceAfter: string | null
) {
  const query = new URLSearchParams()
  if (workspaceId) query.set("workspace_id", workspaceId)
  if (globalAfter) query.set("global_after", globalAfter)
  if (workspaceAfter) query.set("workspace_after", workspaceAfter)
  return query.toString() ? `?${query.toString()}` : ""
}

function waitForReconnect(delayMs: number, signal: AbortSignal) {
  return new Promise<void>((resolve, reject) => {
    if (signal.aborted) {
      reject(signal.reason ?? new DOMException("Aborted", "AbortError"))
      return
    }
    const timer = window.setTimeout(resolve, delayMs)
    signal.addEventListener(
      "abort",
      () => {
        window.clearTimeout(timer)
        reject(signal.reason ?? new DOMException("Aborted", "AbortError"))
      },
      { once: true }
    )
  })
}

async function consumeMessageStream(
  response: Response,
  signal: AbortSignal,
  onEvent: (event: MessageStreamEvent) => void,
  cursors: { globalAfter: string | null; workspaceAfter: string | null }
) {
  if (!response.body) {
    throw new Error("Message stream did not return a response body.")
  }
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ""
  let eventName = ""
  let eventId = ""
  let dataLines: string[] = []
  let unavailable = false

  const dispatch = () => {
    if (!dataLines.length) return
    const raw = dataLines.join("\n")
    dataLines = []
    if (eventName === "unavailable") {
      unavailable = true
      eventName = ""
      eventId = ""
      return
    }
    const event = JSON.parse(raw) as MessageStreamEvent
    if (eventId.startsWith("global:")) {
      cursors.globalAfter = eventId.slice("global:".length)
    } else if (eventId.startsWith("workspace:")) {
      cursors.workspaceAfter = eventId.slice("workspace:".length)
    }
    onEvent(event)
    eventName = ""
    eventId = ""
  }

  const consumeLine = (line: string) => {
    if (!line) {
      dispatch()
      return
    }
    if (line.startsWith("event:")) eventName = line.slice(6).trim()
    else if (line.startsWith("id:")) eventId = line.slice(3).trim()
    else if (line.startsWith("data:")) dataLines.push(line.slice(5).trimStart())
  }

  while (!signal.aborted) {
    const { done, value } = await reader.read()
    buffer += decoder.decode(value, { stream: !done })
    const lines = buffer.split("\n")
    buffer = lines.pop() ?? ""
    lines.forEach(consumeLine)
    if (done) break
  }
  if (buffer) consumeLine(buffer)
  dispatch()
  return unavailable
}

export async function observeMessageStream(
  token: string,
  workspaceId: string | null,
  signal: AbortSignal,
  onEvent: (event: MessageStreamEvent) => void
) {
  const cursors = {
    globalAfter: null as string | null,
    workspaceAfter: null as string | null,
  }
  let reconnectDelay = 500

  while (!signal.aborted) {
    try {
      const response = await fetch(
        apiUrl(
          `/api/v1/messages/stream${streamQuery(
            workspaceId,
            cursors.globalAfter,
            cursors.workspaceAfter
          )}`
        ),
        {
          headers: {
            Authorization: `Bearer ${token}`,
            Accept: "text/event-stream",
          },
          credentials: "include",
          signal,
        }
      )
      if (!response.ok) {
        const message = `Message stream failed with status ${response.status}.`
        const error = Object.assign(new Error(message), {
          status: response.status,
        }) as ApiError
        if (response.status < 500 && response.status !== 429) throw error
        await waitForReconnect(reconnectDelay, signal)
        reconnectDelay = Math.min(reconnectDelay * 2, 5000)
        continue
      }

      const unavailable = await consumeMessageStream(
        response,
        signal,
        onEvent,
        cursors
      )
      reconnectDelay = unavailable ? 5000 : 500
    } catch (error) {
      if (signal.aborted) return
      if (error instanceof Error && "status" in error) {
        const status = Number((error as { status?: unknown }).status)
        if (status < 500 && status !== 429) throw error
      }
    }
    await waitForReconnect(reconnectDelay, signal)
    reconnectDelay = Math.min(reconnectDelay * 2, 5000)
  }
}
