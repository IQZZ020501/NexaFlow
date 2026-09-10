/* @jsxImportSource react */
import { afterEach, beforeEach, describe, expect, test } from "bun:test"
import { cleanup, screen, waitFor } from "@testing-library/react"

import { AgentApiDocumentation } from "@/components/agents/agent-api-documentation"
import { WorkflowApiDocumentation } from "@/components/workflows/workflow-api-documentation"

import {
  jsonResponse,
  makeSession,
  mockUseSession,
  renderPage,
  withFetch,
} from "./helpers/dom"

const session = makeSession()
mockUseSession(session)

beforeEach(() => {
  Object.assign(session, {
    token: "session-token",
    isSessionRestored: true,
  })
})

afterEach(() => {
  cleanup()
})

describe("API documentation browser session", () => {
  test("opens Agent documentation without asking for an API key", async () => {
    let requestedUrl = ""
    let authorization = ""
    withFetch((url, init) => {
      requestedUrl = url
      authorization = new Headers(init?.headers).get("Authorization") ?? ""
      return jsonResponse({
        agent_id: "agent-1",
        agent_name: "Support Agent",
        base_path: "/api/v1/agent-api/agent-1",
      })
    })

    renderPage(<AgentApiDocumentation agentId="agent-1" />)

    await waitFor(() => expect(screen.getByText("Support Agent")).toBeTruthy())
    expect(requestedUrl).toBe("/api/v1/public/agents/agent-1/documentation")
    expect(authorization).toBe("Bearer session-token")
    expect(screen.getByText("基础地址")).toBeTruthy()
    expect(
      screen.getByText("/api/v1/agent-api/agent-1", { selector: "code" })
    ).toBeTruthy()
    expect(screen.getByRole("heading", { name: "创建运行" })).toBeTruthy()
    expect(screen.getAllByText("conversation_id").length).toBeGreaterThan(0)
    expect(screen.getByText("429")).toBeTruthy()
    expect(screen.queryByText("使用 API Key 查看文档")).toBeNull()
    expect(screen.queryByText("更换 API Key")).toBeNull()
  })

  test("opens workflow documentation without asking for an API key", async () => {
    let requestedUrl = ""
    withFetch((url) => {
      requestedUrl = url
      return jsonResponse({
        workflow_id: "workflow-1",
        workflow_name: "Release Workflow",
        base_path: "/api/v1/workflow-api/workflow-1",
        interaction_config: {
          prologue: "",
          tts_type: "BROWSER",
          file_upload: false,
          file_upload_setting: { file_upload_type: [] },
          user_input_title: "",
        },
      })
    })

    renderPage(<WorkflowApiDocumentation workflowId="workflow-1" />)

    await waitFor(() =>
      expect(screen.getByText("Release Workflow")).toBeTruthy()
    )
    expect(requestedUrl).toBe(
      "/api/v1/public/workflows/workflow-1/documentation"
    )
    expect(screen.queryByText("使用 API Key 查看文档")).toBeNull()
  })

  test("keeps API-key unlock available without a browser session", () => {
    Object.assign(session, { token: null, isSessionRestored: true })

    renderPage(<AgentApiDocumentation agentId="agent-1" />)

    expect(screen.getByText("使用 API Key 查看文档")).toBeTruthy()
  })

  test("falls back to API-key unlock when the session has no access", async () => {
    withFetch(() => jsonResponse({ detail: "Agent not found." }, 404))

    renderPage(<AgentApiDocumentation agentId="agent-1" />)

    await waitFor(() =>
      expect(screen.getByText("使用 API Key 查看文档")).toBeTruthy()
    )
  })
})
