/* @jsxImportSource react */
import { afterEach, expect, mock, test } from "bun:test"
import { cleanup, screen, waitFor } from "@testing-library/react"

import { PublicApplicationChat } from "@/components/apps/public-application-chat"

import {
  makeSession,
  mockNextNavigation,
  mockUseSession,
  renderPage,
} from "./helpers/dom"

mock.module("@/components/agents/public-agent-chat", () => ({
  PublicAgentChat: () => <main>Public Agent</main>,
}))
mock.module("@/components/workflows/public-workflow-chat", () => ({
  PublicWorkflowChat: () => <main>Public Workflow</main>,
}))
mock.module("@/lib/api/public-agents", () => ({
  getPublicAgentProfile: async () => ({ id: "agent-1" }),
}))
mock.module("@/lib/api/public-workflows", () => ({
  getPublicWorkflowProfile: async () => ({ id: "workflow-1" }),
}))

const session = makeSession({
  notification: { id: 1, kind: "success", message: "已点赞" },
})
mockUseSession(session)
mockNextNavigation()

afterEach(() => cleanup())

test("shows operation notifications on the public chat route", async () => {
  renderPage(
    <PublicApplicationChat
      applicationId="agent-1"
      initialConversationId={null}
    />
  )

  await waitFor(() => expect(screen.getByText("Public Agent")).toBeTruthy())
  const notification = screen.getByRole("status")
  expect(notification.textContent).toContain("已点赞")
  expect(notification.className).toContain("max-w-xs")
})
