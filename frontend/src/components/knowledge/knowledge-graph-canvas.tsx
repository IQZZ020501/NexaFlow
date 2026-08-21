"use client"

import * as React from "react"
import {
  Controls,
  Handle,
  Position,
  ReactFlow,
  type Edge,
  type Node,
  type NodeProps,
  type ReactFlowInstance,
  useNodesState,
} from "@xyflow/react"

import { useLanguage } from "@/contexts/language-provider"
import type {
  KnowledgeGraphClaim,
  KnowledgeGraphEntity,
} from "@/lib/api/knowledge"

const GOLDEN_ANGLE = Math.PI * (3 - Math.sqrt(5))
const FIT_VIEW_OPTIONS = { padding: 0.08, maxZoom: 1.2 }

type EntityNodeData = {
  label: string
  entityType: string
  size: number
}

type EntityNode = Node<EntityNodeData, "entity">

function KnowledgeEntityNode({ data, selected }: NodeProps<EntityNode>) {
  return (
    <div className="relative flex h-14 w-44 flex-col items-center text-center">
      <Handle
        type="target"
        position={Position.Top}
        className="!pointer-events-none !size-1 !border-0 !bg-transparent !opacity-0"
        style={{ left: "50%", top: data.size / 2 }}
      />
      <Handle
        type="source"
        position={Position.Top}
        className="!pointer-events-none !size-1 !border-0 !bg-transparent !opacity-0"
        style={{ left: "50%", top: data.size / 2 }}
      />
      <span
        className="block shrink-0 rounded-full shadow-sm"
        style={{
          width: data.size,
          height: data.size,
          backgroundColor: selected
            ? "var(--primary)"
            : "var(--muted-foreground)",
          boxShadow: selected
            ? "0 0 0 4px color-mix(in srgb, var(--primary) 25%, transparent)"
            : undefined,
        }}
      />
      <span
        className="mt-1 max-w-44 truncate text-xs font-medium text-foreground"
        title={`${data.label} · ${data.entityType}`}
      >
        {data.label}
      </span>
    </div>
  )
}

const nodeTypes = { entity: KnowledgeEntityNode }

function fitMeasuredNodes(instance: ReactFlowInstance<EntityNode, Edge>) {
  requestAnimationFrame(() =>
    requestAnimationFrame(() => void instance.fitView(FIT_VIEW_OPTIONS))
  )
}

function forceDirectedPositions(
  entities: KnowledgeGraphEntity[],
  claims: KnowledgeGraphClaim[]
) {
  const indexById = new Map(entities.map((entity, index) => [entity.id, index]))
  const points = entities.map((_, index) => {
    const radius = index === 0 ? 0 : 72 * Math.sqrt(index)
    const angle = index * GOLDEN_ANGLE
    return {
      x: Math.cos(angle) * radius,
      y: Math.sin(angle) * radius,
      vx: 0,
      vy: 0,
    }
  })
  const links = claims.flatMap((claim) => {
    const source = indexById.get(claim.subject_entity_id)
    const target = claim.object_entity_id
      ? indexById.get(claim.object_entity_id)
      : undefined
    return source === undefined || target === undefined
      ? []
      : [[source, target]]
  })
  // ponytail: O(n²) repulsion is bounded by the 500-node API cap; use Barnes-Hut if that cap grows.
  const iterations = Math.max(
    24,
    Math.min(72, Math.floor(9_000 / Math.max(entities.length, 1)))
  )
  for (let iteration = 0; iteration < iterations; iteration += 1) {
    const alpha = 1 - iteration / iterations
    const forces = points.map(() => ({ x: 0, y: 0 }))
    for (let left = 0; left < points.length; left += 1) {
      for (let right = left + 1; right < points.length; right += 1) {
        let dx = points[right].x - points[left].x
        let dy = points[right].y - points[left].y
        if (dx === 0 && dy === 0) dx = 0.01 * (right - left)
        const distanceSquared = Math.max(64, dx * dx + dy * dy)
        const distance = Math.sqrt(distanceSquared)
        const force = (2_400 * alpha) / distanceSquared
        dx = (dx / distance) * force
        dy = (dy / distance) * force
        forces[left].x -= dx
        forces[left].y -= dy
        forces[right].x += dx
        forces[right].y += dy
      }
    }
    for (const [source, target] of links) {
      const dx = points[target].x - points[source].x
      const dy = points[target].y - points[source].y
      const distance = Math.max(1, Math.sqrt(dx * dx + dy * dy))
      const force = (distance - 180) * 0.012 * alpha
      const x = (dx / distance) * force
      const y = (dy / distance) * force
      forces[source].x += x
      forces[source].y += y
      forces[target].x -= x
      forces[target].y -= y
    }
    for (let index = 0; index < points.length; index += 1) {
      const point = points[index]
      point.vx = (point.vx + forces[index].x - point.x * 0.002 * alpha) * 0.72
      point.vy = (point.vy + forces[index].y - point.y * 0.002 * alpha) * 0.72
      point.x += point.vx
      point.y += point.vy
    }
  }
  return new Map(
    entities.map((entity, index) => [
      entity.id,
      { x: points[index].x * 1.35, y: points[index].y },
    ])
  )
}

export function graphCanvasElements(
  entities: KnowledgeGraphEntity[],
  claims: KnowledgeGraphClaim[],
  orderedEntityIds: string[] = []
): { nodes: EntityNode[]; edges: Edge[] } {
  const order = new Map(orderedEntityIds.map((id, index) => [id, index]))
  const sorted = [...entities].sort((left, right) => {
    const leftOrder = order.get(left.id)
    const rightOrder = order.get(right.id)
    if (leftOrder !== undefined || rightOrder !== undefined) {
      return (
        (leftOrder ?? Number.MAX_SAFE_INTEGER) -
        (rightOrder ?? Number.MAX_SAFE_INTEGER)
      )
    }
    return (
      right.degree - left.degree ||
      left.canonical_name.localeCompare(right.canonical_name)
    )
  })
  const entityIds = new Set(sorted.map((entity) => entity.id))
  const pathLayout = orderedEntityIds.length > 0
  const positions = pathLayout
    ? new Map(
        sorted.map((entity, index) => [entity.id, { x: index * 220, y: 0 }])
      )
    : forceDirectedPositions(sorted, claims)

  return {
    nodes: sorted.map((entity) => {
      return {
        id: entity.id,
        type: "entity",
        position: positions.get(entity.id) ?? { x: 0, y: 0 },
        data: {
          label: entity.canonical_name,
          entityType: entity.entity_type,
          size: Math.min(18, 9 + Math.sqrt(Math.max(0, entity.degree)) * 2),
        },
        ariaLabel: `${entity.canonical_name}, ${entity.entity_type}`,
      }
    }),
    edges: claims
      .filter(
        (claim) =>
          claim.object_entity_id &&
          entityIds.has(claim.subject_entity_id) &&
          entityIds.has(claim.object_entity_id)
      )
      .map((claim) => ({
        id: claim.id,
        source: claim.subject_entity_id,
        target: claim.object_entity_id as string,
        data: { claimId: claim.id, predicate: claim.predicate },
        ariaLabel: claim.predicate,
        style: {
          stroke: "var(--muted-foreground)",
          strokeOpacity: 0.38,
          strokeWidth: 1,
        },
      })),
  }
}

export function KnowledgeGraphCanvas({
  entities,
  claims,
  orderedEntityIds = [],
  onEntitySelect,
  onClaimSelect,
}: {
  entities: KnowledgeGraphEntity[]
  claims: KnowledgeGraphClaim[]
  orderedEntityIds?: string[]
  onEntitySelect: (entityId: string) => void
  onClaimSelect: (claimId: string) => void
}) {
  const { t } = useLanguage()
  const elements = React.useMemo(
    () => graphCanvasElements(entities, claims, orderedEntityIds),
    [claims, entities, orderedEntityIds]
  )
  const [nodes, setNodes, onNodesChange] = useNodesState<EntityNode>(
    elements.nodes
  )

  React.useEffect(() => setNodes(elements.nodes), [elements.nodes, setNodes])

  return (
    <div
      className="relative h-[calc(100vh-18rem)] min-h-[38rem] w-full bg-muted/20"
      data-testid="knowledge-graph-canvas"
    >
      <div className="pointer-events-none absolute top-3 left-3 z-10 flex gap-3 rounded-md border bg-background/85 px-3 py-2 text-xs text-muted-foreground backdrop-blur">
        <span>
          {t("实体数")} {entities.length}
        </span>
        <span>
          {t("关系数")} {claims.length}
        </span>
      </div>
      <ReactFlow
        nodes={nodes}
        edges={elements.edges}
        nodeTypes={nodeTypes}
        fitView
        fitViewOptions={FIT_VIEW_OPTIONS}
        minZoom={0.08}
        maxZoom={2}
        nodesDraggable
        nodesConnectable={false}
        onlyRenderVisibleElements
        proOptions={{ hideAttribution: true }}
        aria-label={t("知识关联画布")}
        onInit={fitMeasuredNodes}
        onNodesChange={onNodesChange}
        onNodeClick={(_, node) => onEntitySelect(node.id)}
        onEdgeClick={(_, edge) =>
          onClaimSelect(String(edge.data?.claimId ?? edge.id))
        }
      >
        <Controls
          showInteractive={false}
          className="!border-border !bg-background [&>button]:!border-border [&>button]:!bg-background [&>button]:!fill-foreground [&>button:hover]:!bg-muted"
          aria-label={t("知识关联画布控制")}
        />
      </ReactFlow>
    </div>
  )
}
