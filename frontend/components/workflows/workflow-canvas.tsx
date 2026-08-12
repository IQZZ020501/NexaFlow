"use client"

import * as React from "react"
import {
  Background,
  BackgroundVariant,
  Controls,
  MiniMap,
  ReactFlow,
  ReactFlowProvider,
  addEdge,
  useReactFlow,
  type AriaLabelConfig,
  type Connection,
  type EdgeChange,
  type NodeChange,
} from "@xyflow/react"
import { PlusIcon, Trash2Icon } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import type { TFunction } from "@/i18n"
import type { Agent } from "@/lib/api/agents"
import type { KnowledgeBase } from "@/lib/api/knowledge"
import type { RegisteredModel } from "@/lib/api/llm"
import type { McpServer } from "@/lib/api/mcp"
import type {
  WorkflowEdge,
  WorkflowGraph,
  WorkflowNode,
  WorkflowNodeExecution,
  WorkflowNodeType,
} from "@/lib/api/workflows"
import {
  WORKFLOW_NODE_TYPES,
  createWorkflowEdge,
  createWorkflowNode,
  removeWorkflowNode,
  serializeWorkflowGraph,
} from "@/lib/workflows/graph"
import {
  applyWorkflowEdgeChanges,
  applyWorkflowNodeChanges,
  persistedWorkflowViewport,
} from "@/lib/workflows/canvas"

import {
  NODE_ICONS,
  WorkflowNodeCard,
  workflowNodeLabel,
} from "./workflow-node"
import { WorkflowEdgeCard } from "./workflow-edge"

const nodeTypes = { workflow: WorkflowNodeCard }
const edgeTypes = { workflow: WorkflowEdgeCard }
const reactFlowProOptions = { hideAttribution: true }

type WorkflowCanvasProps = {
  agent: Agent
  graph: WorkflowGraph
  models: RegisteredModel[]
  knowledgeBases: KnowledgeBase[]
  mcpServers: McpServer[]
  runtimeStatuses: Record<string, WorkflowNodeExecution["status"]>
  readOnly: boolean
  onChange: (graph: WorkflowGraph) => void
  t: TFunction
}

function JsonEditor({
  id,
  label,
  value,
  readOnly,
  onChange,
  t,
}: {
  id: string
  label: string
  value: unknown
  readOnly: boolean
  onChange: (value: unknown) => void
  t: TFunction
}) {
  const [text, setText] = React.useState(() => JSON.stringify(value, null, 2))
  const [invalid, setInvalid] = React.useState(false)

  return (
    <label className="grid gap-1.5 text-xs font-medium" htmlFor={id}>
      {label}
      <textarea
        id={id}
        className="min-h-28 resize-y rounded-md border bg-background p-2 font-mono text-xs leading-5 outline-none focus-visible:ring-2 focus-visible:ring-ring aria-invalid:border-destructive"
        value={text}
        readOnly={readOnly}
        aria-invalid={invalid}
        onChange={(event) => {
          const next = event.target.value
          setText(next)
          try {
            const parsed = JSON.parse(next)
            setInvalid(false)
            onChange(parsed)
          } catch {
            setInvalid(true)
          }
        }}
      />
      {invalid ? (
        <span className="font-normal text-destructive">{t("JSON 格式无效")}</span>
      ) : null}
    </label>
  )
}

function TextEditor({
  id,
  label,
  value,
  readOnly,
  rows = 3,
  onChange,
}: {
  id: string
  label: string
  value: unknown
  readOnly: boolean
  rows?: number
  onChange: (value: string) => void
}) {
  return (
    <label className="grid gap-1.5 text-xs font-medium" htmlFor={id}>
      {label}
      <textarea
        id={id}
        rows={rows}
        className="resize-y rounded-md border bg-background px-2.5 py-2 text-sm leading-5 outline-none focus-visible:ring-2 focus-visible:ring-ring"
        value={typeof value === "string" ? value : JSON.stringify(value)}
        readOnly={readOnly}
        onChange={(event) => onChange(event.target.value)}
      />
    </label>
  )
}

function NodeConfigPanel({
  node,
  agent,
  models,
  knowledgeBases,
  mcpServers,
  readOnly,
  onUpdate,
  onDelete,
  t,
}: {
  node: WorkflowNode | null
  agent: Agent
  models: RegisteredModel[]
  knowledgeBases: KnowledgeBase[]
  mcpServers: McpServer[]
  readOnly: boolean
  onUpdate: (node: WorkflowNode) => void
  onDelete: () => void
  t: TFunction
}) {
  if (!node) {
    return (
      <div className="p-4 text-sm text-muted-foreground">
        {t("选择一个节点以编辑配置")}
      </div>
    )
  }
  const config = node.data.config
  const updateConfig = (patch: Record<string, unknown>) =>
    onUpdate({
      ...node,
      data: { ...node.data, config: { ...config, ...patch } },
    })
  const activeModels = models.filter(
    (model) => model.model_type === "LLM" && model.status === "active"
  )
  const boundKnowledge = knowledgeBases.filter((item) =>
    agent.knowledge_base_ids.includes(item.id)
  )
  const boundMcp = agent.mcp_tools
    .map((reference) => {
      const server = mcpServers.find((item) => item.id === reference.server_id)
      const tool = server?.tools.find((item) => item.name === reference.tool_name)
      return {
        ...reference,
        policyMode: tool?.policy_mode,
        label: `${server?.name ?? reference.server_id} / ${reference.tool_name}`,
      }
    })
    .filter((item) => item.policyMode === "read_only")

  return (
    <div className="flex h-full flex-col">
      <div className="border-b p-4">
        <p className="text-sm font-semibold">
          {workflowNodeLabel(node.data.type, t)}
        </p>
        <p className="mt-1 truncate text-xs text-muted-foreground">{node.id}</p>
      </div>
      <div className="grid flex-1 content-start gap-4 overflow-y-auto p-4">
        <label className="grid gap-1.5 text-xs font-medium" htmlFor="node-title">
          {t("节点名称")}
          <Input
            id="node-title"
            value={node.data.title}
            maxLength={120}
            readOnly={readOnly}
            onChange={(event) =>
              onUpdate({
                ...node,
                data: { ...node.data, title: event.target.value },
              })
            }
          />
        </label>

        {node.data.type === "start" ? (
          <JsonEditor
            id="start-inputs"
            label={t("输入字段")}
            value={config.inputs ?? []}
            readOnly={readOnly}
            onChange={(inputs) => updateConfig({ inputs })}
            t={t}
          />
        ) : null}
        {node.data.type === "end" ? (
          <JsonEditor
            id="end-outputs"
            label={t("输出映射")}
            value={config.outputs ?? {}}
            readOnly={readOnly}
            onChange={(outputs) => updateConfig({ outputs })}
            t={t}
          />
        ) : null}
        {node.data.type === "llm" ? (
          <>
            <label className="grid gap-1.5 text-xs font-medium" htmlFor="llm-model">
              {t("节点模型")}
              <select
                id="llm-model"
                className="h-9 rounded-md border bg-background px-2 text-sm"
                value={String(config.model_id ?? "")}
                disabled={readOnly}
                onChange={(event) =>
                  updateConfig({ model_id: event.target.value || null })
                }
              >
                <option value="">{t("使用工作流默认模型")}</option>
                {activeModels.map((model) => (
                  <option key={model.id} value={model.id}>
                    {model.name}
                  </option>
                ))}
              </select>
            </label>
            <TextEditor
              id="llm-system"
              label={t("系统提示词")}
              value={config.system_prompt ?? ""}
              readOnly={readOnly}
              onChange={(system_prompt) => updateConfig({ system_prompt })}
            />
            <TextEditor
              id="llm-prompt"
              label={t("用户提示词")}
              value={config.prompt ?? ""}
              readOnly={readOnly}
              rows={6}
              onChange={(prompt) => updateConfig({ prompt })}
            />
          </>
        ) : null}
        {node.data.type === "classifier" ? (
          <>
            <label className="grid gap-1.5 text-xs font-medium" htmlFor="classifier-model">
              {t("节点模型")}
              <select
                id="classifier-model"
                className="h-9 rounded-md border bg-background px-2 text-sm"
                value={String(config.model_id ?? "")}
                disabled={readOnly}
                onChange={(event) =>
                  updateConfig({ model_id: event.target.value || null })
                }
              >
                <option value="">{t("使用工作流默认模型")}</option>
                {activeModels.map((model) => (
                  <option key={model.id} value={model.id}>
                    {model.name}
                  </option>
                ))}
              </select>
            </label>
            <TextEditor
              id="classifier-input"
              label={t("分类输入")}
              value={config.input ?? ""}
              readOnly={readOnly}
              onChange={(input) => updateConfig({ input })}
            />
            <JsonEditor
              id="classifier-classes"
              label={t("分类出口")}
              value={config.classes ?? []}
              readOnly={readOnly}
              onChange={(classes) => updateConfig({ classes })}
              t={t}
            />
            <label className="grid gap-1.5 text-xs font-medium" htmlFor="classifier-default">
              {t("默认出口")}
              <Input
                id="classifier-default"
                value={String(config.default_handle ?? "default")}
                readOnly={readOnly}
                onChange={(event) =>
                  updateConfig({ default_handle: event.target.value })
                }
              />
            </label>
          </>
        ) : null}
        {node.data.type === "knowledge" ? (
          <>
            <label className="grid gap-1.5 text-xs font-medium" htmlFor="knowledge-source">
              {t("知识库")}
              <select
                id="knowledge-source"
                className="h-9 rounded-md border bg-background px-2 text-sm"
                value={String(config.knowledge_base_id ?? "")}
                disabled={readOnly}
                onChange={(event) =>
                  updateConfig({ knowledge_base_id: event.target.value })
                }
              >
                <option value="">{t("选择已绑定知识库")}</option>
                {boundKnowledge.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.name}
                  </option>
                ))}
              </select>
            </label>
            <TextEditor
              id="knowledge-query"
              label={t("检索查询")}
              value={config.query ?? ""}
              readOnly={readOnly}
              onChange={(query) => updateConfig({ query })}
            />
          </>
        ) : null}
        {node.data.type === "condition" ? (
          <>
            <TextEditor
              id="condition-left"
              label={t("左值")}
              value={config.left ?? ""}
              readOnly={readOnly}
              onChange={(left) => updateConfig({ left })}
            />
            <label className="grid gap-1.5 text-xs font-medium" htmlFor="condition-operator">
              {t("运算符")}
              <select
                id="condition-operator"
                className="h-9 rounded-md border bg-background px-2 text-sm"
                value={String(config.operator ?? "equals")}
                disabled={readOnly}
                onChange={(event) => updateConfig({ operator: event.target.value })}
              >
                {([
                  ["equals", "等于"],
                  ["not_equals", "不等于"],
                  ["contains", "包含"],
                  ["not_contains", "不包含"],
                  ["greater_than", "大于"],
                  ["greater_than_or_equal", "大于等于"],
                  ["less_than", "小于"],
                  ["less_than_or_equal", "小于等于"],
                  ["is_empty", "为空"],
                  ["is_not_empty", "不为空"],
                ] as const).map(([operator, label]) => (
                  <option key={operator} value={operator}>
                    {t(label)}
                  </option>
                ))}
              </select>
            </label>
            <JsonEditor
              id="condition-right"
              label={t("右值")}
              value={config.right ?? ""}
              readOnly={readOnly}
              onChange={(right) => updateConfig({ right })}
              t={t}
            />
          </>
        ) : null}
        {node.data.type === "template" ? (
          <TextEditor
            id="template-value"
            label={t("模板内容")}
            value={config.template ?? ""}
            readOnly={readOnly}
            rows={8}
            onChange={(template) => updateConfig({ template })}
          />
        ) : null}
        {node.data.type === "variable" ? (
          <JsonEditor
            id="variable-value"
            label={t("变量值")}
            value={config.value ?? null}
            readOnly={readOnly}
            onChange={(value) => updateConfig({ value })}
            t={t}
          />
        ) : null}
        {node.data.type === "mcp" ? (
          <>
            <label className="grid gap-1.5 text-xs font-medium" htmlFor="mcp-tool">
              {t("MCP 工具")}
              <select
                id="mcp-tool"
                className="h-9 rounded-md border bg-background px-2 text-sm"
                value={`${String(config.server_id ?? "")}:${String(config.tool_name ?? "")}`}
                disabled={readOnly}
                onChange={(event) => {
                  const [server_id, ...name] = event.target.value.split(":")
                  updateConfig({ server_id, tool_name: name.join(":") })
                }}
              >
                <option value=":">{t("选择只读 MCP 工具")}</option>
                {boundMcp.map((item) => (
                  <option
                    key={`${item.server_id}:${item.tool_name}`}
                    value={`${item.server_id}:${item.tool_name}`}
                  >
                    {item.label}
                  </option>
                ))}
              </select>
            </label>
            <JsonEditor
              id="mcp-arguments"
              label={t("工具参数")}
              value={config.arguments ?? {}}
              readOnly={readOnly}
              onChange={(argumentsValue) =>
                updateConfig({ arguments: argumentsValue })
              }
              t={t}
            />
          </>
        ) : null}
        {node.data.type === "code" ? (
          <>
            <TextEditor
              id="code-body"
              label={t("Python 代码")}
              value={config.code ?? ""}
              readOnly={readOnly}
              rows={10}
              onChange={(code) => updateConfig({ code })}
            />
            <JsonEditor
              id="code-inputs"
              label={t("代码输入")}
              value={config.inputs ?? {}}
              readOnly={readOnly}
              onChange={(inputs) => updateConfig({ inputs })}
              t={t}
            />
          </>
        ) : null}
      </div>
      {!readOnly && !["start", "end"].includes(node.data.type) ? (
        <div className="border-t p-3">
          <Button type="button" variant="destructive" className="w-full" onClick={onDelete}>
            <Trash2Icon data-icon="inline-start" />
            {t("删除节点")}
          </Button>
        </div>
      ) : null}
    </div>
  )
}

function CanvasInner(props: WorkflowCanvasProps) {
  const { screenToFlowPosition } = useReactFlow()
  const { t } = props
  const [nodes, setNodes] = React.useState<WorkflowNode[]>(props.graph.nodes)
  const [edges, setEdges] = React.useState<WorkflowEdge[]>(props.graph.edges)
  const [viewport, setViewport] = React.useState(props.graph.viewport)
  const [selectedId, setSelectedId] = React.useState<string | null>(null)
  const [selectedEdgeId, setSelectedEdgeId] = React.useState<string | null>(null)
  const onChangeRef = React.useRef(props.onChange)

  React.useEffect(() => {
    onChangeRef.current = props.onChange
  }, [props.onChange])

  React.useEffect(() => {
    onChangeRef.current(serializeWorkflowGraph(nodes, edges, viewport))
  }, [edges, nodes, viewport])

  const addNode = React.useCallback(
    (type: WorkflowNodeType, position?: { x: number; y: number }) => {
      if (props.readOnly) return
      if (["start", "end"].includes(type) && nodes.some((node) => node.data.type === type)) {
        return
      }
      const node = createWorkflowNode(
        type,
        workflowNodeLabel(type, props.t),
        nodes.length
      )
      if (position) node.position = position
      setNodes((current) => [...current, node])
      setSelectedId(node.id)
    },
    [nodes, props.readOnly, props.t]
  )

  const deleteEdge = React.useCallback((edgeId: string) => {
    setEdges((current) => current.filter((edge) => edge.id !== edgeId))
    setSelectedEdgeId((current) => (current === edgeId ? null : current))
  }, [])

  const updateNode = React.useCallback((nodeId: string, update: (node: WorkflowNode) => WorkflowNode) => {
    setNodes((current) => current.map((node) => (node.id === nodeId ? update(node) : node)))
  }, [])

  const copyNode = React.useCallback((nodeId: string) => {
    if (props.readOnly) return
    const source = nodes.find((node) => node.id === nodeId)
    if (!source) return
    const copy = createWorkflowNode(source.data.type, `${source.data.title} ${t("副本")}`, nodes.length)
    copy.position = { x: source.position.x + 300, y: source.position.y + 80 }
    copy.data.config = structuredClone(source.data.config)
    setNodes((current) => [...current, copy])
    setSelectedId(copy.id)
  }, [nodes, props.readOnly, t])

  const deleteNode = React.useCallback((nodeId: string) => {
    if (props.readOnly || ["start", "end"].some((type) => nodes.find((node) => node.id === nodeId)?.data.type === type)) return
    setNodes((current) => current.filter((node) => node.id !== nodeId))
    setEdges((current) => current.filter((edge) => edge.source !== nodeId && edge.target !== nodeId))
    setSelectedId((current) => (current === nodeId ? null : current))
  }, [nodes, props.readOnly])

  const renameNode = React.useCallback((nodeId: string, title: string) => {
    if (props.readOnly) return
    updateNode(nodeId, (node) => ({ ...node, data: { ...node.data, title } }))
  }, [props.readOnly, updateNode])

  const addConnectedNode = React.useCallback((sourceId: string, sourceHandle: string | null | undefined, type: WorkflowNodeType) => {
    if (props.readOnly) return
    const source = nodes.find((node) => node.id === sourceId)
    if (!source) return
    const nextNode = createWorkflowNode(type, workflowNodeLabel(type, t), nodes.length)
    nextNode.position = { x: source.position.x + 330, y: source.position.y }
    const edge = createWorkflowEdge(source.id, nextNode.id, sourceHandle)
    setNodes((current) => [...current, nextNode])
    setEdges((current) => addEdge(edge, current) as WorkflowEdge[])
    setSelectedId(nextNode.id)
    setSelectedEdgeId(edge.id)
  }, [nodes, props.readOnly, t])

  const selectedNode = nodes.find((node) => node.id === selectedId) ?? null
  const renderedNodes = React.useMemo(
    () =>
      nodes.map((node) => ({
          ...node,
          type: "workflow",
          data: {
            ...node.data,
            runtimeStatus: props.runtimeStatuses[node.id],
            readOnly: props.readOnly,
            onAddConnectedNode: addConnectedNode,
            onCopy: copyNode,
            onDelete: deleteNode,
            onRename: renameNode,
          },
      })),
    [addConnectedNode, copyNode, deleteNode, nodes, props.readOnly, props.runtimeStatuses, renameNode]
  )
  const renderedEdges = React.useMemo(
    () =>
      edges.map((edge) => ({
        ...edge,
        type: "workflow",
        data: {
          deleteLabel: t("删除连线"),
          readOnly: props.readOnly,
          onDelete: deleteEdge,
        },
        selected: edge.id === selectedEdgeId,
        interactionWidth: 28,
        ariaLabel: t("从 {source} 到 {target} 的连线", {
          source: edge.source,
          target: edge.target,
        }),
      })),
    [deleteEdge, edges, selectedEdgeId, t, props.readOnly]
  )
  const ariaLabelConfig = React.useMemo<Partial<AriaLabelConfig>>(() => {
    const directions: Record<string, string> = {
      left: t("左"),
      right: t("右"),
      up: t("上"),
      down: t("下"),
    }
    return {
      "node.a11yDescription.default": t(
        "按 Enter 或空格选择节点。按 Delete 删除，按 Escape 取消。"
      ),
      "node.a11yDescription.keyboardDisabled": t(
        "按 Enter 或空格选择节点，然后使用方向键移动。按 Delete 删除，按 Escape 取消。"
      ),
      "node.a11yDescription.ariaLiveMessage": ({ direction, x, y }) =>
        t("所选节点已向 {direction} 移动。新位置：x {x}，y {y}", {
          direction: directions[direction] ?? direction,
          x,
          y,
        }),
      "edge.a11yDescription.default": t(
        "按 Enter 或空格选择连线。按 Delete 删除，按 Escape 取消。"
      ),
      "controls.ariaLabel": t("画布控件"),
      "controls.zoomIn.ariaLabel": t("放大画布"),
      "controls.zoomOut.ariaLabel": t("缩小画布"),
      "controls.fitView.ariaLabel": t("适应画布"),
      "controls.interactive.ariaLabel": t("切换画布交互"),
      "minimap.ariaLabel": t("小地图"),
      "handle.ariaLabel": t("连接点"),
    }
  }, [t])
  const palette = (
    <div className="flex gap-2 lg:grid lg:gap-1.5">
      {WORKFLOW_NODE_TYPES.map((type) => {
        const Icon = NODE_ICONS[type]
        const disabled =
          props.readOnly ||
          (["start", "end"].includes(type) &&
            nodes.some((node) => node.data.type === type))
        return (
          <button
            key={type}
            type="button"
            draggable={!disabled}
            disabled={disabled}
            className="flex min-w-36 items-center gap-2 rounded-md border bg-background px-2.5 py-2 text-left text-xs font-medium shadow-xs transition-colors hover:bg-muted disabled:cursor-not-allowed disabled:opacity-40 lg:min-w-0"
            onClick={() => addNode(type)}
            onDragStart={(event) => {
              event.dataTransfer.setData("application/nexaflow-node", type)
              event.dataTransfer.effectAllowed = "move"
            }}
          >
            <Icon className="size-4 shrink-0 text-muted-foreground" />
            <span className="truncate">{workflowNodeLabel(type, props.t)}</span>
            <PlusIcon className="ml-auto size-3.5 text-muted-foreground" />
          </button>
        )
      })}
    </div>
  )

  return (
    <div className="grid min-h-0 flex-1 border-t bg-background lg:grid-cols-[180px_minmax(0,1fr)] xl:grid-cols-[180px_minmax(0,1fr)_320px]">
      <aside className="hidden overflow-y-auto border-r bg-muted/20 p-3 lg:block">
        <p className="mb-2 px-1 text-xs font-semibold text-muted-foreground">
          {props.t("节点库")}
        </p>
        {palette}
      </aside>
      <div className="min-w-0">
        <div className="overflow-x-auto border-b bg-muted/20 p-2 lg:hidden">
          {palette}
        </div>
        <div className="h-[56vh] min-h-[440px] lg:h-[calc(100dvh-9.5rem)]">
          <ReactFlow
            nodes={renderedNodes}
            edges={renderedEdges}
            nodeTypes={nodeTypes}
            edgeTypes={edgeTypes}
            defaultViewport={props.graph.viewport}
            ariaLabelConfig={ariaLabelConfig}
            proOptions={reactFlowProOptions}
            minZoom={0.2}
            maxZoom={2}
            nodesDraggable={!props.readOnly}
            nodesConnectable={!props.readOnly}
            elementsSelectable
            onNodesChange={(changes: NodeChange[]) =>
              setNodes((current) =>
                applyWorkflowNodeChanges(current, changes, props.readOnly)
              )
            }
            onEdgesChange={(changes: EdgeChange[]) => {
              const removedIds = new Set(
                changes
                  .filter((change) => change.type === "remove")
                  .map((change) => change.id)
              )
              if (selectedEdgeId && removedIds.has(selectedEdgeId)) {
                setSelectedEdgeId(null)
              }
              setEdges((current) =>
                applyWorkflowEdgeChanges(current, changes, props.readOnly)
              )
            }}
            onConnect={(connection: Connection) => {
              if (
                props.readOnly ||
                !connection.source ||
                !connection.target ||
                connection.source === connection.target ||
                edges.some(
                  (edge) =>
                    edge.source === connection.source &&
                    edge.target === connection.target &&
                    edge.sourceHandle === connection.sourceHandle
                )
              ) {
                return
              }
              const edge = createWorkflowEdge(
                connection.source,
                connection.target,
                connection.sourceHandle,
                connection.targetHandle
              )
              setEdges((current) => addEdge(edge, current) as WorkflowEdge[])
              setSelectedEdgeId(edge.id)
            }}
            onNodeClick={(_event, node) => {
              setSelectedId(node.id)
              setSelectedEdgeId(null)
            }}
            onEdgeClick={(event, edge) => {
              event.stopPropagation()
              setSelectedEdgeId(edge.id)
              setSelectedId(null)
            }}
            onPaneClick={() => {
              setSelectedId(null)
              setSelectedEdgeId(null)
            }}
            onSelectionChange={({ edges: selectedEdges }) => {
              if (selectedEdges.length > 0) {
                setSelectedEdgeId(selectedEdges[0].id)
              }
            }}
            deleteKeyCode={props.readOnly ? null : ["Backspace", "Delete"]}
            onMoveEnd={(_event, nextViewport) =>
              setViewport((current) =>
                persistedWorkflowViewport(current, nextViewport, props.readOnly)
              )
            }
            onDragOver={(event) => {
              event.preventDefault()
              event.dataTransfer.dropEffect = "move"
            }}
            onDrop={(event) => {
              event.preventDefault()
              const type = event.dataTransfer.getData(
                "application/nexaflow-node"
              ) as WorkflowNodeType
              if (!WORKFLOW_NODE_TYPES.includes(type)) return
              addNode(type, screenToFlowPosition({ x: event.clientX, y: event.clientY }))
            }}
          >
            <Background variant={BackgroundVariant.Dots} gap={18} size={1} />
            <Controls showInteractive={false} />
            <MiniMap
              pannable
              zoomable
              className="!border !bg-background"
              nodeColor="var(--muted-foreground)"
              maskColor="color-mix(in oklch, var(--background) 75%, transparent)"
            />
          </ReactFlow>
        </div>
      </div>
      <aside className="min-h-72 border-t bg-muted/10 lg:col-span-2 xl:col-span-1 xl:border-t-0 xl:border-l">
        <NodeConfigPanel
          key={selectedNode?.id ?? "no-selection"}
          node={selectedNode}
          agent={props.agent}
          models={props.models}
          knowledgeBases={props.knowledgeBases}
          mcpServers={props.mcpServers}
          readOnly={props.readOnly}
          onUpdate={(nextNode) =>
            setNodes((current) =>
              current.map((node) => (node.id === nextNode.id ? nextNode : node))
            )
          }
          onDelete={() => {
            if (!selectedNode) return
            const next = removeWorkflowNode(nodes, edges, selectedNode.id)
            setNodes(next.nodes)
            setEdges(next.edges)
            setSelectedId(null)
          }}
          t={props.t}
        />
      </aside>
    </div>
  )
}

export default function WorkflowCanvas(props: WorkflowCanvasProps) {
  return (
    <ReactFlowProvider>
      <CanvasInner {...props} />
    </ReactFlowProvider>
  )
}
