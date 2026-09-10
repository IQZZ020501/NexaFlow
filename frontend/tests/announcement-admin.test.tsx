/* @jsxImportSource react */
import {
  afterEach,
  describe,
  expect,
  mock,
  setSystemTime,
  test,
} from "bun:test"
import { act } from "@testing-library/react"

import { AnnouncementAdminPage } from "@/components/messages/announcement-admin-page"
import type {
  Announcement,
  AnnouncementPayload,
  AnnouncementUpdatePayload,
} from "@/lib/api/announcements"
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
  expires_at: "2030-06-01T04:30:00Z",
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
const createAnnouncementCalls: AnnouncementPayload[] = []
const updateAnnouncementCalls: AnnouncementUpdatePayload[] = []

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
  createAnnouncement: async (
    _token: string,
    _scope: string,
    _workspaceId: string | null,
    payload: AnnouncementPayload
  ) => {
    createAnnouncementCalls.push(payload)
    return announcement
  },
  publishAnnouncement: async () => announcement,
  updateAnnouncement: async (
    _token: string,
    _scope: string,
    _workspaceId: string | null,
    _announcementId: string,
    payload: AnnouncementUpdatePayload
  ) => {
    updateAnnouncementCalls.push(payload)
    return announcement
  },
}))

afterEach(() => {
  cleanup()
  setSystemTime()
  listAnnouncementCalls.length = 0
  listAnnouncementTotal = 1
  createAnnouncementCalls.length = 0
  updateAnnouncementCalls.length = 0
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

  test("creates announcements with an expiration and allows clearing it", async () => {
    setSystemTime(new Date(2031, 2, 1, 10, 0))
    renderPage(<AnnouncementAdminPage />)

    await screen.findByText("Maintenance")
    fireEvent.change(screen.getByLabelText("公告标题"), {
      target: { value: "Expiring notice" },
    })
    fireEvent.change(screen.getByLabelText("公告正文"), {
      target: { value: "Expires soon" },
    })
    expect(document.querySelector('input[type="datetime-local"]')).toBeNull()

    fireEvent.click(screen.getByRole("button", { name: "公告过期时间" }))
    const datePicker = await screen.findByRole("dialog")
    expect(datePicker.className).toContain("bg-popover")
    fireEvent.click(
      within(datePicker).getByRole("button", { name: /2031年3月2日/ })
    )
    const hourInput = within(datePicker).getByLabelText("小时")
    const minuteInput = within(datePicker).getByLabelText("分钟")
    fireEvent.change(hourInput, { target: { value: "14" } })
    fireEvent.blur(hourInput)
    fireEvent.change(minuteInput, { target: { value: "45" } })
    fireEvent.blur(minuteInput)
    fireEvent.click(within(datePicker).getByRole("button", { name: "完成" }))
    fireEvent.click(screen.getByRole("button", { name: "创建草稿" }))

    await waitFor(() => expect(createAnnouncementCalls).toHaveLength(1))
    expect(createAnnouncementCalls[0]?.expires_at).toBe(
      new Date("2031-03-02T14:45").toISOString()
    )

    fireEvent.click(screen.getByRole("button", { name: "编辑" }))
    const expiration = screen.getByRole("button", {
      name: "公告过期时间",
    })
    expect(expiration.textContent).toContain("2030")
    fireEvent.click(expiration)
    const editingDatePicker = await screen.findByRole("dialog")
    fireEvent.click(
      within(editingDatePicker).getByRole("button", { name: "清除" })
    )
    fireEvent.click(
      within(editingDatePicker).getByRole("button", { name: "完成" })
    )
    fireEvent.click(screen.getByRole("button", { name: "保存公告" }))

    await waitFor(() => expect(updateAnnouncementCalls).toHaveLength(1))
    expect(updateAnnouncementCalls[0]?.expires_at).toBeNull()
  })
})
