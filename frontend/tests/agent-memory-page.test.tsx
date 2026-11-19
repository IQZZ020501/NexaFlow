/* @jsxImportSource react */
import { afterEach, beforeEach, expect, test } from "bun:test"
import {
  cleanup,
  fireEvent,
  screen,
  waitFor,
  within,
} from "@testing-library/react"
import userEvent from "@testing-library/user-event"

import { UserMemoryPage } from "@/components/agents/agent-memory-page"
import type { MemoryProfile } from "@/lib/api/memories"
import {
  jsonResponse,
  mockNextNavigation,
  mockUseSession,
  renderPage,
  withFetch,
} from "./helpers/dom"

const base = "/api/v1/workspaces/ws-1/memories"
const originalFetch = globalThis.fetch
mockUseSession()
mockNextNavigation()

let profile: MemoryProfile
let requests: { url: string; method: string; body: unknown }[]
let loadFails: boolean

beforeEach(() => {
  window.localStorage.clear()
  profile = {
    enabled: true,
    automatic: false,
    items: [
      {
        id: "memory-1",
        key: "language",
        content: "Prefer concise Chinese",
        category: "preference",
        project_id: "",
        expires_at: null,
        origin: "explicit",
        source_run_id: "run-1",
        source_quote: "Please remember: concise Chinese",
        source_conversation_id: "conversation-1",
        source_agent_id: "agent-1",
        updated_at: "2026-11-19T10:00:00Z",
      },
    ],
  }
  requests = []
  loadFails = false
  withFetch((url, init) => {
    const method = init?.method ?? "GET"
    const body = init?.body ? JSON.parse(String(init.body)) : undefined
    requests.push({ url, method, body })
    if (url.endsWith("/projects")) return jsonResponse({ items: [] })
    if (url === base && method === "GET") {
      return loadFails
        ? jsonResponse({ detail: "Unavailable" }, 503)
        : jsonResponse(profile)
    }
    if (url === base + "/preferences") {
      profile = { ...profile, ...body }
      return jsonResponse(profile)
    }
    if (url === base + "/memory-1" && method === "PUT") {
      profile.items = [{ ...profile.items[0]!, ...body }]
      return jsonResponse(profile)
    }
    if (url === base && method === "DELETE") {
      profile.items = []
      return new Response(null, { status: 204 })
    }
    throw new Error(`Unhandled memory request: ${method} ${url}`)
  })
})

afterEach(() => {
  cleanup()
  globalThis.fetch = originalFetch
})

test("shows source-backed memories and controls personalization preferences", async () => {
  renderPage(<UserMemoryPage />)
  await screen.findByText("Prefer concise Chinese")
  expect(
    screen
      .getByRole("link", { name: "打开来源对话", hidden: true })
      .getAttribute("href")
  ).toContain("conversation_id=conversation-1")
  fireEvent.click(screen.getByLabelText(/^自动记忆/))
  await waitFor(() => expect(profile.automatic).toBe(true))
  await waitFor(() =>
    expect(
      (screen.getByLabelText(/^使用长期记忆/) as HTMLInputElement).disabled
    ).toBe(false)
  )
  fireEvent.click(screen.getByLabelText(/^使用长期记忆/))
  await waitFor(() => expect(profile.enabled).toBe(false))
  await waitFor(() =>
    expect(
      (screen.getByLabelText(/^自动记忆/) as HTMLInputElement).disabled
    ).toBe(true)
  )
  expect(
    requests
      .filter(({ url }) => url.endsWith("/preferences"))
      .map(({ body }) => body)
  ).toEqual([
    { enabled: true, automatic: true },
    { enabled: false, automatic: true },
  ])
})

test("edits a memory and clears all only after confirmation", async () => {
  renderPage(<UserMemoryPage />)
  fireEvent.click(
    await screen.findByRole("button", { name: "编辑记忆：language" })
  )
  const editor = screen.getByRole("dialog", { name: "编辑记忆" })
  fireEvent.change(within(editor).getByLabelText("记忆内容"), {
    target: { value: "Prefer detailed Chinese" },
  })
  fireEvent.click(within(editor).getByRole("button", { name: "保存" }))
  await screen.findByText("Prefer detailed Chinese")
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull())
  fireEvent.click(screen.getByRole("button", { name: "清空全部记忆" }))
  fireEvent.click(
    within(screen.getByRole("dialog")).getByRole("button", { name: "取消" })
  )
  expect(requests.some(({ method }) => method === "DELETE")).toBe(false)
  fireEvent.click(screen.getByRole("button", { name: "清空全部记忆" }))
  fireEvent.click(
    within(screen.getByRole("dialog")).getByRole("button", { name: "确认" })
  )
  await screen.findByText(
    "暂无长期记忆，可以手动添加，或在对话中明确要求记住。"
  )
  expect(screen.queryByText("Prefer detailed Chinese")).toBeNull()
})

test("recovers from a failed profile load", async () => {
  loadFails = true
  renderPage(<UserMemoryPage />)
  await screen.findByRole("alert")
  loadFails = false
  fireEvent.click(screen.getByRole("button", { name: "重试" }))
  await screen.findByText("Prefer concise Chinese")
  expect(screen.queryByRole("alert")).toBeNull()
})

test("keeps the memory draft open when dropdown triggers are clicked twice", async () => {
  const user = userEvent.setup()
  renderPage(<UserMemoryPage />)
  await user.click(await screen.findByRole("button", { name: "添加记忆" }))
  const editor = screen.getByRole("dialog", { name: "添加记忆" })
  fireEvent.change(within(editor).getByLabelText("记忆主题"), {
    target: { value: "Working preferences" },
  })
  fireEvent.change(within(editor).getByLabelText("记忆内容"), {
    target: { value: "Keep this unsaved draft" },
  })

  for (const name of ["沟通与工作偏好", "个人记忆"]) {
    const trigger = within(editor).getByRole("button", { name })
    await user.click(trigger)
    expect(await screen.findByRole("menu")).toBeTruthy()
    await user.click(trigger)
    expect(screen.getByRole("dialog", { name: "添加记忆" })).toBe(editor)
    expect(screen.queryByRole("menu")).toBeNull()
    expect(
      (within(editor).getByLabelText("记忆主题") as HTMLInputElement).value
    ).toBe("Working preferences")
    expect(
      (within(editor).getByLabelText("记忆内容") as HTMLTextAreaElement).value
    ).toBe("Keep this unsaved draft")
  }
})

test("keeps memory drafts while selecting items and dismisses menus before the dialog", async () => {
  const user = userEvent.setup()
  renderPage(<UserMemoryPage />)
  await user.click(await screen.findByRole("button", { name: "添加记忆" }))
  const editor = screen.getByRole("dialog", { name: "添加记忆" })
  const subject = within(editor).getByLabelText("记忆主题") as HTMLInputElement
  await user.type(subject, "Keep draft")

  await user.click(within(editor).getByRole("button", { name: "沟通与工作偏好" }))
  await user.click(await screen.findByRole("menuitem", { name: "明确背景" }))
  expect(screen.getByRole("dialog", { name: "添加记忆" })).toBe(editor)
  expect(subject.value).toBe("Keep draft")

  const category = within(editor).getByRole("button", { name: "明确背景" })
  await user.click(category)
  await user.click(subject)
  expect(screen.queryByRole("menu")).toBeNull()
  expect(screen.getByRole("dialog", { name: "添加记忆" })).toBe(editor)

  await user.click(category)
  await user.keyboard("{Escape}")
  expect(screen.queryByRole("menu")).toBeNull()
  expect(screen.getByRole("dialog", { name: "添加记忆" })).toBe(editor)
  expect(subject.value).toBe("Keep draft")
  await user.keyboard("{Escape}")
  expect(screen.queryByRole("dialog")).toBeNull()
})
