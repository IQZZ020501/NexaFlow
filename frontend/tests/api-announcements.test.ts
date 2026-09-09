import { afterEach, describe, expect, test } from "bun:test"

import {
  archiveAnnouncement,
  createAnnouncement,
  listAnnouncements,
  publishAnnouncement,
  updateAnnouncement,
  type Announcement,
} from "@/lib/api/announcements"
import {
  getUnreadMessageCount,
  listMessages,
  markAllMessagesRead,
  markMessageRead,
} from "@/lib/api/messages"
import { resetFetch, withFetch } from "./helpers/dom"

const TOKEN = "announcement-token"

type RecordedCall = {
  url: string
  method: string
  body: string | null
}

let calls: RecordedCall[] = []

function install(data: unknown, total?: number) {
  calls = []
  withFetch((url, init) => {
    calls.push({
      url,
      method: init?.method ?? "GET",
      body: typeof init?.body === "string" ? init.body : null,
    })
    if (init?.method === "POST" && url.includes("/read")) {
      return new Response(null, { status: 204 })
    }
    return new Response(JSON.stringify(data), {
      headers: {
        "Content-Type": "application/json",
        ...(total === undefined ? {} : { "X-Total-Count": String(total) }),
      },
    })
  })
}

function lastCall() {
  return calls[calls.length - 1]
}

const announcement: Announcement = {
  id: "announcement-1",
  scope_type: "global",
  workspace_id: null,
  title: "Maintenance",
  body: "Scheduled maintenance",
  severity: "warning",
  pinned: true,
  status: "draft",
  published_at: null,
  expires_at: null,
  created_by_user_id: "user-1",
  updated_by_user_id: "user-1",
  created_at: "2026-09-07T00:00:00Z",
  updated_at: "2026-09-07T00:00:00Z",
}

afterEach(() => resetFetch())

describe("announcement administration API", () => {
  test("uses the global administration endpoints", async () => {
    install([announcement], 1)
    const listed = await listAnnouncements(TOKEN, "global", null)
    expect(listed).toEqual({ items: [announcement], total: 1 })
    expect(lastCall().url).toBe("/api/v1/admin/announcements?limit=20&offset=0")

    install([announcement], 101)
    await listAnnouncements(TOKEN, "global", null, { limit: 50, offset: 50 })
    expect(lastCall().url).toBe(
      "/api/v1/admin/announcements?limit=50&offset=50"
    )

    install(announcement)
    await createAnnouncement(TOKEN, "global", null, {
      title: announcement.title,
      body: announcement.body,
      severity: announcement.severity,
      pinned: announcement.pinned,
    })
    expect(lastCall().method).toBe("POST")
    expect(JSON.parse(lastCall().body ?? "null")).toEqual({
      title: announcement.title,
      body: announcement.body,
      severity: announcement.severity,
      pinned: announcement.pinned,
    })

    await updateAnnouncement(TOKEN, "global", null, announcement.id, {
      title: "Updated",
    })
    expect(lastCall()).toMatchObject({
      url: `/api/v1/admin/announcements/${announcement.id}`,
      method: "PATCH",
    })

    await publishAnnouncement(TOKEN, "global", null, announcement.id)
    expect(lastCall()).toMatchObject({
      url: `/api/v1/admin/announcements/${announcement.id}/publish`,
      method: "POST",
    })

    await archiveAnnouncement(TOKEN, "global", null, announcement.id)
    expect(lastCall()).toMatchObject({
      url: `/api/v1/admin/announcements/${announcement.id}/archive`,
      method: "POST",
    })
  })

  test("scopes workspace announcements to the selected workspace", async () => {
    install([announcement], 1)
    await listAnnouncements(TOKEN, "workspace", "workspace-1")
    expect(lastCall().url).toBe(
      "/api/v1/workspaces/workspace-1/announcements?limit=20&offset=0"
    )
  })
})

describe("message center API", () => {
  test("lists messages and loads the workspace unread count", async () => {
    install([], 0)
    const listed = await listMessages(TOKEN, "workspace-1")
    expect(listed).toEqual({ items: [], total: 0 })
    expect(lastCall().url).toBe(
      "/api/v1/messages?limit=50&offset=0&workspace_id=workspace-1"
    )

    install({ count: 3, next_expiration_at: "2026-09-08T00:00:00Z" })
    await expect(getUnreadMessageCount(TOKEN, "workspace-1")).resolves.toEqual({
      count: 3,
      next_expiration_at: "2026-09-08T00:00:00Z",
    })
    expect(lastCall().url).toBe(
      "/api/v1/messages/unread-count?workspace_id=workspace-1"
    )

    install([], 101)
    await listMessages(TOKEN, "workspace-1", { limit: 20, offset: 40 })
    expect(lastCall().url).toBe(
      "/api/v1/messages?limit=20&offset=40&workspace_id=workspace-1"
    )
  })

  test("marks one message or every visible message as read", async () => {
    install(null)
    await markMessageRead(TOKEN, "message-1", "workspace-1")
    expect(lastCall()).toMatchObject({
      url: "/api/v1/messages/message-1/read?workspace_id=workspace-1",
      method: "POST",
    })

    await markAllMessagesRead(TOKEN, "workspace-1")
    expect(lastCall()).toMatchObject({
      url: "/api/v1/messages/read-all?workspace_id=workspace-1",
      method: "POST",
    })
  })
})
