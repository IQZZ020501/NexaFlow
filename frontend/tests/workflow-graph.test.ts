import { describe, expect, test } from "bun:test"

import {
  createWorkflowEdge,
  defaultNodeConfig,
  initialWorkflowInputs,
  removeWorkflowNode,
  selectWorkflowRunTarget,
  serializeWorkflowGraph,
  workflowGraphSignature,
} from "../lib/workflows/graph"
import {
  applyWorkflowEdgeChanges,
  applyWorkflowNodeChanges,
  persistedWorkflowViewport,
} from "../lib/workflows/canvas"

describe("workflow graph", () => {
  test("serializes only durable React Flow fields", () => {
    const graph = serializeWorkflowGraph(
      [
        {
          id: "start",
          type: "workflow",
          position: { x: 10, y: 20 },
          data: { type: "start", title: "Start", config: defaultNodeConfig("start") },
          selected: true,
        } as never,
      ],
      [
        {
          id: "edge-1",
          source: "start",
          target: "end",
          selected: true,
        } as never,
      ],
      { x: 1, y: 2, zoom: 1.25 }
    )

    expect(graph.nodes[0]).not.toHaveProperty("selected")
    expect(graph.edges[0]).not.toHaveProperty("selected")
    expect(graph.viewport.zoom).toBe(1.25)
  })

  test("treats null and omitted edge handles as the same durable graph", () => {
    const base = {
      nodes: [],
      viewport: { x: 0, y: 0, zoom: 1 },
    }
    expect(
      workflowGraphSignature({
        ...base,
        edges: [
          {
            id: "edge-1",
            source: "start",
            target: "end",
            sourceHandle: null,
            targetHandle: null,
          },
        ],
      })
    ).toBe(
      workflowGraphSignature({
        ...base,
        edges: [{ id: "edge-1", source: "start", target: "end" }],
      })
    )
  })

  test("removes connected edges with a node", () => {
    const edge = createWorkflowEdge("start", "value")
    const result = removeWorkflowNode(
      [
        { id: "start", data: { type: "start" } },
        { id: "value", data: { type: "variable" } },
      ] as never,
      [edge],
      "value"
    )
    expect(result.nodes).toHaveLength(1)
    expect(result.edges).toHaveLength(0)
  })

  test("builds debug inputs from the start node schema", () => {
    expect(
      initialWorkflowInputs({
        nodes: [
          {
            id: "start",
            type: "workflow",
            position: { x: 0, y: 0 },
            data: {
              type: "start",
              title: "Start",
              config: {
                inputs: [
                  { name: "query", type: "string", required: true },
                  { name: "limit", type: "number", default: 3 },
                ],
              },
            },
          },
        ],
        edges: [],
        viewport: { x: 0, y: 0, zoom: 1 },
      })
    ).toEqual({ query: "", limit: 3 })
  })

  test("keeps read-only canvas graph mutations out of the draft", () => {
    const nodes = [
      {
        id: "start",
        type: "workflow",
        position: { x: 0, y: 0 },
        data: { type: "start", title: "Start", config: {} },
      },
    ] as never
    const edges = [{ id: "edge-1", source: "start", target: "end" }]

    expect(
      applyWorkflowNodeChanges(nodes, [{ id: "start", type: "remove" }], true)
    ).toEqual(nodes)
    expect(
      applyWorkflowEdgeChanges(edges, [{ id: "edge-1", type: "remove" }], true)
    ).toEqual(edges)
    expect(
      persistedWorkflowViewport(
        { x: 0, y: 0, zoom: 1 },
        { x: 20, y: 30, zoom: 1.2 },
        true
      )
    ).toEqual({ x: 0, y: 0, zoom: 1 })
  })

  test("selects the latest published version for a read-only run", () => {
    const versionGraph = (x: number) => ({
      nodes: [],
      edges: [],
      viewport: { x, y: 0, zoom: 1 },
    })
    const target = selectWorkflowRunTarget(false, [
      { version_number: 1, graph: versionGraph(1) },
      { version_number: 3, graph: versionGraph(3) },
      { version_number: 2, graph: versionGraph(2) },
    ] as never)

    if (!target) throw new Error("expected a published run target")
    expect(target.source).toBe("published")
    expect(target.versionNumber).toBe(3)
    expect(target.graph).toEqual(versionGraph(3))
  })

  test("lets editors select a specific published version", () => {
    const published = {
      nodes: [],
      edges: [],
      viewport: { x: 4, y: 0, zoom: 1 },
    }
    const target = selectWorkflowRunTarget(true, [
      { version_number: 4, graph: published },
    ] as never, 4)

    expect(target).toEqual({
      source: "published",
      versionNumber: 4,
      graph: published,
    })
  })
})
