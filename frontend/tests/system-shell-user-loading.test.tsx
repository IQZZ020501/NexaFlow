/* @jsxImportSource react */
import { afterEach, beforeEach, describe, expect, test } from "bun:test"
import { Profiler } from "react"
import { act } from "@testing-library/react"

import { SystemShell, type SystemTab } from "@/components/system/system-shell"
import { LanguageProvider } from "@/contexts/language-provider"
import type { User, WorkspaceMember } from "@/lib/api/system"
import {
  cleanup,
  fireEvent,
  jsonResponse,
  makeSession,
  mockNextNavigation,
  mockUseSession,
  renderPage,
  resetFetch,
  screen,
  waitFor,
  withFetch,
} from "./helpers/dom"

const session = makeSession()
mockUseSession(session)
mockNextNavigation()

type UsersFrame = {
  empty: boolean
  loading: boolean
  table: boolean
  text: string
}

// Capture every commit, including the render before passive loading effects run.
function trackedShell(frames: UsersFrame[], activeTab: SystemTab = "users") {
  return (
    <Profiler
      id="system-users"
      onRender={() => {
        const panel = document.querySelector("#system-panel-users")
        if (panel) {
          frames.push({
            empty: panel.textContent?.includes("暂无用户") ?? false,
            loading: Boolean(panel.querySelector(".animate-spin")),
            table: Boolean(panel.querySelector('[role="table"]')),
            text: panel.textContent ?? "",
          })
        }
      }}
    >
      <SystemShell activeTab={activeTab} />
    </Profiler>
  )
}

function deferredResponse() {
  let resolve!: (response: Response) => void
  const promise = new Promise<Response>((resolveResponse) => {
    resolve = resolveResponse
  })
  return { promise, resolve }
}

function addWorkspace() {
  session.workspaces.push({
    ...session.workspaces[0],
    id: "ws-2",
    name: "Second Workspace",
  })
  session.me.memberships.push({ workspace_id: "ws-2", role: "admin" })
}

function member(name: string): WorkspaceMember {
  const user: User = {
    ...session.me.user,
    id: name,
    name,
    username: name.toLowerCase(),
    email: `${name}@example.test`,
  }
  return { user, role: "member" }
}

beforeEach(() => {
  Object.assign(session, makeSession())
  const testWindow = window as typeof window & {
    happyDOM: { setURL: (url: string) => void }
  }
  testWindow.happyDOM.setURL("https://nexaflow.example/system/users")
})

afterEach(() => {
  cleanup()
  resetFetch()
})

for (const role of ["global", "workspace"] as const) {
  describe(`${role} users loading`, () => {
    test("does not flash an empty state when entering from audit before the first response", async () => {
      session.me.user.is_global_admin = role === "global"
      const response = deferredResponse()
      withFetch((url) =>
        url.includes("audit-logs") ? jsonResponse([]) : response.promise
      )
      const frames: UsersFrame[] = []
      renderPage(trackedShell(frames, "audit"))
      await screen.findByText("暂无审计日志")

      fireEvent.click(screen.getByRole("tab", { name: "用户管理" }))
      const pendingFrames = [...frames]
      await act(async () => {
        response.resolve(
          jsonResponse(
            role === "global" ? [session.me.user] : [member("WorkspaceUser")]
          )
        )
      })

      expect(await screen.findByRole("table")).toBeTruthy()
      expect(pendingFrames.length).toBeGreaterThan(0)
      expect(
        pendingFrames.every((frame) => frame.loading && !frame.empty)
      ).toBe(true)
    })

    for (const empty of [false, true]) {
      test(`keeps the ${empty ? "empty state" : "user list"} visible while refreshing after audit`, async () => {
        session.me.user.is_global_admin = role === "global"
        const rows = empty
          ? []
          : role === "global"
            ? [session.me.user]
            : [member("WorkspaceUser")]
        const response = deferredResponse()
        let userRequests = 0
        withFetch((url) => {
          if (url.includes("audit-logs")) return jsonResponse([])
          userRequests += 1
          return userRequests === 1 ? jsonResponse(rows) : response.promise
        })
        const frames: UsersFrame[] = []
        renderPage(trackedShell(frames))
        if (empty) {
          await screen.findByText("暂无用户")
        } else {
          await screen.findByRole("table")
        }
        fireEvent.click(screen.getByRole("tab", { name: "审计日志" }))
        await screen.findByText("暂无审计日志")
        frames.length = 0

        fireEvent.click(screen.getByRole("tab", { name: "用户管理" }))
        const pendingFrames = [...frames]
        await act(async () => {
          response.resolve(jsonResponse(rows))
        })

        expect(userRequests).toBe(2)
        expect(pendingFrames.length).toBeGreaterThan(0)
        expect(
          pendingFrames.every(
            (frame) =>
              !frame.loading && frame.empty === empty && frame.table === !empty
          )
        ).toBe(true)
      })
    }
  })
}

describe("workspace user isolation", () => {
  test("hides the previous workspace's users in every commit while the next workspace loads", async () => {
    session.me.user.is_global_admin = false
    addWorkspace()
    const response = deferredResponse()
    withFetch((url) =>
      url.includes("/ws-1/")
        ? jsonResponse([member("FirstWorkspaceUser")])
        : response.promise
    )
    const frames: UsersFrame[] = []
    const view = renderPage(trackedShell(frames))
    await screen.findByText("FirstWorkspaceUser")
    frames.length = 0

    session.selectedWorkspaceId = "ws-2"
    view.rerender(
      <LanguageProvider defaultLanguage="zh-Hans">
        {trackedShell(frames)}
      </LanguageProvider>
    )
    const pendingFrames = [...frames]
    await act(async () => {
      response.resolve(jsonResponse([member("SecondWorkspaceUser")]))
    })

    expect(await screen.findByText("SecondWorkspaceUser")).toBeTruthy()
    expect(pendingFrames.length).toBeGreaterThan(0)
    expect(
      pendingFrames.every(
        (frame) => frame.loading && !frame.text.includes("FirstWorkspaceUser")
      )
    ).toBe(true)
  })

  test("ignores a previous workspace's response after the new workspace has loaded", async () => {
    session.me.user.is_global_admin = false
    addWorkspace()
    const previousResponse = deferredResponse()
    const requests: string[] = []
    withFetch((url) => {
      requests.push(url)
      return url.includes("/ws-1/")
        ? previousResponse.promise
        : jsonResponse([member("SecondWorkspaceUser")])
    })
    const frames: UsersFrame[] = []
    const view = renderPage(trackedShell(frames))
    await waitFor(() => expect(requests.length).toBe(1))

    session.selectedWorkspaceId = "ws-2"
    view.rerender(
      <LanguageProvider defaultLanguage="zh-Hans">
        {trackedShell(frames)}
      </LanguageProvider>
    )
    await screen.findByText("SecondWorkspaceUser")
    frames.length = 0
    await act(async () => {
      previousResponse.resolve(jsonResponse([member("FirstWorkspaceUser")]))
    })

    expect(screen.queryByText("FirstWorkspaceUser")).toBeNull()
    expect(screen.getByText("SecondWorkspaceUser")).toBeTruthy()
    expect(
      frames.every((frame) => !frame.text.includes("FirstWorkspaceUser"))
    ).toBe(true)
  })
})

test("does not reuse another account's loaded users", async () => {
  const response = deferredResponse()
  let requests = 0
  withFetch(() => {
    requests += 1
    return requests === 1
      ? jsonResponse([
          { ...session.me.user, id: "old-user", name: "Old account user" },
        ])
      : response.promise
  })
  const frames: UsersFrame[] = []
  const view = renderPage(trackedShell(frames))
  await screen.findByText("Old account user")
  session.me.user = { ...session.me.user, id: "new-account" }
  session.token = "new-account-token"
  frames.length = 0
  view.rerender(
    <LanguageProvider defaultLanguage="zh-Hans">
      {trackedShell(frames)}
    </LanguageProvider>
  )
  const pendingFrames = [...frames]
  await act(async () => {
    response.resolve(jsonResponse([]))
  })

  expect(requests).toBe(2)
  expect(pendingFrames.length).toBeGreaterThan(0)
  expect(
    pendingFrames.every((frame) => !frame.text.includes("Old account user"))
  ).toBe(true)
})
