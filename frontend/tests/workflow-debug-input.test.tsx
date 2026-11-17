/* @jsxImportSource react */
import { afterEach, expect, mock, test } from "bun:test"
import { cleanup, fireEvent, screen, within } from "@testing-library/react"
import { translate, type TFunction } from "@/i18n"
import type { Agent } from "@/lib/api/agents"
import type { AgentFormState } from "@/components/agents/agents-page"
import { defaultInteractionConfig } from "@/lib/interaction-config"
import { jsonResponse, renderPage, resetFetch, withFetch } from "./helpers/dom"

mock.module("next/dynamic", () => ({ default: () => () => null }))
const { WorkflowDetailWorkspace } =
  await import("@/components/workflows/workflow-detail-workspace")

afterEach(() => {
  cleanup()
  resetFetch()
})
test("workflow debugging sends on Enter while Shift and IME composition keep editing", async () => {
  const graph = { nodes: [], edges: [], viewport: { x: 0, y: 0, zoom: 1 } }
  withFetch((url) =>
    jsonResponse(
      url.endsWith("/definition")
        ? { id: "definition", revision: 1, graph }
        : url.includes("/versions")
          ? { items: [] }
          : []
    )
  )
  const form: AgentFormState = {
    id: "workflow",
    appType: "workflow",
    name: "Workflow",
    description: "",
    interactionConfig: defaultInteractionConfig(),
    modelId: "",
    imageModelId: "",
    instructions: "",
    knowledgeBaseIds: [],
    tools: [],
    skills: [],
    status: "active",
  }
  const t: TFunction = (key, values) => translate("zh-Hans", key, values)
  renderPage(
    <WorkflowDetailWorkspace
      agent={
        {
          id: "workflow",
          name: "Workflow",
          status: "active",
          can_edit: true,
        } as Agent
      }
      form={form}
      setForm={() => {}}
      models={[]}
      knowledgeBases={[]}
      mcpServers={[]}
      token="token"
      workspaceId="ws"
      canManagePublishing={false}
      isAppDirty={false}
      isSavingApp={false}
      onDiscardAppChanges={() => {}}
      activeView="settings"
      onBack={() => {}}
      onDelete={() => {}}
      onSaveApp={() => {}}
      onViewChange={() => {}}
      notify={() => {}}
      t={t}
    />
  )
  fireEvent.click(await screen.findByRole("button", { name: "调试运行" }))
  const input = within(
    screen.getByRole("dialog", { name: "运行工作流" })
  ).getByRole("textbox", { name: "请输入问题" }) as HTMLTextAreaElement
  let submits = 0
  input.form!.requestSubmit = () => {
    submits += 1
  }
  fireEvent.keyDown(input, { key: "Enter", shiftKey: true })
  fireEvent.keyDown(input, { key: "Enter", isComposing: true })
  expect(submits).toBe(0)
  fireEvent.keyDown(input, { key: "Enter" })
  expect(submits).toBe(1)
})
