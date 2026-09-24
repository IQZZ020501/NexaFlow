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
let listAnnouncementItems: Announcement[] = [announcement]
const createAnnouncementCalls: AnnouncementPayload[] = []
const updateAnnouncementCalls: AnnouncementUpdatePayload[] = []
const deleteAnnouncementCalls: string[] = []

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
    return { items: listAnnouncementItems, total: listAnnouncementTotal }
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
  deleteAnnouncement: async (
    _token: string,
    _scope: string,
    _workspaceId: string | null,
    announcementId: string
  ) => {
    deleteAnnouncementCalls.push(announcementId)
    listAnnouncementItems = []
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
  listAnnouncementItems = [announcement]
  createAnnouncementCalls.length = 0
  updateAnnouncementCalls.length = 0
  deleteAnnouncementCalls.length = 0
})

describe("AnnouncementAdminPage", () => {
  test("keeps rows title-only and deletes archived announcements after confirmation", async () => {
    listAnnouncementItems = [{ ...announcement, status: "archived" }]
    renderPage(<AnnouncementAdminPage />)

    const title = await screen.findByText("Maintenance")
    const list = title.closest("section")
    expect(list).toBeTruthy()
    expect(within(list!).queryByText("已归档")).toBeNull()
    expect(within(list!).queryByText("警告")).toBeNull()

    await act(async () => {
      fireEvent.click(
        screen.getByRole("button", { name: "删除公告：Maintenance" })
      )
      await new Promise((resolve) => window.setTimeout(resolve, 0))
    })
    const confirmation = await screen.findByRole("dialog")
    expect(within(confirmation).getByText(/Maintenance/)).toBeTruthy()
    await act(async () => {
      fireEvent.click(
        within(confirmation).getByRole("button", { name: "删除" })
      )
      await new Promise((resolve) => window.setTimeout(resolve, 0))
    })

    await waitFor(() =>
      expect(deleteAnnouncementCalls).toEqual(["announcement-1"])
    )
    await waitFor(() => expect(screen.queryByText("Maintenance")).toBeNull())
  })

  test("keeps announcement rows compact and opens the full body in a dialog", async () => {
    renderPage(<AnnouncementAdminPage />)

    const title = await screen.findByText("Maintenance")
    const list = title.closest("section")
    expect(list).toBeTruthy()
    expect(within(list!).queryByText("Scheduled")).toBeNull()
    expect(
      within(list!).getByRole("img", { name: "警告" }).className
    ).toContain("bg-amber-400")

    fireEvent.click(title.closest("button") ?? title)

    const dialog = await screen.findByRole("dialog")
    expect(within(dialog).getByRole("heading").textContent).toBe("Maintenance")
    expect(within(dialog).getByText("Scheduled")).toBeTruthy()
    expect(within(dialog).getByText("maintenance")).toBeTruthy()

    fireEvent.click(within(dialog).getByRole("button", { name: "关闭" }))
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull())
  })

  test("maps announcement severity to green, yellow, and red dots", async () => {
    listAnnouncementItems = [
      { ...announcement, id: "info", title: "Info", severity: "info" },
      { ...announcement, id: "warning", title: "Warning", severity: "warning" },
      {
        ...announcement,
        id: "critical",
        title: "Critical",
        severity: "critical",
      },
    ]
    listAnnouncementTotal = listAnnouncementItems.length
    renderPage(<AnnouncementAdminPage />)

    const list = (await screen.findByText("Info")).closest("section")
    expect(list).toBeTruthy()
    expect(
      within(list!).getByRole("img", { name: "信息" }).className
    ).toContain("bg-emerald-500")
    expect(
      within(list!).getByRole("img", { name: "警告" }).className
    ).toContain("bg-amber-400")
    expect(
      within(list!).getByRole("img", { name: "严重" }).className
    ).toContain("bg-red-500")
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
