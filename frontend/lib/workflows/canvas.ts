import {
  applyEdgeChanges,
  applyNodeChanges,
  type EdgeChange,
  type NodeChange,
} from "@xyflow/react"

import type { WorkflowEdge, WorkflowGraph, WorkflowNode } from "@/lib/api/workflows"

export function draggedCanvasPosition(
  position: { x: number; y: number },
  dragStart: { x: number; y: number },
  pointer: { x: number; y: number }
) {
  return {
    x: position.x + pointer.x - dragStart.x,
    y: position.y + pointer.y - dragStart.y,
  }
}

export function applyWorkflowNodeChanges(
  nodes: WorkflowNode[],
  changes: NodeChange[],
  readOnly: boolean
) {
  const allowed = readOnly
    ? changes.filter((change) => ["dimensions", "select"].includes(change.type))
    : changes
  return applyNodeChanges(allowed, nodes) as WorkflowNode[]
}

export function applyWorkflowEdgeChanges(
  edges: WorkflowEdge[],
  changes: EdgeChange[],
  readOnly: boolean
) {
  const allowed = readOnly
    ? changes.filter((change) => change.type === "select")
    : changes
  return applyEdgeChanges(allowed, edges) as WorkflowEdge[]
}

export function persistedWorkflowViewport(
  current: WorkflowGraph["viewport"],
  next: WorkflowGraph["viewport"],
  readOnly: boolean
) {
  return readOnly ? current : next
}
