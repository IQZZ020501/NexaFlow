import type {
  WorkflowEdge,
  WorkflowGraph,
  WorkflowNode,
  WorkflowNodeType,
  WorkflowVersion,
} from "@/lib/api/workflows"

export const WORKFLOW_NODE_TYPES: WorkflowNodeType[] = [
  "start",
  "end",
  "llm",
  "classifier",
  "knowledge",
  "condition",
  "template",
  "variable",
  "mcp",
  "code",
]

export function defaultNodeConfig(
  type: WorkflowNodeType
): Record<string, unknown> {
  switch (type) {
    case "start":
      return { inputs: [{ name: "input", type: "string", required: true }] }
    case "end":
      return { outputs: { result: "{{start.input}}" } }
    case "llm":
      return { prompt: "{{start.input}}", system_prompt: "" }
    case "classifier":
      return {
        input: "{{start.input}}",
        classes: [
          { handle: "match", label: "Match", description: "" },
          { handle: "other", label: "Other", description: "" },
        ],
        default_handle: "default",
      }
    case "knowledge":
      return { knowledge_base_id: "", query: "{{start.input}}" }
    case "condition":
      return {
        left: "{{start.input}}",
        operator: "equals",
        right: "",
      }
    case "template":
      return { template: "{{start.input}}" }
    case "variable":
      return { value: "{{start.input}}" }
    case "mcp":
      return { server_id: "", tool_name: "", arguments: {} }
    case "code":
      return { code: "result = inputs", inputs: { input: "{{start.input}}" } }
  }
}

export function createWorkflowNode(
  type: WorkflowNodeType,
  title: string,
  index: number
): WorkflowNode {
  return {
    id: `${type}-${crypto.randomUUID().slice(0, 8)}`,
    type: "workflow",
    position: {
      x: 240 + (index % 3) * 260,
      y: 80 + Math.floor(index / 3) * 180,
    },
    data: { type, title, config: defaultNodeConfig(type) },
  }
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

export function initialWorkflowInputs(graph: WorkflowGraph) {
  const fields = graph.nodes.find((node) => node.data.type === "start")?.data
    .config.inputs
  if (!Array.isArray(fields)) return {}
  return Object.fromEntries(
    fields.flatMap((field) => {
      if (!field || typeof field !== "object") return []
      const item = field as Record<string, unknown>
      if (typeof item.name !== "string" || !item.name) return []
      const value =
        item.default ??
        (item.type === "number"
          ? 0
          : item.type === "boolean"
            ? false
            : item.type === "object"
              ? {}
              : item.type === "array"
                ? []
                : "")
      return [[item.name, value]]
    })
  )
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
