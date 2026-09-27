/* @jsxImportSource react */

import { afterEach, describe, expect, test } from "bun:test"
import { fireEvent, screen, waitFor } from "@testing-library/react"

import {
  filterKnowledgeLinkGraph,
  KnowledgeLinkGraph,
} from "@/components/knowledge/knowledge-link-graph"
import type { KnowledgeLinkGraph as KnowledgeLinkGraphData } from "@/lib/api/knowledge"
import {
  cleanup,
  jsonResponse,
  mockNextNavigation,
  renderPage,
  resetFetch,
  withFetch,
} from "./helpers/dom"

const navigations: string[] = []
mockNextNavigation({ push: (href) => navigations.push(href) })

const graph: KnowledgeLinkGraphData = {
  revision: "revision-1",
  nodes: [
    {
      id: "doc-a",
      kind: "document",
      document_id: "doc-a",
      label: "a",
      filename: "a.md",
      content_type: "text/markdown",
      status: "indexed",
      incoming: 0,
      outgoing: 2,
      degree: 2,
    },
    {
      id: "doc-b",
      kind: "document",
      document_id: "doc-b",
      label: "b",
      filename: "b.md",
      content_type: "text/markdown",
      status: "indexed",
      incoming: 2,
      outgoing: 1,
      degree: 3,
    },
    {
      id: "missing",
      kind: "unresolved",
      document_id: null,
      label: "missing",
      filename: "missing.md",
      content_type: null,
      status: null,
      incoming: 1,
      outgoing: 0,
      degree: 1,
    },
    {
      id: "orphan",
      kind: "document",
      document_id: "orphan",
      label: "orphan",
      filename: "orphan.md",
      content_type: "text/markdown",
      status: "indexed",
      incoming: 0,
      outgoing: 0,
      degree: 0,
    },
  ],
  edges: [
    {
      id: "a-b",
      source: "doc-a",
      target: "doc-b",
      target_label: "b.md",
      target_sections: [],
      resolved: true,
      count: 2,
    },
    {
      id: "b-missing",
      source: "doc-b",
      target: "missing",
      target_label: "missing.md",
      target_sections: [],
      resolved: false,
      count: 1,
    },
  ],
  document_count: 3,
  unresolved_count: 1,
  edge_count: 2,
  truncated: false,
}

afterEach(() => {
  cleanup()
  resetFetch()
  navigations.length = 0
})

describe("knowledge link graph", () => {
  test("traverses local incoming and outgoing links by depth", () => {
    const outgoing = filterKnowledgeLinkGraph(graph, {
      query: "",
      includeUnresolved: true,
      includeOrphans: true,
      rootId: "doc-a",
      depth: 1,
      direction: "outgoing",
    })
    expect(outgoing.nodes.map((node) => node.id)).toEqual(["doc-a", "doc-b"])
    expect(outgoing.edges.map((edge) => edge.id)).toEqual(["a-b"])

    const secondHop = filterKnowledgeLinkGraph(graph, {
      query: "",
      includeUnresolved: true,
      includeOrphans: true,
      rootId: "doc-a",
      depth: 2,
      direction: "outgoing",
    })
    expect(secondHop.nodes.map((node) => node.id)).toEqual([
      "doc-a",
      "doc-b",
      "missing",
    ])

    const incoming = filterKnowledgeLinkGraph(graph, {
      query: "",
      includeUnresolved: true,
      includeOrphans: true,
      rootId: "doc-b",
      depth: 1,
      direction: "incoming",
    })
    expect(incoming.nodes.map((node) => node.id)).toEqual(["doc-a", "doc-b"])
  })

  test("filters unresolved, orphan, and searched nodes", () => {
    const filtered = filterKnowledgeLinkGraph(graph, {
      query: "b.md",
      includeUnresolved: false,
      includeOrphans: false,
      rootId: null,
      depth: 2,
      direction: "both",
    })
    expect(filtered.nodes.map((node) => node.id)).toEqual(["doc-b"])
    expect(filtered.edges).toEqual([])
  })

  test("loads the link snapshot and opens a selected document", async () => {
    withFetch((url) => {
      expect(url.endsWith("/graph/links")).toBe(true)
      return jsonResponse(graph)
    })
    renderPage(
      <KnowledgeLinkGraph
        token="token"
        workspaceId="ws-1"
        knowledgeBaseId="kb-1"
        reportError={() => undefined}
      />
    )

    await screen.findByRole("heading", { name: "关系图谱" })
    expect(
      screen.getByText("基于 Markdown 显式链接生成，不使用 AI 或语义向量")
    ).toBeTruthy()
    fireEvent.click(screen.getByRole("button", { name: "选择节点 b.md" }))
    await waitFor(() => expect(screen.getByText("已解析文档节点")).toBeTruthy())
    fireEvent.click(screen.getByRole("button", { name: "打开文档" }))
    expect(navigations).toEqual(["/app/knowledge/kb-1/documents/doc-b"])
  })
})
