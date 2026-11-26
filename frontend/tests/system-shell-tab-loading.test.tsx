/* @jsxImportSource react */
import { afterEach, beforeEach, describe, expect, test } from "bun:test"
import { Profiler } from "react"
import { act } from "@testing-library/react"

import { SystemShell, type SystemTab } from "@/components/system/system-shell"
import { LanguageProvider } from "@/contexts/language-provider"
import type { MemoryProfile } from "@/lib/api/memories"
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

function memoryProfile(content: string): MemoryProfile {
  return {
    enabled: true,
    automatic: false,
    items: [
      {
        id: "memory-1",
        category: "preference",
        key: "style",
        content,
        project_id: "",
        expires_at: null,
        origin: "manual",
        source_run_id: null,
        source_quote: "",
        source_conversation_id: null,
        source_agent_id: null,
        updated_at: "2026-11-19T10:00:00Z",
      },
    ],
  }
}

function deferredResponse() {
  let resolve!: (response: Response) => void
  const promise = new Promise<Response>((resolveResponse) => {
    resolve = resolveResponse
  })
  return { promise, resolve }
}

type PanelFrame = { text: string; loading: boolean }
function trackedShell(
  activeTab: SystemTab,
  frames: PanelFrame[],
  selector = "#system-panel-memories"
) {
  return (
    <Profiler
      id="system-tabs"
      onRender={() => {
        const panel = document.querySelector(selector)
        if (panel) {
          frames.push({
            text: panel.textContent ?? "",
            loading: Boolean(panel.querySelector(".animate-spin")),
          })
        }
      }}
    >
      <SystemShell activeTab={activeTab} />
    </Profiler>
  )
}

beforeEach(() => {
  Object.assign(session, makeSession())
  const testWindow = window as typeof window & {
    happyDOM: { setURL: (url: string) => void }
  }
  testWindow.happyDOM.setURL("https://nexaflow.example/system/workspaces")
})

afterEach(() => {
  cleanup()
  resetFetch()
})

describe("system memories tab", () => {
  test("keeps loaded memories visible while revalidating after another tab", async () => {
    const response = deferredResponse()
    let memoryRequests = 0
    withFetch((url) => {
      if (url.endsWith("/memories/projects")) return jsonResponse({ items: [] })
      if (url.endsWith("/memories")) {
        memoryRequests += 1
        return memoryRequests === 1
          ? jsonResponse(memoryProfile("Saved preference"))
          : response.promise
      }
      return jsonResponse([])
    })
    const frames: PanelFrame[] = []
    renderPage(trackedShell("memories", frames))
    await screen.findByText("Saved preference")
    fireEvent.click(screen.getByRole("tab", { name: "审计日志" }))
    await screen.findByText("暂无审计日志")
    expect(screen.queryByRole("tabpanel", { name: "记忆" })).toBeNull()
    frames.length = 0

    fireEvent.click(screen.getByRole("tab", { name: "记忆" }))
    await waitFor(() => expect(memoryRequests).toBe(2))
    const pendingFrames = [...frames]
    await act(async () => {
      response.resolve(jsonResponse(memoryProfile("Updated preference")))
    })

    expect(await screen.findByText("Updated preference")).toBeTruthy()
    expect(pendingFrames.length).toBeGreaterThan(0)
    expect(
      pendingFrames.every(
        (frame) => !frame.loading && frame.text.includes("Saved preference")
      )
    ).toBe(true)
  })

  test("loads memories only after opening the tab", async () => {
    const requests: string[] = []
    withFetch((url) => {
      requests.push(url)
      return url.endsWith("/projects")
        ? jsonResponse({ items: [] })
        : jsonResponse(memoryProfile("Lazy preference"))
    })
    renderPage(<SystemShell activeTab="workspaces" />)
    expect(requests).toEqual([])
    fireEvent.click(screen.getByRole("tab", { name: "记忆" }))
    expect(await screen.findByText("Lazy preference")).toBeTruthy()
    expect(requests.length).toBe(2)
  })

  test("removes memory dialog overlays and aborts requests while the tab is hidden", async () => {
    let signal: AbortSignal | undefined
    withFetch((url, init) => {
      if (url.endsWith("/projects")) return jsonResponse({ items: [] })
      signal = init?.signal ?? undefined
      return jsonResponse(memoryProfile("Saved preference"))
    })
    renderPage(<SystemShell activeTab="memories" />)
    fireEvent.click(await screen.findByRole("button", { name: "添加记忆" }))
    expect(screen.getByRole("dialog", { name: "添加记忆" })).toBeTruthy()

    // History navigation can leave the page even while a modal is open.
    await act(async () => {
      fireEvent.click(document.getElementById("system-tab-teams")!)
    })
    expect(screen.queryByRole("dialog")).toBeNull()
    expect(signal?.aborted).toBe(true)
    expect(document.body.style.pointerEvents).not.toBe("none")
  })

  for (const scopeChange of ["workspace", "token"] as const) {
    test(`hides previous memories on a ${scopeChange} change while the panel is hidden`, async () => {
      const response = deferredResponse()
      let memoryRequests = 0
      withFetch((url) => {
        if (url.endsWith("/projects")) return jsonResponse({ items: [] })
        if (url.endsWith("/memories")) {
          memoryRequests += 1
          return memoryRequests === 1
            ? jsonResponse(memoryProfile("Private old preference"))
            : response.promise
        }
        return jsonResponse([])
      })
      const frames: PanelFrame[] = []
      const view = renderPage(trackedShell("memories", frames))
      await screen.findByText("Private old preference")
      fireEvent.click(screen.getByRole("tab", { name: "团队" }))
      if (scopeChange === "workspace") {
        session.selectedWorkspaceId = "ws-2"
      } else {
        session.token = "replacement-token"
      }
      view.rerender(
        <LanguageProvider defaultLanguage="zh-Hans">
          {trackedShell("memories", frames)}
        </LanguageProvider>
      )
      frames.length = 0

      fireEvent.click(screen.getByRole("tab", { name: "记忆" }))
      await waitFor(() => expect(memoryRequests).toBe(2))
      const pendingFrames = [...frames]
      await act(async () => {
        response.resolve(jsonResponse(memoryProfile("New preference")))
      })

      expect(await screen.findByText("New preference")).toBeTruthy()
      expect(pendingFrames.length).toBeGreaterThan(0)
      expect(
        pendingFrames.every(
          (frame) => !frame.text.includes("Private old preference")
        )
      ).toBe(true)
    })
  }
})

describe("other system tabs", () => {
  test("reuses workspace and team data without fetching during tab round trips", () => {
    const requests: string[] = []
    session.teams = [
      {
        id: "team-1",
        workspace_id: "ws-1",
        name: "Saved team",
        description: "",
        status: "active",
        is_default: false,
      },
    ]
    withFetch((url) => {
      requests.push(url)
      return jsonResponse([])
    })
    renderPage(<SystemShell activeTab="workspaces" />)
    for (let index = 0; index < 2; index += 1) {
      fireEvent.click(screen.getByRole("tab", { name: "团队" }))
      expect(screen.getByText("Saved team")).toBeTruthy()
      fireEvent.click(screen.getByRole("tab", { name: "工作空间" }))
      expect(screen.getByText("Test Workspace")).toBeTruthy()
    }
    expect(requests).toEqual([])
  })

  test("keeps the resource catalog visible while refreshing after another tab", async () => {
    const response = deferredResponse()
    const permissionResponse = deferredResponse()
    let resourceRequests = 0
    let permissionRequests = 0
    const resources = [
      {
        id: "kb-1",
        name: "Saved knowledge base",
        description: "",
        status: "active",
        created_by_user_id: "another-user",
      },
    ]
    withFetch((url) => {
      const path = new URL(url, "https://nexaflow.example").pathname
      if (path.endsWith("/members")) {
        return jsonResponse([{ user: session.me.user, role: "member" }])
      }
      if (path.endsWith("/knowledge-bases")) {
        resourceRequests += 1
        return resourceRequests === 1
          ? jsonResponse(resources)
          : response.promise
      }
      if (path.endsWith("/permissions")) {
        permissionRequests += 1
        return permissionRequests === 1
          ? jsonResponse([])
          : permissionResponse.promise
      }
      return jsonResponse([])
    })
    const frames: PanelFrame[] = []
    renderPage(trackedShell("teams", frames, "div.w-full.min-w-0"))
    fireEvent.click(
      screen.getByRole("button", { name: "知识库", hidden: true })
    )
    await screen.findByText("Saved knowledge base")
    fireEvent.click(screen.getByRole("tab", { name: "团队" }))
    frames.length = 0

    fireEvent.click(
      screen.getByRole("button", { name: "知识库", hidden: true })
    )
    await waitFor(() => expect(resourceRequests).toBe(2))
    const pendingFrames = [...frames]
    await act(async () => {
      response.resolve(jsonResponse(resources))
    })
    await waitFor(() => expect(permissionRequests).toBeGreaterThan(1))
    const catalogDuringPermissionRefresh = screen.queryByText(
      "Saved knowledge base"
    )
    const inputs = screen.queryAllByRole("radio") as HTMLInputElement[]
    const disabledDuringPermissionRefresh = inputs.every(
      (input) => input.disabled
    )
    await act(async () => {
      permissionResponse.resolve(jsonResponse([]))
    })

    expect(pendingFrames.length).toBeGreaterThan(0)
    expect(
      pendingFrames.every((frame) =>
        frame.text.includes("Saved knowledge base")
      )
    ).toBe(true)
    expect(catalogDuringPermissionRefresh).toBeTruthy()
    expect(inputs.length).toBe(3)
    expect(disabledDuringPermissionRefresh).toBe(true)
    await waitFor(() =>
      expect(inputs.every((input) => !input.disabled)).toBe(true)
    )
  })

  test("keeps loaded audit rows while returning from another tab", async () => {
    const response = deferredResponse()
    const log = {
      id: "audit-1",
      workspace_id: "ws-1",
      actor_user_id: "u-1",
      actor_username: "admin",
      action: "workspace.create",
      resource_type: "workspace",
      resource_id: "ws-1",
      resource_name: "Saved audit row",
      details: {},
      created_at: "2026-11-26T00:00:00Z",
    }
    let auditRequests = 0
    withFetch(() => {
      auditRequests += 1
      return auditRequests === 1 ? jsonResponse([log]) : response.promise
    })
    const frames: PanelFrame[] = []
    renderPage(trackedShell("audit", frames, "#system-panel-audit"))
    await screen.findByText("Saved audit row")
    fireEvent.click(screen.getByRole("tab", { name: "团队" }))
    frames.length = 0
    fireEvent.click(screen.getByRole("tab", { name: "审计日志" }))
    const pendingFrames = [...frames]
    await act(async () => {
      response.resolve(jsonResponse([log]))
    })

    expect(auditRequests).toBe(2)
    expect(pendingFrames.length).toBeGreaterThan(0)
    expect(
      pendingFrames.every((frame) => frame.text.includes("Saved audit row"))
    ).toBe(true)
  })

  test("keeps the selected audit page when returning from another tab", async () => {
    const response = deferredResponse()
    const offsets: number[] = []
    withFetch((url) => {
      const offset = Number(
        new URL(url, "https://nexaflow.example").searchParams.get("offset")
      )
      offsets.push(offset)
      if (offsets.length === 3) return response.promise
      return new Response(
        JSON.stringify(
          Array.from({ length: offset ? 1 : 20 }, (_, index) => ({
            id: `audit-${offset + index}`,
            actor_username: "admin",
            action: "workspace.create",
            resource_type: "workspace",
            resource_id: "ws-1",
            resource_name: `Audit row ${offset + index}`,
            details: {},
            created_at: "2026-11-26T00:00:00Z",
          }))
        ),
        {
          headers: {
            "Content-Type": "application/json",
            "X-Total-Count": "21",
          },
        }
      )
    })
    const frames: PanelFrame[] = []
    renderPage(trackedShell("audit", frames, "#system-panel-audit"))
    await screen.findByText("Audit row 0")
    fireEvent.click(screen.getByRole("button", { name: "下一页" }))
    await screen.findByText("Audit row 20")
    fireEvent.click(screen.getByRole("tab", { name: "团队" }))
    frames.length = 0

    fireEvent.click(screen.getByRole("tab", { name: "审计日志" }))
    const pendingFrames = [...frames]
    await act(async () => {
      response.resolve(jsonResponse([]))
    })

    expect(offsets).toEqual([0, 20, 20])
    expect(pendingFrames.length).toBeGreaterThan(0)
    expect(
      pendingFrames.every((frame) => frame.text.includes("Audit row 20"))
    ).toBe(true)
  })

  for (const scopeChange of ["workspace", "token"] as const) {
    test(`hides old resource grants on a ${scopeChange} change while the panel is hidden`, async () => {
      session.workspaces.push({
        ...session.workspaces[0],
        id: "ws-2",
        name: "Second Workspace",
      })
      const response = deferredResponse()
      let resourceRequests = 0
      withFetch((url) => {
        const path = new URL(url, "https://nexaflow.example").pathname
        if (path.endsWith("/members"))
          return jsonResponse([{ user: session.me.user, role: "member" }])
        if (path.endsWith("/knowledge-bases")) {
          resourceRequests += 1
          return resourceRequests === 1
            ? jsonResponse([
                { id: "old-kb", name: "Private old catalog", status: "active" },
              ])
            : response.promise
        }
        return jsonResponse([])
      })
      const frames: PanelFrame[] = []
      const view = renderPage(
        trackedShell("teams", frames, "div.w-full.min-w-0")
      )
      fireEvent.click(
        screen.getByRole("button", { name: "知识库", hidden: true })
      )
      await screen.findByText("Private old catalog")
      fireEvent.click(screen.getByRole("tab", { name: "团队" }))
      if (scopeChange === "workspace") session.selectedWorkspaceId = "ws-2"
      else session.token = "replacement-token"
      view.rerender(
        <LanguageProvider defaultLanguage="zh-Hans">
          {trackedShell("teams", frames, "div.w-full.min-w-0")}
        </LanguageProvider>
      )
      frames.length = 0

      fireEvent.click(
        screen.getByRole("button", { name: "知识库", hidden: true })
      )
      await waitFor(() => expect(resourceRequests).toBe(2))
      const pendingFrames = [...frames]
      await act(async () => {
        response.resolve(
          jsonResponse([
            { id: "new-kb", name: "New catalog", status: "active" },
          ])
        )
      })

      expect(await screen.findByText("New catalog")).toBeTruthy()
      expect(pendingFrames.length).toBeGreaterThan(0)
      expect(
        pendingFrames.every(
          (frame) => !frame.text.includes("Private old catalog")
        )
      ).toBe(true)
    })
  }
})
