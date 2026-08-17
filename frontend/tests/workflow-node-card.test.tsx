/* @jsxImportSource react */
/**
 * DOM-level coverage for the workflow node card (components/workflows/
 * workflow-node.tsx): every node type renders, expands, and exposes its
 * settings; interactions (collapse, rename, delete, settings dialog,
 * read-only, runtime status) behave as users see them.
 */
import { afterEach, beforeEach, describe, expect, test } from "bun:test"
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react"
import { ReactFlowProvider } from "@xyflow/react"
import type { ReactElement } from "react"

import { WorkflowNodeCard } from "@/components/workflows/workflow-node"
import type { Agent } from "@/lib/api/agents"
import type { KnowledgeBase } from "@/lib/api/knowledge"
import type { RegisteredModel } from "@/lib/api/llm"
import type { McpServer } from "@/lib/api/mcp"
import type { ToolDetail } from "@/lib/api/tools"
import type {
  WorkflowEdge,
  WorkflowNode,
  WorkflowNodeData,
  WorkflowNodeExecution,
  WorkflowNodeType,
} from "@/lib/api/workflows"
import { makeSession, mockUseSession, renderPage } from "./helpers/dom"

const WS = "ws-1"

function model(
  id: string,
  name: string,
  modelType: "LLM" | "RERANKER" = "LLM"
): RegisteredModel {
  return {
    id,
    workspace_id: WS,
    name,
    provider: "deepseek",
    provider_type: "openai",
    model_type: modelType,
    model_name: `model-${id}`,
    status: "active",
    credential: {},
    api_base: "",
    has_api_key: true,
    api_key_hint: "sk-…abc",
  } as RegisteredModel
}

function agent(id: string, name: string): Agent {
  return {
    id,
    workspace_id: WS,
    name,
    app_type: "agent",
    status: "active",
    description: "",
    model_id: "model-1",
    interaction_config: {
      conversation_type: "single",
      message_turn_limit: 10,
      message_word_limit: 100,
    },
    instructions: "Answer directly.",
    knowledge_query_mode: "required",
    knowledge_base_ids: [],
    tools: [],
    created_by_user_id: "u-1",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
  } as unknown as Agent
}

function tool(id: string, displayName: string): ToolDetail {
  return {
    id,
    workspace_id: WS,
    kind: "builtin",
    function_name: `fn_${id}`,
    display_name: displayName,
    description: "A tool",
    current_version_id: "version-1",
    status: "active",
    availability: "available",
    source: {
      id: "source-1",
      name: "Built-in",
      kind: "builtin",
      transport: null,
    },
    created_by_user_id: "u-1",
    permission: "use",
    can_view: true,
    can_use: true,
    can_manage: false,
  } as ToolDetail
}

function workflowTool(id: string, displayName: string): ToolDetail {
  return {
    ...tool(id, displayName),
    approval: "auto",
    workflow_callable: true,
  } as ToolDetail
}

function knowledgeBase(id: string, name: string) {
  return {
    id,
    workspace_id: WS,
    name,
    description: "",
    status: "active",
    permission: "edit",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
  } as unknown as KnowledgeBase
}

function mcpServer(
  id: string,
  name: string,
  tools: Array<{ name: string; policyMode?: "read_only" | "approval_required" }>
) {
  return {
    id,
    workspace_id: WS,
    name,
    transport: "streamable_http",
    url: "http://localhost:8000",
    stdio_command: null,
    tools: tools.map((tool) => ({
      name: tool.name,
      description: "MCP tool",
      input_schema: {},
      annotations: null,
      definition_hash: "hash",
      policy_mode: tool.policyMode ?? "read_only",
    })),
    status: "active",
    has_bearer_token: false,
    bearer_token_hint: null,
    last_error: null,
    created_by_user_id: "u-1",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
  } as unknown as McpServer
}

function graphNode(
  id: string,
  type: WorkflowNodeType,
  title: string
): WorkflowNode {
  return {
    id,
    type: "workflow",
    position: { x: 0, y: 0 },
    data: nodeData(type, { title }),
  } as unknown as WorkflowNode
}

/** Guarded access to `config.branch` (condition node) as plain objects. */
function branchList(
  data: WorkflowNodeData | undefined
): Array<Record<string, unknown>> {
  const list = data?.config.branch
  if (!Array.isArray(list)) return []
  return list.filter(
    (item): item is Record<string, unknown> =>
      Boolean(item) && typeof item === "object" && !Array.isArray(item)
  )
}

/** Guarded access to a condition branch's `conditions` array. */
function ruleList(
  branch: Record<string, unknown> | undefined
): Array<Record<string, unknown>> {
  if (!branch || !Array.isArray(branch.conditions)) return []
  return branch.conditions.filter(
    (item): item is Record<string, unknown> =>
      Boolean(item) && typeof item === "object" && !Array.isArray(item)
  )
}

/** Guarded access to `config.form_field_list` (form node) as plain objects. */
function fieldList(
  data: WorkflowNodeData | undefined
): Array<Record<string, unknown>> {
  const list = data?.config.form_field_list
  if (!Array.isArray(list)) return []
  return list.filter(
    (item): item is Record<string, unknown> =>
      Boolean(item) && typeof item === "object" && !Array.isArray(item)
  )
}

function nodeData(
  type: WorkflowNodeType,
  overrides: Partial<WorkflowNodeData> = {}
): WorkflowNodeData {
  return {
    type,
    title: `Node ${type}`,
    config: {},
    onUpdate: () => undefined,
    agent: agent("agent-wf", "Workflow"),
    models: [model("model-1", "DeepSeek Chat")],
    knowledgeBases: [],
    mcpServers: [],
    tools: [],
    agents: [agent("agent-1", "Research agent")],
    ...overrides,
  }
}

function renderNode(
  data: WorkflowNodeData,
  {
    id = "node-1",
    selected = false,
  }: { id?: string; selected?: boolean } = {}
) {
  const ui = (
    <ReactFlowProvider>
      <WorkflowNodeCard
        id={id}
        data={data}
        selected={selected}
        type="workflow"
        dragging={false}
        zIndex={0}
        selectable={false}
        deletable={false}
        draggable={false}
        isConnectable={false}
        positionAbsoluteX={0}
        positionAbsoluteY={0}
      />
    </ReactFlowProvider>
  ) as ReactElement
  return renderPage(ui)
}

beforeEach(() => {
  mockUseSession()
})
afterEach(() => {
  cleanup()
})

describe("WorkflowNodeCard", () => {
  test("renders every node type with its localized label", () => {
    const labels: Array<[WorkflowNodeType, string]> = [
      ["start", "开始节点"],
      ["end", "结束节点"],
      ["llm", "大语言模型"],
      ["classifier", "问题分类器"],
      ["knowledge", "知识检索节点"],
      ["reranker-node", "多路召回"],
      ["form-node", "表单收集"],
      ["document-extract-node", "文档内容提取"],
      ["condition", "条件分支"],
      ["reply-node", "指定回复"],
      ["template", "模板转换"],
      ["variable", "变量赋值"],
      ["tool", "工具"],
      ["agent", "Agent"],
      ["mcp", "MCP 工具节点"],
      ["code", "Python 代码"],
    ]
    for (const [type, label] of labels) {
      renderNode(nodeData(type))
      expect(screen.getByText(`Node ${type}`)).toBeTruthy()
      if (type === "tool" || type === "agent" || type === "code") {
        expect(screen.getAllByText(label).length).toBeGreaterThan(0)
      } else {
        expect(screen.getByText(label)).toBeTruthy()
      }
    }
  })

  test("collapses and re-expands the configuration", () => {
    renderNode(
      nodeData("llm", { config: { prompt: "Summarize this" } })
    )
    expect(screen.getByRole("button", { name: "收起节点" })).toBeTruthy()
    expect(screen.getByLabelText("提示词")).toBeTruthy()
    fireEvent.click(screen.getByRole("button", { name: "收起节点" }))
    expect(screen.getByRole("button", { name: "展开节点" })).toBeTruthy()
    expect(screen.queryByLabelText("提示词")).toBeNull()
    fireEvent.click(screen.getByRole("button", { name: "展开节点" }))
    expect(screen.getByLabelText("提示词")).toBeTruthy()
  })

  test("deletes a node through the more menu and confirm dialog", async () => {
    const deleted: string[] = []
    renderNode(
      nodeData("knowledge", {
        onDelete: (nodeId) => deleted.push(nodeId),
      })
    )
    const trigger = screen.getByTitle("更多")
    fireEvent.pointerDown(trigger)
    fireEvent.click(trigger)
    fireEvent.click(await screen.findByRole("menuitem", { name: /删除节点/ }))
    fireEvent.click(await screen.findByRole("button", { name: "删除" }))
    await waitFor(() => expect(deleted).toEqual(["node-1"]))
  })

  test("exposes rename through the more menu", async () => {
    // The input lifecycle itself (autoFocus + radix focus restore) races in
    // happy-dom; the commitTitle/Enter/Escape logic is covered by the
    // source-level layout test. Here we assert the entry point exists and
    // selection fires (menu closes).
    renderNode(
      nodeData("start", {
        onRename: () => undefined,
      })
    )
    const trigger = screen.getByTitle("更多")
    fireEvent.pointerDown(trigger)
    fireEvent.click(trigger)
    expect(
      await screen.findByRole("menuitem", { name: /重命名/ })
    ).toBeTruthy()
    fireEvent.click(screen.getByRole("menuitem", { name: /重命名/ }))
    await waitFor(() =>
      expect(screen.queryAllByRole("menuitem")).toEqual([])
    )
  })

  test("read-only nodes hide the more menu", () => {
    renderNode(nodeData("llm", { readOnly: true }))
    expect(screen.queryByRole("button", { name: "更多" })).toBeNull()
  })

  test("shows the runtime status chip", () => {
    renderNode(nodeData("llm", { runtimeStatus: "failed" }))
    expect(screen.getByText("运行失败")).toBeTruthy()
  })

  test("LLM settings dialog opens from the card", () => {
    renderNode(
      nodeData("llm", {
        config: { prompt: "Hello", model_setting: {} },
      })
    )
    fireEvent.click(screen.getByRole("button", { name: "高级模型设置" }))
    const dialog = screen.getByRole("dialog")
    expect(within(dialog).getByText("高级模型设置")).toBeTruthy()
    fireEvent.click(within(dialog).getByRole("button", { name: "关闭" }))
  })

  test("condition node renders its branch list", () => {
    renderNode(
      nodeData("condition", {
        config: {
          branch_list: [
            { branch_name: "yes", condition: "{{x}} == 1", handle: "yes" },
          ],
        },
      })
    )
    expect(screen.getByText("条件分支")).toBeTruthy()
  })

  test("form node lists its fields", () => {
    renderNode(
      nodeData("form-node", {
        config: {
          form_field_list: [
            {
              variable: "name",
              name: "姓名",
              type: "input",
              is_required: true,
              default_value: "",
              show_default_value: false,
              optionList: [],
            },
          ],
        },
      })
    )
    expect(
      (screen.getByLabelText("显示名称") as HTMLInputElement).value
    ).toBe("姓名")
  })

  test("tool node shows its pinned binding name", () => {
    renderNode(
      nodeData("tool", {
        tools: [tool("tool-1", "Current Time")],
        config: {
          tool: { tool_id: "tool-1", version_id: "version-1" },
          arguments: {},
        },
      })
    )
    expect(screen.getByText("Current Time")).toBeTruthy()
  })

  test("tool node keeps unavailable bindings visible and offers version upgrades", () => {
    const updates: WorkflowNodeData[] = []
    const unavailable = {
      ...workflowTool("tool-1", "Current Time"),
      current_version_id: "version-2",
      status: "disabled",
      availability: "unavailable",
      can_use: false,
    } as ToolDetail
    const { unmount } = renderNode(
      nodeData("tool", {
        tools: [unavailable],
        config: {
          tool: { tool_id: "tool-1", version_id: "version-1" },
          arguments: {},
        },
      })
    )
    expect(screen.getByText("工具已不可用或授权已撤销")).toBeTruthy()
    expect(screen.getByText("可从节点菜单移除该工具")).toBeTruthy()
    expect(
      screen.queryByRole("button", { name: "升级到当前版本" })
    ).toBeNull()

    unmount()
    renderNode(
      nodeData("tool", {
        onUpdate: (data) => updates.push(data),
        tools: [
          {
            ...workflowTool("tool-1", "Current Time"),
            current_version_id: "version-2",
          } as ToolDetail,
        ],
        config: {
          tool: { tool_id: "tool-1", version_id: "version-1" },
          arguments: {},
        },
      })
    )
    fireEvent.click(
      screen.getByRole("button", { name: "升级到当前版本" })
    )
    expect(updates.at(-1)?.config.tool).toEqual({
      tool_id: "tool-1",
      version_id: "version-2",
    })
  })

  test("selected card gains the selection ring", () => {
    renderNode(nodeData("llm"), { selected: true })
    const title = screen.getByText("Node llm")
    const card = title.closest("div[class*='relative']")!
    expect(card.className).toContain("ring-2")
  })

  test("knowledge node selects its knowledge base", async () => {
    const updates: WorkflowNodeData[] = []
    renderNode(
      nodeData("knowledge", {
        onUpdate: (data) => updates.push(data),
        knowledgeBases: [
          {
            id: "kb-1",
            workspace_id: WS,
            name: "Docs",
            description: "",
            status: "active",
            permission: "edit",
            created_at: "2026-01-01T00:00:00Z",
            updated_at: "2026-01-01T00:00:00Z",
          } as unknown as import("@/lib/api/knowledge").KnowledgeBase,
        ],
        config: { search_mode: "embedding" },
      })
    )
    const trigger = screen.getByRole("button", { name: "选择知识库" })
    fireEvent.pointerDown(trigger)
    fireEvent.click(trigger)
    fireEvent.click(await screen.findByText("Docs"))
    expect(updates.length).toBeGreaterThan(0)
    expect(updates.at(-1)?.config.knowledge_base_ids).toContain("kb-1")
  })

  test("LLM model selector commits a model choice", async () => {
    const updates: WorkflowNodeData[] = []
    renderNode(
      nodeData("llm", {
        onUpdate: (data) => updates.push(data),
        config: { prompt: "x" },
      })
    )
    const trigger = screen.getByRole("button", { name: "节点模型" })
    fireEvent.pointerDown(trigger)
    fireEvent.click(trigger)
    fireEvent.click(
      await screen.findByRole("menuitem", { name: /DeepSeek Chat/ })
    )
    expect(updates.at(-1)?.config.model_id).toBe("model-1")
  })

  test("reply node switches between custom and referencing modes", async () => {
    const updates: WorkflowNodeData[] = []
    renderNode(
      nodeData("reply-node", {
        onUpdate: (data) => updates.push(data),
        config: { reply_type: "custom", answer: "Hello" },
      })
    )
    fireEvent.pointerDown(screen.getByRole("button", { name: "自定义" }))
    fireEvent.click(screen.getByRole("button", { name: "自定义" }))
    fireEvent.click(
      await screen.findByRole("menuitem", { name: /引用变量/ })
    )
    expect(updates.at(-1)?.config.reply_type).toBe("referencing")
  })

  test("condition node adds a branch", () => {
    const updates: WorkflowNodeData[] = []
    renderNode(
      nodeData("condition", {
        onUpdate: (data) => updates.push(data),
        config: { branch_list: [] },
      })
    )
    fireEvent.click(screen.getByRole("button", { name: "添加分支" }))
    expect(updates.at(-1)?.config.branch_list).toBeDefined()
  })

  test("form node adds a field", () => {
    const updates: WorkflowNodeData[] = []
    renderNode(
      nodeData("form-node", {
        onUpdate: (data) => updates.push(data),
        config: { form_field_list: [] },
      })
    )
    fireEvent.click(screen.getByRole("button", { name: "添加字段" }))
    const fields = updates.at(-1)?.config.form_field_list as unknown[]
    expect(fields?.length).toBe(1)
  })

  test("code node edits its code body", () => {
    const updates: WorkflowNodeData[] = []
    renderNode(
      nodeData("code", {
        onUpdate: (data) => updates.push(data),
        config: { code: "print(1)" },
      })
    )
    const editor = screen.getByLabelText("Python 代码")
    fireEvent.change(editor, { target: { value: "print(2)" } })
    expect(updates.at(-1)?.config.code).toBe("print(2)")
  })

  test("end node adds and removes an output mapping", () => {
    const updates: WorkflowNodeData[] = []
    renderNode(
      nodeData("end", {
        onUpdate: (data) => updates.push(data),
        config: { outputs: { result: "{{start.question}}" } },
      })
    )
    fireEvent.click(screen.getByRole("button", { name: "添加" }))
    const outputs = updates.at(-1)?.config.outputs as Record<string, unknown>
    expect(Object.keys(outputs).length).toBe(2)
    // The fixture's onUpdate does not re-render the card, so the visible
    // rows stay at the original mapping; removing it must drop "result".
    fireEvent.click(screen.getByRole("button", { name: "删除" }))
    const after = updates.at(-1)?.config.outputs as Record<string, unknown>
    expect(after).not.toHaveProperty("result")
  })

  test("agent node shows its pinned binding and edits input", () => {
    const updates: WorkflowNodeData[] = []
    renderNode(
      nodeData("agent", {
        onUpdate: (data) => updates.push(data),
        config: { agent_id: "agent-1", input: "hello" },
      })
    )
    expect(screen.getByDisplayValue("Research agent")).toBeTruthy()
    const editor = screen.getByLabelText("输入内容")
    fireEvent.change(editor, { target: { value: "revised" } })
    expect(updates.at(-1)?.config.input).toBe("revised")
  })

  test("shows every runtime status chip label", () => {
    const cases: Array<[WorkflowNodeExecution["status"], string]> = [
      ["running", "运行中"],
      ["awaiting_input", "等待填写表单"],
      ["awaiting_child", "等待执行"],
      ["succeeded", "运行成功"],
      ["skipped", "已跳过"],
    ]
    for (const [status, label] of cases) {
      cleanup()
      renderNode(
        nodeData("llm", { runtimeStatus: status })
      )
      expect(screen.getByText(label)).toBeTruthy()
    }
  })

  test("more menu copies the node", async () => {
    const copied: string[] = []
    renderNode(
      nodeData("llm", {
        onCopy: (nodeId) => copied.push(nodeId),
        config: { prompt: "x" },
      })
    )
    const trigger = screen.getByTitle("更多")
    fireEvent.pointerDown(trigger)
    fireEvent.click(trigger)
    fireEvent.click(await screen.findByRole("menuitem", { name: /复制节点/ }))
    await waitFor(() => expect(copied).toEqual(["node-1"]))
  })

  test("LLM settings dialog commits model params and reasoning toggle", () => {
    const updates: WorkflowNodeData[] = []
    renderNode(
      nodeData("llm", {
        onUpdate: (data) => updates.push(data),
        config: { prompt: "x", model_params_setting: { temperature: 0.5 } },
      })
    )
    fireEvent.click(screen.getByRole("button", { name: "高级模型设置" }))
    const dialog = screen.getByRole("dialog")
    const temperature = within(dialog).getByLabelText("温度")
    expect((temperature as HTMLInputElement).value).toBe("0.5")
    fireEvent.change(temperature, { target: { value: "0.7" } })
    expect(updates[0].config.model_params_setting).toEqual({
      temperature: 0.7,
    })
    fireEvent.change(within(dialog).getByLabelText("Top P"), {
      target: { value: "0.5" },
    })
    // The fixture's onUpdate does not re-render, so later payloads rebuild
    // from the original render's model_params_setting ({temperature: 0.5}).
    expect(updates[1].config.model_params_setting).toMatchObject({ top_p: 0.5 })
    fireEvent.change(within(dialog).getByLabelText("最大输出 Token"), {
      target: { value: "2048" },
    })
    expect(updates[2].config.model_params_setting).toMatchObject({
      max_tokens: 2048,
    })
    fireEvent.click(within(dialog).getByRole("switch", { name: "思考过程" }))
    expect(updates[3].config.model_setting).toEqual({
      reasoning_content_enable: true,
    })
    // Empty temperature removes the key from the base params.
    fireEvent.change(temperature, { target: { value: "" } })
    expect(updates[4].config.model_params_setting).toEqual({})
    fireEvent.click(within(dialog).getByRole("button", { name: "关闭" }))
  })

  test("LLM node edits dialogue history mode and number", async () => {
    const updates: WorkflowNodeData[] = []
    renderNode(
      nodeData("llm", {
        onUpdate: (data) => updates.push(data),
        config: { prompt: "x", dialogue_type: "NODE", dialogue_number: 2 },
      })
    )
    expect(screen.getByText("仅取本节点历史")).toBeTruthy()
    const dialogueTrigger = screen.getByRole("button", { name: "多轮对话数" })
    fireEvent.pointerDown(dialogueTrigger)
    fireEvent.click(dialogueTrigger)
    fireEvent.click(
      await screen.findByRole("menuitem", { name: "整条流程历史" })
    )
    expect(updates.at(-1)?.config.dialogue_type).toBe("WORKFLOW")
    fireEvent.change(screen.getByRole("spinbutton", { name: "多轮对话数" }), {
      target: { value: "5" },
    })
    expect(updates.at(-1)?.config.dialogue_number).toBe(5)
    fireEvent.click(screen.getByRole("switch", { name: "返回内容" }))
    expect(updates.at(-1)?.config.is_result).toBe(false)
  })

  test("LLM node toggles workflow tools", () => {
    // Check path: unchecked → checked.
    const updates: WorkflowNodeData[] = []
    renderNode(
      nodeData("llm", {
        onUpdate: (data) => updates.push(data),
        tools: [workflowTool("tool-1", "Weather")],
        config: { prompt: "x" },
      })
    )
    fireEvent.click(screen.getByRole("checkbox", { name: "Weather" }))
    expect(updates.at(-1)?.config.tools).toEqual([
      { tool_id: "tool-1", version_id: "version-1" },
    ])
    // Uncheck path: controlled checkboxes snap back to the render's props,
    // so re-render with the tool already pinned to observe the removal.
    cleanup()
    const removals: WorkflowNodeData[] = []
    renderNode(
      nodeData("llm", {
        onUpdate: (data) => removals.push(data),
        tools: [workflowTool("tool-1", "Weather")],
        config: {
          prompt: "x",
          tools: [{ tool_id: "tool-1", version_id: "version-1" }],
        },
      })
    )
    fireEvent.click(screen.getByRole("checkbox", { name: "Weather" }))
    expect(removals.at(-1)?.config.tools).toEqual([])
  })

  test("LLM node lists no available tools", () => {
    renderNode(nodeData("llm", { config: { prompt: "x" } }))
    expect(screen.getByText("暂无可用工具")).toBeTruthy()
  })

  test("LLM node shows unavailable tools and MCP switches", async () => {
    const updates: WorkflowNodeData[] = []
    renderNode(
      nodeData("llm", {
        onUpdate: (data) => updates.push(data),
        mcpServers: [
          mcpServer("mcp-1", "My MCP", [
            { name: "search" },
            { name: "fetch", policyMode: "approval_required" },
          ]),
        ],
        config: {
          prompt: "x",
          mcp_enable: true,
          tools: [
            { tool_id: "gone-1", version_id: "v1" },
            { tool_id: "no-version" },
          ],
        },
      })
    )
    expect(screen.getByText(/gone-1/)).toBeTruthy()
    expect(screen.getByText("My MCP / search")).toBeTruthy()
    expect(screen.queryByText("My MCP / fetch")).toBeNull()
    // Toggle the read-only MCP tool on (the reference carries its label).
    fireEvent.click(screen.getByRole("checkbox", { name: "My MCP / search" }))
    expect(updates.at(-1)?.config.mcp_servers).toMatchObject([
      { server_id: "mcp-1", tool_name: "search" },
    ])
    // Disabling the MCP switch clears the server list.
    fireEvent.click(screen.getByRole("switch", { name: "启用 MCP" }))
    expect(updates.at(-1)?.config.mcp_enable).toBe(false)
    expect(updates.at(-1)?.config.mcp_servers).toEqual([])
    // Remove the unavailable pinned tool.
    fireEvent.click(screen.getByRole("checkbox", { name: /gone-1/ }))
    expect(updates.at(-1)?.config.tools).toEqual([])
    // Uncheck path: re-render with the MCP server already pinned so the
    // checkbox starts checked; clicking it removes the reference.
    cleanup()
    const removals: WorkflowNodeData[] = []
    renderNode(
      nodeData("llm", {
        onUpdate: (data) => removals.push(data),
        mcpServers: [mcpServer("mcp-1", "My MCP", [{ name: "search" }])],
        config: {
          prompt: "x",
          mcp_enable: true,
          mcp_servers: [{ server_id: "mcp-1", tool_name: "search" }],
        },
      })
    )
    fireEvent.click(screen.getByRole("checkbox", { name: "My MCP / search" }))
    expect(removals.at(-1)?.config.mcp_servers).toEqual([])
  })

  test("LLM node with MCP enabled but no servers shows empty state", () => {
    renderNode(
      nodeData("llm", { config: { prompt: "x", mcp_enable: true } })
    )
    expect(screen.getByText("暂无可用 MCP 工具")).toBeTruthy()
  })

  test("condition editor edits rules and branches", async () => {
    const updates: WorkflowNodeData[] = []
    renderNode(
      nodeData("condition", {
        onUpdate: (data) => updates.push(data),
        config: {
          branch: [
            {
              id: "b1",
              type: "IF",
              condition: "and",
              conditions: [
                { field: ["start", "question"], compare: "eq", value: "hello" },
                { field: ["start", "files"], compare: "contain", value: "x" },
              ],
            },
            { id: "b2", type: "ELSE", condition: "and", conditions: [] },
          ],
        },
      })
    )
    expect(screen.getByText("IF")).toBeTruthy()
    expect(screen.getByText("ELSE")).toBeTruthy()
    expect(screen.getByText("分支 · 2")).toBeTruthy()
    // Change the field reference via the variable picker.
    fireEvent.pointerDown(screen.getByRole("button", { name: "start · question" }))
    fireEvent.click(screen.getByRole("button", { name: "start · question" }))
    fireEvent.click(await screen.findByRole("menuitem", { name: "当前时间" }))
    expect(ruleList(branchList(updates.at(-1))[0])[0].field).toEqual([
      "global",
      "time",
    ])
    // Change the compare value.
    fireEvent.change(screen.getAllByLabelText("比较值")[0], {
      target: { value: "world" },
    })
    expect(ruleList(branchList(updates.at(-1))[0])[0].value).toBe("world")
    // Toggle the condition combinator.
    fireEvent.click(screen.getByRole("button", { name: "任一满足" }))
    expect(branchList(updates.at(-1))[0].condition).toBe("or")
    // Change the compare operator.
    fireEvent.pointerDown(screen.getByRole("button", { name: "等于" }))
    fireEvent.click(screen.getByRole("button", { name: "等于" }))
    fireEvent.click(await screen.findByRole("menuitem", { name: "包含" }))
    expect(ruleList(branchList(updates.at(-1))[0])[0].compare).toBe("contain")
    // Add a condition (payload rebuilds from the render's two rules).
    fireEvent.click(screen.getByRole("button", { name: "添加条件" }))
    expect(ruleList(branchList(updates.at(-1))[0]).length).toBe(3)
    // Remove a condition (the payload rebuilds from the render's two rules).
    fireEvent.click(screen.getAllByRole("button", { name: "删除条件" })[0])
    expect(ruleList(branchList(updates.at(-1))[0]).length).toBe(1)
    // Add a branch (splices an ELSE IF before ELSE).
    fireEvent.click(screen.getByRole("button", { name: "添加分支" }))
    const branches = branchList(updates.at(-1))
    expect(branches.length).toBe(3)
    expect(branches[1].type).toBe("ELSE IF")
    expect(branches[2].type).toBe("ELSE")
  })

  test("condition editor removes branches and single-rule branches", () => {
    const updates: WorkflowNodeData[] = []
    renderNode(
      nodeData("condition", {
        onUpdate: (data) => updates.push(data),
        config: {
          branch: [
            {
              id: "b1",
              type: "IF",
              condition: "and",
              conditions: [
                { field: ["start", "question"], compare: "eq", value: "x" },
              ],
            },
            {
              id: "b2",
              type: "ELSE IF",
              condition: "and",
              conditions: [
                { field: ["start", "files"], compare: "contain", value: "y" },
              ],
            },
            { id: "b3", type: "ELSE", condition: "and", conditions: [] },
          ],
        },
      })
    )
    expect(screen.getByText("未命中以上条件时执行")).toBeTruthy()
    // 删除条件 on a single-rule branch removes the whole branch.
    fireEvent.click(screen.getAllByRole("button", { name: "删除条件" })[0])
    expect(branchList(updates.at(-1)).length).toBe(2)
    // 删除分支 removes the first branch (payload rebuilds from the render).
    fireEvent.click(screen.getAllByRole("button", { name: "删除分支" })[0])
    expect(branchList(updates.at(-1)).length).toBe(2)
  })

  test("condition node renders legacy config", () => {
    renderNode(
      nodeData("condition", {
        config: {
          left: "{{start.question}}",
          operator: "equals",
          right: "yes",
        },
      })
    )
    expect(screen.getByText("分支 · 2")).toBeTruthy()
    expect((screen.getByLabelText("比较值") as HTMLInputElement).value).toBe(
      "yes"
    )
  })

  test("knowledge node switches search mode and adjusts parameters", async () => {
    const updates: WorkflowNodeData[] = []
    renderNode(
      nodeData("knowledge", {
        onUpdate: (data) => updates.push(data),
        knowledgeBases: [
          knowledgeBase("kb-1", "Docs"),
          knowledgeBase("kb-2", "Blog"),
        ],
        config: {
          search_mode: "embedding",
          knowledge_base_ids: ["kb-1", "kb-2"],
        },
      })
    )
    expect(screen.getByText("已选择 2 个知识库")).toBeTruthy()
    // Deselect one knowledge base through the multi-select dropdown.
    fireEvent.pointerDown(
      screen.getByRole("button", { name: "已选择 2 个知识库" })
    )
    fireEvent.click(screen.getByRole("button", { name: "已选择 2 个知识库" }))
    fireEvent.click(await screen.findByText("Docs"))
    expect(updates.at(-1)?.config.knowledge_base_ids).toEqual(["kb-2"])
    expect(updates.at(-1)?.config.knowledge_base_id).toBeNull()
    // Switch the search mode.
    const modeTrigger = screen.getByLabelText("检索模式")
    fireEvent.pointerDown(modeTrigger)
    fireEvent.click(modeTrigger)
    fireEvent.click(await screen.findByRole("menuitem", { name: "混合检索" }))
    expect(updates.at(-1)?.config.search_mode).toBe("blend")
    // Similarity via the number input.
    fireEvent.change(screen.getByRole("spinbutton", { name: "相似度" }), {
      target: { value: "0.8" },
    })
    expect(updates.at(-1)?.config.similarity).toBe(0.8)
    // Reference limit via the stepper buttons.
    fireEvent.click(screen.getAllByRole("button", { name: "增加数值" })[1])
    expect(updates.at(-1)?.config.limit).toBe(4)
    // Max chars via the number input.
    fireEvent.change(
      screen.getByRole("spinbutton", { name: "最大引用字符数" }),
      { target: { value: "6000" } }
    )
    expect(updates.at(-1)?.config.max_paragraph_char_number).toBe(6000)
    // Query editor.
    fireEvent.change(screen.getByLabelText("检索问题"), {
      target: { value: "what is X" },
    })
    expect(updates.at(-1)?.config.query).toBe("what is X")
  })

  test("knowledge node without bases shows the empty state", () => {
    renderNode(
      nodeData("knowledge", { config: { search_mode: "embedding" } })
    )
    expect(screen.getByText("暂无可用知识库")).toBeTruthy()
    expect(
      screen.getByRole("button", { name: "选择知识库" })
    ).toBeTruthy()
  })

  test("reranker node selects model and manages references", async () => {
    const updates: WorkflowNodeData[] = []
    renderNode(
      nodeData("reranker-node", {
        onUpdate: (data) => updates.push(data),
        models: [
          model("r-1", "BGE Rerank", "RERANKER"),
          model("m-1", "DeepSeek Chat"),
        ],
        config: { reranker_reference_list: ["{{start.question}}"] },
      })
    )
    // Reranker model select (the wrapping label names the trigger 重排模型).
    fireEvent.pointerDown(screen.getByRole("button", { name: "重排模型" }))
    fireEvent.click(screen.getByRole("button", { name: "重排模型" }))
    fireEvent.click(
      await screen.findByRole("menuitem", { name: "BGE Rerank" })
    )
    expect(updates.at(-1)?.config.reranker_model_id).toBe("r-1")
    // Question reference picker.
    fireEvent.pointerDown(screen.getByRole("button", { name: "选择引用变量" }))
    fireEvent.click(screen.getByRole("button", { name: "选择引用变量" }))
    fireEvent.click(await screen.findByRole("menuitem", { name: "用户问题" }))
    expect(updates.at(-1)?.config.question_reference_address).toBe(
      "{{start.question}}"
    )
    // Add a reference.
    fireEvent.pointerDown(screen.getByRole("button", { name: "添加引用" }))
    fireEvent.click(screen.getByRole("button", { name: "添加引用" }))
    fireEvent.click(await screen.findByRole("menuitem", { name: "当前时间" }))
    expect(updates.at(-1)?.config.reranker_reference_list).toEqual([
      "{{start.question}}",
      "{{global.time}}",
    ])
    // Replace the first reference (payload rebuilds from the render's list).
    fireEvent.pointerDown(
      screen.getByRole("button", { name: "{{start.question}}" })
    )
    fireEvent.click(screen.getByRole("button", { name: "{{start.question}}" }))
    fireEvent.click(await screen.findByRole("menuitem", { name: "当前时间" }))
    expect(updates.at(-1)?.config.reranker_reference_list).toEqual([
      "{{global.time}}",
    ])
    // Remove a reference (payload rebuilds from the render's list).
    fireEvent.click(screen.getByRole("button", { name: "删除" }))
    expect(updates.at(-1)?.config.reranker_reference_list).toEqual([])
    // Top-n and max chars steppers.
    fireEvent.change(
      screen.getByRole("spinbutton", { name: "引用分段数" }),
      { target: { value: "5" } }
    )
    expect(updates.at(-1)?.config.reranker_setting).toMatchObject({ top_n: 5 })
    fireEvent.click(screen.getAllByRole("button", { name: "增加数值" })[2])
    expect(updates.at(-1)?.config.reranker_setting).toMatchObject({
      max_paragraph_char_number: 5100,
    })
  })

  test("classifier node edits classes, input and default handle", async () => {
    const updates: WorkflowNodeData[] = []
    renderNode(
      nodeData("classifier", {
        onUpdate: (data) => updates.push(data),
        config: {
          classes: [
            { handle: "tech" },
            { handle: "sales" },
            { handle: 42 },
          ],
          default_handle: "default",
          input: "q",
          model_id: "model-1",
        },
      })
    )
    expect(screen.getByText("分类出口 · 4")).toBeTruthy()
    // Class handles render as output rows and source handle labels.
    expect(screen.getAllByText("tech").length).toBeGreaterThan(0)
    expect(screen.getAllByText("sales").length).toBeGreaterThan(0)
    // Model dropdown resets to the workflow default (modal menu: the trigger
    // becomes aria-hidden once open, so reuse the captured element).
    const modelTrigger = screen.getByRole("button", { name: "节点模型" })
    fireEvent.pointerDown(modelTrigger)
    fireEvent.click(modelTrigger)
    fireEvent.click(
      await screen.findByRole("menuitem", { name: "使用工作流默认模型" })
    )
    expect(updates.at(-1)?.config.model_id).toBeNull()
    // Classes JSON editor.
    const classesEditor = screen.getByLabelText("分类出口")
    fireEvent.change(classesEditor, { target: { value: '[{"handle": "tech"}]' } })
    expect(updates.at(-1)?.config.classes).toEqual([{ handle: "tech" }])
    // Invalid JSON shows the error without updating.
    fireEvent.change(classesEditor, { target: { value: "{oops" } })
    expect(screen.getByText("JSON 格式无效")).toBeTruthy()
    expect(updates.at(-1)?.config.classes).toEqual([{ handle: "tech" }])
    // 分类输入 editor.
    fireEvent.change(screen.getByLabelText("分类输入"), {
      target: { value: "q2" },
    })
    expect(updates.at(-1)?.config.input).toBe("q2")
    // 默认出口 input.
    fireEvent.change(screen.getByLabelText("默认出口"), {
      target: { value: "other" },
    })
    expect(updates.at(-1)?.config.default_handle).toBe("other")
  })

  test("mcp node selects a read-only tool and edits arguments", async () => {
    const updates: WorkflowNodeData[] = []
    renderNode(
      nodeData("mcp", {
        onUpdate: (data) => updates.push(data),
        mcpServers: [
          mcpServer("mcp-1", "My MCP", [
            { name: "search" },
            { name: "write", policyMode: "approval_required" },
          ]),
        ],
        config: {},
      })
    )
    expect(
      screen.getAllByText("选择只读 MCP 工具").length
    ).toBeGreaterThan(0)
    fireEvent.pointerDown(
      screen.getByRole("button", { name: "选择只读 MCP 工具" })
    )
    fireEvent.click(screen.getByRole("button", { name: "选择只读 MCP 工具" }))
    fireEvent.click(
      await screen.findByRole("menuitem", { name: "My MCP / search" })
    )
    expect(updates.at(-1)?.config).toMatchObject({
      server_id: "mcp-1",
      tool_name: "search",
    })
    fireEvent.change(screen.getByLabelText("工具参数"), {
      target: { value: '{"q": "x"}' },
    })
    expect(updates.at(-1)?.config.arguments).toEqual({ q: "x" })
  })

  test("tool node edits schema and extra arguments", () => {
    const updates: WorkflowNodeData[] = []
    const weatherTool = {
      ...tool("tool-1", "Weather"),
      version_id: "version-1",
      input_schema: {
        type: "object",
        properties: {
          city: { type: "string", title: "城市", description: "目标城市" },
          units: { type: "string", default: "metric" },
        },
        required: ["city"],
      },
    } as ToolDetail
    renderNode(
      nodeData("tool", {
        onUpdate: (data) => updates.push(data),
        tools: [weatherTool],
        config: {
          tool: { tool_id: "tool-1", version_id: "version-1" },
          arguments: { city: "SF", extra_key: 123 },
        },
      })
    )
    expect(screen.getByText("目标城市")).toBeTruthy()
    fireEvent.change(screen.getByLabelText("城市 *"), {
      target: { value: '"NYC"' },
    })
    expect(updates.at(-1)?.config.arguments).toMatchObject({ city: "NYC" })
    fireEvent.change(screen.getByLabelText("units"), {
      target: { value: '"imperial"' },
    })
    expect(updates.at(-1)?.config.arguments).toMatchObject({
      units: "imperial",
    })
    fireEvent.change(screen.getByLabelText("extra_key"), {
      target: { value: "456" },
    })
    expect(updates.at(-1)?.config.arguments).toMatchObject({ extra_key: 456 })
  })

  test("tool node without schema uses the JSON arguments editor", () => {
    const updates: WorkflowNodeData[] = []
    renderNode(
      nodeData("tool", {
        onUpdate: (data) => updates.push(data),
        tools: [tool("tool-1", "Weather")],
        config: {
          tool: { tool_id: "tool-1", version_id: "version-1" },
          arguments: {},
        },
      })
    )
    const editor = screen.getByLabelText("工具参数")
    fireEvent.change(editor, { target: { value: '{"x": 1}' } })
    expect(updates.at(-1)?.config.arguments).toEqual({ x: 1 })
    fireEvent.change(editor, { target: { value: "oops" } })
    expect(screen.getByText("JSON 格式无效")).toBeTruthy()
  })

  test("template node shows localized preview and edits content", async () => {
    const updates: WorkflowNodeData[] = []
    renderNode(
      nodeData("template", {
        onUpdate: (data) => updates.push(data),
        nodes: [graphNode("start", "start", "开始")],
        config: {
          template: "Hello {{global.time}} and {{start.question}}",
        },
      })
    )
    expect(screen.getByText(/模板内容 · Hello/)).toBeTruthy()
    // The localized preview button (named by its label) replaces the textarea.
    expect(screen.getAllByText(/Hello/).length).toBeGreaterThan(0)
    expect(screen.getByText(/【全局变量 · 当前时间】/)).toBeTruthy()
    expect(screen.getByText(/【开始节点 · 用户问题】/)).toBeTruthy()
    fireEvent.click(screen.getByRole("button", { name: "模板内容" }))
    const editor = screen.getByRole("textbox", { name: "模板内容" })
    fireEvent.focus(editor)
    fireEvent.select(editor)
    fireEvent.change(editor, { target: { value: "New template" } })
    expect(updates.at(-1)?.config.template).toBe("New template")
    fireEvent.blur(editor)
    // Insert a global variable at the end of the raw value.
    fireEvent.pointerDown(screen.getByRole("button", { name: "插入变量" }))
    fireEvent.click(screen.getByRole("button", { name: "插入变量" }))
    fireEvent.click(await screen.findByRole("menuitem", { name: "当前时间" }))
    expect(updates.at(-1)?.config.template).toContain("{{global.time}}")
  })

  test("template node inserts an upstream variable", async () => {
    const updates: WorkflowNodeData[] = []
    const graphNodes = [
      graphNode("start", "start", "开始"),
      graphNode("kb-1", "knowledge", "KB 节点"),
    ]
    const edges = [
      { source: "kb-1", target: "node-1" },
    ] as unknown as WorkflowEdge[]
    renderNode(
      nodeData("template", {
        onUpdate: (data) => updates.push(data),
        nodes: graphNodes,
        edges,
        config: { template: "Hello" },
      })
    )
    // Upstream node fields render in the picker and insert.
    fireEvent.pointerDown(screen.getByRole("button", { name: "插入变量" }))
    fireEvent.click(screen.getByRole("button", { name: "插入变量" }))
    expect(
      await screen.findByRole("menuitem", { name: "检索结果的分段列表" })
    ).toBeTruthy()
    fireEvent.click(
      screen.getByRole("menuitem", { name: "检索结果的分段列表" })
    )
    expect(updates.at(-1)?.config.template).toContain(
      "{{kb-1.paragraph_list}}"
    )
  })

  test("variable node edits its JSON value", () => {
    const updates: WorkflowNodeData[] = []
    renderNode(
      nodeData("variable", {
        onUpdate: (data) => updates.push(data),
        config: { value: "abc" },
      })
    )
    const editor = screen.getByLabelText("变量值")
    fireEvent.change(editor, { target: { value: '"xyz"' } })
    expect(updates.at(-1)?.config.value).toBe("xyz")
  })

  test("end node renames an output key and edits its expression", () => {
    const updates: WorkflowNodeData[] = []
    renderNode(
      nodeData("end", {
        onUpdate: (data) => updates.push(data),
        config: { outputs: { result: "{{start.question}}", output_2: "" } },
      })
    )
    fireEvent.change(screen.getAllByLabelText("字段名")[0], {
      target: { value: "renamed" },
    })
    expect(updates.at(-1)?.config.outputs).toEqual({
      renamed: "{{start.question}}",
      output_2: "",
    })
    fireEvent.change(screen.getAllByLabelText("表达式")[1], {
      target: { value: "{{start.files}}" },
    })
    expect(updates.at(-1)?.config.outputs).toMatchObject({
      output_2: "{{start.files}}",
    })
  })

  test("reply node referencing mode picks a field", async () => {
    const updates: WorkflowNodeData[] = []
    renderNode(
      nodeData("reply-node", {
        onUpdate: (data) => updates.push(data),
        config: { reply_type: "referencing", is_result: true },
      })
    )
    fireEvent.pointerDown(
      screen.getByRole("button", { name: "选择引用变量" })
    )
    fireEvent.click(screen.getByRole("button", { name: "选择引用变量" }))
    fireEvent.click(await screen.findByRole("menuitem", { name: "用户问题" }))
    expect(updates.at(-1)?.config.fields).toEqual([
      ["start", "question"],
      "用户问题",
    ])
    fireEvent.click(screen.getByRole("switch", { name: "返回内容" }))
    expect(updates.at(-1)?.config.is_result).toBe(false)
  })

  test("reply node custom mode edits content", () => {
    const updates: WorkflowNodeData[] = []
    renderNode(
      nodeData("reply-node", {
        onUpdate: (data) => updates.push(data),
        config: { reply_type: "custom", content: "hi" },
      })
    )
    fireEvent.change(screen.getByLabelText("内容"), {
      target: { value: "bye" },
    })
    expect(updates.at(-1)?.config.content).toBe("bye")
  })

  test("form node edits a select field and its options", async () => {
    const updates: WorkflowNodeData[] = []
    renderNode(
      nodeData("form-node", {
        onUpdate: (data) => updates.push(data),
        config: {
          form_field_list: [
            {
              variable: "name",
              name: "姓名",
              type: "select",
              is_required: true,
              default_value: "默认",
              show_default_value: true,
              optionList: ["a", "b"],
            },
            // An entry without a variable key exercises the flatMap fallback.
            { name: "Only Name" },
          ],
          form_content_format: "{{ form }}",
        },
      })
    )
    const options = screen.getByLabelText("选项")
    expect((options as HTMLInputElement).value).toBe("a, b")
    fireEvent.focus(options)
    fireEvent.change(options, { target: { value: "x, y" } })
    expect(fieldList(updates.at(-1))[0].optionList).toEqual(["x", "y"])
    fireEvent.blur(options)
    // Type dropdown.
    fireEvent.pointerDown(screen.getByRole("button", { name: "下拉选择" }))
    fireEvent.click(screen.getByRole("button", { name: "下拉选择" }))
    fireEvent.click(
      await screen.findByRole("menuitem", { name: "多行文本" })
    )
    expect(fieldList(updates.at(-1))[0].type).toBe("textarea")
    // Required, default value, and preset toggles (one per field row).
    fireEvent.click(screen.getAllByRole("checkbox", { name: "必填" })[0])
    expect(fieldList(updates.at(-1))[0].is_required).toBe(false)
    fireEvent.change(screen.getByLabelText("默认值"), {
      target: { value: "新默认" },
    })
    expect(fieldList(updates.at(-1))[0].default_value).toBe("新默认")
    fireEvent.click(screen.getAllByRole("checkbox", { name: "预填默认值" })[0])
    expect(fieldList(updates.at(-1))[0].show_default_value).toBe(false)
    // 字段名 and 显示名称 edits.
    fireEvent.change(screen.getAllByLabelText("字段名")[0], {
      target: { value: "renamed" },
    })
    expect(fieldList(updates.at(-1))[0].variable).toBe("renamed")
    fireEvent.change(screen.getAllByLabelText("显示名称")[0], {
      target: { value: "新姓名" },
    })
    expect(fieldList(updates.at(-1))[0].name).toBe("新姓名")
    // Delete the first field.
    fireEvent.click(screen.getAllByRole("button", { name: "删除" })[0])
    expect(fieldList(updates.at(-1)).length).toBe(1)
    // Form content editor and result checkbox.
    fireEvent.change(screen.getByLabelText("表单输出内容"), {
      target: { value: "{{ form }}!" },
    })
    expect(updates.at(-1)?.config.form_content_format).toBe("{{ form }}!")
    fireEvent.click(screen.getByRole("checkbox", { name: "返回内容" }))
    expect(updates.at(-1)?.config.is_result).toBe(false)
  })

  test("document extract node edits the document list", () => {
    const updates: WorkflowNodeData[] = []
    renderNode(
      nodeData("document-extract-node", {
        onUpdate: (data) => updates.push(data),
        config: { document_list: "" },
      })
    )
    fireEvent.change(screen.getByLabelText("文档"), {
      target: { value: "doc-1" },
    })
    expect(updates.at(-1)?.config.document_list).toBe("doc-1")
  })

  test("code node edits its JSON inputs", () => {
    const updates: WorkflowNodeData[] = []
    renderNode(
      nodeData("code", {
        onUpdate: (data) => updates.push(data),
        config: { code: "print(1)", inputs: { x: 1 } },
      })
    )
    expect(screen.getByText("代码输入 · 1")).toBeTruthy()
    fireEvent.change(screen.getByLabelText("代码输入"), {
      target: { value: '{"x": 2}' },
    })
    expect(updates.at(-1)?.config.inputs).toEqual({ x: 2 })
  })

  test("agent node summary resolves via published version", () => {
    const published = {
      ...agent("agent-1", "Research agent"),
      current_published_version_id: "v9",
    } as unknown as Agent
    renderNode(
      nodeData("agent", {
        agents: [published],
        config: { agent_version_id: "v9" },
      })
    )
    expect(screen.getAllByText("Research agent").length).toBeGreaterThan(0)
  })

  test("output field copy buttons copy references and notify", async () => {
    const notifyCalls: Array<[string, string]> = []
    mockUseSession(
      makeSession({
        notify: (kind: string, message: string) =>
          notifyCalls.push([kind, message]),
      })
    )
    const written: string[] = []
    const originalClipboard = navigator.clipboard
    Object.defineProperty(navigator, "clipboard", {
      value: {
        writeText: async (value: string) => void written.push(value),
      },
      configurable: true,
    })
    renderNode(nodeData("start", {}))
    fireEvent.click(screen.getAllByRole("button", { name: "复制变量" })[0])
    await waitFor(() =>
      expect(notifyCalls).toEqual([["success", "已复制"]])
    )
    expect(written[0]).toBe("{{global.time}}")
    Object.defineProperty(navigator, "clipboard", {
      value: originalClipboard,
      configurable: true,
    })
  })

  test("output field copy reports clipboard failure", async () => {
    const notifyCalls: Array<[string, string]> = []
    mockUseSession(
      makeSession({
        notify: (kind: string, message: string) =>
          notifyCalls.push([kind, message]),
      })
    )
    const originalClipboard = navigator.clipboard
    Object.defineProperty(navigator, "clipboard", {
      value: {
        writeText: async () => {
          throw new Error("denied")
        },
      },
      configurable: true,
    })
    renderNode(nodeData("template", { config: { template: "x" } }))
    fireEvent.click(screen.getByRole("button", { name: "复制变量" }))
    await waitFor(() =>
      expect(notifyCalls).toEqual([["error", "复制失败"]])
    )
    Object.defineProperty(navigator, "clipboard", {
      value: originalClipboard,
      configurable: true,
    })
  })
})
