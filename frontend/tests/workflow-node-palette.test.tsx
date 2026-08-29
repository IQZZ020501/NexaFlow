/* @jsxImportSource react */
import { describe, expect, test } from "bun:test"

import { WorkflowNodePalette } from "@/components/workflows/workflow-node-palette"
import type { Agent } from "@/lib/api/agents"
import type { ToolDetail } from "@/lib/api/tools"
import { translate } from "@/i18n"
import { fireEvent, renderPage, screen } from "./helpers/dom"

const tool: ToolDetail = {
  id: "tool-1",
  workspace_id: "ws-1",
  kind: "python",
  function_name: "lookup",
  display_name: "Lookup",
  description: "Lookup data",
  current_version_id: "version-1",
  status: "active",
  availability: "available",
  source: { id: "source-1", name: "Mine", kind: "python", transport: null },
  created_by_user_id: "u-1",
  permission: "owner",
  can_view: true,
  can_use: true,
  can_manage: true,
  version_id: "version-1",
  revision: 1,
  input_schema: { type: "object", properties: { query: { type: "string" } } },
  output_schema: { type: "object" },
  approval: "auto",
  effect: "pure",
  workflow_callable: true,
  parallel_safe: false,
  draft: null,
}

const agent: Agent & { current_published_version_id: string | null } = {
  id: "agent-1",
  workspace_id: "ws-1",
  name: "Research agent",
  app_type: "agent",
  description: "Research topics",
  interaction_config: {
    prologue: "",
    tts_type: "NONE",
    file_upload: false,
    file_upload_setting: { file_upload_type: [] },
    user_input_title: "",
  },
  instructions: "Research",
  model_id: "model-1",
  knowledge_query_mode: "agentic",
  knowledge_base_ids: [],
  mcp_tools: [],
  status: "active",
  published: true,
  current_published_version_id: "agent-version-1",
  has_unpublished_changes: false,
  published_by_user_id: "u-1",
  published_at: "2026-08-17T00:00:00Z",
  created_by_user_id: "u-1",
  can_edit: false,
  created_at: "2026-08-17T00:00:00Z",
  updated_at: "2026-08-17T00:00:00Z",
}

describe("WorkflowNodePalette", () => {
  test("does not expose an add entry for read-only Workflows", () => {
    renderPage(
      <WorkflowNodePalette
        tools={[tool]}
        agents={[agent]}
        graph={{ nodes: [], edges: [], viewport: { x: 0, y: 0, zoom: 1 } }}
        onAdd={() => undefined}
        t={(key, values) => translate("zh-Hans", key, values)}
        readOnly
      />
    )

    expect(screen.queryByRole("button", { name: "添加节点" })).toBeNull()
  })

  test("uses the exact three tabs and creates pinned tool and Agent nodes", () => {
    const added: Array<{ type: string; config?: Record<string, unknown> }> = []
    renderPage(
      <WorkflowNodePalette
        tools={[tool]}
        agents={[agent]}
        graph={{ nodes: [], edges: [], viewport: { x: 0, y: 0, zoom: 1 } }}
        onAdd={(type, _title, config) => added.push({ type, config })}
        t={(key, values) => translate("zh-Hans", key, values)}
      />
    )
    fireEvent.click(screen.getByRole("button", { name: "添加节点" }))
    expect(screen.getAllByRole("tab").map((tab) => tab.textContent)).toEqual([
      "基础节点",
      "工具",
      "Agent",
    ])
    fireEvent.mouseDown(screen.getByRole("tab", { name: "工具" }), {
      button: 0,
      ctrlKey: false,
    })
    fireEvent.click(screen.getByRole("button", { name: "Lookup" }))
    expect(added.at(-1)).toEqual({
      type: "tool",
      config: {
        tool: { tool_id: "tool-1", version_id: "version-1" },
        arguments: {},
      },
    })

    fireEvent.click(screen.getByRole("button", { name: "添加节点" }))
    fireEvent.mouseDown(screen.getByRole("tab", { name: "Agent" }), {
      button: 0,
      ctrlKey: false,
    })
    fireEvent.click(screen.getByRole("button", { name: "Research agent" }))
    expect(added.at(-1)).toEqual({
      type: "agent",
      config: {
        agent_id: "agent-1",
        agent_version_id: "agent-version-1",
        input: "{{start.question}}",
      },
    })
  })

  test("offers a built-in Skill as a selectable Workflow tool", () => {
    const added: Array<{ type: string; config?: Record<string, unknown> }> = []
    const skillTool = {
      ...tool,
      id: "skill-documents",
      function_name: "documents_skill",
      display_name: "Documents Skill",
      input_schema: {
        type: "object",
        properties: {
          content: { type: "string" },
          filename: { type: "string" },
        },
      },
    }
    renderPage(
      <WorkflowNodePalette
        tools={[skillTool]}
        agents={[]}
        graph={{ nodes: [], edges: [], viewport: { x: 0, y: 0, zoom: 1 } }}
        onAdd={(type, _title, config) => added.push({ type, config })}
        t={(key, values) => translate("zh-Hans", key, values)}
      />
    )
    fireEvent.click(screen.getByRole("button", { name: "添加节点" }))
    fireEvent.mouseDown(screen.getByRole("tab", { name: "工具" }), {
      button: 0,
      ctrlKey: false,
    })
    fireEvent.click(screen.getByRole("button", { name: "文档 Skill" }))
    expect(added.at(-1)).toEqual({
      type: "tool",
      config: {
        tool: { tool_id: "skill-documents", version_id: "version-1" },
        arguments: {},
      },
    })
  })

  test("does not offer the legacy artifact runtime as a Workflow tool", () => {
    renderPage(
      <WorkflowNodePalette
        tools={[
          {
            ...tool,
            function_name: "create_artifact",
            display_name: "Create downloadable file",
          },
        ]}
        agents={[]}
        graph={{ nodes: [], edges: [], viewport: { x: 0, y: 0, zoom: 1 } }}
        onAdd={() => undefined}
        t={(key, values) => translate("zh-Hans", key, values)}
      />
    )
    fireEvent.click(screen.getByRole("button", { name: "添加节点" }))
    fireEvent.mouseDown(screen.getByRole("tab", { name: "工具" }), {
      button: 0,
      ctrlKey: false,
    })
    expect(screen.queryByRole("button", { name: "创建文件" })).toBeNull()
  })

  test("keeps visible tools disabled with localized reasons and filters Agents", () => {
    const added: string[] = []
    renderPage(
      <WorkflowNodePalette
        tools={[
          {
            ...tool,
            id: "approval-tool",
            display_name: "Approval tool",
            approval: "each_call",
          },
          {
            ...tool,
            id: "disabled-tool",
            display_name: "Disabled tool",
            approval: "disabled",
          },
          {
            ...tool,
            id: "unavailable-tool",
            display_name: "Unavailable tool",
            availability: "unavailable",
          },
          {
            ...tool,
            id: "forbidden-tool",
            display_name: "Forbidden tool",
            can_use: false,
          },
          {
            ...tool,
            id: "direct-only-tool",
            display_name: "Direct only tool",
            workflow_callable: false,
          },
        ]}
        agents={[
          {
            ...agent,
            id: "draft",
            published: false,
            current_published_version_id: null,
          },
          { ...agent, id: "workflow", app_type: "workflow" },
        ]}
        graph={{ nodes: [], edges: [], viewport: { x: 0, y: 0, zoom: 1 } }}
        onAdd={(type) => added.push(type)}
        t={(key, values) => translate("zh-Hans", key, values)}
      />
    )
    fireEvent.click(screen.getByRole("button", { name: "添加节点" }))
    fireEvent.mouseDown(screen.getByRole("tab", { name: "工具" }), {
      button: 0,
      ctrlKey: false,
    })
    for (const name of [
      "Approval tool",
      "Disabled tool",
      "Unavailable tool",
      "Forbidden tool",
      "Direct only tool",
    ]) {
      expect(
        (screen.getByRole("button", { name }) as HTMLButtonElement).disabled
      ).toBe(true)
    }
    expect(screen.getByText("需要逐次审批")).toBeTruthy()
    expect(screen.getByText("工具调用已禁用")).toBeTruthy()
    expect(screen.getByText("工具当前不可用")).toBeTruthy()
    expect(screen.getByText("没有使用权限")).toBeTruthy()
    expect(screen.getByText("不支持工作流调用")).toBeTruthy()
    fireEvent.click(screen.getByRole("button", { name: "Approval tool" }))
    expect(added).toEqual([])
    fireEvent.mouseDown(screen.getByRole("tab", { name: "Agent" }), {
      button: 0,
      ctrlKey: false,
    })
    expect(screen.getByText("暂无可用 Agent")).toBeTruthy()
  })

  test("shows a retryable error when any Tool detail could not load", () => {
    let retries = 0
    renderPage(
      <WorkflowNodePalette
        tools={[tool]}
        agents={[]}
        graph={{ nodes: [], edges: [], viewport: { x: 0, y: 0, zoom: 1 } }}
        toolsError="detail unavailable"
        onRetryTools={() => {
          retries += 1
        }}
        onAdd={() => undefined}
        t={(key, values) => translate("zh-Hans", key, values)}
      />
    )

    fireEvent.click(screen.getByRole("button", { name: "添加节点" }))
    fireEvent.mouseDown(screen.getByRole("tab", { name: "工具" }), {
      button: 0,
      ctrlKey: false,
    })
    expect(screen.getByText("工具加载失败")).toBeTruthy()
    expect(screen.getByText("detail unavailable")).toBeTruthy()
    expect(screen.getByRole("button", { name: "Lookup" })).toBeTruthy()
    fireEvent.click(screen.getByRole("button", { name: "重试" }))
    expect(retries).toBe(1)
  })
})
