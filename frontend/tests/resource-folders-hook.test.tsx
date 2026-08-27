/* @jsxImportSource react */
import { afterEach, expect, test } from "bun:test"

import { useResourceFolders } from "@/components/resource-folders/use-resource-folders"
import {
  cleanup,
  fireEvent,
  jsonResponse,
  makeSession,
  mockUseSession,
  renderPage,
  resetFetch,
  screen,
  waitFor,
  withFetch,
} from "./helpers/dom"

const folder = (id: string, name: string, parentId: string | null) => ({
  id,
  workspace_id: "ws-1",
  resource_type: "knowledge",
  parent_id: parentId,
  name,
  created_by_user_id: "u-1",
  created_at: "2026-08-27T00:00:00Z",
  updated_at: "2026-08-27T00:00:00Z",
})

function Harness() {
  const state = useResourceFolders("knowledge")
  return (
    <div>
      {state.folders.map((item) => (
        <span key={item.id} data-folder={item.id}>
          {item.name}
        </span>
      ))}
      <span data-selected={state.selectedFolderId ?? "none"}>sel</span>
      <button type="button" onClick={() => void state.create("新建", null)}>
        create
      </button>
      <button
        type="button"
        onClick={() => void state.rename("folder-1", "改名")}
      >
        rename
      </button>
      <button type="button" onClick={() => void state.remove("folder-1")}>
        remove
      </button>
      <button type="button" onClick={() => void state.move("kb-1", "folder-2")}>
        move
      </button>
      <button type="button" onClick={() => state.setSelectedFolderId("folder-2")}>
        select
      </button>
    </div>
  )
}

const session = makeSession()

mockUseSession(session)

afterEach(() => {
  cleanup()
  resetFetch()
})

test("loads folders and manages create, rename, remove, and move", async () => {
  const notifications: Array<{ kind: string; message: string }> = []
  session.notify = ((kind: string, message: string) => {
    notifications.push({ kind, message })
  }) as typeof session.notify
  const requests: string[] = []

  withFetch((url, init) => {
    const parsed = new URL(url, "http://localhost")
    const method = init?.method ?? "GET"
    requests.push(`${method} ${parsed.pathname}`)
    if (
      parsed.pathname === "/api/v1/workspaces/ws-1/resource-folders" &&
      method === "GET"
    ) {
      return jsonResponse([
        folder("folder-1", "规章制度", null),
        folder("folder-2", "人事制度", "folder-1"),
      ])
    }
    if (method === "POST") return jsonResponse(folder("folder-3", "新建", null), 201)
    if (method === "PATCH" && parsed.pathname.endsWith("/folder-1")) {
      return jsonResponse(folder("folder-1", "改名", null))
    }
    if (method === "DELETE") return new Response(null, { status: 204 })
    if (method === "PUT") return new Response(null, { status: 204 })
    throw new Error(`Unexpected request: ${url}`)
  })

  renderPage(<Harness />)
  expect(await screen.findByText("规章制度")).toBeTruthy()
  expect(screen.getByText("人事制度")).toBeTruthy()

  fireEvent.click(screen.getByText("create"))
  await waitFor(() => expect(screen.getByText("新建")).toBeTruthy())
  expect(notifications).toContainEqual({ kind: "success", message: "文件夹已创建" })

  fireEvent.click(screen.getByText("rename"))
  await waitFor(() => expect(screen.getByText("改名")).toBeTruthy())
  expect(notifications).toContainEqual({ kind: "success", message: "文件夹已重命名" })

  fireEvent.click(screen.getByText("select"))
  await waitFor(() => expect(screen.getByText("sel").dataset.selected).toBe("folder-2"))

  fireEvent.click(screen.getByText("move"))
  await waitFor(() =>
    expect(requests).toContain("PUT /api/v1/workspaces/ws-1/resource-folders/resources/move")
  )
  expect(notifications).toContainEqual({ kind: "success", message: "已移动到文件夹" })

  fireEvent.click(screen.getByText("remove"))
  await waitFor(() => expect(screen.queryByText("规章制度")).toBeNull())
  // The child folder is reparented to the removed folder's parent (null).
  expect(requests).toContain("DELETE /api/v1/workspaces/ws-1/resource-folders/folder-1")
  expect(notifications).toContainEqual({ kind: "success", message: "文件夹已删除" })
})

test("clears folders without a token and notifies on load errors", async () => {
  const notifications: Array<{ kind: string; message: string }> = []
  session.notify = ((kind: string, message: string) => {
    notifications.push({ kind, message })
  }) as typeof session.notify

  ;(session as { token: string | null }).token = null
  renderPage(<Harness />)
  expect(screen.queryByText("规章制度")).toBeNull()

  ;(session as { token: string | null }).token = "test-token"
  withFetch((url) => {
    const parsed = new URL(url, "http://localhost")
    if (parsed.pathname === "/api/v1/workspaces/ws-1/resource-folders") {
      return new Response(JSON.stringify({ detail: "kaboom" }), {
        status: 500,
        headers: { "Content-Type": "application/json" },
      })
    }
    throw new Error(`Unexpected request: ${url}`)
  })
  renderPage(<Harness />)
  await waitFor(() =>
    expect(notifications.some((item) => item.kind === "error")).toBe(true)
  )
  expect(screen.queryByText("规章制度")).toBeNull()
})
