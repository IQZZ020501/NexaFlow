/* @jsxImportSource react */
import { afterEach, expect, mock, test } from "bun:test"

import { LanguageProvider } from "@/contexts/language-provider"
import { ResourcePermissionsPage } from "@/components/system/resource-permissions-page"
import {
  cleanup,
  jsonResponse,
  makeSession,
  mockNextNavigation,
  render,
  resetFetch,
  screen,
  waitFor,
  withFetch,
} from "./helpers/dom"

const workspace = {
  id: "ws-1",
  name: "Workspace One",
  description: "",
  status: "active",
  is_default: false,
}
const session = makeSession({ workspaces: [workspace] })
const sessionState = { value: session }

// SessionProvider rebuilds its context value whenever it re-renders, for
// example to show a notification, so returning that fresh object is the
// behavior the page has to tolerate.
mock.module("@/contexts/session-context", () => ({
  useSession: () => sessionState.value,
  useCurrentWorkspaceName: () => "Test Workspace",
  replaceSessionUser: () => undefined,
  addCreatedWorkspaceMembership: () => undefined,
  addCreatedTeamMembership: () => undefined,
  getInitialWorkspaceId: () => "ws-1",
  SessionProvider: ({ children }: { children: React.ReactNode }) => children,
}))
mockNextNavigation()

afterEach(() => {
  cleanup()
  resetFetch()
})

test("keeps permission requests when the session value changes identity", async () => {
  session.selectedWorkspaceId = "ws-1"
  const permissionRequests: string[] = []
  const member = { user: session.me.user, role: "member" }

  withFetch((url) => {
    const parsed = new URL(url, "http://localhost")
    if (parsed.pathname === "/api/v1/workspaces/ws-1/tools") {
      return jsonResponse([
        {
          id: "tool-1",
          display_name: "Tool One",
          description: "A tool",
          status: "active",
          created_by_user_id: "owner-1",
          can_manage: true,
        },
      ])
    }
    if (parsed.pathname.endsWith("/members")) return jsonResponse([member])
    if (parsed.pathname.endsWith("/permissions")) {
      permissionRequests.push(parsed.pathname)
      return jsonResponse([])
    }
    throw new Error(`Unexpected request: ${url}`)
  })

  const view = render(
    <LanguageProvider defaultLanguage="zh-Hans">
      <ResourcePermissionsPage type="tools" />
    </LanguageProvider>
  )

  expect(await screen.findByText("Tool One")).toBeTruthy()
  await waitFor(() =>
    expect(permissionRequests).toEqual([
      "/api/v1/workspaces/ws-1/tools/tool-1/permissions",
    ])
  )

  sessionState.value = { ...session }
  view.rerender(
    <LanguageProvider defaultLanguage="zh-Hans">
      <ResourcePermissionsPage type="tools" />
    </LanguageProvider>
  )
  await Bun.sleep(50)

  expect(permissionRequests).toEqual([
    "/api/v1/workspaces/ws-1/tools/tool-1/permissions",
  ])
})
