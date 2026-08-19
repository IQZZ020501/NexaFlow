import type {
  WorkflowEdge,
  WorkflowGraph,
  WorkflowNode,
  WorkflowNodeData,
  WorkflowNodeType,
  WorkflowVersion,
} from "@/lib/api/workflows"
import type { TFunction, TranslationKey } from "@/i18n"

export const WORKFLOW_NODE_TYPES: WorkflowNodeType[] = [
  "reply-node",
  "start",
  "end",
  "llm",
  "classifier",
  "knowledge",
  "reranker-node",
  "form-node",
  "document-extract-node",
  "condition",
  "variable",
  "mcp",
  "code",
  "tool",
  "agent",
]

export const WORKFLOW_BASIC_NODE_TYPES: WorkflowNodeType[] = [
  "reply-node",
  "start",
  "end",
  "llm",
  "classifier",
  "knowledge",
  "reranker-node",
  "form-node",
  "document-extract-node",
  "condition",
  "variable",
]

const WORKFLOW_NODE_LABELS: Record<WorkflowNodeType, TranslationKey> = {
  start: "开始节点",
  end: "结束节点",
  llm: "大语言模型",
  classifier: "问题分类器",
  knowledge: "知识检索节点",
  "reranker-node": "多路召回",
  "form-node": "表单收集",
  "document-extract-node": "文档内容提取",
  condition: "条件分支",
  "reply-node": "指定回复",
  template: "模板转换",
  variable: "变量赋值",
  tool: "工具",
  agent: "Agent",
  mcp: "MCP 工具节点",
  code: "Python 代码",
}

const WORKFLOW_ERROR_LABELS: Partial<Record<string, TranslationKey>> = {
  "Workflow reranker content must contain non-empty text.":
    "重排内容必须包含非空文本。",
  "Workflow model request failed.": "工作流模型请求失败。",
  "Workflow model request timed out.": "工作流模型请求超时。",
  "Workflow node execution failed.": "工作流节点执行失败。",
  "Workflow node failed.": "工作流节点执行失败。",
  "Workflow execution failed.": "工作流执行失败。",
  "Workflow run failed.": "工作流运行失败。",
  "Workflow run was cancelled.": "工作流运行已取消。",
  "Workflow document references must contain a file id.":
    "文档引用必须包含文件 ID。",
}

/**
 * Resolves the localized label for a workflow node type.
 *
 * @returns The localized node label
 */
export function workflowNodeLabel(type: WorkflowNodeType, t: TFunction) {
  return t(WORKFLOW_NODE_LABELS[type])
}

/**
 * Resolves the display label for a workflow execution node.
 *
 * @param nodeId - The graph node identifier
 * @param type - The node type used when no title is available
 * @param graph - The workflow graph containing the node, if available
 * @returns The node's trimmed title, or its localized type label when no title is available
 */
export function workflowExecutionNodeLabel(
  nodeId: string,
  type: WorkflowNodeType,
  graph: WorkflowGraph | null,
  t: TFunction
) {
  const title = graph?.nodes
    .find((node) => node.id === nodeId)
    ?.data.title.trim()
  return title || workflowNodeLabel(type, t)
}

/**
 * Translates a recognized workflow error message.
 *
 * @param message - The workflow error message to translate
 * @param t - The translation function
 * @returns The translated error message, or the original message when no translation is defined
 */
export function workflowErrorMessage(message: string, t: TFunction) {
  const label = WORKFLOW_ERROR_LABELS[message]
  return label ? t(label) : message
}

/** Start node globals, referenced as {{global.<value>}} (MaxKB-compatible). */
export const WORKFLOW_START_GLOBALS: Array<{
  label: TranslationKey
  value: string
}> = [
  { label: "当前时间", value: "time" },
  { label: "历史记录", value: "history_context" },
  { label: "会话 ID", value: "chat_id" },
  { label: "运行开始时间戳", value: "start_time" },
]

/** Start node run outputs, referenced as {{<nodeId>.<value>}}. */
export const WORKFLOW_START_FIELDS: Array<{
  label: TranslationKey
  value: string
}> = [
  { label: "用户问题", value: "question" },
  { label: "上传文件", value: "files" },
  { label: "文档", value: "document" },
]

export type WorkflowNodePreset = {
  id: string
  type: WorkflowNodeType
  label: TranslationKey
  config: (t: TFunction, startNodeId?: string) => Record<string, unknown>
}

export const WORKFLOW_NODE_PRESETS: WorkflowNodePreset[] = [
  {
    id: "question-optimizer",
    type: "llm",
    label: "问题优化",
    config: (t, startNodeId = "start") => ({
      system_prompt: t("你是一个问题优化专家。"),
      prompt: t(
        "请在不改变原意的前提下优化下面的问题，只返回优化后的问题：\n\n{{start.question}}"
      ).replace("{{start.question}}", `{{${startNodeId}.question}}`),
    }),
  },
]

/**
 * Creates the default configuration for a workflow node type.
 *
 * @param type - The workflow node type to configure
 * @param startNodeId - The identifier used for references to the workflow start node
 * @returns The initial configuration for the specified node type
 */
export function defaultNodeConfig(
  type: WorkflowNodeType,
  startNodeId = "start"
): Record<string, unknown> {
  const questionReference = `{{${startNodeId}.question}}`
  switch (type) {
    case "start":
      return {}
    case "end":
      return { outputs: { result: questionReference } }
    case "llm":
      return {
        prompt: questionReference,
        system_prompt: "",
        dialogue_number: 1,
        dialogue_type: "NODE",
        model_params_setting: {},
        model_setting: {},
        tools: [],
        is_result: true,
      }
    case "classifier":
      return {
        input: questionReference,
        classes: [
          { handle: "match", label: "Match", description: "" },
          { handle: "other", label: "Other", description: "" },
        ],
        default_handle: "default",
      }
    case "knowledge":
      return {
        knowledge_base_ids: [],
        query: questionReference,
        limit: 3,
        similarity: 0.6,
        search_mode: "embedding",
        max_paragraph_char_number: 5000,
      }
    case "reranker-node":
      return {
        reranker_model_id: "",
        question_reference_address: questionReference,
        reranker_reference_list: [],
        reranker_setting: {
          top_n: 3,
          similarity: 0,
          max_paragraph_char_number: 5000,
        },
      }
    case "form-node":
      return {
        form_field_list: [],
        form_content_format: "{{ form }}",
        is_result: true,
      }
    case "document-extract-node":
      return { document_list: `{{${startNodeId}.document}}` }
    case "condition":
      return {
        branch: [
          {
            id: crypto.randomUUID().replaceAll("-", "").slice(0, 12),
            type: "IF",
            condition: "and",
            conditions: [
              { field: [startNodeId, "question"], compare: "eq", value: "" },
            ],
          },
          {
            id: crypto.randomUUID().replaceAll("-", "").slice(0, 12),
            type: "ELSE IF",
            condition: "and",
            conditions: [
              { field: [startNodeId, "question"], compare: "eq", value: "" },
            ],
          },
          {
            id: crypto.randomUUID().replaceAll("-", "").slice(0, 12),
            type: "ELSE",
            condition: "and",
            conditions: [],
          },
        ],
      }
    case "reply-node":
      return {
        reply_type: "custom",
        content: "",
        fields: null,
        is_result: true,
      }
    case "template":
      return { template: questionReference }
    case "variable":
      return { value: questionReference }
    case "tool":
      return {
        tool: { tool_id: "", version_id: "" },
        arguments: {},
      }
    case "agent":
      return {
        agent_id: "",
        agent_version_id: "",
        input: questionReference,
      }
    case "mcp":
      return { server_id: "", tool_name: "", arguments: {} }
    case "code":
      return {
        code: "result = inputs",
        inputs: { input: questionReference },
      }
  }
}

/**
 * Creates a workflow graph node with a generated identifier, grid position, and configuration.
 *
 * @param type - The workflow node type
 * @param title - The node title
 * @param index - The node's layout index
 * @param config - Optional node configuration; defaults to the configuration for `type`
 * @param startNodeId - The identifier of the workflow start node used by the default configuration
 * @returns A configured workflow node
 */
export function createWorkflowNode(
  type: WorkflowNodeType,
  title: string,
  index: number,
  config?: Record<string, unknown>,
  startNodeId = "start"
): WorkflowNode {
  return {
    id: `${type}-${crypto.randomUUID().slice(0, 8)}`,
    type: "workflow",
    position: {
      x: 240 + (index % 3) * 260,
      y: 80 + Math.floor(index / 3) * 180,
    },
    data: {
      type,
      title,
      config: structuredClone(config ?? defaultNodeConfig(type, startNodeId)),
    },
  }
}

/**
 * Ensures condition nodes with only `IF` and `ELSE` branches include an `ELSE IF` branch.
 *
 * Existing edges from the `ELSE` branch are duplicated and redirected to the new `ELSE IF` branch.
 *
 * @param graph - The workflow graph to update
 * @returns The updated graph, or the original graph when no condition branches require migration
 */
export function ensureConditionElseIfBranches(
  graph: WorkflowGraph
): WorkflowGraph {
  const startNodeId =
    graph.nodes.find((node) => node.data.type === "start")?.id ?? "start"
  const edges = [...graph.edges]
  let changed = false
  const nodes = graph.nodes.map((node) => {
    const branches = node.data.config.branch
    if (
      node.data.type !== "condition" ||
      !Array.isArray(branches) ||
      branches.length !== 2 ||
      !branches[0] ||
      typeof branches[0] !== "object" ||
      !branches[1] ||
      typeof branches[1] !== "object" ||
      (branches[0] as Record<string, unknown>).type !== "IF" ||
      (branches[1] as Record<string, unknown>).type !== "ELSE"
    ) {
      return node
    }
    changed = true
    const branchId = crypto.randomUUID().replaceAll("-", "").slice(0, 12)
    const elseBranchId = String((branches[1] as Record<string, unknown>).id)
    edges.push(
      ...graph.edges
        .filter(
          (edge) =>
            edge.source === node.id && edge.sourceHandle === elseBranchId
        )
        .map((edge) => ({
          ...edge,
          id: `edge-${crypto.randomUUID().slice(0, 12)}`,
          sourceHandle: branchId,
        }))
    )
    return {
      ...node,
      data: {
        ...node.data,
        config: {
          ...node.data.config,
          branch: [
            branches[0],
            {
              id: branchId,
              type: "ELSE IF",
              condition: "and",
              conditions: [
                {
                  field: [startNodeId, "question"],
                  compare: "eq",
                  value: "",
                },
              ],
            },
            branches[1],
          ],
        },
      },
    }
  })
  return changed ? { ...graph, nodes, edges } : graph
}

/**
 * Creates a workflow edge connecting two nodes.
 *
 * @param source - The identifier of the source node
 * @param target - The identifier of the target node
 * @param sourceHandle - The optional source handle identifier
 * @param targetHandle - The optional target handle identifier
 * @returns A workflow edge with a generated identifier
 */
export function createWorkflowEdge(
  source: string,
  target: string,
  sourceHandle?: string | null,
  targetHandle?: string | null
): WorkflowEdge {
  return {
    id: `edge-${crypto.randomUUID().slice(0, 12)}`,
    source,
    target,
    ...(sourceHandle ? { sourceHandle } : {}),
    ...(targetHandle ? { targetHandle } : {}),
  }
}

/**
 * Creates a normalized, independent workflow graph snapshot.
 *
 * @param nodes - The workflow nodes to include
 * @param edges - The workflow edges to include
 * @param viewport - The graph viewport to include
 * @returns A normalized workflow graph with cloned node configurations and viewport data
 */
export function serializeWorkflowGraph(
  nodes: WorkflowNode[],
  edges: WorkflowEdge[],
  viewport: WorkflowGraph["viewport"]
): WorkflowGraph {
  return {
    nodes: nodes.map((node) => ({
      id: node.id,
      type: "workflow",
      position: { x: node.position.x, y: node.position.y },
      data: {
        type: node.data.type,
        title: node.data.title,
        config: structuredClone(node.data.config),
      },
    })),
    edges: edges.map((edge) => ({
      id: edge.id,
      source: edge.source,
      target: edge.target,
      ...(edge.sourceHandle ? { sourceHandle: edge.sourceHandle } : {}),
      ...(edge.targetHandle ? { targetHandle: edge.targetHandle } : {}),
    })),
    viewport: { ...viewport },
  }
}

/**
 * Creates a stable serialized representation of a workflow graph.
 *
 * @param graph - The workflow graph to serialize
 * @returns A JSON string containing the normalized graph
 */
export function workflowGraphSignature(graph: WorkflowGraph) {
  return JSON.stringify(
    serializeWorkflowGraph(graph.nodes, graph.edges, graph.viewport)
  )
}

/**
 * Collects output fields from nodes reachable upstream of a workflow node.
 *
 * @param nodeId - The ID of the node whose incoming graph is traversed
 * @param fieldsOf - Extracts available output field names from a node's data
 * @returns Reachable upstream nodes with their IDs, titles, and output fields
 */
export function upstreamWorkflowFields(
  nodes: WorkflowNode[],
  edges: WorkflowEdge[],
  nodeId: string,
  fieldsOf: (node: WorkflowNodeData) => string[]
): Array<{ id: string; title: string; fields: string[] }> {
  const byId = new Map(nodes.map((node) => [node.id, node]))
  const incoming = new Map<string, string[]>()
  for (const edge of edges) {
    const sources = incoming.get(edge.target) ?? []
    sources.push(edge.source)
    incoming.set(edge.target, sources)
  }
  const visited = new Set<string>()
  const result: Array<{ id: string; title: string; fields: string[] }> = []
  const stack = [...(incoming.get(nodeId) ?? [])]
  while (stack.length) {
    const id = stack.pop()
    if (!id || visited.has(id)) continue
    visited.add(id)
    const node = byId.get(id)
    if (!node) continue
    const fields = fieldsOf(node.data)
    if (fields.length) {
      result.push({ id, title: node.data.title, fields })
    }
    stack.push(...(incoming.get(id) ?? []))
  }
  return result
}

/**
 * Removes a workflow node and its connected edges from a graph.
 *
 * @param nodes - The workflow nodes in the graph
 * @param edges - The workflow edges in the graph
 * @param nodeId - The identifier of the node to remove
 * @returns The graph without the specified node or edges connected to it
 */
export function removeWorkflowNode(
  nodes: WorkflowNode[],
  edges: WorkflowEdge[],
  nodeId: string
) {
  return {
    nodes: nodes.filter((node) => node.id !== nodeId),
    edges: edges.filter(
      (edge) => edge.source !== nodeId && edge.target !== nodeId
    ),
  }
}

/**
 * Selects the workflow graph to use for execution.
 *
 * @param canEdit - Whether the workflow is editable.
 * @param versions - Available published workflow versions.
 * @param selectedVersionNumber - The requested version number, or the latest version when omitted.
 * @returns The draft target for editable workflows without a selected version, a published target when available, or `null` when no matching version exists.
 */
export function selectWorkflowRunTarget(
  canEdit: boolean,
  versions: Pick<WorkflowVersion, "version_number" | "graph">[],
  selectedVersionNumber?: number | null
) {
  if (canEdit && selectedVersionNumber == null) {
    return { source: "draft" as const, versionNumber: undefined, graph: null }
  }
  const version = selectedVersionNumber
    ? versions.find((item) => item.version_number === selectedVersionNumber)
    : versions.reduce<(typeof versions)[number] | null>(
        (latest, item) =>
          !latest || item.version_number > latest.version_number
            ? item
            : latest,
        null
      )
  return version
    ? {
        source: "published" as const,
        versionNumber: version.version_number,
        graph: version.graph,
      }
    : null
}
