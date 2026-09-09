/* @jsxImportSource react */
import { afterEach, describe, expect, mock, test } from "bun:test"
import { act } from "@testing-library/react"

import { AnnouncementAdminPage } from "@/components/messages/announcement-admin-page"
import type { Announcement } from "@/lib/api/announcements"
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

const announcement: Announcement = {
  id: "announcement-1",
  scope_type: "global",
  workspace_id: null,
  title: "Maintenance",
  body: "Scheduled **maintenance**",
  severity: "warning",
  pinned: true,
  status: "published",
  published_at: "2026-09-07T15:15:00Z",
  expires_at: null,
  created_by_user_id: "user-1",
  updated_by_user_id: "user-1",
  created_at: "2026-09-07T15:00:00Z",
  updated_at: "2026-09-07T15:15:00Z",
}

const listAnnouncementCalls: Array<{
  limit?: number
  offset?: number
}> = []
let listAnnouncementTotal = 1

mockNextNavigation()
mockUseSession()
mock.module("@/lib/api/announcements", () => ({
  listAnnouncements: async (
    _token: string,
    _scope: string,
    _workspaceId: string | null,
    options: { limit?: number; offset?: number } = {}
  ) => {
    listAnnouncementCalls.push(options)
    return { items: [announcement], total: listAnnouncementTotal }
  },
  archiveAnnouncement: async () => announcement,
  createAnnouncement: async () => announcement,
  publishAnnouncement: async () => announcement,
  updateAnnouncement: async () => announcement,
}))

afterEach(() => {
  cleanup()
  listAnnouncementCalls.length = 0
  listAnnouncementTotal = 1
})

describe("AnnouncementAdminPage", () => {
  test("keeps announcement rows compact and opens the full body in a dialog", async () => {
    renderPage(<AnnouncementAdminPage />)

    const title = await screen.findByText("Maintenance")
    const list = title.closest("section")
    expect(list).toBeTruthy()
    expect(within(list!).queryByText("Scheduled")).toBeNull()

    fireEvent.click(title.closest("button") ?? title)

    const dialog = await screen.findByRole("dialog")
    expect(within(dialog).getByRole("heading").textContent).toBe("Maintenance")
    expect(within(dialog).getByText("Scheduled")).toBeTruthy()
    expect(within(dialog).getByText("maintenance")).toBeTruthy()

    fireEvent.click(within(dialog).getByRole("button", { name: "关闭" }))
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull())
  })

  test("pages through every announcement reported by the API", async () => {
    listAnnouncementTotal = 21
    renderPage(<AnnouncementAdminPage />)

    await screen.findByText("Maintenance")
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "下一页" }))
      await new Promise((resolve) => window.setTimeout(resolve, 0))
    })

    await waitFor(() =>
      expect(listAnnouncementCalls).toContainEqual({ limit: 20, offset: 20 })
    )
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "2" }).getAttribute("aria-current")
      ).toBe("page")
    )
  })
})
