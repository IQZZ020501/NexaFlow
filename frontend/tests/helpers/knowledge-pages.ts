import type { KnowledgeDocument, KnowledgeTask } from "@/lib/api/knowledge"

/** Emulate the paginated server over a test's document/task fixtures. */
export async function knowledgePageResponse(
  url: string,
  response: Response,
  list: (url: string) => Response | Promise<Response>,
  deletedIds: Set<string> = new Set()
): Promise<Response> {
  const parsed = new URL(url, "http://test.local")
  if (!response.ok || !/\/(documents|tasks)\/page$/.test(parsed.pathname))
    return response
  const payload = await response.clone().json()
  if (!Array.isArray(payload)) return response
  const data = payload.filter((item) => !deletedIds.has(item.id))
  const offset = Number(parsed.searchParams.get("offset") ?? 0)
  const limit = Number(parsed.searchParams.get("limit") ?? 10)
  let result: unknown
  if (parsed.pathname.endsWith("/documents/page")) {
    const documents: KnowledgeDocument[] = data
    const taskResponse = documents.length
      ? await list(parsed.pathname.replace(/\/documents\/page$/, "/tasks"))
      : null
    const taskPayload = taskResponse?.ok ? await taskResponse.json() : []
    const tasks: KnowledgeTask[] = Array.isArray(taskPayload)
      ? taskPayload.filter((task) => !deletedIds.has(task.id))
      : []
    const summary = {
      total: documents.length,
      indexed: 0,
      indexing: 0,
      failed: 0,
      pending: 0,
      processing: 0,
    }
    for (const document of documents) {
      if (document.status === "indexed") summary.indexed += 1
      else if (["index_queued", "indexing"].includes(document.status))
        summary.indexing += 1
      else if (document.status.endsWith("_failed")) summary.failed += 1
      else summary.pending += 1
      if (
        ["parse_queued", "parsing", "index_queued", "indexing"].includes(
          document.status
        )
      )
        summary.processing += 1
    }
    const search = (parsed.searchParams.get("search") ?? "").toLowerCase()
    const status = parsed.searchParams.get("status")
    const field = (parsed.searchParams.get("sort_by") ??
      "created_at") as keyof KnowledgeDocument
    const direction =
      parsed.searchParams.get("sort_direction") === "asc" ? 1 : -1
    const matchesStatus = (item: KnowledgeDocument) => {
      if (!status) return true
      if (status === "indexed") return item.status === "indexed"
      if (status === "indexing")
        return ["index_queued", "indexing"].includes(item.status)
      if (status === "failed") return item.status.endsWith("_failed")
      if (status === "pending")
        return (
          item.status !== "indexed" &&
          !["index_queued", "indexing"].includes(item.status) &&
          !item.status.endsWith("_failed")
        )
      return true
    }
    const filtered = documents
      .filter(
        (item) =>
          item.filename.toLowerCase().includes(search) && matchesStatus(item)
      )
      .sort((a, b) => {
        const left = a[field],
          right = b[field]
        return (
          (typeof left === "string"
            ? left.localeCompare(String(right))
            : Number(left) - Number(right)) * direction
        )
      })
    result = {
      items: filtered.slice(offset, offset + limit),
      total: filtered.length,
      summary,
      active_rebuild_task:
        tasks.find(
          (task) =>
            task.task_type === "rebuild_index" &&
            ["queued", "running", "cancelling"].includes(task.status)
        ) ?? null,
      document_tasks: tasks,
    }
  } else {
    result = {
      items: data.slice(offset, offset + limit),
      total: data.length,
      has_processing: data.some((task) =>
        ["queued", "running", "cancelling"].includes(task.status)
      ),
    }
  }
  return new Response(JSON.stringify(result), {
    headers: { "Content-Type": "application/json" },
  })
}
