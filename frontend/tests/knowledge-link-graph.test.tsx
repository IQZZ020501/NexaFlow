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
      entity_type: "Document",
      properties: { document_id: "doc-a" },
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
      entity_type: "Document",
      properties: { document_id: "doc-b" },
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
      entity_type: null,
      properties: {},
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
      entity_type: "Document",
      properties: { document_id: "orphan" },
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
      predicate: "references",
      source_kind: "document_reference",
      quality_score: 1,
      support_count: 1,
      evidence_ids: ["evidence-a-b"],
    },
    {
      id: "b-missing",
      source: "doc-b",
      target: "missing",
      target_label: "missing.md",
      target_sections: [],
      resolved: false,
      count: 1,
      predicate: null,
      source_kind: null,
      quality_score: null,
      support_count: 0,
      evidence_ids: [],
    },
  ],
  document_count: 3,
  entity_count: 3,
  unresolved_count: 1,
  edge_count: 2,
  graph_revision_id: null,
  source: "legacy_references",
  truncated: false,
}

const disabledGraphSettings = {
  enabled: false,
  extraction_model_id: null,
  active_schema_id: null,
  active_revision_id: null,
}

const idleGraphStatus = {
  enabled: false,
  active_schema_id: null,
  active_revision_id: null,
  revision_no: null,
  revision_status: null,
  source_watermark: null,
  stats: {},
  model_usage: {},
  pending_review_count: 0,
  last_error: null,
  published_at: null,
  build_task_id: null,
  build_task_status: null,
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
      if (url.endsWith("/graph/links")) return jsonResponse(graph)
      if (url.endsWith("/graph/settings"))
        return jsonResponse(disabledGraphSettings)
      if (url.endsWith("/graph/status")) return jsonResponse(idleGraphStatus)
      throw new Error(`Unexpected request: ${url}`)
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

  test("enables Evidence Graph construction from the Obsidian shell", async () => {
    let enabled = false
    const notifications: Array<[string, string]> = []
    withFetch((url, init) => {
      const method = init?.method ?? "GET"
      if (url.endsWith("/graph/links")) return jsonResponse(graph)
      if (url.endsWith("/graph/settings") && method === "PATCH") {
        enabled = true
        expect(JSON.parse(String(init?.body))).toEqual({ enabled: true })
        return jsonResponse({ ...disabledGraphSettings, enabled: true })
      }
      if (url.endsWith("/graph/settings")) {
        return jsonResponse({ ...disabledGraphSettings, enabled })
      }
      if (url.endsWith("/graph/status")) {
        return jsonResponse({
          ...idleGraphStatus,
          enabled,
          build_task_id: enabled ? "graph-task" : null,
          build_task_status: enabled ? "queued" : null,
        })
      }
      throw new Error(`Unexpected request: ${url}`)
    })
    renderPage(
      <KnowledgeLinkGraph
        token="token"
        workspaceId="ws-1"
        knowledgeBaseId="kb-1"
        canEdit
        notify={(kind, message) => notifications.push([kind, message])}
        reportError={() => undefined}
      />
    )

    fireEvent.click(await screen.findByRole("button", { name: "启用知识关联" }))
    await waitFor(() => expect(enabled).toBe(true))
    expect(notifications).toContainEqual([
      "success",
      "知识关联已启用，正在自动抽取已有文件",
    ])
    expect(
      await screen.findByText(
        "正在自动抽取已有文件；完成后将在这里显示实体关系图"
      )
    ).toBeTruthy()
  })

  test("rebuilds the published Evidence Graph without replacing the Pixi shell", async () => {
    let rebuildCalls = 0
    const evidenceGraph = {
      ...graph,
      graph_revision_id: "graph-revision-2",
      source: "evidence_graph" as const,
      unresolved_count: 0,
    }
    withFetch((url, init) => {
      const method = init?.method ?? "GET"
      if (url.endsWith("/graph/links")) return jsonResponse(evidenceGraph)
      if (url.endsWith("/graph/settings")) {
        return jsonResponse({
          ...disabledGraphSettings,
          enabled: true,
          active_revision_id: "graph-revision-2",
        })
      }
      if (url.endsWith("/graph/status")) {
        return jsonResponse({
          ...idleGraphStatus,
          enabled: true,
          active_revision_id: "graph-revision-2",
          revision_no: 2,
          revision_status: "published",
        })
      }
      if (url.endsWith("/graph/rebuild") && method === "POST") {
        rebuildCalls += 1
        return jsonResponse({ id: "graph-rebuild-task" }, 202)
      }
      throw new Error(`Unexpected request: ${url}`)
    })
    renderPage(
      <KnowledgeLinkGraph
        token="token"
        workspaceId="ws-1"
        knowledgeBaseId="kb-1"
        canEdit
        reportError={() => undefined}
      />
    )

    expect(
      await screen.findByText("关系图谱与检索共享同一份已发布证据图谱")
    ).toBeTruthy()
    expect(screen.getByTestId("knowledge-graph-canvas")).toBeTruthy()
    fireEvent.click(screen.getByRole("button", { name: "重新抽取全部文件" }))
    await waitFor(() => expect(rebuildCalls).toBe(1))
  })
})
