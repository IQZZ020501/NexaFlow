/* @jsxImportSource react */

import { afterEach, describe, expect, test } from "bun:test"
import { fireEvent, screen, waitFor } from "@testing-library/react"

import { KnowledgeGraph } from "@/components/knowledge/knowledge-graph"
import { graphCanvasElements } from "@/components/knowledge/knowledge-graph-canvas"
import { LanguageProvider } from "@/contexts/language-provider"
import type {
  KnowledgeGraphEntity,
  KnowledgeGraphQueryResult,
  KnowledgeGraphReviewItem,
  KnowledgeGraphSchema,
  KnowledgeGraphSettings,
  KnowledgeGraphStatus,
} from "@/lib/api/knowledge"
import type { RegisteredModel } from "@/lib/api/llm"
import {
  cleanup,
  jsonResponse,
  renderPage,
  resetFetch,
  withFetch,
} from "./helpers/dom"

const token = "token"
const workspaceId = "ws-1"
const knowledgeBaseId = "kb-1"
const requests: Array<{ url: string; method: string; body: unknown }> = []
const notifications: Array<[string, string]> = []
const errors: unknown[] = []

class TestResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
}

;(globalThis as unknown as { ResizeObserver: unknown }).ResizeObserver =
  TestResizeObserver

const llmModel: RegisteredModel = {
  id: "llm-1",
  workspace_id: workspaceId,
  name: "Graph Extractor",
  provider: "openai",
  provider_type: "openai",
  model_type: "LLM",
  model_name: "gpt-5-mini",
  status: "active",
  credential: {},
  api_base: "",
  has_api_key: true,
  api_key_hint: null,
  meta: {},
  created_by_user_id: "user-1",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
}

function entity(
  id: string,
  entityType: string,
  canonicalName: string,
  degree = 1
): KnowledgeGraphEntity {
  return {
    id,
    entity_type: entityType,
    canonical_name: canonicalName,
    aliases: [],
    properties: {},
    profile_markdown: `${canonicalName} profile`,
    component_id: null,
    degree,
  }
}

const bankEntities = [
  entity("account-a", "Account", "账户 A"),
  entity("phone-p", "Phone", "手机号 P", 2),
  entity("account-b", "Account", "账户 B", 2),
  entity("device-d", "Device", "设备 D", 2),
  entity("account-c", "Account", "账户 C", 2),
  entity("company-x", "Organization", "公司 X"),
]

const claimSpecs = [
  ["claim-1", "account-a", "uses_phone", "phone-p"],
  ["claim-2", "account-b", "uses_phone", "phone-p"],
  ["claim-3", "account-b", "logged_in_on", "device-d"],
  ["claim-4", "account-c", "logged_in_on", "device-d"],
  ["claim-5", "account-c", "legal_representative_of", "company-x"],
] as const

const bankClaims = claimSpecs.map(([id, subject, predicate, object]) => ({
  id,
  subject_entity_id: subject,
  predicate,
  object_entity_id: object,
  object_value: null,
  properties: {},
  quality_score: 1,
  support_count: 1,
  evidence_ids: [`evidence-${id}`],
}))

const bankResult: KnowledgeGraphQueryResult = {
  revision_id: "revision-1",
  operation: "path",
  resolved_entities: [bankEntities[0], bankEntities[5]],
  nodes: bankEntities,
  claims: bankClaims,
  paths: [
    {
      nodes: bankEntities,
      steps: [
        {
          claim_id: "claim-1",
          predicate: "uses_phone",
          source_entity_id: "account-a",
          target_entity_id: "phone-p",
          semantic_direction: "forward",
          quality_score: 1,
          support_count: 1,
          evidence_ids: ["evidence-claim-1"],
        },
        {
          claim_id: "claim-2",
          predicate: "uses_phone",
          source_entity_id: "phone-p",
          target_entity_id: "account-b",
          semantic_direction: "reverse",
          quality_score: 1,
          support_count: 1,
          evidence_ids: ["evidence-claim-2"],
        },
        {
          claim_id: "claim-3",
          predicate: "logged_in_on",
          source_entity_id: "account-b",
          target_entity_id: "device-d",
          semantic_direction: "forward",
          quality_score: 1,
          support_count: 1,
          evidence_ids: ["evidence-claim-3"],
        },
        {
          claim_id: "claim-4",
          predicate: "logged_in_on",
          source_entity_id: "device-d",
          target_entity_id: "account-c",
          semantic_direction: "reverse",
          quality_score: 1,
          support_count: 1,
          evidence_ids: ["evidence-claim-4"],
        },
        {
          claim_id: "claim-5",
          predicate: "legal_representative_of",
          source_entity_id: "account-c",
          target_entity_id: "company-x",
          semantic_direction: "forward",
          quality_score: 1,
          support_count: 1,
          evidence_ids: ["evidence-claim-5"],
        },
      ],
    },
  ],
  evidence: claimSpecs.map(([id, , predicate]) => ({
    id: `evidence-${id}`,
    claim_id: id,
    document_id: "doc-1",
    document_filename: "bank.jsonl",
    chunk_id: `chunk-${id}`,
    quote:
      predicate === "logged_in_on" && id === "claim-3"
        ? "账户 B 在设备 D 登录。"
        : `${predicate} evidence`,
    start_offset: 0,
    end_offset: 12,
    source_kind: "structured_import",
  })),
  visited_nodes: 6,
  truncated: false,
  limit_reason: null,
}

const graphSchema: KnowledgeGraphSchema = {
  id: "schema-1",
  version: 1,
  status: "active",
  schema_json: {
    entity_types: [
      { name: "Account" },
      { name: "Phone" },
      { name: "Device" },
      { name: "Organization" },
    ],
    relations: [
      { name: "uses_phone" },
      { name: "logged_in_on" },
      { name: "legal_representative_of" },
    ],
  },
  schema_hash: "schema-hash",
}

const graphSettings: KnowledgeGraphSettings = {
  enabled: true,
  extraction_model_id: llmModel.id,
  active_schema_id: graphSchema.id,
  active_revision_id: "revision-1",
}

const graphStatus: KnowledgeGraphStatus = {
  enabled: true,
  active_schema_id: graphSchema.id,
  active_revision_id: "revision-1",
  revision_no: 1,
  revision_status: "published",
  source_watermark: "watermark-1",
  stats: { claim_count: 5 },
  model_usage: {},
  pending_review_count: 0,
  last_error: null,
  published_at: "2026-01-01T00:00:00Z",
}

type GraphFetchOptions = {
  settings?: KnowledgeGraphSettings
  status?: KnowledgeGraphStatus
  schema?: KnowledgeGraphSchema | null
  entities?: KnowledgeGraphEntity[]
  reviews?: KnowledgeGraphReviewItem[]
  custom?: (
    url: string,
    method: string,
    body: unknown,
    init?: RequestInit
  ) => Response | Promise<Response> | undefined
}

function installGraphFetch(options: GraphFetchOptions = {}) {
  const settings = options.settings ?? graphSettings
  const status = options.status ?? graphStatus
  const schema = options.schema === undefined ? graphSchema : options.schema
  const entities = options.entities ?? bankEntities
  const reviews = options.reviews ?? []
  withFetch(async (url, init) => {
    const method = init?.method ?? "GET"
    const body =
      typeof init?.body === "string"
        ? JSON.parse(init.body)
        : (init?.body ?? null)
    requests.push({ url, method, body })
    const custom = await options.custom?.(url, method, body, init)
    if (custom) return custom
    if (url.endsWith("/graph/settings")) return jsonResponse(settings)
    if (url.endsWith("/graph/status")) return jsonResponse(status)
    if (url.endsWith("/graph/schema")) return jsonResponse(schema)
    if (url.includes("/graph/entities")) {
      return jsonResponse({
        items: entities,
        total: entities.length,
        limit: 20,
        offset: 0,
      })
    }
    if (url.includes("/graph/reviews")) {
      return jsonResponse({
        items: reviews,
        total: reviews.length,
        limit: 20,
        offset: 0,
      })
    }
    throw new Error(`Unexpected request: ${method} ${url}`)
  })
}

function renderGraph(canEdit = true, nextKnowledgeBaseId = knowledgeBaseId) {
  return renderPage(
    <KnowledgeGraph
      token={token}
      workspaceId={workspaceId}
      knowledgeBaseId={nextKnowledgeBaseId}
      canEdit={canEdit}
      llmModels={[llmModel]}
      notify={(kind, message) => notifications.push([kind, message])}
      reportError={(error) => errors.push(error)}
    />
  )
}

afterEach(() => {
  cleanup()
  resetFetch()
  requests.length = 0
  notifications.length = 0
  errors.length = 0
})

describe("knowledge graph workspace", () => {
  test("orders a path and keeps semantic claim direction", () => {
    const result = graphCanvasElements(
      [bankEntities[0], bankEntities[1]],
      [bankClaims[0]],
      ["account-a", "phone-p"]
    )
    expect(result.nodes.map((node) => node.id)).toEqual([
      "account-a",
      "phone-p",
    ])
    expect(result.edges[0]?.source).toBe("account-a")
    expect(result.edges[0]?.target).toBe("phone-p")
    expect(result.edges[0]?.label).toBe("uses_phone")
  })

  test("enables a disabled graph with the selected LLM", async () => {
    const disabledSettings = {
      ...graphSettings,
      enabled: false,
      extraction_model_id: null,
      active_schema_id: null,
      active_revision_id: null,
    }
    installGraphFetch({
      settings: disabledSettings,
      status: {
        ...graphStatus,
        enabled: false,
        active_schema_id: null,
        active_revision_id: null,
        revision_no: null,
        revision_status: null,
        stats: {},
        published_at: null,
      },
      schema: null,
      entities: [],
      custom: (url, method, body) => {
        if (url.endsWith("/graph/settings") && method === "PATCH") {
          expect(body).toEqual({
            enabled: true,
            extraction_model_id: llmModel.id,
          })
          return jsonResponse({ ...disabledSettings, enabled: true })
        }
      },
    })
    renderGraph()

    await screen.findByText("知识关联尚未启用")
    fireEvent.click(screen.getByRole("button", { name: "启用知识关联" }))
    await waitFor(() =>
      expect(
        requests.some(
          (request) =>
            request.method === "PATCH" &&
            request.url.endsWith("/graph/settings")
        )
      ).toBe(true)
    )
    expect(notifications).toContainEqual([
      "success",
      "知识关联已启用，正在自动抽取已有文件",
    ])
  })

  test("queries a bounded path and shows edge evidence", async () => {
    let pathBody: unknown
    installGraphFetch({
      custom: (url, method, body) => {
        if (url.endsWith("/graph/path") && method === "POST") {
          pathBody = body
          return jsonResponse(bankResult)
        }
      },
    })
    renderGraph()

    await screen.findByText("输入起点探索邻域，或同时输入终点查找路径")
    fireEvent.change(screen.getByPlaceholderText("输入实体名称"), {
      target: { value: "账户 A" },
    })
    fireEvent.change(screen.getByPlaceholderText("留空时查询邻域"), {
      target: { value: "公司 X" },
    })
    fireEvent.change(screen.getByLabelText("最大图谱跳数"), {
      target: { value: "5" },
    })
    fireEvent.click(screen.getByRole("checkbox", { name: "logged_in_on" }))
    fireEvent.click(screen.getByRole("button", { name: "查找路径" }))

    const edge = await screen.findByRole("button", {
      name: /账户 B → logged_in_on → 设备 D/,
    })
    fireEvent.click(edge)
    await screen.findByText("账户 B 在设备 D 登录。")
    expect(pathBody).toEqual({
      source_entity: "账户 A",
      target_entity: "公司 X",
      max_hops: 5,
      relation_filters: ["logged_in_on"],
    })
    expect(
      screen.getByText("bank.jsonl · 分段 chunk-claim-3 · 字符 0-12")
    ).toBeTruthy()
  })

  test("uses neighborhood mode and reports bounded query states", async () => {
    let neighborhoodBody: unknown
    let queryCount = 0
    installGraphFetch({
      status: {
        ...graphStatus,
        revision_status: "failed",
        last_error: "model unavailable",
      },
      custom: (url, method, body) => {
        if (url.endsWith("/graph/neighborhood") && method === "POST") {
          neighborhoodBody = body
          return jsonResponse({
            ...bankResult,
            operation: "ambiguous",
            paths: [],
            claims: [],
            truncated: true,
            limit_reason: "size",
          })
        }
        if (url.endsWith("/graph/path") && method === "POST") {
          queryCount += 1
          if (queryCount === 1) {
            return jsonResponse({ ...bankResult, paths: [], claims: [] })
          }
          return jsonResponse({ detail: "query failed" }, 500)
        }
      },
    })
    renderGraph()

    await screen.findByText("构建失败：model unavailable")
    fireEvent.change(screen.getByPlaceholderText("输入实体名称"), {
      target: { value: "账户 A" },
    })
    fireEvent.change(screen.getByLabelText("最大图谱跳数"), {
      target: { value: "3" },
    })
    fireEvent.click(screen.getByRole("button", { name: "查询邻域" }))
    await waitFor(() => expect(neighborhoodBody).toBeTruthy())
    await screen.findByText("实体匹配存在歧义")
    expect(screen.getByText(/结果已截断：达到大小限制/)).toBeTruthy()
    expect(neighborhoodBody).toEqual({
      entity: "账户 A",
      max_hops: 3,
      relation_filters: [],
    })

    fireEvent.change(screen.getByPlaceholderText("留空时查询邻域"), {
      target: { value: "公司 X" },
    })
    fireEvent.click(screen.getByRole("button", { name: "查找路径" }))
    await screen.findByText("未找到路径")
    fireEvent.change(screen.getByPlaceholderText("输入实体名称"), {
      target: { value: "账户 B" },
    })
    fireEvent.click(screen.getByRole("button", { name: "查找路径" }))
    await screen.findByText("query failed")
    expect(errors.length).toBe(1)
  })

  test("keeps reviews and settings read-only for view permission", async () => {
    installGraphFetch({
      reviews: [
        {
          id: "review-1",
          kind: "implicit_relation",
          payload: { claim_id: "claim-1" },
          status: "open",
          revision_id: "revision-1",
          created_at: "2026-01-01T00:00:00Z",
        },
      ],
    })
    renderGraph(false)

    fireEvent.click(await screen.findByRole("tab", { name: /审核/ }))
    await screen.findByText("只读审核详情")
    expect(screen.queryByRole("button", { name: "批准关系" })).toBeNull()
    expect(screen.queryByRole("button", { name: "拒绝关系" })).toBeNull()
    fireEvent.click(screen.getByRole("tab", { name: "设置" }))
    expect(screen.queryByRole("button", { name: "保存图谱设置" })).toBeNull()
    expect(
      screen.queryByRole("button", { name: "重新抽取全部文件" })
    ).toBeNull()
    expect(screen.queryByRole("button", { name: "导入结构化记录" })).toBeNull()
  })

  test("submits approve and reject review decisions", async () => {
    const review: KnowledgeGraphReviewItem = {
      id: "review-claim",
      kind: "implicit_relation",
      payload: { claim_id: "claim-1" },
      status: "open",
      revision_id: "revision-1",
      created_at: "2026-01-01T00:00:00Z",
    }
    for (const [button, action] of [
      ["批准关系", "approve_claim"],
      ["拒绝关系", "reject_claim"],
    ] as const) {
      installGraphFetch({
        reviews: [review],
        custom: (url, method, body) => {
          if (url.endsWith("/reviews/review-claim/resolve")) {
            expect(method).toBe("POST")
            expect(body).toEqual({ action, claim_ids: ["claim-1"] })
            return jsonResponse({ id: `task-${action}` }, 202)
          }
        },
      })
      renderGraph()
      fireEvent.click(await screen.findByRole("tab", { name: /审核/ }))
      fireEvent.click(screen.getByRole("button", { name: button }))
      await waitFor(() =>
        expect(
          requests.some((request) =>
            request.url.endsWith("/reviews/review-claim/resolve")
          )
        ).toBe(true)
      )
      cleanup()
      resetFetch()
      requests.length = 0
    }
  })

  test("submits merge and split review decisions", async () => {
    const review: KnowledgeGraphReviewItem = {
      id: "review-entity",
      kind: "ambiguous_entity",
      payload: {
        entity_id: "account-a",
        candidate_entity_ids: ["account-b"],
        mention_ids: ["mention-1"],
        claim_ids: ["claim-1"],
      },
      status: "open",
      revision_id: "revision-1",
      created_at: "2026-01-01T00:00:00Z",
    }
    let decision: unknown
    installGraphFetch({
      reviews: [review],
      custom: (url, _method, body) => {
        if (url.includes("/graph/entities?") && url.includes("query=")) {
          return jsonResponse({
            items: [bankEntities[2]],
            total: 1,
            limit: 20,
            offset: 0,
          })
        }
        if (url.endsWith("/reviews/review-entity/resolve")) {
          decision = body
          return jsonResponse({ id: "task-merge" }, 202)
        }
      },
    })
    renderGraph()
    fireEvent.click(await screen.findByRole("tab", { name: /审核/ }))
    const search = screen.getByLabelText("搜索合并目标")
    fireEvent.change(search, { target: { value: "账户 B" } })
    fireEvent.submit(search.closest("form")!)
    fireEvent.click(await screen.findByRole("radio", { name: "账户 B" }))
    fireEvent.click(screen.getByRole("button", { name: "确认合并" }))
    await waitFor(() =>
      expect(decision).toEqual({
        action: "merge_entities",
        target_entity_id: "account-b",
      })
    )

    cleanup()
    resetFetch()
    decision = null
    installGraphFetch({
      reviews: [review],
      custom: (url, _method, body) => {
        if (url.endsWith("/reviews/review-entity/resolve")) {
          decision = body
          return jsonResponse({ id: "task-split" }, 202)
        }
      },
    })
    renderGraph()
    fireEvent.click(await screen.findByRole("tab", { name: /审核/ }))
    fireEvent.change(screen.getByLabelText("新实体名称"), {
      target: { value: "账户 A-2" },
    })
    fireEvent.pointerDown(screen.getByRole("button", { name: "实体类型" }))
    fireEvent.click(await screen.findByText("Account"))
    fireEvent.click(screen.getByRole("checkbox", { name: /提及 · mention-1/ }))
    fireEvent.click(screen.getByRole("button", { name: "确认拆分" }))
    await waitFor(() =>
      expect(decision).toEqual({
        action: "split_entity",
        canonical_name: "账户 A-2",
        entity_type: "Account",
        mention_ids: ["mention-1"],
        claim_ids: [],
      })
    )
  })

  test("validates schema locally and refreshes after rebuild", async () => {
    let putCount = 0
    let statusCount = 0
    let rebuildStarted = false
    let importStarted = false
    let entityCount = 0
    installGraphFetch({
      custom: (url, method, body) => {
        if (url.endsWith("/graph/schema") && method === "PUT") {
          putCount += 1
          expect(body).toEqual(graphSchema.schema_json)
          return jsonResponse({ ...graphSchema, status: "draft" })
        }
        if (url.endsWith("/graph/rebuild") && method === "POST") {
          rebuildStarted = true
          return jsonResponse({ id: "task-rebuild" }, 202)
        }
        if (url.endsWith("/graph/import") && method === "POST") {
          expect(body).toBeInstanceOf(FormData)
          importStarted = true
          return jsonResponse({ id: "task-import" }, 202)
        }
        if (url.endsWith("/graph/status")) {
          statusCount += 1
          return jsonResponse(
            rebuildStarted
              ? {
                  ...graphStatus,
                  revision_no: 2,
                  active_revision_id: "revision-2",
                }
              : graphStatus
          )
        }
        if (url.includes("/graph/entities")) {
          entityCount += 1
          const items = rebuildStarted ? [bankEntities[5]] : bankEntities
          return jsonResponse({
            items,
            total: items.length,
            limit: 20,
            offset: 0,
          })
        }
      },
    })
    renderGraph()

    fireEvent.click(await screen.findByRole("tab", { name: "设置" }))
    fireEvent.click(screen.getByText("自定义 Schema（高级）"))
    const editor = screen.getByLabelText("Schema JSON")
    fireEvent.change(editor, { target: { value: "{" } })
    fireEvent.click(screen.getByRole("button", { name: "保存 Schema 草稿" }))
    expect(putCount).toBe(0)
    expect(notifications).toContainEqual(["error", "Schema JSON 无效"])

    fireEvent.change(editor, {
      target: { value: JSON.stringify(graphSchema.schema_json) },
    })
    fireEvent.click(screen.getByRole("button", { name: "保存 Schema 草稿" }))
    await waitFor(() => expect(putCount).toBe(1))
    fireEvent.click(screen.getByRole("button", { name: "重新抽取全部文件" }))
    await waitFor(() => expect(rebuildStarted).toBe(true))
    await waitFor(() => expect(screen.getByText("#2 · 已发布")).toBeTruthy(), {
      timeout: 4500,
    })
    expect(statusCount).toBeGreaterThanOrEqual(2)
    expect(entityCount).toBeGreaterThanOrEqual(2)

    const file = new File(["{}"], "graph.json", {
      type: "application/json",
    })
    fireEvent.change(screen.getByLabelText("选择图谱导入文件"), {
      target: { files: [file] },
    })
    fireEvent.click(screen.getByRole("button", { name: "导入结构化记录" }))
    await waitFor(() => expect(importStarted).toBe(true))
  })

  test("searches entities and opens the selected entity detail", async () => {
    installGraphFetch({
      entities: [],
      custom: (url) => {
        if (url.includes("/graph/entities?") && url.includes("query=")) {
          return jsonResponse({
            items: [bankEntities[0]],
            total: 1,
            limit: 20,
            offset: 0,
          })
        }
        if (url.endsWith("/graph/entities/account-a")) {
          return jsonResponse({
            ...bankEntities[0],
            aliases: ["账号甲"],
            claims: [],
            evidence: [],
          })
        }
      },
    })
    renderGraph()

    await screen.findByText("暂无实体")
    const search = screen.getByLabelText("实体搜索")
    fireEvent.change(search, { target: { value: "账户" } })
    fireEvent.submit(search.closest("form")!)
    fireEvent.click(await screen.findByRole("button", { name: /账户 A/ }))

    await waitFor(() =>
      expect(
        requests.some((request) =>
          request.url.endsWith("/graph/entities/account-a")
        )
      ).toBe(true)
    )
    expect(errors).toEqual([])
  })

  test("aborts stale initial requests when the knowledge base changes", async () => {
    const pending: Array<(response: Response) => void> = []
    let staleSignal: AbortSignal | undefined
    withFetch((url, init) => {
      if (url.includes("/kb-old/")) {
        staleSignal = init?.signal ?? undefined
        return new Promise<Response>((resolve) => pending.push(resolve))
      }
      if (url.endsWith("/graph/settings")) return jsonResponse(graphSettings)
      if (url.endsWith("/graph/status")) return jsonResponse(graphStatus)
      if (url.endsWith("/graph/schema")) return jsonResponse(graphSchema)
      if (url.includes("/graph/entities")) {
        return jsonResponse({
          items: [bankEntities[5]],
          total: 1,
          limit: 20,
          offset: 0,
        })
      }
      if (url.includes("/graph/reviews")) {
        return jsonResponse({ items: [], total: 0, limit: 20, offset: 0 })
      }
      throw new Error(`Unexpected request: ${url}`)
    })
    const rendered = renderGraph(true, "kb-old")
    rendered.rerender(
      <LanguageProvider defaultLanguage="zh-Hans">
        <KnowledgeGraph
          token={token}
          workspaceId={workspaceId}
          knowledgeBaseId="kb-new"
          canEdit
          llmModels={[llmModel]}
          notify={(kind, message) => notifications.push([kind, message])}
          reportError={(error) => errors.push(error)}
        />
      </LanguageProvider>
    )

    await screen.findByText("公司 X")
    expect(staleSignal?.aborted).toBe(true)
    for (const resolve of pending) resolve(jsonResponse({}))
    await Promise.resolve()
    expect(screen.getByText("公司 X")).toBeTruthy()
    expect(errors).toEqual([])
  })
})
