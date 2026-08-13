import {
  applyEdgeChanges,
  applyNodeChanges,
  type EdgeChange,
  type NodeChange,
} from "@xyflow/react"

import type { WorkflowEdge, WorkflowGraph, WorkflowNode } from "@/lib/api/workflows"

type CanvasPosition = { x: number; y: number }
type CanvasSize = { width: number; height: number }
export type CanvasRect = CanvasPosition & CanvasSize
const CANVAS_CARD_GAP = 24

export function draggedCanvasPosition(
  position: CanvasPosition,
  dragStart: CanvasPosition,
  pointer: CanvasPosition
) {
  return {
    x: position.x + pointer.x - dragStart.x,
    y: position.y + pointer.y - dragStart.y,
  }
}

export function nonOverlappingCanvasPosition(
  position: CanvasPosition,
  size: CanvasSize,
  obstacles: CanvasRect[],
  gap = CANVAS_CARD_GAP
) {
  const overlaps = (candidate: CanvasPosition) =>
    obstacles.some(
      (obstacle) =>
        candidate.x < obstacle.x + obstacle.width + gap &&
        candidate.x + size.width + gap > obstacle.x &&
        candidate.y < obstacle.y + obstacle.height + gap &&
        candidate.y + size.height + gap > obstacle.y
    )

  if (!overlaps(position)) return position

  const candidates = obstacles.flatMap((obstacle) => [
    { x: obstacle.x - size.width - gap, y: position.y },
    { x: obstacle.x + obstacle.width + gap, y: position.y },
    { x: position.x, y: obstacle.y - size.height - gap },
    { x: position.x, y: obstacle.y + obstacle.height + gap },
  ])
  return candidates
    .filter((candidate) => !overlaps(candidate))
    .sort(
      (left, right) =>
        Math.abs(left.x - position.x) +
        Math.abs(left.y - position.y) * 2 -
        (Math.abs(right.x - position.x) +
          Math.abs(right.y - position.y) * 2)
    )[0] ?? position
}

export function canvasPositionLeftOf(
  anchor: CanvasRect,
  size: CanvasSize,
  gap = CANVAS_CARD_GAP
) {
  return { x: anchor.x - size.width - gap, y: anchor.y }
}

export function viewportIncludingCanvasX(
  viewport: WorkflowGraph["viewport"],
  x: number,
  padding = 16
) {
  const screenX = x * viewport.zoom + viewport.x
  if (screenX >= padding) return viewport
  return { ...viewport, x: viewport.x + padding - screenX }
}

export function workflowNodeRects(nodes: WorkflowNode[]): CanvasRect[] {
  return nodes.map((node) => {
    const runtimeNode = node as WorkflowNode & {
      measured?: { width?: number; height?: number }
      width?: number
      height?: number
    }
    return {
      x: node.position.x,
      y: node.position.y,
      width: runtimeNode.measured?.width ?? runtimeNode.width ?? 256,
      height: runtimeNode.measured?.height ?? runtimeNode.height ?? 96,
    }
  })
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
