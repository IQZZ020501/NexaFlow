/* @jsxImportSource react */
import { afterEach, expect, test } from "bun:test"
import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react"

import { PublicWorkflowChat } from "@/components/workflows/public-workflow-chat"
import type { ExternalWorkflowRun } from "@/lib/api/public-workflows"
import {
  jsonResponse,
  makeSession,
  mockNextNavigation,
  mockUseSession,
  renderPage,
  resetFetch,
  withFetch,
} from "./helpers/dom"

mockUseSession(makeSession())
mockNextNavigation()
afterEach(() => {
  cleanup()
  resetFetch()
})

test("restores a pending approval and resumes after the consumer approves", async () => {
  const pending: ExternalWorkflowRun = {
    id: "run-1",
    conversation_id: "conversation-1",
    inputs: { question: "查找音乐" },
    outputs: {},
    status: "awaiting_approval",
    error: null,
    progress: [],
    pending_form: null,
    created_at: "2026-11-17T00:00:00Z",
    updated_at: "2026-11-17T00:00:00Z",
    started_at: null,
    finished_at: null,
    tool_calls: [
      {
        call_id: "llm:llm:0:lookup",
        turn: 0,
        tool_name: "lookup",
        tool_kind: "mcp",
        server_name: "",
        arguments: { id: "123" },
        status: "awaiting_approval",
        approval_required: true,
        last_error: null,
        approved_at: null,
        started_at: null,
        finished_at: null,
      },
    ],
  }
  const decisions: unknown[] = []
  let observed = 0
  withFetch((url, init) => {
    if (url.endsWith("/profile"))
      return jsonResponse({
        id: "wf-1",
        name: "音乐查询",
        description: "",
        interaction_config: {
          prologue: "",
          tts_type: "BROWSER",
          file_upload: false,
          file_upload_setting: { file_upload_type: [] },
          user_input_title: "",
        },
      })
    if (url.endsWith("/conversations")) return jsonResponse({ items: [] })
    if (url.includes("/approval")) {
      expect(url).toContain("llm%3Allm%3A0%3Alookup")
      decisions.push(JSON.parse(String(init?.body)))
      return jsonResponse({ ...pending, status: "queued", tool_calls: [] })
    }
    if (url.includes("/stream")) {
      observed += 1
      return new Response(
        `${JSON.stringify({ type: "complete", sequence: 2, run: { ...pending, status: "succeeded", outputs: { result: "查询完成" }, tool_calls: [] } })}\n`
      )
    }
    if (url.includes("/runs?"))
      return jsonResponse({ items: [pending], total: 1 })
    throw new Error(`Unexpected request: ${url}`)
  })
  renderPage(
    <PublicWorkflowChat
      workflowId="wf-1"
      initialConversationId="conversation-1"
    />
  )
  const approve = await screen.findByRole("button", { name: "批准并执行" })
  expect(screen.getByText("工具调用需要确认")).toBeTruthy()
  expect(
    (screen.getByRole("textbox", { name: "请输入问题" }) as HTMLTextAreaElement)
      .disabled
  ).toBe(true)
  fireEvent.click(approve)
  await waitFor(() => expect(screen.getByText("查询完成")).toBeTruthy())
  expect(decisions).toEqual([{ approve: true }])
  expect(observed).toBe(1)
  expect(screen.queryByRole("button", { name: "批准并执行" })).toBeNull()
})
