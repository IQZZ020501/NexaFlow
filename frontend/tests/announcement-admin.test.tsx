/* @jsxImportSource react */
import { afterEach, describe, expect, mock, test } from "bun:test"

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

mockNextNavigation()
mockUseSession()
mock.module("@/lib/api/announcements", () => ({
  listAnnouncements: async () => ({ items: [announcement], total: 1 }),
  archiveAnnouncement: async () => announcement,
  createAnnouncement: async () => announcement,
  publishAnnouncement: async () => announcement,
  updateAnnouncement: async () => announcement,
}))

afterEach(() => cleanup())

describe("AnnouncementAdminPage", () => {
  test("keeps announcement rows compact and opens the full body in a dialog", async () => {
    renderPage(<AnnouncementAdminPage />)

    const title = await screen.findByText("Maintenance")
    expect(screen.queryByText("Scheduled maintenance")).toBeNull()

    fireEvent.click(title.closest("button") ?? title)

    const dialog = await screen.findByRole("dialog")
    expect(within(dialog).getByRole("heading").textContent).toBe("Maintenance")
    expect(within(dialog).getByText("Scheduled")).toBeTruthy()
    expect(within(dialog).getByText("maintenance")).toBeTruthy()

    fireEvent.click(within(dialog).getByRole("button", { name: "关闭" }))
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull())
  })
})
