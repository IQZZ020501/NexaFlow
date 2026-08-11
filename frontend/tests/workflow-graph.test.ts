import { describe, expect, test } from "bun:test"

import {
  createWorkflowEdge,
  defaultNodeConfig,
  initialWorkflowInputs,
  removeWorkflowNode,
  serializeWorkflowGraph,
  workflowGraphSignature,
} from "../lib/workflows/graph"

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
})
