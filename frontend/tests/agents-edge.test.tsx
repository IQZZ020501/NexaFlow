/* @jsxImportSource react */
/**
 * Edge coverage for the agent domain outside the DOM surface:
 * - lib/api/workflows.ts API client direct calls
 * - lib/workflows/graph.ts pure graph helpers (node/edge validation, cycles,
 *   unnamed variable resolution, run target selection)
 */
import { afterEach, describe, expect, test } from "bun:test"

import { jsonResponse } from "./helpers/dom"

import {
  createWorkflowRun,
  getWorkflowDefinition,
  listWorkflowNodeExecutions,
  listWorkflowRuns,
  listWorkflowVersions,
  observeWorkflowRun,
  publishWorkflow,
  restoreWorkflowVersion,
  submitWorkflowForm,
  updateWorkflowDefinition,
  uploadWorkflowFiles,
  validateWorkflowDefinition,
  type WorkflowGraph,
  type WorkflowNode,
  type WorkflowRun,
} from "@/lib/api/workflows"
import {
  WORKFLOW_NODE_PRESETS,
  WORKFLOW_NODE_TYPES,
  WORKFLOW_START_FIELDS,
  WORKFLOW_START_GLOBALS,
  createWorkflowEdge,
  createWorkflowNode,
  defaultNodeConfig,
  ensureConditionElseIfBranches,
  removeWorkflowNode,
  selectWorkflowRunTarget,
  serializeWorkflowGraph,
  upstreamWorkflowFields,
  workflowErrorMessage,
  workflowExecutionNodeLabel,
  workflowGraphSignature,
  workflowNodeLabel,
} from "@/lib/workflows/graph"

const originalFetch = globalThis.fetch

afterEach(() => {
  globalThis.fetch = originalFetch
})

function ndjson(events: unknown[]): Response {
  const encoder = new TextEncoder()
  return new Response(
    new ReadableStream({
      start(controller) {
        for (const event of events) {
          controller.enqueue(encoder.encode(`${JSON.stringify(event)}\n`))
        }
        controller.close()
      },
    }),
    { status: 200 }
  )
}

function recordingFetch() {
  const calls: Array<{ url: string; method: string; body?: string }> = []
  globalThis.fetch = (async (
    input: RequestInfo | URL,
    init?: RequestInit
  ) => {
    calls.push({
      url: String(input),
      method: init?.method ?? "GET",
      body: init?.body ? String(init.body) : undefined,
    })
    return jsonResponse({})
  }) as unknown as typeof fetch
  return calls
}

const graph: WorkflowGraph = {
  nodes: [],
  edges: [],
  viewport: { x: 0, y: 0, zoom: 1 },
}

function runFixture(overrides: Partial<WorkflowRun> = {}): WorkflowRun {
  return {
    id: "run-1",
    conversation_id: "conversation-1",
    workspace_id: "ws-1",
    agent_id: "workflow-1",
    requested_by_user_id: "u-1",
    status: "succeeded",
    source: "draft",
    definition_revision: 3,
    version_number: null,
    graph_hash: "hash-1",
    inputs: {},
    outputs: {},
    max_steps: 30,
    max_model_tokens: 2000,
    step_count: 4,
    token_usage: 120,
    last_error: null,
    trace_id: "trace-1",
    started_at: "2026-08-01T00:00:00Z",
    finished_at: "2026-08-01T00:00:01Z",
    created_at: "2026-08-01T00:00:00Z",
    updated_at: "2026-08-01T00:00:01Z",
    pending_form: null,
    ...overrides,
  }
}

describe("lib/api/workflows", () => {
  test("getWorkflowDefinition requests the definition with auth", async () => {
    const calls = recordingFetch()
    await getWorkflowDefinition("token", "ws-1", "workflow-1")
    expect(calls).toHaveLength(1)
    expect(calls[0].url).toBe(
      "/api/v1/workspaces/ws-1/workflows/workflow-1/definition"
    )
    expect(calls[0].method).toBe("GET")
  })

  test("updateWorkflowDefinition sends the expected revision and graph", async () => {
    const calls = recordingFetch()
    await updateWorkflowDefinition("token", "ws-1", "workflow-1", 7, graph)
    expect(calls[0].method).toBe("PUT")
    expect(JSON.parse(calls[0].body ?? "{}")).toEqual({
      expected_revision: 7,
      graph,
    })
  })

  test("validateWorkflowDefinition posts the graph", async () => {
    const calls = recordingFetch()
    await validateWorkflowDefinition("token", "ws-1", "workflow-1", graph)
    expect(calls[0].method).toBe("POST")
    expect(calls[0].url).toContain("/workflows/workflow-1/validate")
    expect(JSON.parse(calls[0].body ?? "{}")).toEqual({ graph })
  })

  test("publishWorkflow posts to the publish route", async () => {
    const calls = recordingFetch()
    await publishWorkflow("token", "ws-1", "workflow-1")
    expect(calls[0].method).toBe("POST")
    expect(calls[0].url).toContain("/workflows/workflow-1/publish")
    expect(calls[0].body).toBeUndefined()
  })

  test("listWorkflowVersions lists versions", async () => {
    const calls = recordingFetch()
    await listWorkflowVersions("token", "ws-1", "workflow-1")
    expect(calls[0].url).toContain("/workflows/workflow-1/versions")
  })

  test("restoreWorkflowVersion restores a specific version", async () => {
    const calls = recordingFetch()
    await restoreWorkflowVersion("token", "ws-1", "workflow-1", 3, 5)
    expect(calls[0].method).toBe("POST")
    expect(calls[0].url).toContain("/workflows/workflow-1/versions/3/restore")
    expect(JSON.parse(calls[0].body ?? "{}")).toEqual({ expected_revision: 5 })
  })

  test("createWorkflowRun supports draft, published, and file ids", async () => {
    const calls = recordingFetch()
    await createWorkflowRun("token", "ws-1", "workflow-1", "question", "draft")
    expect(JSON.parse(calls[0].body ?? "{}")).toEqual({
      question: "question",
      source: "draft",
    })

    await createWorkflowRun(
      "token",
      "ws-1",
      "workflow-1",
      "release",
      "published",
      2
    )
    expect(JSON.parse(calls[1].body ?? "{}")).toEqual({
      question: "release",
      source: "published",
      version_number: 2,
    })

    await createWorkflowRun(
      "token",
      "ws-1",
      "workflow-1",
      "files",
      "draft",
      undefined,
      ["file-1", "file-2"]
    )
    expect(JSON.parse(calls[2].body ?? "{}")).toEqual({
      question: "files",
      source: "draft",
      file_ids: ["file-1", "file-2"],
    })
  })

  test("uploadWorkflowFiles sends multipart form data", async () => {
    const calls: Array<{ url: string; method: string; body: BodyInit | null | undefined }> = []
    globalThis.fetch = (async (
      input: RequestInfo | URL,
      init?: RequestInit
    ) => {
      calls.push({ url: String(input), method: init?.method ?? "GET", body: init?.body })
      return jsonResponse([
        {
          id: "up-1",
          filename: "a.txt",
          content_type: "text/plain",
          size_bytes: 1,
          category: "document",
        },
      ])
    }) as unknown as typeof fetch
    const files = [new File(["a"], "a.txt", { type: "text/plain" })]
    const uploaded = await uploadWorkflowFiles("token", "ws-1", "workflow-1", files)
    expect(uploaded).toEqual([
      {
        id: "up-1",
        filename: "a.txt",
        content_type: "text/plain",
        size_bytes: 1,
        category: "document",
      },
    ])
    expect(calls[0].url).toContain("/workflows/workflow-1/uploads")
    expect(calls[0].body).toBeInstanceOf(FormData)
    expect((calls[0].body as FormData).getAll("files")).toEqual(files)
  })

  test("submitWorkflowForm posts the runtime node and form data", async () => {
    const calls = recordingFetch()
    await submitWorkflowForm("token", "ws-1", "workflow-1", "run-1", "node-9", {
      name: "Ada",
    })
    expect(calls[0].method).toBe("POST")
    expect(calls[0].url).toContain("/workflows/workflow-1/runs/run-1/form")
    expect(JSON.parse(calls[0].body ?? "{}")).toEqual({
      runtime_node_id: "node-9",
      form_data: { name: "Ada" },
    })
  })

  test("listWorkflowRuns builds the query string", async () => {
    const calls = recordingFetch()
    await listWorkflowRuns("token", "ws-1", "workflow-1", { limit: 10, offset: 20 })
    expect(calls[0].url).toBe(
      "/api/v1/workspaces/ws-1/workflows/workflow-1/runs?limit=10&offset=20"
    )
    await listWorkflowRuns("token", "ws-1", "workflow-1")
    expect(calls[1].url).toBe(
      "/api/v1/workspaces/ws-1/workflows/workflow-1/runs"
    )
  })

  test("listWorkflowNodeExecutions lists node executions", async () => {
    const calls = recordingFetch()
    await listWorkflowNodeExecutions("token", "ws-1", "workflow-1", "run-1")
    expect(calls[0].url).toContain(
      "/workflows/workflow-1/runs/run-1/nodes"
    )
  })

  test("observeWorkflowRun delivers stream events until the terminal event", async () => {
    const finished = runFixture({ status: "succeeded" })
    globalThis.fetch = (async () =>
      ndjson([
        { type: "workflow_node_started", sequence: 1, node_id: "llm-1", node_type: "llm", execution_sequence: 1 },
        { type: "workflow_node", sequence: 2, node_id: "llm-1", node_type: "llm", status: "succeeded", execution_sequence: 1, inputs: {}, outputs: { result: "ok" }, model_usage: {}, error: null, duration_ms: 10 },
        { type: "complete", sequence: 3, run: finished },
      ])) as unknown as typeof fetch

    const seen: Array<{ type: string; node_id?: string }> = []
    await observeWorkflowRun("token", "ws-1", "workflow-1", "run-1", (event) => {
      const nodeId = "node_id" in event && typeof event.node_id === "string" ? event.node_id : undefined
      seen.push({ type: event.type, node_id: nodeId })
    })
    expect(seen.map((item) => item.type)).toEqual([
      "workflow_node_started",
      "workflow_node",
      "complete",
    ])
  })

  test("observeWorkflowRun observes from the given cursor", async () => {
    let requestedUrl = ""
    globalThis.fetch = (async (input: RequestInfo | URL) => {
      requestedUrl = String(input)
      return ndjson([{ type: "complete", sequence: 9, run: runFixture() }])
    }) as unknown as typeof fetch
    const seen: unknown[] = []
    await observeWorkflowRun("token", "ws-1", "workflow-1", "run-1", (event) => {
      seen.push(event)
    }, undefined, 9)
    expect(requestedUrl).toContain("after=9")
    expect(seen).toHaveLength(1)
  })
})

describe("lib/workflows/graph", () => {
  test("labels every node type", () => {
    const t = ((key: string) => key) as never
    expect(workflowNodeLabel("start", t)).toBe("开始节点")
    expect(workflowNodeLabel("end", t)).toBe("结束节点")
    expect(workflowNodeLabel("llm", t)).toBe("大语言模型")
    expect(workflowNodeLabel("classifier", t)).toBe("问题分类器")
    expect(workflowNodeLabel("knowledge", t)).toBe("知识检索节点")
    expect(workflowNodeLabel("reranker-node", t)).toBe("多路召回")
    expect(workflowNodeLabel("form-node", t)).toBe("表单收集")
    expect(workflowNodeLabel("document-extract-node", t)).toBe("文档内容提取")
    expect(workflowNodeLabel("condition", t)).toBe("条件分支")
    expect(workflowNodeLabel("reply-node", t)).toBe("指定回复")
    expect(workflowNodeLabel("template", t)).toBe("模板转换")
    expect(workflowNodeLabel("variable", t)).toBe("变量赋值")
    expect(workflowNodeLabel("mcp", t)).toBe("MCP 工具节点")
    expect(workflowNodeLabel("code", t)).toBe("Python 代码")
    expect(WORKFLOW_NODE_TYPES).toContain("reply-node")
    expect(WORKFLOW_NODE_TYPES).toContain("code")
    expect(WORKFLOW_START_GLOBALS.map((item) => item.value)).toEqual([
      "time",
      "history_context",
      "chat_id",
      "start_time",
    ])
    expect(WORKFLOW_START_FIELDS.map((item) => item.value)).toEqual([
      "question",
      "files",
      "document",
    ])
  })

  test("workflowExecutionNodeLabel resolves titles and falls back to type labels", () => {
    const t = ((key: string) => key) as never
    const graph: WorkflowGraph = {
      nodes: [
        {
          id: "llm-1",
          type: "workflow",
          position: { x: 0, y: 0 },
          data: { type: "llm", title: " 摘要生成 ", config: {} },
        },
      ],
      edges: [],
      viewport: { x: 0, y: 0, zoom: 1 },
    }
    expect(workflowExecutionNodeLabel("llm-1", "llm", graph, t)).toBe("摘要生成")
    expect(workflowExecutionNodeLabel("missing", "llm", graph, t)).toBe("大语言模型")
    expect(workflowExecutionNodeLabel("llm-1", "llm", null, t)).toBe("大语言模型")
  })

  test("workflowErrorMessage maps known errors and passes through others", () => {
    const t = ((key: string) => key) as never
    expect(workflowErrorMessage("Workflow model request failed.", t)).toBe(
      "工作流模型请求失败。"
    )
    expect(workflowErrorMessage("Workflow model request timed out.", t)).toBe(
      "工作流模型请求超时。"
    )
    expect(workflowErrorMessage("Workflow node execution failed.", t)).toBe(
      "工作流节点执行失败。"
    )
    expect(workflowErrorMessage("Workflow node failed.", t)).toBe(
      "工作流节点执行失败。"
    )
    expect(workflowErrorMessage("Workflow execution failed.", t)).toBe(
      "工作流执行失败。"
    )
    expect(workflowErrorMessage("Workflow run failed.", t)).toBe(
      "工作流运行失败。"
    )
    expect(workflowErrorMessage("Workflow run was cancelled.", t)).toBe(
      "工作流运行已取消。"
    )
    expect(
      workflowErrorMessage(
        "Workflow document references must contain a file id.",
        t
      )
    ).toBe("文档引用必须包含文件 ID。")
    expect(workflowErrorMessage("Something else", t)).toBe("Something else")
  })

  test("defaultNodeConfig covers every node type", () => {
    expect(defaultNodeConfig("classifier")).toEqual({
      input: "{{start.question}}",
      classes: [
        { handle: "match", label: "Match", description: "" },
        { handle: "other", label: "Other", description: "" },
      ],
      default_handle: "default",
    })
    expect(defaultNodeConfig("reranker-node")).toEqual({
      reranker_model_id: "",
      question_reference_address: "{{start.question}}",
      reranker_reference_list: [],
      reranker_setting: {
        top_n: 3,
        similarity: 0,
        max_paragraph_char_number: 5000,
      },
    })
    expect(defaultNodeConfig("form-node")).toEqual({
      form_field_list: [],
      form_content_format: "{{ form }}",
      is_result: true,
    })
    expect(defaultNodeConfig("document-extract-node")).toEqual({
      document_list: "{{start.document}}",
    })
    expect(defaultNodeConfig("variable")).toEqual({
      value: "{{start.question}}",
    })
    expect(defaultNodeConfig("mcp")).toEqual({
      server_id: "",
      tool_name: "",
      arguments: {},
    })
    expect(defaultNodeConfig("code")).toEqual({
      code: "result = inputs",
      inputs: { input: "{{start.question}}" },
    })
    expect(defaultNodeConfig("knowledge")).toEqual({
      knowledge_base_ids: [],
      query: "{{start.question}}",
      limit: 3,
      similarity: 0.6,
      search_mode: "embedding",
      graph_mode: "auto",
      source_entity: null,
      target_entity: null,
      max_hops: 6,
      relation_filters: [],
      max_paragraph_char_number: 5000,
    })
    expect(defaultNodeConfig("reply-node")).toEqual({
      reply_type: "custom",
      content: "",
      fields: null,
      is_result: true,
    })
    expect(defaultNodeConfig("template")).toEqual({
      template: "{{start.question}}",
    })
    expect(defaultNodeConfig("llm").prompt).toBe("{{start.question}}")
    expect(defaultNodeConfig("llm").dialogue_number).toBe(1)
    expect(defaultNodeConfig("llm").is_result).toBe(true)
    expect(defaultNodeConfig("end").outputs).toEqual({
      result: "{{start.question}}",
    })
    expect(defaultNodeConfig("start")).toEqual({})
    const condition = defaultNodeConfig("condition") as {
      branch: Array<{ type: string }>
    }
    expect(condition.branch.map((branch) => branch.type)).toEqual([
      "IF",
      "ELSE IF",
      "ELSE",
    ])
  })

  test("createWorkflowNode lays out a grid position and clones config", () => {
    const node = createWorkflowNode("llm", "LLM", 4, { custom: { deep: true } })
    expect(node.data.type).toBe("llm")
    expect(node.data.title).toBe("LLM")
    expect(node.data.config).toEqual({ custom: { deep: true } })
    expect(node.position).toEqual({ x: 240 + (4 % 3) * 260, y: 80 + 1 * 180 })
    expect(node.id.startsWith("llm-")).toBe(true)
    const defaulted = createWorkflowNode("end", "End", 0)
    expect(defaulted.data.config.outputs).toEqual({
      result: "{{start.question}}",
    })
  })

  test("ensureConditionElseIfBranches migrates IF/ELSE pairs and skips others", () => {
    const conditionNode: WorkflowNode = {
      id: "condition-1",
      type: "workflow",
      position: { x: 0, y: 0 },
      data: {
        type: "condition",
        title: "Condition",
        config: {
          branch: [
            { id: "if-1", type: "IF", condition: "and", conditions: [] },
            { id: "else-1", type: "ELSE", condition: "and", conditions: [] },
          ],
        },
      },
    }
    const graph: WorkflowGraph = {
      nodes: [
        { id: "start", type: "workflow", position: { x: 0, y: 0 }, data: { type: "start", title: "Start", config: {} } },
        conditionNode,
      ],
      edges: [
        { id: "edge-1", source: "condition-1", target: "end-1", sourceHandle: "else-1" },
      ],
      viewport: { x: 0, y: 0, zoom: 1 },
    }
    const migrated = ensureConditionElseIfBranches(graph)
    const branches = migrated.nodes[1].data.config.branch as Array<{ type: string; id: string }>
    expect(branches.map((branch) => branch.type)).toEqual(["IF", "ELSE IF", "ELSE"])
    expect(migrated.edges.map((edge) => edge.sourceHandle)).toContain(branches[1].id)

    // Single-branch conditions and non-condition nodes are untouched.
    const untouchedInput: WorkflowGraph = {
      nodes: [
        {
          ...conditionNode,
          data: {
            ...conditionNode.data,
            config: {
              branch: [{ id: "if-1", type: "IF", condition: "and", conditions: [] }],
            },
          },
        },
      ],
      edges: [],
      viewport: { x: 0, y: 0, zoom: 1 },
    }
    expect(ensureConditionElseIfBranches(untouchedInput)).toBe(untouchedInput)
    const threeBranches: WorkflowGraph = {
      nodes: [
        {
          ...conditionNode,
          data: {
            ...conditionNode.data,
            config: {
              branch: [
                { id: "if-1", type: "IF", condition: "and", conditions: [] },
                { id: "eif-1", type: "ELSE IF", condition: "and", conditions: [] },
                { id: "else-1", type: "ELSE", condition: "and", conditions: [] },
              ],
            },
          },
        },
      ],
      edges: [],
      viewport: { x: 0, y: 0, zoom: 1 },
    }
    expect(ensureConditionElseIfBranches(threeBranches)).toBe(threeBranches)
  })

  test("createWorkflowEdge only keeps provided handles", () => {
    const edge = createWorkflowEdge("start", "end", "source-1", "target-1")
    expect(edge.source).toBe("start")
    expect(edge.target).toBe("end")
    expect(edge.sourceHandle).toBe("source-1")
    expect(edge.targetHandle).toBe("target-1")
    const bare = createWorkflowEdge("start", "end")
    expect(bare.sourceHandle).toBeUndefined()
    expect(bare.targetHandle).toBeUndefined()
    expect(bare.id.startsWith("edge-")).toBe(true)
  })

  test("serializeWorkflowGraph keeps only durable fields", () => {
    const serialized = serializeWorkflowGraph(
      [
        {
          id: "start",
          type: "workflow",
          position: { x: 1, y: 2 },
          data: { type: "start", title: "Start", config: { extra: true } },
          selected: true,
          dragging: true,
        } as never,
      ],
      [
        { id: "edge-1", source: "start", target: "end", sourceHandle: "h", selected: true } as never,
      ],
      { x: 0, y: 0, zoom: 2 }
    )
    expect(serialized.nodes[0]).toEqual({
      id: "start",
      type: "workflow",
      position: { x: 1, y: 2 },
      data: { type: "start", title: "Start", config: { extra: true } },
    })
    expect(serialized.edges[0]).toEqual({
      id: "edge-1",
      source: "start",
      target: "end",
      sourceHandle: "h",
    })
    expect(serialized.viewport).toEqual({ x: 0, y: 0, zoom: 2 })
    expect(workflowGraphSignature(serialized)).toBe(
      JSON.stringify(serializeWorkflowGraph(serialized.nodes, serialized.edges, serialized.viewport))
    )
  })

  test("upstreamWorkflowFields collects reachable fields and guards cycles", () => {
    const nodes: WorkflowNode[] = [
      { id: "start", type: "workflow", position: { x: 0, y: 0 }, data: { type: "start", title: "Start", config: {} } },
      { id: "llm-1", type: "workflow", position: { x: 0, y: 0 }, data: { type: "llm", title: "LLM", config: {} } },
      { id: "knowledge-1", type: "workflow", position: { x: 0, y: 0 }, data: { type: "knowledge", title: "Knowledge", config: {} } },
      { id: "end-1", type: "workflow", position: { x: 0, y: 0 }, data: { type: "end", title: "End", config: {} } },
    ]
    const edges = [
      { id: "e1", source: "start", target: "llm-1" },
      { id: "e2", source: "llm-1", target: "end-1" },
      { id: "e3", source: "knowledge-1", target: "end-1" },
    ]
    const fieldsOf = (node: { type: string }) =>
      node.type === "start" ? [] : node.type === "llm" ? ["answer"] : node.type === "knowledge" ? ["chunks"] : []
    const upstream = upstreamWorkflowFields(nodes, edges, "end-1", fieldsOf as never)
    const byId = Object.fromEntries(upstream.map((item) => [item.id, item.fields]))
    expect(byId["llm-1"]).toEqual(["answer"])
    expect(byId["knowledge-1"]).toEqual(["chunks"])
    expect(byId["start"]).toBeUndefined()

    // A cycle through llm-1 does not loop forever and unknown nodes are skipped.
    const cyclic = upstreamWorkflowFields(
      [
        ...nodes,
        { id: "ghost", type: "workflow", position: { x: 0, y: 0 }, data: { type: "llm", title: "Ghost", config: {} } },
      ],
      [...edges, { id: "e4", source: "end-1", target: "llm-1" }, { id: "e5", source: "missing", target: "end-1" }],
      "end-1",
      fieldsOf as never
    )
    expect(cyclic.length).toBeLessThanOrEqual(3)
  })

  test("removeWorkflowNode drops inbound and outbound edges", () => {
    const result = removeWorkflowNode(
      [
        { id: "a", type: "workflow", position: { x: 0, y: 0 }, data: { type: "start", title: "A", config: {} } },
        { id: "b", type: "workflow", position: { x: 0, y: 0 }, data: { type: "end", title: "B", config: {} } },
      ] as never,
      [
        { id: "e1", source: "a", target: "b" },
        { id: "e2", source: "b", target: "a" },
        { id: "e3", source: "x", target: "y" },
      ] as never,
      "a"
    )
    expect(result.nodes.map((node) => node.id)).toEqual(["b"])
    expect(result.edges.map((edge) => edge.id)).toEqual(["e3"])
  })

  test("selectWorkflowRunTarget picks draft or the requested version", () => {
    const versions = [
      { version_number: 2, graph: { nodes: [], edges: [], viewport: { x: 0, y: 0, zoom: 1 } } },
      { version_number: 5, graph: { nodes: [], edges: [], viewport: { x: 0, y: 0, zoom: 1 } } },
    ]
    expect(selectWorkflowRunTarget(true, versions)).toEqual({
      source: "draft",
      versionNumber: undefined,
      graph: null,
    })
    expect(selectWorkflowRunTarget(false, versions)).toEqual({
      source: "published",
      versionNumber: 5,
      graph: versions[1].graph,
    })
    expect(selectWorkflowRunTarget(false, versions, 2)).toEqual({
      source: "published",
      versionNumber: 2,
      graph: versions[0].graph,
    })
    expect(selectWorkflowRunTarget(false, versions, 99)).toBeNull()
    expect(selectWorkflowRunTarget(false, [])).toBeNull()
  })

  test("WORKFLOW_NODE_PRESETS builds the question optimizer config", () => {
    const optimizer = WORKFLOW_NODE_PRESETS.find(
      (preset) => preset.id === "question-optimizer"
    )
    expect(optimizer?.type).toBe("llm")
    expect(optimizer?.config(((key: string) => key) as never, "start-2")).toEqual({
      system_prompt: "你是一个问题优化专家。",
      prompt: expect.stringContaining("{{start-2.question}}"),
    })
  })
})
