/* @jsxImportSource react */
import { afterEach, describe, expect, test } from "bun:test"
import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react"

import { KnowledgeEvaluation } from "@/components/knowledge/knowledge-evaluation"
import type { KnowledgeDocument } from "@/lib/api/knowledge"
import {
  jsonResponse,
  renderPage,
  resetFetch,
  withFetch,
} from "./helpers/dom"

const document: KnowledgeDocument = {
  id: "doc-1",
  workspace_id: "ws-1",
  knowledge_base_id: "kb-1",
  filename: "guide.md",
  content_type: "text/markdown",
  size_bytes: 10,
  attachment_id: "att-1",
  meta: {},
  status: "indexed",
  is_active: true,
  chunk_count: 1,
  last_error: null,
  created_by_user_id: "user-1",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
}

const evaluationCase = {
  id: "case-1",
  workspace_id: "ws-1",
  knowledge_base_id: "kb-1",
  question: "如何回滚？",
  expected_document_ids: ["doc-1"],
  created_by_user_id: "user-1",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
}

const queuedTask = {
  id: "task-1",
  workspace_id: "ws-1",
  knowledge_base_id: "kb-1",
  document_id: null,
  task_type: "evaluate",
  status: "queued",
  attempts: 0,
  max_attempts: 3,
  total_items: 1,
  processed_items: 0,
  last_error: null,
  created_by_user_id: "user-1",
  started_at: null,
  finished_at: null,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
}

afterEach(() => {
  cleanup()
  resetFetch()
})

describe("knowledge evaluation", () => {
  test("creates a case, polls a run, and renders metrics", async () => {
    const requestBodies: Array<Record<string, unknown>> = []
    const inspectBodies: Array<Record<string, unknown>> = []
    let inspectRequests = 0
    withFetch((url, init) => {
      const method = init?.method ?? "GET"
      if (method === "GET" && url.endsWith("/evaluations/cases")) {
        return jsonResponse([])
      }
      if (method === "GET" && url.endsWith("/evaluations/runs")) {
        return jsonResponse([])
      }
      if (method === "POST" && url.includes("/query/inspect")) {
        inspectRequests += 1
        inspectBodies.push(JSON.parse(String(init?.body)))
        return jsonResponse({
          hits: [
            {
              chunk_id: "chunk-1",
              document_id: "doc-1",
              document_filename: "guide.md",
              parent_id: null,
              parent_title: null,
              parent_index: null,
              chunk_index: 0,
              content: "safe rollback",
              distance: 0.1,
              similarity: 0.95,
              kind: "document",
              question: null,
              source: null,
              sources: ["keywords"],
              reference_hops: 0,
              rerank_score: null,
            },
          ],
          trace: {
            trace_id: "trace-1",
            search_mode: "keywords",
            limit: 5,
            min_similarity: 0.6,
            max_distance: 0.8,
            vector_candidates: 0,
            keyword_candidates: 1,
            reference_candidates: 0,
            fused_candidates: 1,
            rerank_status: "skipped",
            returned_hits: 1,
            duration_ms: 5,
            stage_duration_ms: {},
          },
        })
      }
      if (method === "POST" && url.endsWith("/evaluations/cases")) {
        requestBodies.push(JSON.parse(String(init?.body)))
        return jsonResponse(evaluationCase, 201)
      }
      if (method === "POST" && url.endsWith("/evaluations/runs")) {
        requestBodies.push(JSON.parse(String(init?.body)))
        return jsonResponse(queuedTask, 202)
      }
      if (url.endsWith("/evaluations/runs/task-1/results")) {
        return jsonResponse({
          task: { ...queuedTask, status: "succeeded", attempts: 1, processed_items: 1 },
          count: 1,
          failed_count: 0,
          mean_hit_at_k: 1,
          mean_recall_at_k: 1,
          mean_reciprocal_rank: 1,
          mean_ndcg_at_k: 1,
          p50_latency_ms: 12,
          p95_latency_ms: 12,
          results: [
            {
              id: "result-1",
              case_id: "case-1",
              question: "如何回滚？",
              returned_document_ids: ["doc-1"],
              returned_chunk_ids: ["chunk-1"],
              hit_at_k: 1,
              recall_at_k: 1,
              reciprocal_rank: 1,
              ndcg_at_k: 1,
              latency_ms: 12,
              trace: {},
              error: null,
              created_at: "2026-01-01T00:00:00Z",
            },
          ],
        })
      }
      if (url.endsWith("/evaluations/runs/task-1")) {
        return jsonResponse({
          ...queuedTask,
          status: "succeeded",
          attempts: 1,
          processed_items: 1,
        })
      }
      return jsonResponse({ detail: "unexpected request" }, 500)
    })

    const errors: unknown[] = []
    renderPage(
      <KnowledgeEvaluation
        token="token"
        workspaceId="ws-1"
        knowledgeBaseId="kb-1"
        documents={[document]}
        canEdit
        reportError={(error) => errors.push(error)}
      />,
    )

    await screen.findByText("暂无评测用例")
    const queryInput = screen.getByLabelText("查询内容") as HTMLTextAreaElement
    fireEvent.change(queryInput, {
      target: { value: "如何回滚？" },
    })
    const searchModeTrigger = screen.getByRole("button", { name: "检索模式" })
    fireEvent.pointerDown(searchModeTrigger)
    fireEvent.click(await screen.findByText("关键词检索"))
    expect(
      (screen.getByRole("button", { name: "测试召回" }) as HTMLButtonElement).disabled,
    ).toBe(false)
    fireEvent.submit(queryInput.closest("form")!)

    await waitFor(() => expect(inspectRequests).toBe(1))
    expect(inspectBodies[0]?.search_mode).toBe("keywords")
    await screen.findByText("保存当前检索")
    fireEvent.click(screen.getByRole("button", { name: "添加用例" }))
    await screen.findByRole("checkbox", { name: "选择用例：如何回滚？" })
    expect(requestBodies[0]).toEqual({
      question: "如何回滚？",
      expected_document_ids: ["doc-1"],
    })

    fireEvent.click(
      await screen.findByRole("button", { name: "开始评测（1 条）" }),
    )
    await waitFor(
      () => expect(screen.getByText("P95 延迟")).toBeTruthy(),
      { timeout: 2500 },
    )
    const evaluationHelp = screen.getByRole("button", { name: "查看评测说明" })
    fireEvent.click(evaluationHelp)
    expect(evaluationHelp.getAttribute("aria-expanded")).toBe("true")
    await screen.findByText("评测指标说明")
    expect(screen.getByText("测试问题：怎么申请年假？")).toBeTruthy()
    expect(screen.getAllByText("1").length).toBeGreaterThan(0)
    expect(requestBodies[1]).toEqual({
      case_ids: ["case-1"],
      limit: 5,
      search_mode: "keywords",
      similarity: 0.6,
      include_references: true,
    })
    expect(errors).toEqual([])
  })

  test("loads history, deletes a case, and reopens a run", async () => {
    const succeededTask = {
      ...queuedTask,
      status: "succeeded",
      attempts: 1,
      processed_items: 1,
    }
    const summary = {
      task: succeededTask,
      count: 1,
      failed_count: 0,
      mean_hit_at_k: 1,
      mean_recall_at_k: 1,
      mean_reciprocal_rank: 1,
      mean_ndcg_at_k: 1,
      p50_latency_ms: 12,
      p95_latency_ms: 12,
      results: [],
    }
    let summaryRequests = 0
    let deleteCaseRequests = 0
    let deleteRunRequests = 0
    withFetch((url, init) => {
      const method = init?.method ?? "GET"
      if (method === "GET" && url.endsWith("/evaluations/cases")) {
        return jsonResponse([evaluationCase])
      }
      if (method === "GET" && url.endsWith("/evaluations/runs")) {
        return jsonResponse([succeededTask])
      }
      if (method === "GET" && url.endsWith("/evaluations/runs/task-1/results")) {
        summaryRequests += 1
        return jsonResponse(summary)
      }
      if (method === "DELETE" && url.endsWith("/evaluations/cases/case-1")) {
        deleteCaseRequests += 1
        return new Response(null, { status: 204 })
      }
      if (method === "DELETE" && url.endsWith("/evaluations/runs/task-1")) {
        deleteRunRequests += 1
        return new Response(null, { status: 204 })
      }
      return jsonResponse({ detail: "unexpected request" }, 500)
    })

    renderPage(
      <KnowledgeEvaluation
        token="token"
        workspaceId="ws-1"
        knowledgeBaseId="kb-1"
        documents={[document]}
        canEdit
        reportError={() => undefined}
      />,
    )

    await screen.findByText("P95 延迟")
    const caseCheckbox = screen.getByRole("checkbox", {
      name: "选择用例：如何回滚？",
    })
    fireEvent.click(caseCheckbox)
    fireEvent.click(caseCheckbox)
    fireEvent.click(
      screen.getByRole("button", { name: "删除用例：如何回滚？" }),
    )
    fireEvent.click(
      screen.getByRole("button", { name: /^删除$/ }),
    )
    await waitFor(() => expect(deleteCaseRequests).toBe(1))

    fireEvent.click(screen.getByRole("button", { name: /成功/ }))
    await waitFor(() => expect(summaryRequests).toBe(2))
    fireEvent.click(
      screen.getByRole("button", { name: /删除运行记录：/ }),
    )
    fireEvent.click(
      screen.getByRole("button", { name: /^删除$/ }),
    )
    await waitFor(() => expect(deleteRunRequests).toBe(1))
  })

  test("keeps the delete dialog open when deleting a case fails", async () => {
    const errors: unknown[] = []
    let deleteCaseRequests = 0
    withFetch((url, init) => {
      const method = init?.method ?? "GET"
      if (method === "GET" && url.endsWith("/evaluations/cases")) {
        return jsonResponse([evaluationCase])
      }
      if (method === "GET" && url.endsWith("/evaluations/runs")) {
        return jsonResponse([])
      }
      if (method === "DELETE" && url.endsWith("/evaluations/cases/case-1")) {
        deleteCaseRequests += 1
        return jsonResponse({ detail: "case is in use" }, 409)
      }
      return jsonResponse({ detail: "unexpected request" }, 500)
    })

    renderPage(
      <KnowledgeEvaluation
        token="token"
        workspaceId="ws-1"
        knowledgeBaseId="kb-1"
        documents={[document]}
        canEdit
        reportError={(error) => errors.push(error)}
      />,
    )

    await screen.findByRole("button", { name: "删除用例：如何回滚？" })
    fireEvent.click(screen.getByRole("button", { name: "删除用例：如何回滚？" }))
    await screen.findByText("删除后无法恢复。")
    fireEvent.click(screen.getByRole("button", { name: /^删除$/ }))

    await waitFor(() => expect(deleteCaseRequests).toBe(1))
    expect(screen.getByText("删除后无法恢复。")).toBeTruthy()
    expect(errors).toHaveLength(1)
  })
})
