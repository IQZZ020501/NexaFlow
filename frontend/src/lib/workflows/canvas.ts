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

/**
 * Computes a canvas position after applying pointer movement from the drag start.
 *
 * @param position - The position before dragging
 * @param dragStart - The pointer position when dragging began
 * @param pointer - The current pointer position
 * @returns The updated canvas position
 */
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

/**
 * Finds a position that avoids overlapping canvas obstacles.
 *
 * @param position - The proposed canvas position.
 * @param size - The dimensions of the item being positioned.
 * @param obstacles - Rectangles that the item must avoid.
 * @param gap - Minimum spacing required between the item and each obstacle.
 * @returns The proposed position when it is clear, or the closest available non-overlapping position; the proposed position if no alternative is available.
 */
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

/**
 * Positions a canvas item immediately to the left of an anchor rectangle.
 *
 * @param anchor - The rectangle that determines the item's vertical position.
 * @param size - The dimensions of the item to position.
 * @param gap - The space to leave between the item and the anchor.
 * @returns The item's position to the left of the anchor.
 */
export function canvasPositionLeftOf(
  anchor: CanvasRect,
  size: CanvasSize,
  gap = CANVAS_CARD_GAP
) {
  return { x: anchor.x - size.width - gap, y: anchor.y }
}

/**
 * Adjusts the viewport so a canvas X coordinate remains within the specified left padding.
 *
 * @param viewport - The current workflow viewport
 * @param x - The canvas X coordinate to include
 * @param padding - The minimum screen-space distance from the left edge
 * @returns The adjusted viewport
 */
export function viewportIncludingCanvasX(
  viewport: WorkflowGraph["viewport"],
  x: number,
  padding = 16
) {
  const screenX = x * viewport.zoom + viewport.x
  if (screenX >= padding) return viewport
  return { ...viewport, x: viewport.x + padding - screenX }
}

/**
 * Adjusts the viewport so a canvas Y coordinate appears at or below the top padding.
 *
 * @param y - The canvas Y coordinate to bring into view
 * @param padding - The minimum screen-space distance from the top edge
 * @returns The adjusted viewport
 */
export function viewportIncludingCanvasY(
  viewport: WorkflowGraph["viewport"],
  y: number,
  padding = 16
) {
  const screenY = y * viewport.zoom + viewport.y
  if (screenY >= padding) return viewport
  return { ...viewport, y: viewport.y + padding - screenY }
}

/**
 * Converts workflow nodes into canvas rectangles using their positions and available dimensions.
 *
 * @param nodes - The workflow nodes to convert
 * @returns A canvas rectangle for each workflow node
 */
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

/**
 * Applies workflow node changes, limiting read-only updates to dimensions and selection.
 *
 * @param readOnly - Whether to restrict changes to dimensions and selection updates.
 * @returns The workflow nodes after applying the permitted changes.
 */
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

/**
 * Applies workflow edge changes, limiting read-only updates to edge selection changes.
 *
 * @param readOnly - Whether to restrict changes to selection updates
 * @returns The updated workflow edges
 */
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

/**
 * Selects the viewport state to persist based on the workflow's editing mode.
 *
 * @param current - The currently persisted viewport
 * @param next - The proposed viewport
 * @param readOnly - Whether the workflow is read-only
 * @returns The current viewport when read-only, otherwise the proposed viewport
 */
export function persistedWorkflowViewport(
  current: WorkflowGraph["viewport"],
  next: WorkflowGraph["viewport"],
  readOnly: boolean
) {
  return readOnly ? current : next
}
