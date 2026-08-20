/* @jsxImportSource react */
import { afterEach, describe, expect, test } from "bun:test"

import { InvitationPage } from "@/components/auth/invitation-page"
import { SystemGovernancePage } from "@/components/system/system-governance-page"
import {
  cleanup,
  fireEvent,
  jsonResponse,
  mockNextLink,
  mockNextNavigation,
  mockUseSession,
  renderPage,
  screen,
  waitFor,
  withFetch,
} from "./helpers/dom"

mockUseSession()
mockNextNavigation({ pathname: "/system/governance" })
mockNextLink()

afterEach(() => cleanup())

describe("workspace invitations", () => {
  test("accepts account details from a reusable invitation", async () => {
    let requestBody: unknown = null
    withFetch((_url, init) => {
      requestBody = JSON.parse(String(init?.body)) as Record<string, string>
      return jsonResponse({
        id: "user-2",
        username: "new-member",
        email: "new-member@example.com",
        name: "New Member",
        is_global_admin: false,
        must_change_password: false,
        is_active: true,
        created_at: "2026-08-20T00:00:00Z",
        workspaces: [],
        teams: [],
      })
    })

    renderPage(<InvitationPage token="generic-invitation-token-value" generic />)
    fireEvent.change(screen.getByLabelText("账号"), { target: { value: "new-member" } })
    fireEvent.change(screen.getByLabelText("邮箱"), { target: { value: "new-member@example.com" } })
    fireEvent.change(screen.getByLabelText("姓名"), { target: { value: "New Member" } })
    fireEvent.change(screen.getByLabelText("新密码"), { target: { value: "Password1" } })
    fireEvent.change(screen.getByLabelText("确认密码"), { target: { value: "Password1" } })
    fireEvent.click(screen.getByRole("button", { name: "接受邀请" }))

    await waitFor(() => expect(screen.getByText("邀请已接受")).toBeTruthy())
    expect(requestBody).toEqual({
      token: "generic-invitation-token-value",
      password: "Password1",
      username: "new-member",
      email: "new-member@example.com",
      name: "New Member",
    })
  })

  test("shows and submits a reusable invitation as a full URL", async () => {
    const testWindow = window as typeof window & {
      happyDOM: { setURL: (url: string) => void }
    }
    testWindow.happyDOM.setURL("https://nexaflow.example/system/governance")
    let createBody: unknown = null
    withFetch((url, init) => {
      if (url.endsWith("/inventory")) {
        return jsonResponse({
          workspace_id: "ws-1",
          members_total: 1,
          teams_total: 0,
          agents_total: 0,
          knowledge_bases_total: 0,
          models_total: 0,
          tools_total: 0,
          workflows_total: 0,
          active_runs: 0,
          failed_runs_24h: 0,
          failed_tasks_24h: 0,
        })
      }
      if (url.endsWith("/governance")) {
        return jsonResponse({
          workspace_id: "ws-1",
          daily_run_limit: null,
          monthly_token_limit: null,
          alert_threshold_percent: 80,
          retention_days: null,
          timezone: "UTC",
          updated_at: "2026-08-20T00:00:00Z",
        })
      }
      if (url.endsWith("/invitations") && init?.method === "POST") {
        createBody = JSON.parse(String(init.body)) as Record<string, string>
        return jsonResponse({
          id: "invitation-1",
          workspace_id: "ws-1",
          kind: "generic",
          username: null,
          email: null,
          name: null,
          role: "member",
          expires_at: "2026-08-27T00:00:00Z",
          accepted_at: null,
          created_at: "2026-08-20T00:00:00Z",
          token: "reusable-token",
          invite_url: "/invite/reusable-token?mode=generic",
        }, 201)
      }
      if (url.endsWith("/invitations")) return jsonResponse([])
      throw new Error(`Unexpected request: ${url}`)
    })

    renderPage(<SystemGovernancePage section="governance" />)
    await waitFor(() => expect(screen.getByRole("button", { name: "邀请方式" })).toBeTruthy())
    fireEvent.pointerDown(screen.getByRole("button", { name: "邀请方式" }))
    fireEvent.click(await screen.findByRole("menuitem", { name: "通用邀请" }))
    fireEvent.click(screen.getByRole("button", { name: "生成邀请链接" }))

    const expectedUrl = `${window.location.origin}/invite/reusable-token?mode=generic`
    await waitFor(() => expect(screen.getByDisplayValue(expectedUrl)).toBeTruthy())
    expect(createBody).toEqual({ kind: "generic", role: "member" })
  })
})
