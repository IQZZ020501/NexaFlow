"use client"

import * as React from "react"
import {
  Background,
  Controls,
  MarkerType,
  ReactFlow,
  type Edge,
  type Node,
} from "@xyflow/react"

import { useLanguage } from "@/contexts/language-provider"
import type {
  KnowledgeGraphClaim,
  KnowledgeGraphEntity,
} from "@/lib/api/knowledge"

const ENTITY_COLORS = [
  "#2563eb",
  "#7c3aed",
  "#0891b2",
  "#059669",
  "#d97706",
  "#dc2626",
] as const

function entityColor(entityType: string) {
  let hash = 0
  for (const character of entityType) {
    hash = (hash * 31 + character.charCodeAt(0)) >>> 0
  }
  return ENTITY_COLORS[hash % ENTITY_COLORS.length]
}

export function graphCanvasElements(
  entities: KnowledgeGraphEntity[],
  claims: KnowledgeGraphClaim[],
  orderedEntityIds: string[] = []
): { nodes: Node[]; edges: Edge[] } {
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
    return left.canonical_name.localeCompare(right.canonical_name)
  })
  const columns = orderedEntityIds.length
    ? Math.max(1, orderedEntityIds.length)
    : Math.max(1, Math.ceil(Math.sqrt(sorted.length)))
  const entityIds = new Set(sorted.map((entity) => entity.id))

  return {
    nodes: sorted.map((entity, index) => ({
      id: entity.id,
      position: {
        x: (index % columns) * 220,
        y: Math.floor(index / columns) * 130,
      },
      data: { label: `${entity.canonical_name}\n${entity.entity_type}` },
      style: {
        background: "var(--background)",
        borderColor: entityColor(entity.entity_type),
        borderWidth: 2,
        borderRadius: 10,
        width: 180,
        whiteSpace: "pre-line",
      },
    })),
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
        label: claim.predicate,
        data: { claimId: claim.id },
        markerEnd: { type: MarkerType.ArrowClosed },
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

  return (
    <div
      className="h-[32rem] min-h-80 w-full"
      data-testid="knowledge-graph-canvas"
    >
      <ReactFlow
        nodes={elements.nodes}
        edges={elements.edges}
        fitView
        minZoom={0.25}
        maxZoom={1.5}
        nodesDraggable={false}
        nodesConnectable={false}
        aria-label={t("知识关联画布")}
        onNodeClick={(_, node) => onEntitySelect(node.id)}
        onEdgeClick={(_, edge) =>
          onClaimSelect(String(edge.data?.claimId ?? edge.id))
        }
      >
        <Background />
        <Controls showInteractive={false} aria-label={t("知识关联画布控制")} />
      </ReactFlow>
    </div>
  )
}
