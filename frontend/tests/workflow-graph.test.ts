import { describe, expect, test } from "bun:test"

import {
  WORKFLOW_BASIC_NODE_TYPES,
  WORKFLOW_NODE_PRESETS,
  WORKFLOW_NODE_TYPES,
  createWorkflowEdge,
  createWorkflowNode,
  defaultNodeConfig,
  ensureConditionElseIfBranches,
  removeWorkflowNode,
  selectWorkflowRunTarget,
  serializeWorkflowGraph,
  workflowErrorMessage,
  workflowExecutionNodeLabel,
  workflowGraphSignature,
  workflowNodeLabel,
} from "../src/lib/workflows/graph"
import {
  applyWorkflowEdgeChanges,
  applyWorkflowNodeChanges,
  canvasPositionLeftOf,
  draggedCanvasPosition,
  nonOverlappingCanvasPosition,
  persistedWorkflowViewport,
  viewportIncludingCanvasX,
  workflowNodeRects,
} from "../src/lib/workflows/canvas"

describe("workflow graph", () => {
  test("presents workflow execution details in the active language", () => {
    const t = ((key: string) => key) as never
    const graph = {
      nodes: [
        {
          id: "reranker-1",
          type: "workflow",
          position: { x: 0, y: 0 },
          data: { type: "reranker-node", title: "个人知识重排", config: {} },
        },
      ],
      edges: [],
      viewport: { x: 0, y: 0, zoom: 1 },
    } as never

    expect(
      workflowExecutionNodeLabel("reranker-1", "reranker-node", graph, t)
    ).toBe("个人知识重排")
    expect(
      workflowExecutionNodeLabel("missing", "reranker-node", graph, t)
    ).toBe("多路召回")
    expect(workflowNodeLabel("document-extract-node", t)).toBe("文档内容提取")
    expect(
      workflowErrorMessage(
        "Workflow reranker content must contain non-empty text.",
        t
      )
    ).toBe("重排内容必须包含非空文本。")
    expect(workflowErrorMessage("Provider detail", t)).toBe("Provider detail")
  })

  test("moves canvas components in flow coordinates", () => {
    expect(
      draggedCanvasPosition(
        { x: 16, y: 16 },
        { x: 100, y: 120 },
        { x: 260, y: 310 }
      )
    ).toEqual({ x: 176, y: 206 })
  })

  test("keeps the basic info card clear of workflow nodes", () => {
    const position = canvasPositionLeftOf(
      { x: 80, y: 180, width: 256, height: 320 },
      { width: 400, height: 620 }
    )
    expect(position).toEqual({ x: -344, y: 180 })
    expect(
      viewportIncludingCanvasX({ x: 0, y: 0, zoom: 1 }, position.x)
    ).toEqual({ x: 360, y: 0, zoom: 1 })

    expect(
      nonOverlappingCanvasPosition(
        { x: 16, y: 16 },
        { width: 400, height: 620 },
        [
          { x: 80, y: 180, width: 256, height: 320 },
          { x: 460, y: 180, width: 256, height: 320 },
        ]
      )
    ).toEqual({ x: -344, y: 16 })

    expect(
      nonOverlappingCanvasPosition(
        { x: 16, y: 16 },
        { width: 400, height: 120 },
        [{ x: 80, y: 180, width: 256, height: 320 }]
      )
    ).toEqual({ x: 16, y: 16 })

    expect(
      workflowNodeRects([
        {
          id: "start",
          type: "workflow",
          position: { x: 80, y: 180 },
          measured: { width: 256, height: 320 },
          data: { type: "start", title: "Start", config: {} },
        } as never,
      ])
    ).toEqual([{ x: 80, y: 180, width: 256, height: 320 }])
  })

  test("builds reference-node presets from existing node types", () => {
    const t = ((key: string) => key) as never
    const optimizer = WORKFLOW_NODE_PRESETS.find(
      (preset) => preset.id === "question-optimizer"
    )

    expect(optimizer?.type).toBe("llm")
    expect(optimizer?.config(t)).toEqual({
      system_prompt: "你是一个问题优化专家。",
      prompt:
        "请在不改变原意的前提下优化下面的问题，只返回优化后的问题：\n\n{{start.question}}",
    })
    expect(optimizer?.config(t, "start-custom")).toEqual({
      system_prompt: "你是一个问题优化专家。",
      prompt:
        "请在不改变原意的前提下优化下面的问题，只返回优化后的问题：\n\n{{start-custom.question}}",
    })
    expect(WORKFLOW_NODE_TYPES[0]).toBe("reply-node")
    expect(WORKFLOW_NODE_TYPES).not.toContain("template")
    expect(WORKFLOW_NODE_TYPES).toContain("tool")
    expect(WORKFLOW_NODE_TYPES).toContain("agent")
    expect(WORKFLOW_BASIC_NODE_TYPES).not.toContain("tool")
    expect(WORKFLOW_BASIC_NODE_TYPES).not.toContain("agent")
    expect(WORKFLOW_BASIC_NODE_TYPES).not.toContain("mcp")
    expect(WORKFLOW_BASIC_NODE_TYPES).not.toContain("code")
    expect(defaultNodeConfig("template")).toEqual({
      template: "{{start.question}}",
    })
    expect(defaultNodeConfig("reply-node")).toEqual({
      reply_type: "custom",
      content: "",
      fields: null,
      is_result: true,
    })
    expect(defaultNodeConfig("knowledge")).toEqual({
      knowledge_base_ids: [],
      query: "{{start.question}}",
      limit: 3,
      similarity: 0.6,
      search_mode: "embedding",
      max_paragraph_char_number: 5000,
    })
    expect(defaultNodeConfig("start")).toEqual({})
    expect(defaultNodeConfig("end")).toEqual({
      outputs: { result: "{{start.question}}" },
    })
    expect(defaultNodeConfig("llm")).toMatchObject({ tools: [] })
    expect(defaultNodeConfig("tool")).toEqual({
      tool: { tool_id: "", version_id: "" },
      arguments: {},
    })
    expect(defaultNodeConfig("agent", "start-custom")).toEqual({
      agent_id: "",
      agent_version_id: "",
      input: "{{start-custom.question}}",
    })
    const condition = defaultNodeConfig("condition") as {
      branch: Array<Record<string, unknown>>
    }
    expect(condition.branch).toHaveLength(3)
    expect(condition.branch.map((branch) => branch.type)).toEqual([
      "IF",
      "ELSE IF",
      "ELSE",
    ])
    expect(condition.branch[0].conditions).toEqual([
      { field: ["start", "question"], compare: "eq", value: "" },
    ])
    expect(condition.branch[1].conditions).toEqual([
      { field: ["start", "question"], compare: "eq", value: "" },
    ])
    const customStartCondition = defaultNodeConfig(
      "condition",
      "start-custom"
    ) as { branch: Array<{ conditions: Array<{ field: string[] }> }> }
    expect(customStartCondition.branch[0].conditions[0].field).toEqual([
      "start-custom",
      "question",
    ])
    expect(
      createWorkflowNode("llm", "LLM", 1, undefined, "start-custom").data.config
        .prompt
    ).toBe("{{start-custom.question}}")
  })

  test("migrates editable two-branch conditions without a dead branch", () => {
    const graph = ensureConditionElseIfBranches({
      nodes: [
        {
          id: "start-custom",
          type: "workflow",
          position: { x: 0, y: 0 },
          data: { type: "start", title: "Start", config: {} },
        },
        {
          id: "condition-1",
          type: "workflow",
          position: { x: 200, y: 0 },
          data: {
            type: "condition",
            title: "Condition",
            config: {
              branch: [
                {
                  id: "yes",
                  type: "IF",
                  condition: "and",
                  conditions: [
                    {
                      field: ["start-custom", "question"],
                      compare: "eq",
                      value: "yes",
                    },
                  ],
                },
                { id: "no", type: "ELSE", condition: "and", conditions: [] },
              ],
            },
          },
        },
        {
          id: "end-1",
          type: "workflow",
          position: { x: 400, y: 0 },
          data: { type: "end", title: "End", config: { outputs: {} } },
        },
      ],
      edges: [
        {
          id: "edge-no",
          source: "condition-1",
          target: "end-1",
          sourceHandle: "no",
        },
      ],
      viewport: { x: 0, y: 0, zoom: 1 },
    } as never)
    const branches = graph.nodes[1].data.config.branch as Array<{
      id: string
      type: string
      conditions: Array<{ field: string[] }>
    }>

    expect(branches.map((branch) => branch.type)).toEqual([
      "IF",
      "ELSE IF",
      "ELSE",
    ])
    expect(branches[1].conditions[0].field).toEqual([
      "start-custom",
      "question",
    ])
    expect(graph.edges).toContainEqual(
      expect.objectContaining({
        source: "condition-1",
        target: "end-1",
        sourceHandle: branches[1].id,
      })
    )
  })

  test("serializes only durable React Flow fields", () => {
    const graph = serializeWorkflowGraph(
      [
        {
          id: "start",
          type: "workflow",
          position: { x: 10, y: 20 },
          data: {
            type: "start",
            title: "Start",
            config: defaultNodeConfig("start"),
          },
          selected: true,
        } as never,
      ],
      [
        {
          id: "edge-1",
          source: "start",
          target: "end",
          selected: true,
        } as never,
      ],
      { x: 1, y: 2, zoom: 1.25 }
    )

    expect(graph.nodes[0]).not.toHaveProperty("selected")
    expect(graph.edges[0]).not.toHaveProperty("selected")
    expect(graph.viewport.zoom).toBe(1.25)
  })

  test("treats null and omitted edge handles as the same durable graph", () => {
    const base = {
      nodes: [],
      viewport: { x: 0, y: 0, zoom: 1 },
    }
    expect(
      workflowGraphSignature({
        ...base,
        edges: [
          {
            id: "edge-1",
            source: "start",
            target: "end",
            sourceHandle: null,
            targetHandle: null,
          },
        ],
      })
    ).toBe(
      workflowGraphSignature({
        ...base,
        edges: [{ id: "edge-1", source: "start", target: "end" }],
      })
    )
  })

  test("removes connected edges with a node", () => {
    const edge = createWorkflowEdge("start", "value")
    const result = removeWorkflowNode(
      [
        { id: "start", data: { type: "start" } },
        { id: "value", data: { type: "variable" } },
      ] as never,
      [edge],
      "value"
    )
    expect(result.nodes).toHaveLength(1)
    expect(result.edges).toHaveLength(0)
  })

  test("keeps read-only canvas graph mutations out of the draft", () => {
    const nodes = [
      {
        id: "start",
        type: "workflow",
        position: { x: 0, y: 0 },
        data: { type: "start", title: "Start", config: {} },
      },
    ] as never
    const edges = [{ id: "edge-1", source: "start", target: "end" }]

    expect(
      applyWorkflowNodeChanges(nodes, [{ id: "start", type: "remove" }], true)
    ).toEqual(nodes)
    expect(
      applyWorkflowEdgeChanges(edges, [{ id: "edge-1", type: "remove" }], true)
    ).toEqual(edges)
    expect(
      persistedWorkflowViewport(
        { x: 0, y: 0, zoom: 1 },
        { x: 20, y: 30, zoom: 1.2 },
        true
      )
    ).toEqual({ x: 0, y: 0, zoom: 1 })
  })

  test("selects the latest published version for a read-only run", () => {
    const versionGraph = (x: number) => ({
      nodes: [],
      edges: [],
      viewport: { x, y: 0, zoom: 1 },
    })
    const target = selectWorkflowRunTarget(false, [
      { version_number: 1, graph: versionGraph(1) },
      { version_number: 3, graph: versionGraph(3) },
      { version_number: 2, graph: versionGraph(2) },
    ] as never)

    if (!target) throw new Error("expected a published run target")
    expect(target.source).toBe("published")
    expect(target.versionNumber).toBe(3)
    expect(target.graph).toEqual(versionGraph(3))
  })

  test("lets editors select a specific published version", () => {
    const published = {
      nodes: [],
      edges: [],
      viewport: { x: 4, y: 0, zoom: 1 },
    }
    const target = selectWorkflowRunTarget(
      true,
      [{ version_number: 4, graph: published }] as never,
      4
    )

    expect(target).toEqual({
      source: "published",
      versionNumber: 4,
      graph: published,
    })
  })
})
