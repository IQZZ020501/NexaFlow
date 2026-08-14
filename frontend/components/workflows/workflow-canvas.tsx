"use client"

import * as React from "react"
import {
  Background,
  BackgroundVariant,
  Controls,
  MiniMap,
  ReactFlow,
  ReactFlowProvider,
  ViewportPortal,
  addEdge,
  useReactFlow,
  type AriaLabelConfig,
  type Connection,
  type EdgeChange,
  type NodeChange,
} from "@xyflow/react"
import {
  ChevronDownIcon,
  ChevronUpIcon,
  FileTextIcon,
  PlusIcon,
} from "lucide-react"

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { IconButton } from "@/components/ui/icon-button"
import { Input } from "@/components/ui/input"
import type { TFunction } from "@/i18n"
import type { Agent } from "@/lib/api/agents"
import type { AgentFormState } from "@/components/agents/agents-page"
import { InteractionConfigFields } from "@/components/agents/interaction-config-fields"
import type { KnowledgeBase } from "@/lib/api/knowledge"
import type { RegisteredModel } from "@/lib/api/llm"
import type { McpServer } from "@/lib/api/mcp"
import type {
  WorkflowEdge,
  WorkflowGraph,
  WorkflowNode,
  WorkflowNodeData,
  WorkflowNodeExecution,
  WorkflowNodeType,
} from "@/lib/api/workflows"
import {
  WORKFLOW_NODE_PRESETS,
  WORKFLOW_NODE_TYPES,
  createWorkflowEdge,
  createWorkflowNode,
  ensureConditionElseIfBranches,
  serializeWorkflowGraph,
} from "@/lib/workflows/graph"
import {
  applyWorkflowEdgeChanges,
  applyWorkflowNodeChanges,
  canvasPositionLeftOf,
  draggedCanvasPosition,
  nonOverlappingCanvasPosition,
  persistedWorkflowViewport,
  viewportIncludingCanvasX,
  viewportIncludingCanvasY,
  workflowNodeRects,
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
  paletteOpen: boolean
  onClosePalette: () => void
  form: AgentFormState
  setForm: React.Dispatch<React.SetStateAction<AgentFormState>>
  onChange: (graph: WorkflowGraph) => void
  t: TFunction
}

function CanvasInner(props: WorkflowCanvasProps) {
  const { screenToFlowPosition, setViewport: setFlowViewport } = useReactFlow()
  const { t } = props
  const [initialGraph] = React.useState(() =>
    props.readOnly ? props.graph : ensureConditionElseIfBranches(props.graph)
  )
  const [nodes, setNodes] = React.useState<WorkflowNode[]>(initialGraph.nodes)
  const [edges, setEdges] = React.useState<WorkflowEdge[]>(initialGraph.edges)
  const startNodeId =
    nodes.find((node) => node.data.type === "start")?.id ?? "start"
  const [viewport, setViewport] = React.useState(props.graph.viewport)
  const [selectedEdgeId, setSelectedEdgeId] = React.useState<string | null>(null)
  const [infoOpen, setInfoOpen] = React.useState(true)
  const [infoPosition, setInfoPosition] = React.useState({ x: 16, y: 16 })
  const infoCardRef = React.useRef<HTMLDivElement | null>(null)
  const infoPositionInitializedRef = React.useRef(false)
  const infoViewportAdjustedRef = React.useRef(false)
  const transientViewportRef = React.useRef<WorkflowGraph["viewport"] | null>(
    null
  )
  const skipInitialChangeRef = React.useRef(true)
  const onChangeRef = React.useRef(props.onChange)

  React.useEffect(() => {
    onChangeRef.current = props.onChange
  }, [props.onChange])

  React.useEffect(() => {
    if (skipInitialChangeRef.current) {
      skipInitialChangeRef.current = false
      return
    }
    onChangeRef.current(serializeWorkflowGraph(nodes, edges, viewport))
  }, [edges, nodes, viewport])

  const addNode = React.useCallback(
    (
      type: WorkflowNodeType,
      position?: { x: number; y: number },
      title = workflowNodeLabel(type, props.t),
      config?: Record<string, unknown>
    ) => {
      if (props.readOnly) return
      if (["start", "end"].includes(type) && nodes.some((node) => node.data.type === type)) {
        return
      }
      const node = createWorkflowNode(
        type,
        title,
        nodes.length,
        config,
        startNodeId
      )
      if (position) node.position = position
      setNodes((current) => [...current, node])
    },
    [nodes, props.readOnly, props.t, startNodeId]
  )

  const flowPaneRef = React.useRef<HTMLDivElement | null>(null)
  const infoDragRef = React.useRef<{
    pointerId: number
    pointer: { x: number; y: number }
    position: { x: number; y: number }
  } | null>(null)
  const { onClosePalette } = props

  const clearInfoCardPosition = React.useCallback(
    (position: { x: number; y: number }) => {
      const card = infoCardRef.current
      if (!card) return position
      return nonOverlappingCanvasPosition(
        position,
        { width: card.offsetWidth, height: card.offsetHeight },
        workflowNodeRects(nodes)
      )
    },
    [nodes]
  )

  React.useLayoutEffect(() => {
    if (infoPositionInitializedRef.current) return
    const card = infoCardRef.current
    if (!card) return
    const nodeRects = workflowNodeRects(nodes)
    const startNode = nodeRects[nodes.findIndex((node) => node.data.type === "start")]
    if (!startNode) return
    const next = nonOverlappingCanvasPosition(
      canvasPositionLeftOf(startNode, {
        width: card.offsetWidth,
        height: card.offsetHeight,
      }),
      { width: card.offsetWidth, height: card.offsetHeight },
      nodeRects
    )
    infoPositionInitializedRef.current = true
    setInfoPosition(next)
  }, [nodes])

  React.useEffect(() => {
    if (
      !infoPositionInitializedRef.current ||
      infoViewportAdjustedRef.current
    ) {
      return
    }
    infoViewportAdjustedRef.current = true
    const top = Math.min(infoPosition.y, ...nodes.map((node) => node.position.y))
    const next = viewportIncludingCanvasY(
      viewportIncludingCanvasX(viewport, infoPosition.x),
      top
    )
    if (next.x === viewport.x && next.y === viewport.y) return
    transientViewportRef.current = next
    void setFlowViewport(next)
  }, [infoPosition.x, infoPosition.y, nodes, setFlowViewport, viewport])

  const moveInfoCardBy = React.useCallback(
    (x: number, y: number) => {
      setInfoPosition((current) =>
        clearInfoCardPosition({ x: current.x + x, y: current.y + y })
      )
    },
    [clearInfoCardPosition]
  )

  const handleInfoDragStart = React.useCallback(
    (event: React.PointerEvent<HTMLButtonElement>) => {
      if (event.button !== 0) return
      infoDragRef.current = {
        pointerId: event.pointerId,
        pointer: screenToFlowPosition({ x: event.clientX, y: event.clientY }),
        position: infoPosition,
      }
      event.currentTarget.setPointerCapture(event.pointerId)
      event.preventDefault()
      event.stopPropagation()
    },
    [infoPosition, screenToFlowPosition]
  )

  const handleInfoDragMove = React.useCallback(
    (event: React.PointerEvent<HTMLButtonElement>) => {
      const drag = infoDragRef.current
      if (!drag || drag.pointerId !== event.pointerId) return
      setInfoPosition(
        clearInfoCardPosition(
          draggedCanvasPosition(
            drag.position,
            drag.pointer,
            screenToFlowPosition({ x: event.clientX, y: event.clientY })
          )
        )
      )
      event.preventDefault()
      event.stopPropagation()
    },
    [clearInfoCardPosition, screenToFlowPosition]
  )

  const handleInfoDragEnd = React.useCallback(
    (event: React.PointerEvent<HTMLButtonElement>) => {
      if (infoDragRef.current?.pointerId !== event.pointerId) return
      infoDragRef.current = null
      setInfoPosition((current) => clearInfoCardPosition(current))
      if (event.currentTarget.hasPointerCapture(event.pointerId)) {
        event.currentTarget.releasePointerCapture(event.pointerId)
      }
      event.stopPropagation()
    },
    [clearInfoCardPosition]
  )

  const handleInfoDragKeyDown = React.useCallback(
    (event: React.KeyboardEvent<HTMLButtonElement>) => {
      const distance = event.shiftKey ? 40 : 10
      const movement = {
        ArrowUp: [0, -distance],
        ArrowDown: [0, distance],
        ArrowLeft: [-distance, 0],
        ArrowRight: [distance, 0],
      }[event.key]
      if (!movement) return
      event.preventDefault()
      event.stopPropagation()
      moveInfoCardBy(movement[0], movement[1])
    },
    [moveInfoCardBy]
  )

  const toggleInfoOpen = React.useCallback(() => {
    setInfoOpen((current) => !current)
  }, [])

  const addNodeAtCenter = React.useCallback(
    (
      type: WorkflowNodeType,
      title?: string,
      config?: Record<string, unknown>
    ) => {
      const pane = flowPaneRef.current
      if (pane) {
        const rect = pane.getBoundingClientRect()
        addNode(
          type,
          screenToFlowPosition({
            x: rect.left + rect.width / 2,
            y: rect.top + rect.height / 2,
          }),
          title,
          config
        )
      } else {
        addNode(type, undefined, title, config)
      }
      onClosePalette()
    },
    [addNode, onClosePalette, screenToFlowPosition]
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
  }, [nodes, props.readOnly, t])

  const deleteNode = React.useCallback((nodeId: string) => {
    if (props.readOnly || ["start", "end"].some((type) => nodes.find((node) => node.id === nodeId)?.data.type === type)) return
    setNodes((current) => current.filter((node) => node.id !== nodeId))
    setEdges((current) => current.filter((edge) => edge.source !== nodeId && edge.target !== nodeId))
  }, [nodes, props.readOnly])

  const renameNode = React.useCallback((nodeId: string, title: string) => {
    if (props.readOnly) return
    updateNode(nodeId, (node) => ({ ...node, data: { ...node.data, title } }))
  }, [props.readOnly, updateNode])

  const renderedNodes = React.useMemo(
    () =>
      nodes.map((node) => ({
          ...node,
          type: "workflow",
          data: {
            ...node.data,
            runtimeStatus: props.runtimeStatuses[node.id],
            readOnly: props.readOnly,
            onCopy: copyNode,
            onDelete: deleteNode,
            onRename: renameNode,
            onUpdate: (nextData: WorkflowNodeData) => {
              if (node.data.type === "condition") {
                const nextHandles = new Set(
                  Array.isArray(nextData.config.branch)
                    ? nextData.config.branch.flatMap((branch) =>
                        branch &&
                        typeof branch === "object" &&
                        typeof (branch as Record<string, unknown>).id === "string"
                          ? [String((branch as Record<string, unknown>).id)]
                          : []
                      )
                    : []
                )
                setEdges((current) =>
                  current.filter(
                    (edge) =>
                      edge.source !== node.id ||
                      nextHandles.has(String(edge.sourceHandle ?? ""))
                  )
                )
              }
              setNodes((current) =>
                current.map((item) =>
                  item.id === node.id ? { ...item, data: nextData } : item
                )
              )
            },
            agent: props.agent,
            models: props.models,
            knowledgeBases: props.knowledgeBases,
            mcpServers: props.mcpServers,
            nodes,
            edges,
          },
      })),
    [copyNode, deleteNode, edges, nodes, props.agent, props.knowledgeBases, props.mcpServers, props.models, props.readOnly, props.runtimeStatuses, renameNode]
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

  return (
    <div className="flex min-h-0 flex-1 border-t bg-background">
      <div className="flex min-w-0 flex-1 flex-col lg:min-h-0">
        <div
          ref={flowPaneRef}
          className="relative h-[56vh] min-h-[440px] lg:h-full"
        >
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
            onNodeClick={() => {
              setSelectedEdgeId(null)
            }}
            onEdgeClick={(event, edge) => {
              event.stopPropagation()
              setSelectedEdgeId(edge.id)
            }}
            onPaneClick={() => {
              setSelectedEdgeId(null)
            }}
            onSelectionChange={({ edges: selectedEdges }) => {
              if (selectedEdges.length > 0) {
                setSelectedEdgeId(selectedEdges[0].id)
              }
            }}
            deleteKeyCode={props.readOnly ? null : ["Backspace", "Delete"]}
            onMoveEnd={(_event, nextViewport) => {
              const transient = transientViewportRef.current
              transientViewportRef.current = null
              if (
                transient &&
                Math.abs(transient.x - nextViewport.x) < 0.01 &&
                Math.abs(transient.y - nextViewport.y) < 0.01 &&
                Math.abs(transient.zoom - nextViewport.zoom) < 0.001
              ) {
                return
              }
              setViewport((current) =>
                persistedWorkflowViewport(current, nextViewport, props.readOnly)
              )
            }}
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
            {!props.readOnly ? (
              <ViewportPortal>
                <div
                  ref={infoCardRef}
                  style={{
                    transform: `translate(${infoPosition.x}px, ${infoPosition.y}px)`,
                  }}
                  className="nodrag nopan nowheel pointer-events-auto absolute z-10 w-[25rem] max-w-[calc(100vw-2rem)] select-text rounded-lg border bg-card/95 p-3 shadow-md backdrop-blur"
                >
                  <div className="flex items-center gap-2">
                    <button
                      type="button"
                      aria-label={t("拖动基本信息")}
                      className="flex min-w-0 flex-1 cursor-grab touch-none select-none items-center gap-2 rounded-md text-left outline-none active:cursor-grabbing focus-visible:ring-2 focus-visible:ring-ring"
                      onPointerDown={handleInfoDragStart}
                      onPointerMove={handleInfoDragMove}
                      onPointerUp={handleInfoDragEnd}
                      onPointerCancel={handleInfoDragEnd}
                      onLostPointerCapture={() => {
                        infoDragRef.current = null
                      }}
                      onKeyDown={handleInfoDragKeyDown}
                    >
                      <span className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-orange-500/10 text-orange-600 dark:text-orange-400">
                        <FileTextIcon className="size-4" />
                      </span>
                      <span className="min-w-0 flex-1 truncate text-sm font-semibold">
                        {t("基本信息")}
                      </span>
                    </button>
                    <IconButton
                      label={infoOpen ? t("收起") : t("展开")}
                      className="size-6"
                      aria-expanded={infoOpen}
                      onClick={toggleInfoOpen}
                    >
                      {infoOpen ? (
                        <ChevronUpIcon className="size-3.5" />
                      ) : (
                        <ChevronDownIcon className="size-3.5" />
                      )}
                    </IconButton>
                  </div>
                  {infoOpen ? (
                    <div className="mt-3 grid max-h-[70vh] gap-4 overflow-y-auto pr-1">
                      <label className="grid gap-1.5 text-xs font-medium" htmlFor="basic-info-name">
                        <span>{t("名称")}</span>
                        <Input
                          id="basic-info-name"
                          className="focus-visible:border-ring focus-visible:ring-0"
                          value={props.form.name}
                          maxLength={120}
                          onChange={(event) =>
                            props.setForm((current) => ({
                              ...current,
                              name: event.target.value,
                            }))
                          }
                        />
                        <span className="text-right text-[10px] text-muted-foreground">
                          {props.form.name.length} / 120
                        </span>
                      </label>
                      <label className="grid gap-1.5 text-xs font-medium" htmlFor="basic-info-description">
                        <span>{t("描述")}</span>
                        <textarea
                          id="basic-info-description"
                          rows={3}
                          maxLength={500}
                          value={props.form.description}
                          onChange={(event) =>
                            props.setForm((current) => ({
                              ...current,
                              description: event.target.value,
                            }))
                          }
                          className="resize-y rounded-md border bg-background px-2.5 py-2 text-sm leading-5 outline-none focus-visible:border-ring"
                        />
                        <span className="text-right text-[10px] text-muted-foreground">
                          {props.form.description.length} / 500
                        </span>
                      </label>
                      <InteractionConfigFields
                        appType="workflow"
                        value={props.form.interactionConfig}
                        onChange={(interactionConfig) =>
                          props.setForm((current) => ({
                            ...current,
                            interactionConfig,
                          }))
                        }
                        t={t}
                        idPrefix="basic-info"
                        readOnly={props.readOnly}
                        compact
                      />
                    </div>
                  ) : null}
                </div>
              </ViewportPortal>
            ) : null}
            <Background variant={BackgroundVariant.Dots} gap={18} size={1} />
            <Controls
              showInteractive={false}
              className="overflow-hidden rounded-md !border !border-border !shadow-sm [--xy-controls-button-background-color-hover:var(--muted)] [--xy-controls-button-background-color:var(--card)] [--xy-controls-button-border-color:var(--border)] [--xy-controls-button-color-hover:var(--foreground)] [--xy-controls-button-color:var(--card-foreground)]"
            />
            <MiniMap
              pannable
              zoomable
              className="hidden !border !bg-background sm:block"
              nodeColor="var(--muted-foreground)"
              maskColor="color-mix(in oklch, var(--background) 75%, transparent)"
            />
          </ReactFlow>
        </div>
      </div>
      <Dialog
        open={props.paletteOpen}
        onOpenChange={(open) => {
          if (!open) props.onClosePalette()
        }}
      >
        <DialogContent className="max-w-sm">
          <DialogHeader>
            <DialogTitle>{props.t("节点库")}</DialogTitle>
            <DialogDescription>
              {props.t("点击添加节点到画布中央")}
            </DialogDescription>
          </DialogHeader>
          <div className="grid grid-cols-2 gap-2">
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
                  disabled={disabled}
                  className="flex items-center gap-2 rounded-md border bg-background px-2.5 py-2 text-left text-xs font-medium shadow-xs transition-colors hover:bg-muted disabled:cursor-not-allowed disabled:opacity-40"
                  onClick={() => addNodeAtCenter(type)}
                >
                  <Icon className="size-4 shrink-0 text-muted-foreground" />
                  <span className="truncate">
                    {workflowNodeLabel(type, props.t)}
                  </span>
                  <PlusIcon className="ml-auto size-3.5 text-muted-foreground" />
                </button>
              )
            })}
            {WORKFLOW_NODE_PRESETS.map((preset) => {
              const Icon = NODE_ICONS[preset.type]
              return (
                <button
                  key={preset.id}
                  type="button"
                  disabled={props.readOnly}
                  className="flex items-center gap-2 rounded-md border bg-background px-2.5 py-2 text-left text-xs font-medium shadow-xs transition-colors hover:bg-muted disabled:cursor-not-allowed disabled:opacity-40"
                  onClick={() =>
                    addNodeAtCenter(
                      preset.type,
                      props.t(preset.label),
                      preset.config(props.t, startNodeId)
                    )
                  }
                >
                  <Icon className="size-4 shrink-0 text-muted-foreground" />
                  <span className="truncate">{props.t(preset.label)}</span>
                  <PlusIcon className="ml-auto size-3.5 text-muted-foreground" />
                </button>
              )
            })}
          </div>
        </DialogContent>
      </Dialog>
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
