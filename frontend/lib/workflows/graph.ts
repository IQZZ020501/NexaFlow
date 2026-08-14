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
  "condition",
  "variable",
  "mcp",
  "code",
]

/** Start node globals, referenced as {{global.<value>}} (MaxKB-compatible). */
export const WORKFLOW_START_GLOBALS: Array<{ label: TranslationKey; value: string }> = [
  { label: "当前时间", value: "time" },
  { label: "历史记录", value: "history_context" },
  { label: "会话 ID", value: "chat_id" },
  { label: "运行开始时间戳", value: "start_time" },
]

/** Start node run outputs, referenced as {{<nodeId>.<value>}}. */
export const WORKFLOW_START_FIELDS: Array<{ label: TranslationKey; value: string }> = [
  { label: "用户问题", value: "question" },
  { label: "上传文件", value: "files" },
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
      prompt: t("请在不改变原意的前提下优化下面的问题，只返回优化后的问题：\n\n{{start.question}}").replace(
        "{{start.question}}",
        `{{${startNodeId}.question}}`
      ),
    }),
  },
]

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
        mcp_enable: false,
        mcp_servers: [],
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
    case "mcp":
      return { server_id: "", tool_name: "", arguments: {} }
    case "code":
      return {
        code: "result = inputs",
        inputs: { input: questionReference },
      }
  }
}

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

export function workflowGraphSignature(graph: WorkflowGraph) {
  return JSON.stringify(
    serializeWorkflowGraph(graph.nodes, graph.edges, graph.viewport)
  )
}

/**
 * Collects every upstream node reachable through incoming edges together with
 * its output field names, for variable picking in node inputs. The start node
 * is intentionally not included: its fields are always available through the
 * `{{global.*}}` namespace.
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
          !latest || item.version_number > latest.version_number ? item : latest,
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
