/* @jsxImportSource react */
import { afterEach, beforeEach, expect, test } from "bun:test"
import { act, fireEvent, within } from "@testing-library/react"
import { useState } from "react"

import { EnterpriseIdentityPage } from "@/components/system/enterprise-identity-page"
import {
  cleanup,
  jsonResponse,
  makeSession,
  mockUseSession,
  renderPage,
  resetFetch,
  screen,
  waitFor,
  withFetch,
} from "./helpers/dom"

const workspaces = [
  {
    id: "ws-1",
    name: "Workspace A",
    description: "",
    status: "active" as const,
    is_default: false,
  },
  {
    id: "ws-2",
    name: "Workspace B",
    description: "",
    status: "active" as const,
    is_default: false,
  },
]
const session = makeSession({ workspaces, selectedWorkspaceId: "ws-1" })
const sessionState = session as typeof session & { selectedWorkspaceId: string }
mockUseSession(session)

function connection(workspaceId: string, name: string) {
  return {
    id: `connection-${workspaceId}`,
    workspace_id: workspaceId,
    provider: "feishu",
    name,
    client_id: `client-${workspaceId}`,
    tenant_id: `tenant-${workspaceId}`,
    agent_id: null,
    enabled: true,
    has_client_secret: true,
    client_secret_hint: "****cret",
    callback_url: `https://nexaflow.example/callback/${workspaceId}`,
    login_url: `https://nexaflow.example/login?workspace=${workspaceId}`,
    updated_at: "2026-09-06T00:00:00Z",
  }
}

function payloadFor(url: string, workspaceId: string, name: string) {
  if (url.includes("/connections")) {
    return jsonResponse([connection(workspaceId, name)])
  }
  return jsonResponse([])
}

function WorkspaceSwitchHarness() {
  const [, setRevision] = useState(0)
  return (
    <>
      <button
        type="button"
        onClick={() => {
          sessionState.selectedWorkspaceId = "ws-2"
          setRevision((current) => current + 1)
        }}
      >
        switch workspace
      </button>
      <EnterpriseIdentityPage />
    </>
  )
}

beforeEach(() => {
  sessionState.selectedWorkspaceId = "ws-1"
})

afterEach(() => {
  cleanup()
  resetFetch()
})

test("discards stale provider settings after switching workspaces", async () => {
  const resolveWorkspaceA: Array<() => void> = []
  withFetch((url) => {
    if (url.includes("ws-1")) {
      return new Promise<Response>((resolve) => {
        resolveWorkspaceA.push(() =>
          resolve(payloadFor(url, "ws-1", "Feishu A"))
        )
      })
    }
    if (url.includes("ws-2")) {
      return payloadFor(url, "ws-2", "Feishu B")
    }
    throw new Error(`Unexpected request: ${url}`)
  })

  renderPage(<WorkspaceSwitchHarness />)
  await waitFor(() => expect(resolveWorkspaceA).toHaveLength(3))

  await act(async () => {
    screen.getByRole("button", { name: "switch workspace" }).click()
  })
  await waitFor(() => expect(screen.getByDisplayValue("Feishu B")).toBeTruthy())

  await act(async () => {
    resolveWorkspaceA.forEach((resolve) => resolve())
    await Promise.resolve()
  })

  expect(screen.getByDisplayValue("Feishu B")).toBeTruthy()
  expect(screen.queryByDisplayValue("Feishu A")).toBeNull()
  expect(screen.queryByText("Tenant Key")).toBeNull()
})

test("omits the Feishu tenant key when saving", async () => {
  let savedBody: Record<string, unknown> | undefined
  withFetch((url, init) => {
    if (init?.method === "PUT") {
      savedBody = JSON.parse(String(init.body)) as Record<string, unknown>
      return jsonResponse(connection("ws-1", "Feishu A"))
    }
    return payloadFor(url, "ws-1", "Feishu A")
  })

  renderPage(<EnterpriseIdentityPage />)
  await waitFor(() => expect(screen.getByDisplayValue("Feishu A")).toBeTruthy())

  await act(async () => {
    screen.getAllByRole("button", { name: "保存" })[0]?.click()
  })
  await waitFor(() => expect(savedBody).toBeDefined())

  expect(savedBody).not.toHaveProperty("tenant_id")
})

test("shows one provider form and switches it from the dropdown", async () => {
  withFetch((url) => payloadFor(url, "ws-1", "Feishu A"))

  renderPage(<EnterpriseIdentityPage />)
  await waitFor(() => expect(screen.getByDisplayValue("Feishu A")).toBeTruthy())

  expect(screen.getAllByText("显示名称")).toHaveLength(1)
  expect(screen.getAllByRole("button", { name: "保存" })).toHaveLength(1)

  fireEvent.pointerDown(screen.getByRole("button", { name: "选择登录平台" }))
  fireEvent.click(
    within(await screen.findByRole("menu")).getByRole("menuitem", {
      name: "钉钉",
    })
  )

  expect(screen.getByDisplayValue("钉钉")).toBeTruthy()
  expect(screen.getByLabelText("企业 ID")).toBeTruthy()
  expect(screen.queryByDisplayValue("Feishu A")).toBeNull()
})
