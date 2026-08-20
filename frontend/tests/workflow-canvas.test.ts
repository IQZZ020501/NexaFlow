/* @jsxImportSource react */
import { describe, expect, test } from "bun:test"

import type {
  WorkflowEdge,
  WorkflowGraph,
  WorkflowNode,
} from "@/lib/api/workflows"
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

function node(id: string, position = { x: 0, y: 0 }): WorkflowNode {
  return {
    id,
    type: "workflow",
    position,
    data: { type: "start", title: id, config: {} },
  }
}

function edge(id: string): WorkflowEdge {
  return { id, source: "a", target: "b" }
}

type ChangeableNode = WorkflowNode & {
  selected?: boolean
  measured?: { width: number; height: number }
}
type ChangeableEdge = WorkflowEdge & { selected?: boolean }

describe("workflow canvas", () => {
  test("applies pointer movement to a canvas position", () => {
    expect(
      draggedCanvasPosition(
        { x: 100, y: 50 },
        { x: 10, y: 10 },
        { x: 40, y: 60 }
      )
    ).toEqual({ x: 130, y: 100 })
  })

  test("places items to the left of an anchor with the card gap", () => {
    expect(
      canvasPositionLeftOf(
        { x: 300, y: 180, width: 256, height: 320 },
        { width: 200, height: 120 }
      )
    ).toEqual({ x: 76, y: 180 })
    expect(
      canvasPositionLeftOf(
        { x: 300, y: 180, width: 256, height: 320 },
        { width: 200, height: 120 },
        8
      )
    ).toEqual({ x: 92, y: 180 })
  })

  test("returns the proposed position when it does not overlap", () => {
    const position = { x: 0, y: 0 }
    expect(
      nonOverlappingCanvasPosition(
        position,
        { width: 200, height: 120 },
        [{ x: 400, y: 0, width: 256, height: 320 }]
      )
    ).toBe(position)
  })

  test("shifts overlapping positions to the nearest clear candidate", () => {
    const position = nonOverlappingCanvasPosition(
      { x: 16, y: 16 },
      { width: 400, height: 120 },
      [{ x: 80, y: 60, width: 256, height: 320 }]
    )
    // The candidate above the obstacle is closest to the proposed position
    // under the x + 2*y distance heuristic.
    expect(position).toEqual({ x: 16, y: -84 })
  })

  test("respects a custom gap when placing items", () => {
    expect(
      nonOverlappingCanvasPosition(
        { x: 0, y: 0 },
        { width: 100, height: 100 },
        [{ x: 0, y: 100, width: 100, height: 100 }],
        40
      )
    ).toEqual({ x: 0, y: -40 })
  })

  test("keeps canvas X coordinates within the left padding", () => {
    const viewport = { x: 100, y: 0, zoom: 1 }
    // screenX = 10 * 1 + 100 = 110 >= 16: unchanged.
    expect(viewportIncludingCanvasX(viewport, 10)).toBe(viewport)
    // screenX = -10 * 1 + 100 = 90 >= 16: unchanged.
    expect(viewportIncludingCanvasX(viewport, -10)).toBe(viewport)
    // screenX = -200 * 1 + 100 = -100 < 16: shifted right by 116.
    expect(viewportIncludingCanvasX(viewport, -200)).toEqual({
      x: 216,
      y: 0,
      zoom: 1,
    })
    // Custom padding: screenX = -100 + 100 = 0 < 50: shifted right by 50.
    expect(viewportIncludingCanvasX(viewport, -100, 50)).toEqual({
      x: 150,
      y: 0,
      zoom: 1,
    })
  })

  test("keeps canvas Y coordinates at or below the top padding", () => {
    const viewport = { x: 0, y: 80, zoom: 1 }
    // screenY = 100 * 1 + 80 = 180 >= 16: unchanged.
    expect(viewportIncludingCanvasY(viewport, 100)).toBe(viewport)
    // screenY = -200 + 80 = -120 < 16: shifted down by 136.
    expect(viewportIncludingCanvasY(viewport, -200)).toEqual({
      x: 0,
      y: 216,
      zoom: 1,
    })
    // Custom padding: screenY = -100 + 80 = -20 < 32: shifted down by 52.
    expect(viewportIncludingCanvasY(viewport, -100, 32)).toEqual({
      x: 0,
      y: 132,
      zoom: 1,
    })
  })

  test("derives canvas rects from measured and fallback dimensions", () => {
    const measured = {
      ...node("a"),
      measured: { width: 320, height: 200 },
    } as WorkflowNode
    const explicit = {
      ...node("b"),
      width: 240,
      height: 140,
    } as WorkflowNode
    const defaulted = node("c", { x: 10, y: 20 })

    expect(workflowNodeRects([measured, explicit, defaulted])).toEqual([
      { x: 0, y: 0, width: 320, height: 200 },
      { x: 0, y: 0, width: 240, height: 140 },
      { x: 10, y: 20, width: 256, height: 96 },
    ])
  })

  test("applies every node change when editable", () => {
    const nodes = [node("a"), node("b")]
    const updated = applyWorkflowNodeChanges(
      nodes,
      [
        { id: "a", type: "position", position: { x: 40, y: 50 } },
        { id: "b", type: "select", selected: true },
        { id: "a", type: "remove" },
      ],
      false
    )

    expect(updated.map(({ id }) => id)).toEqual(["b"])
    expect((updated[0] as ChangeableNode).selected).toBe(true)
  })

  test("restricts read-only node changes to dimensions and selection", () => {
    const nodes = [node("a"), node("b"), node("c")]
    const updated = applyWorkflowNodeChanges(
      nodes,
      [
        { id: "a", type: "position", position: { x: 999, y: 999 } },
        { id: "b", type: "select", selected: true },
        {
          id: "c",
          type: "dimensions",
          dimensions: { width: 300, height: 150 },
        },
        { id: "a", type: "remove" },
      ],
      true
    )

    expect(updated.map(({ id }) => id)).toEqual(["a", "b", "c"])
    expect(updated[0]?.position).toEqual({ x: 0, y: 0 })
    expect((updated[1] as ChangeableNode).selected).toBe(true)
    expect((updated[2] as ChangeableNode).measured).toEqual({
      width: 300,
      height: 150,
    })
  })

  test("applies every edge change when editable", () => {
    const edges = [edge("e1"), edge("e2")]
    const updated = applyWorkflowEdgeChanges(
      edges,
      [
        { id: "e1", type: "select", selected: true },
        { id: "e2", type: "remove" },
      ],
      false
    )

    expect(updated.map(({ id }) => id)).toEqual(["e1"])
    expect((updated[0] as ChangeableEdge).selected).toBe(true)
  })

  test("restricts read-only edge changes to selection", () => {
    const edges = [edge("e1"), edge("e2")]
    const updated = applyWorkflowEdgeChanges(
      edges,
      [
        { id: "e1", type: "select", selected: true },
        { id: "e2", type: "remove" },
      ],
      true
    )

    expect(updated.map(({ id }) => id)).toEqual(["e1", "e2"])
    expect((updated[0] as ChangeableEdge).selected).toBe(true)
  })

  test("persists the proposed viewport only when editable", () => {
    const current: WorkflowGraph["viewport"] = { x: 0, y: 0, zoom: 1 }
    const next: WorkflowGraph["viewport"] = { x: 100, y: 50, zoom: 0.5 }
    expect(persistedWorkflowViewport(current, next, true)).toBe(current)
    expect(persistedWorkflowViewport(current, next, false)).toBe(next)
  })
})
