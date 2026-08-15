/* @jsxImportSource react */
import { afterEach, describe, expect, test } from "bun:test"
import { act, fireEvent, screen, waitFor } from "@testing-library/react"

import { ChunkPreviewList } from "@/components/knowledge/chunk-preview-list"
import { KnowledgeUploadFlow } from "@/components/knowledge/knowledge-upload-flow"
import {
  KnowledgeUploadStateProvider,
  useKnowledgeUploadState,
} from "@/components/knowledge/knowledge-upload-state"
import type {
  KnowledgeAsset,
  KnowledgeAttachment,
  KnowledgeBase,
  KnowledgeDocument,
  KnowledgeDocumentChunk,
  KnowledgeTask,
} from "@/lib/api/knowledge"
import {
  DEFAULT_KNOWLEDGE_UPLOAD_PARSE_SETTINGS,
  type KnowledgeUploadParseSettings,
  type KnowledgeUploadRouteState,
  type KnowledgeUploadStep,
} from "@/lib/knowledge-upload-route"
import { useInfiniteScroll } from "@/lib/use-infinite-scroll"

import { LanguageProvider } from "@/contexts/language-provider"
import { cleanup, jsonResponse, render, renderPage, withFetch } from "./helpers/dom"

const TOKEN = "test-token"
const WS_ID = "ws-1"
const KB_ID = "kb-1"
const TS = "2026-01-01T00:00:00Z"

const SMART_SETTINGS: KnowledgeUploadParseSettings = {
  ...DEFAULT_KNOWLEDGE_UPLOAD_PARSE_SETTINGS,
  cleaningRules: [...DEFAULT_KNOWLEDGE_UPLOAD_PARSE_SETTINGS.cleaningRules],
}

const KNOWLEDGE_BASE: KnowledgeBase = {
  id: KB_ID,
  workspace_id: WS_ID,
  name: "产品知识库",
  description: "产品资料",
  status: "active",
  embedding_model_id: "em-1",
  reranker_model_id: null,
  created_by_user_id: "u-1",
  created_at: TS,
  updated_at: TS,
  permission: "edit",
}

function makeAttachment(
  overrides: Partial<KnowledgeAttachment> = {},
): KnowledgeAttachment {
  return {
    id: "att-1",
    workspace_id: WS_ID,
    knowledge_base_id: KB_ID,
    filename: "guide.md",
    content_type: "text/markdown",
    size_bytes: 2048,
    status: "stored",
    created_by_user_id: "u-1",
    created_at: TS,
    updated_at: TS,
    ...overrides,
  }
}

function makeDocument(
  overrides: Partial<KnowledgeDocument> = {},
): KnowledgeDocument {
  return {
    id: "doc-1",
    workspace_id: WS_ID,
    knowledge_base_id: KB_ID,
    filename: "guide.md",
    content_type: "text/markdown",
    size_bytes: 2048,
    attachment_id: "att-1",
    meta: { staged: true },
    status: "uploaded",
    is_active: true,
    chunk_count: 0,
    last_error: null,
    created_by_user_id: "u-1",
    created_at: TS,
    updated_at: TS,
    ...overrides,
  }
}

function makeChunk(
  overrides: Partial<KnowledgeDocumentChunk> = {},
): KnowledgeDocumentChunk {
  return {
    id: "chunk-1",
    workspace_id: WS_ID,
    knowledge_base_id: KB_ID,
    document_id: "doc-1",
    parent_id: null,
    parent_title: null,
    parent_index: null,
    chunk_index: 0,
    start_offset: 0,
    end_offset: 24,
    content: "alpha beta gamma-delta-epsilon",
    char_count: 24,
    token_count: 5,
    vector_id: null,
    status: "parsed",
    images: [],
    created_at: TS,
    updated_at: TS,
    ...overrides,
  }
}

function makeAsset(overrides: Partial<KnowledgeAsset> = {}): KnowledgeAsset {
  return {
    id: "asset-1",
    kind: "image",
    filename: "diagram.png",
    content_type: "image/png",
    size_bytes: 512,
    alt_text: "示意图",
    ...overrides,
  }
}

function makeTask(overrides: Partial<KnowledgeTask> = {}): KnowledgeTask {
  return {
    id: "task-1",
    workspace_id: WS_ID,
    knowledge_base_id: KB_ID,
    document_id: "doc-1",
    task_type: "parse",
    status: "queued",
    attempts: 0,
    max_attempts: 3,
    total_items: 1,
    processed_items: 0,
    last_error: null,
    created_by_user_id: "u-1",
    started_at: null,
    finished_at: null,
    created_at: TS,
    updated_at: TS,
    ...overrides,
  }
}

function deferred<T>() {
  const { promise, resolve, reject } = Promise.withResolvers<T>()
  return { promise, resolve, reject }
}

type AttachmentRequest = {
  gate: { promise: Promise<Response>; resolve: (r: Response) => void; reject: (e: Error) => void }
  file: File
}

/** Mutable fake backend for the knowledge upload endpoints. */
class KnowledgeApi {
  documents: KnowledgeDocument[] = []
  chunksByDocument = new Map<string, KnowledgeDocumentChunk[]>()
  taskStatusByDocument = new Map<string, string>()
  taskStatusSequenceByDocument = new Map<string, string[]>()
  taskPollCount = new Map<string, number>()
  parseFailureByDocument = new Map<string, string>()
  indexFailureByDocument = new Map<string, string>()
  chunkFailureByDocument = new Map<string, string>()
  /** Fail the chunks endpoint only from the second request onward (after the
   * initial preview load succeeded). */
  failChunksAfterFirstLoad = false
  chunkRequestCount = new Map<string, number>()
  deleteFailureByDocument = new Map<string, string>()
  listDocumentsFailure = false
  /** When set, the documents list request waits on this gate. */
  listGate: { promise: Promise<Response>; resolve: (r: Response) => void } | null =
    null
  autoSucceedParses = true
  /** When set, document creation only consumes this many attachment ids. */
  createLimit: number | null = null
  attachments: KnowledgeAttachment[] = []
  deletedAttachmentIds: string[] = []
  deletedDocumentIds: string[] = []
  parseRequests: Array<{ documentId: string; body: unknown }> = []
  indexRequests: string[] = []
  attachmentPosts = 0
  attachmentRequests: AttachmentRequest[] = []
  private attachmentCounter = 0

  addDocuments(...documents: KnowledgeDocument[]) {
    this.documents.push(...documents)
  }

  setChunks(documentId: string, chunks: KnowledgeDocumentChunk[]) {
    this.chunksByDocument.set(documentId, chunks)
  }

  setTaskStatus(documentId: string, status: string) {
    this.taskStatusByDocument.set(documentId, status)
  }

  setTaskStatusSequence(documentId: string, statuses: string[]) {
    this.taskStatusSequenceByDocument.set(documentId, statuses)
  }

  failParse(documentId: string, detail: string) {
    this.parseFailureByDocument.set(documentId, detail)
  }

  failIndex(documentId: string, detail: string) {
    this.indexFailureByDocument.set(documentId, detail)
  }

  failChunks(documentId: string, detail: string) {
    this.chunkFailureByDocument.set(documentId, detail)
  }

  failDelete(documentId: string, detail: string) {
    this.deleteFailureByDocument.set(documentId, detail)
  }

  resolveAttachmentGate(index: number) {
    const request = this.attachmentRequests[index]
    if (!request) {
      return
    }
    this.attachmentCounter += 1
    const attachment = makeAttachment({
      id: `att-${this.attachmentCounter}`,
      filename: request.file.name,
      content_type: request.file.type || "application/octet-stream",
      size_bytes: request.file.size,
    })
    this.attachments.push(attachment)
    request.gate.resolve(jsonResponse(attachment, 201))
  }

  failAttachmentGate(index: number, detail: string) {
    const request = this.attachmentRequests[index]
    if (!request) {
      return
    }
    request.gate.reject(new Error(detail))
  }

  handler = (url: string, init?: RequestInit): Response | Promise<Response> => {
    const method = (init?.method ?? "GET").toUpperCase()

    const attachmentMatch = url.match(/\/attachments(?:\/([^/?]+))?$/)
    if (attachmentMatch) {
      if (method === "POST") {
        const formData = init?.body as FormData
        const file = formData.get("file") as File
        this.attachmentPosts += 1
        const gate = deferred<Response>()
        this.attachmentRequests.push({ gate, file })
        return gate.promise
      }
      if (method === "DELETE" && attachmentMatch[1]) {
        this.deletedAttachmentIds.push(attachmentMatch[1])
        return jsonResponse(null, 204)
      }
    }

    const documentMatch = url.match(/\/documents(?:\/([^/?]+))?/)
    if (documentMatch) {
      const documentId = documentMatch[1]
      if (documentId) {
        if (method === "POST" && url.endsWith("/parse")) {
          const failure = this.parseFailureByDocument.get(documentId)
          if (failure) {
            return jsonResponse({ detail: failure }, 500)
          }
          const body = init?.body ? JSON.parse(String(init.body)) : undefined
          this.parseRequests.push({ documentId, body })
          return jsonResponse(
            makeTask({
              id: `task-${documentId}`,
              document_id: documentId,
              status: "queued",
            }),
            201,
          )
        }
        if (method === "POST" && url.endsWith("/index")) {
          const failure = this.indexFailureByDocument.get(documentId)
          if (failure) {
            return jsonResponse({ detail: failure }, 500)
          }
          this.indexRequests.push(documentId)
          return jsonResponse(
            makeTask({
              id: `task-idx-${documentId}`,
              document_id: documentId,
              status: "queued",
            }),
            201,
          )
        }
        if (url.includes("/chunks")) {
          const chunkCount =
            (this.chunkRequestCount.get(documentId) ?? 0) + 1
          this.chunkRequestCount.set(documentId, chunkCount)
          const failure = this.chunkFailureByDocument.get(documentId)
          if (failure && !(this.failChunksAfterFirstLoad && chunkCount === 1)) {
            return jsonResponse({ detail: failure }, 500)
          }
          return jsonResponse(this.chunksByDocument.get(documentId) ?? [])
        }
        if (url.endsWith("/tasks")) {
          const sequence = this.taskStatusSequenceByDocument.get(documentId)
          let status: string
          if (sequence) {
            const pollIndex = this.taskPollCount.get(documentId) ?? 0
            this.taskPollCount.set(documentId, pollIndex + 1)
            status =
              sequence[Math.min(pollIndex, sequence.length - 1)] ??
              this.taskStatusByDocument.get(documentId) ??
              "queued"
          } else {
            status =
              this.taskStatusByDocument.get(documentId) ??
              (this.autoSucceedParses ? "succeeded" : "queued")
          }
          return jsonResponse([
            makeTask({
              id: `task-${documentId}`,
              document_id: documentId,
              status,
              last_error: status === "failed" ? "corrupt file" : null,
            }),
          ])
        }
        if (method === "DELETE") {
          const failure = this.deleteFailureByDocument.get(documentId)
          if (failure) {
            return jsonResponse({ detail: failure }, 500)
          }
          this.deletedDocumentIds.push(documentId)
          return jsonResponse(null, 204)
        }
      } else if (method === "POST") {
        const body = JSON.parse(String(init?.body)) as {
          attachment_ids: string[]
          staged: boolean
        }
        const attachmentIds =
          this.createLimit === null
            ? body.attachment_ids
            : body.attachment_ids.slice(0, this.createLimit)
        const created = attachmentIds.map((attachmentId, index) => {
          const attachment = this.attachments.find(
            (item) => item.id === attachmentId,
          )
          return makeDocument({
            id: `doc-${this.documents.length + index + 1}`,
            attachment_id: attachmentId,
            filename: attachment?.filename ?? `attachment-${attachmentId}.bin`,
            content_type: attachment?.content_type ?? "application/octet-stream",
            size_bytes: attachment?.size_bytes ?? 0,
            meta: { staged: body.staged },
            status: "uploaded",
          })
        })
        this.documents.push(...created)
        return jsonResponse(created, 201)
      } else if (method === "GET") {
        if (this.listDocumentsFailure) {
          return jsonResponse({ detail: "list failed" }, 500)
        }
        if (this.listGate) {
          return this.listGate.promise
        }
        return jsonResponse(this.documents)
      }
    }

    throw new Error(`Unhandled fetch: ${method} ${url}`)
  }
}

/**
 * Fast-forwards the parse poll interval (2000ms) while leaving every other
 * timer untouched so Testing Library's waitFor keeps working.
 */
function patchPollTimer() {
  const original = window.setTimeout
  const patched = ((
    fn: (...args: unknown[]) => void,
    ms?: number,
    ...args: unknown[]
  ) => {
    if (ms === 2000) {
      fn(...args)
      return 0 as unknown as NodeJS.Timeout
    }
    return original(fn, ms, ...args)
  }) as typeof setTimeout
  window.setTimeout = patched
  return () => {
    window.setTimeout = original
  }
}

type Mocked<Args extends unknown[], R> = ((...args: Args) => R) & {
  mock: { calls: Args[] }
}

/** Minimal mock-fn replacement: records invocations for assertions. */
function createMock<Args extends unknown[], R>(
  impl: (...args: Args) => R,
): Mocked<Args, R> {
  const calls: Args[] = []
  const fn = (...args: Args): R => {
    calls.push(args)
    return impl(...args)
  }
  ;(fn as { mock?: { calls: Args[] } }).mock = { calls }
  return fn as Mocked<Args, R>
}

type FlowCallbacks = {
  onCancel: Mocked<[], void>
  onRouteSegment: Mocked<[KnowledgeUploadRouteState], void>
  onBackToFiles: Mocked<[], void>
  onDone: Mocked<[], Promise<void>>
  onNotify: Mocked<[string, string], void>
}

function flowElement(
  props: { step: KnowledgeUploadStep; routeState?: KnowledgeUploadRouteState },
  callbacks: FlowCallbacks,
) {
  return (
    <LanguageProvider defaultLanguage="zh-Hans">
      <KnowledgeUploadStateProvider>
        <KnowledgeUploadFlow
          token={TOKEN}
          workspaceId={WS_ID}
          knowledgeBase={KNOWLEDGE_BASE}
          step={props.step}
          routeState={props.routeState}
          onCancel={callbacks.onCancel}
          onRouteSegment={callbacks.onRouteSegment}
          onBackToFiles={callbacks.onBackToFiles}
          onDone={callbacks.onDone}
          onNotify={callbacks.onNotify}
        />
      </KnowledgeUploadStateProvider>
    </LanguageProvider>
  )
}

function renderFlow(
  props: { step: KnowledgeUploadStep; routeState?: KnowledgeUploadRouteState },
  overrides: Partial<FlowCallbacks> = {},
) {
  const callbacks: FlowCallbacks = {
    onCancel: createMock<[], void>(() => undefined),
    onRouteSegment: createMock<[KnowledgeUploadRouteState], void>(
      () => undefined,
    ),
    onBackToFiles: createMock<[], void>(() => undefined),
    onDone: createMock<[], Promise<void>>(async () => undefined),
    onNotify: createMock<[string, string], void>(() => undefined),
    ...overrides,
  }
  const view = render(flowElement(props, callbacks))
  return { ...view, callbacks }
}

function notifyMessages(calls: unknown[][]) {
  return calls.map((call) => String(call[1]))
}

function notifyKinds(calls: unknown[][]) {
  return calls.map((call) => String(call[0]))
}

function parsedDocuments(count: number): KnowledgeDocument[] {
  return Array.from({ length: count }, (_, index) =>
    makeDocument({
      id: `doc-${index + 1}`,
      filename: index === 0 ? "guide.md" : "notes.txt",
      status: "parsed",
      meta: { staged: true },
    }),
  )
}

function parsedChunks(documentId: string, contents: string[]): KnowledgeDocumentChunk[] {
  return contents.map((content, index) =>
    makeChunk({
      id: `${documentId}-chunk-${index + 1}`,
      document_id: documentId,
      chunk_index: index,
      content,
      char_count: content.length,
      token_count: index + 1,
    }),
  )
}

afterEach(() => {
  cleanup()
})

describe("knowledge upload flow: files step", () => {
  test("renders the empty queue state and cancels without staged documents", async () => {
    const { callbacks } = renderFlow({ step: "files" })
    expect(screen.getByText("等待选择文件")).toBeTruthy()
    expect(screen.getByText("支持格式：", { exact: false })).toBeTruthy()
    const nextButton = screen.getByRole("button", { name: "下一步" })
    expect((nextButton as HTMLButtonElement).disabled).toBe(true)
    fireEvent.click(screen.getByRole("button", { name: "取消" }))
    await waitFor(() =>
      expect(callbacks.onCancel.mock.calls.length).toBeGreaterThan(0),
    )
  })

  test("appends files from the file input and removes them from the queue", () => {
    const { container } = renderFlow({ step: "files" })
    const fileInput = container.querySelectorAll('input[type="file"]')[0]
    const guide = new File(["# Guide"], "guide.md", { type: "text/markdown" })
    const notes = new File(["notes"], "notes.txt", { type: "text/plain" })
    fireEvent.change(fileInput, { target: { files: [guide, notes] } })

    expect(screen.getByText("guide.md")).toBeTruthy()
    expect(screen.getByText("notes.txt")).toBeTruthy()
    expect(screen.getByText("2 个")).toBeTruthy()
    expect(screen.getByText(/已选择 2 个文件，合计/)).toBeTruthy()

    fireEvent.click(screen.getByRole("button", { name: "移除 guide.md" }))
    expect(screen.queryByText("guide.md")).toBeNull()
    expect(screen.getByText("1 个")).toBeTruthy()
  })

  test("ignores unsupported file formats and notifies", () => {
    const { container, callbacks } = renderFlow({ step: "files" })
    const fileInput = container.querySelectorAll('input[type="file"]')[0]
    const files = [
      new File(["ok"], "guide.md", { type: "text/markdown" }),
      new File(["bad"], "setup.exe", { type: "application/x-msdownload" }),
      new File(["ok2"], "readme.txt", { type: "text/plain" }),
    ]
    fireEvent.change(fileInput, { target: { files } })

    expect(screen.queryByText("setup.exe")).toBeNull()
    expect(screen.getByText("guide.md")).toBeTruthy()
    expect(screen.getByText("readme.txt")).toBeTruthy()
    expect(notifyMessages(callbacks.onNotify.mock.calls)).toContain(
      "已忽略不支持的文件格式",
    )
  })

  test("caps the queue at the upload limit", () => {
    const { container, callbacks } = renderFlow({ step: "files" })
    const fileInput = container.querySelectorAll('input[type="file"]')[0]
    const files = Array.from(
      { length: 31 },
      (_, index) => new File(["x"], `${index + 1}.txt`, { type: "text/plain" }),
    )
    fireEvent.change(fileInput, { target: { files } })

    expect(screen.getByText("30 个")).toBeTruthy()
    expect(screen.queryByText("31.txt")).toBeNull()
    expect(notifyMessages(callbacks.onNotify.mock.calls)).toContain(
      "队列最多保留 30 个文件",
    )
  })

  test("handles drag and drop file selection", () => {
    const { container } = renderFlow({ step: "files" })
    const dropzone = container.querySelector(".border-dashed") as HTMLElement
    expect(dropzone).toBeTruthy()

    fireEvent.dragOver(dropzone)
    expect(dropzone.className).toContain("border-primary")

    const guide = new File(["# Guide"], "guide.md", { type: "text/markdown" })
    fireEvent.drop(dropzone, { dataTransfer: { files: [guide] } })
    expect(screen.getByText("guide.md")).toBeTruthy()
    expect(dropzone.className).not.toContain("border-primary")

    fireEvent.dragOver(dropzone)
    fireEvent.dragLeave(dropzone)
    expect(dropzone.className).not.toContain("border-primary")

    fireEvent.drop(dropzone, { dataTransfer: { files: [] } })
    expect(screen.getByText("guide.md")).toBeTruthy()
  })

  test("selects files through the folder input", () => {
    const { container, callbacks } = renderFlow({ step: "files" })
    const folderInput = container.querySelectorAll('input[type="file"]')[1]
    fireEvent.change(folderInput, {
      target: {
        files: [
          new File(["# Guide"], "guide.md", { type: "text/markdown" }),
          new File(["bad"], "setup.exe", { type: "application/x-msdownload" }),
        ],
      },
    })

    expect(screen.getByText("guide.md")).toBeTruthy()
    expect(screen.queryByText("setup.exe")).toBeNull()
    expect(notifyMessages(callbacks.onNotify.mock.calls)).toContain(
      "已忽略不支持的文件格式",
    )
  })

  test("next routes to the segment step with smart parse settings", () => {
    const { container, callbacks } = renderFlow({ step: "files" })
    const fileInput = container.querySelectorAll('input[type="file"]')[0]
    fireEvent.change(fileInput, {
      target: {
        files: [new File(["# Guide"], "guide.md", { type: "text/markdown" })],
      },
    })

    fireEvent.click(screen.getByRole("button", { name: "下一步" }))
    expect(callbacks.onRouteSegment.mock.calls.length).toBe(1)
    const state = callbacks.onRouteSegment.mock.calls[0][0] as KnowledgeUploadRouteState
    expect(state.documentIds).toEqual([])
    expect(state.parseSettings).toEqual(SMART_SETTINGS)
  })
})

describe("knowledge upload flow: segment step route restore", () => {
  test("backs out when the segment step has no route state", async () => {
    const { callbacks } = renderFlow({ step: "segment", routeState: undefined })
    await waitFor(() =>
      expect(callbacks.onBackToFiles.mock.calls.length).toBeGreaterThan(0),)
  })

  test("backs out when no upload was prepared", async () => {
    const { callbacks, container } = renderFlow({
      step: "segment",
      routeState: { documentIds: [], parseSettings: SMART_SETTINGS },
    })
    await waitFor(() =>
      expect(callbacks.onBackToFiles.mock.calls.length).toBeGreaterThan(0),)
    fireEvent.click(screen.getByRole("button", { name: "刷新" }))
    expect(container).toBeTruthy()
  })

  test("ignores a cancelled upload after leaving the segment step", async () => {
    const api = new KnowledgeApi()
    withFetch(api.handler)
    const { rerender, container, callbacks } = renderFlow({ step: "files" })

    const fileInput = container.querySelectorAll('input[type="file"]')[0]
    fireEvent.change(fileInput, {
      target: {
        files: [new File(["# Guide"], "guide.md", { type: "text/markdown" })],
      },
    })
    fireEvent.click(screen.getByRole("button", { name: "下一步" }))
    const nextState = callbacks.onRouteSegment.mock.calls[0][0] as KnowledgeUploadRouteState

    rerender(flowElement({ step: "segment", routeState: nextState }, callbacks))
    await waitFor(() => expect(api.attachmentPosts).toBe(1))

    rerender(flowElement({ step: "files", routeState: nextState }, callbacks))
    await act(async () => {
      api.resolveAttachmentGate(0)
    })
    await new Promise((resolve) => globalThis.setTimeout(resolve, 20))
    expect(callbacks.onRouteSegment.mock.calls.length).toBe(1)
    expect(callbacks.onBackToFiles.mock.calls.length).toBe(0)
  })

  test("backs out when none of the routed documents exist", async () => {
    const api = new KnowledgeApi()
    withFetch(api.handler)

    const { callbacks } = renderFlow({
      step: "segment",
      routeState: { documentIds: ["missing-doc"], parseSettings: SMART_SETTINGS },
    })
    await waitFor(() =>
      expect(callbacks.onBackToFiles.mock.calls.length).toBeGreaterThan(0),)
  })

  test("ignores a route restore cancelled before documents load", async () => {
    const api = new KnowledgeApi()
    api.addDocuments(...parsedDocuments(1))
    api.setChunks("doc-1", parsedChunks("doc-1", ["guide chunk one"]))
    const gate = deferred<Response>()
    api.listGate = gate
    withFetch(api.handler)

    const { rerender, callbacks } = renderFlow({
      step: "segment",
      routeState: { documentIds: ["doc-1"], parseSettings: SMART_SETTINGS },
    })
    rerender(flowElement({ step: "files", routeState: undefined }, callbacks))
    await act(async () => {
      gate.resolve(
        jsonResponse([
          makeDocument({ id: "doc-1", status: "parsed", meta: { staged: true } }),
        ]),
      )
    })
    await new Promise((resolve) => globalThis.setTimeout(resolve, 20))
    expect(callbacks.onRouteSegment.mock.calls.length).toBe(0)
    expect(callbacks.onBackToFiles.mock.calls.length).toBe(0)
  })

  test("uploads prepared files, shows progress, then routes into preview", async () => {
    const api = new KnowledgeApi()
    withFetch(api.handler)
    const { rerender, container, callbacks } = renderFlow({ step: "files" })

    const fileInput = container.querySelectorAll('input[type="file"]')[0]
    fireEvent.change(fileInput, {
      target: {
        files: [
          new File(["# Guide"], "guide.md", { type: "text/markdown" }),
          new File(["notes"], "notes.txt", { type: "text/plain" }),
        ],
      },
    })
    fireEvent.click(screen.getByRole("button", { name: "下一步" }))
    const nextState = callbacks.onRouteSegment.mock.calls[0][0] as KnowledgeUploadRouteState
    expect(nextState.documentIds).toEqual([])

    rerender(flowElement({ step: "segment", routeState: nextState }, callbacks))
    await waitFor(() => expect(api.attachmentPosts).toBe(2))

    expect(screen.getByText("正在生成分段预览")).toBeTruthy()
    const backButton = screen.getByRole("button", { name: "返回知识库" })
    expect((backButton as HTMLButtonElement).disabled).toBe(true)

    await act(async () => {
      api.resolveAttachmentGate(0)
      api.resolveAttachmentGate(1)
    })
    await waitFor(() =>
      expect(callbacks.onRouteSegment.mock.calls.length).toBe(2),
    )
    const restoreState = callbacks.onRouteSegment.mock.calls[1][0] as KnowledgeUploadRouteState
    expect(restoreState.documentIds).toEqual(["doc-1", "doc-2"])
    expect(restoreState.parseSettings).toEqual(SMART_SETTINGS)
  })

  test("reports the failure when every upload fails", async () => {
    const api = new KnowledgeApi()
    withFetch(api.handler)
    const { rerender, container, callbacks } = renderFlow({ step: "files" })

    const fileInput = container.querySelectorAll('input[type="file"]')[0]
    fireEvent.change(fileInput, {
      target: {
        files: [new File(["# Guide"], "guide.md", { type: "text/markdown" })],
      },
    })
    fireEvent.click(screen.getByRole("button", { name: "下一步" }))
    const nextState = callbacks.onRouteSegment.mock.calls[0][0] as KnowledgeUploadRouteState

    rerender(flowElement({ step: "segment", routeState: nextState }, callbacks))
    await waitFor(() => expect(api.attachmentPosts).toBe(1))
    await act(async () => {
      api.failAttachmentGate(0, "upload boom")
    })

    await waitFor(() =>
      expect(callbacks.onBackToFiles.mock.calls.length).toBeGreaterThan(0),)
    expect(notifyMessages(callbacks.onNotify.mock.calls)).toContain("upload boom")
  })

  test("cleans up attachments when document creation fails", async () => {
    const api = new KnowledgeApi()
    withFetch(api.handler)
    const { rerender, container, callbacks } = renderFlow({ step: "files" })

    const fileInput = container.querySelectorAll('input[type="file"]')[0]
    fireEvent.change(fileInput, {
      target: {
        files: [
          new File(["# Guide"], "guide.md", { type: "text/markdown" }),
          new File(["notes"], "notes.txt", { type: "text/plain" }),
        ],
      },
    })
    fireEvent.click(screen.getByRole("button", { name: "下一步" }))
    const nextState = callbacks.onRouteSegment.mock.calls[0][0] as KnowledgeUploadRouteState

    const originalPost = api.handler
    const failingHandler = (url: string, init?: RequestInit) => {
      if (
        (init?.method ?? "GET").toUpperCase() === "POST" &&
        /\/documents$/.test(url)
      ) {
        return jsonResponse({ detail: "create boom" }, 500)
      }
      return originalPost(url, init)
    }
    withFetch(failingHandler)

    rerender(flowElement({ step: "segment", routeState: nextState }, callbacks))
    await waitFor(() => expect(api.attachmentPosts).toBe(2))
    await act(async () => {
      api.resolveAttachmentGate(0)
      api.resolveAttachmentGate(1)
    })

    await waitFor(() =>
      expect(callbacks.onBackToFiles.mock.calls.length).toBeGreaterThan(0),)
    expect(api.deletedAttachmentIds).toEqual(["att-1", "att-2"])
    expect(notifyMessages(callbacks.onNotify.mock.calls)).toContain("create boom")
  })

  test("continues with a partial upload and reports the failure count", async () => {
    const api = new KnowledgeApi()
    withFetch(api.handler)
    const { rerender, container, callbacks } = renderFlow({ step: "files" })

    const fileInput = container.querySelectorAll('input[type="file"]')[0]
    fireEvent.change(fileInput, {
      target: {
        files: [
          new File(["# Guide"], "guide.md", { type: "text/markdown" }),
          new File(["notes"], "notes.txt", { type: "text/plain" }),
        ],
      },
    })
    fireEvent.click(screen.getByRole("button", { name: "下一步" }))
    const nextState = callbacks.onRouteSegment.mock.calls[0][0] as KnowledgeUploadRouteState

    rerender(flowElement({ step: "segment", routeState: nextState }, callbacks))
    await waitFor(() => expect(api.attachmentPosts).toBe(2))
    await act(async () => {
      api.resolveAttachmentGate(0)
      api.failAttachmentGate(1, "notes boom")
    })

    await waitFor(() =>
      expect(callbacks.onRouteSegment.mock.calls.length).toBe(2),
    )
    const restoreState = callbacks.onRouteSegment.mock.calls[1][0] as KnowledgeUploadRouteState
    expect(restoreState.documentIds).toEqual(["doc-1"])
    expect(notifyMessages(callbacks.onNotify.mock.calls)).toContain(
      "已上传 1 个文件，1 个上传失败",
    )
  })

  test("restores a fully parsed route without regenerating previews", async () => {
    const api = new KnowledgeApi()
    api.addDocuments(...parsedDocuments(1))
    api.setChunks("doc-1", parsedChunks("doc-1", ["guide chunk one"]))
    withFetch(api.handler)

    const { callbacks } = renderFlow({
      step: "segment",
      routeState: {
        documentIds: ["doc-1", "ghost-document"],
        parseSettings: SMART_SETTINGS,
      },
    })

    await waitFor(() => screen.getByText("guide chunk one"))
    expect(screen.getByText("待向量化")).toBeTruthy()
    expect(screen.getByText("1 个文档、1 个片段可入库")).toBeTruthy()
    const importButton = screen.getByRole("button", { name: "开始导入" })
    expect((importButton as HTMLButtonElement).disabled).toBe(false)
    expect(callbacks.onRouteSegment.mock.calls.length).toBe(0)
    expect(notifyKinds(callbacks.onNotify.mock.calls)).not.toContain("success")
  })

  test("regenerates previews for uploaded documents restored from the route", async () => {
    const api = new KnowledgeApi()
    api.addDocuments(parsedDocuments(1)[0] && makeDocument({ id: "doc-1" }))
    api.setChunks("doc-1", parsedChunks("doc-1", ["parsed chunk one"]))
    withFetch(api.handler)
    const restoreTimer = patchPollTimer()

    try {
      const { callbacks } = renderFlow({
        step: "segment",
        routeState: { documentIds: ["doc-1"], parseSettings: SMART_SETTINGS },
      })

      await waitFor(() => screen.getByText("parsed chunk one"))
      expect(screen.getByText("待向量化")).toBeTruthy()
      expect(notifyMessages(callbacks.onNotify.mock.calls)).toContain(
        "已生成分段预览",
      )
      expect(api.parseRequests).toHaveLength(1)
      expect(api.parseRequests[0].body).toEqual({
        strategy: "hierarchical",
        chunk_size: SMART_SETTINGS.chunkSize,
        chunk_overlap: SMART_SETTINGS.chunkOverlap,
        split_separator: SMART_SETTINGS.splitSeparator,
        cleaning_rules: SMART_SETTINGS.cleaningRules,
        auto_index: false,
      })
    } finally {
      restoreTimer()
    }
  })

  test("polls until a queued parse task succeeds", async () => {
    const api = new KnowledgeApi()
    api.addDocuments(makeDocument({ id: "doc-1", filename: "guide.md" }))
    api.setChunks("doc-1", parsedChunks("doc-1", ["eventual chunk"]))
    api.setTaskStatusSequence("doc-1", ["queued", "succeeded"])
    withFetch(api.handler)
    const restoreTimer = patchPollTimer()

    try {
      const { callbacks } = renderFlow({
        step: "segment",
        routeState: { documentIds: ["doc-1"], parseSettings: SMART_SETTINGS },
      })

      await waitFor(() => screen.getByText("eventual chunk"))
      expect(notifyMessages(callbacks.onNotify.mock.calls)).toContain(
        "已生成分段预览",
      )
      expect(api.taskPollCount.get("doc-1")).toBe(2)
    } finally {
      restoreTimer()
    }
  })

  test("retries route restoration from the refresh button after a failure", async () => {
    const api = new KnowledgeApi()
    api.addDocuments(makeDocument({ id: "doc-1", status: "parsed" }))
    api.setChunks("doc-1", parsedChunks("doc-1", ["restored chunk"]))
    api.listDocumentsFailure = true
    withFetch(api.handler)

    const { callbacks } = renderFlow({
      step: "segment",
      routeState: { documentIds: ["doc-1"], parseSettings: SMART_SETTINGS },
    })

    await waitFor(() =>
      expect(notifyMessages(callbacks.onNotify.mock.calls)).toContain(
        "list failed",
      ),
    )
    expect(screen.getByText("暂无文件")).toBeTruthy()
    expect(callbacks.onBackToFiles.mock.calls.length).toBe(0)

    api.listDocumentsFailure = false
    fireEvent.click(screen.getByRole("button", { name: "刷新" }))
    await waitFor(() => expect(screen.getByText("restored chunk")).toBeTruthy())
  })

  test("refresh reloads the preview documents", async () => {
    const api = new KnowledgeApi()
    api.addDocuments(...parsedDocuments(1))
    api.setChunks("doc-1", parsedChunks("doc-1", ["refreshed chunk"]))
    withFetch(api.handler)

    const { callbacks } = renderFlow({
      step: "segment",
      routeState: { documentIds: ["doc-1"], parseSettings: SMART_SETTINGS },
    })
    await waitFor(() => screen.getByText("refreshed chunk"))

    fireEvent.click(screen.getByRole("button", { name: "刷新" }))
    await waitFor(() =>
      expect(screen.getAllByText("refreshed chunk").length).toBeGreaterThan(0),
    )
    expect(notifyKinds(callbacks.onNotify.mock.calls)).not.toContain("error")

    api.listDocumentsFailure = true
    fireEvent.click(screen.getByRole("button", { name: "刷新" }))
    await waitFor(() =>
      expect(notifyMessages(callbacks.onNotify.mock.calls)).toContain(
        "list failed",
      ),
    )
  })

  test("resumes polling for parsing documents restored from the route", async () => {
    const api = new KnowledgeApi()
    api.addDocuments(
      makeDocument({ id: "doc-1", filename: "mid.pdf", status: "parsing" }),
    )
    api.setChunks("doc-1", parsedChunks("doc-1", ["restored chunk"]))
    api.setTaskStatusSequence("doc-1", ["queued", "succeeded"])
    withFetch(api.handler)
    const restoreTimer = patchPollTimer()

    try {
      const { callbacks } = renderFlow({
        step: "segment",
        routeState: { documentIds: ["doc-1"], parseSettings: SMART_SETTINGS },
      })

      await waitFor(() => screen.getByText("待向量化"))
      expect(screen.getByText("restored chunk")).toBeTruthy()
      expect(api.parseRequests).toHaveLength(0)
      expect(api.taskPollCount.get("doc-1")).toBe(2)
      expect(notifyMessages(callbacks.onNotify.mock.calls)).toContain(
        "已生成分段预览",
      )
    } finally {
      restoreTimer()
    }
  })

  test("retries an upload after the first attempt fails", async () => {
    const api = new KnowledgeApi()
    withFetch(api.handler)
    const { rerender, container, callbacks } = renderFlow({ step: "files" })

    const fileInput = container.querySelectorAll('input[type="file"]')[0]
    fireEvent.change(fileInput, {
      target: {
        files: [new File(["# Guide"], "guide.md", { type: "text/markdown" })],
      },
    })
    fireEvent.click(screen.getByRole("button", { name: "下一步" }))
    const firstState = callbacks.onRouteSegment.mock
      .calls[0][0] as KnowledgeUploadRouteState

    rerender(flowElement({ step: "segment", routeState: firstState }, callbacks))
    await waitFor(() => expect(api.attachmentPosts).toBe(1))
    await act(async () => {
      api.failAttachmentGate(0, "transient failure")
    })
    await waitFor(() =>
      expect(callbacks.onBackToFiles.mock.calls.length).toBeGreaterThan(0),
    )
    expect(notifyMessages(callbacks.onNotify.mock.calls)).toContain(
      "transient failure",
    )

    // Back on the files step the queue is preserved, so retry directly.
    rerender(flowElement({ step: "files", routeState: firstState }, callbacks))
    fireEvent.click(screen.getByRole("button", { name: "下一步" }))
    const secondState = callbacks.onRouteSegment.mock
      .calls[1][0] as KnowledgeUploadRouteState
    expect(secondState.documentIds).toEqual([])

    rerender(flowElement({ step: "segment", routeState: secondState }, callbacks))
    await waitFor(() => expect(api.attachmentPosts).toBe(2))
    await act(async () => {
      api.resolveAttachmentGate(1)
    })

    await waitFor(() =>
      expect(callbacks.onRouteSegment.mock.calls.length).toBe(3),
    )
    const restoreState = callbacks.onRouteSegment.mock
      .calls[2][0] as KnowledgeUploadRouteState
    expect(restoreState.documentIds).toEqual(["doc-1"])
  })
})

describe("knowledge upload flow: preview generation", () => {
  test("marks a document parse_failed when its parse task fails", async () => {
    const api = new KnowledgeApi()
    api.addDocuments(makeDocument({ id: "doc-1", filename: "corrupt.pdf" }))
    api.setTaskStatus("doc-1", "failed")
    withFetch(api.handler)
    const restoreTimer = patchPollTimer()

    try {
      const { callbacks } = renderFlow({
        step: "segment",
        routeState: { documentIds: ["doc-1"], parseSettings: SMART_SETTINGS },
      })

      await waitFor(() => screen.getByText("corrupt file"))
      expect(notifyMessages(callbacks.onNotify.mock.calls)).toContain(
        "corrupt.pdf 分段失败",
      )
      const importButton = screen.getByRole("button", { name: "开始导入" })
      expect((importButton as HTMLButtonElement).disabled).toBe(true)
    } finally {
      restoreTimer()
    }
  })

  test("marks a document parse_failed when enqueueing the parse task fails", async () => {
    const api = new KnowledgeApi()
    api.addDocuments(makeDocument({ id: "doc-1", filename: "corrupt.pdf" }))
    api.failParse("doc-1", "parse boom")
    withFetch(api.handler)
    const restoreTimer = patchPollTimer()

    try {
      const { callbacks } = renderFlow({
        step: "segment",
        routeState: { documentIds: ["doc-1"], parseSettings: SMART_SETTINGS },
      })

      await waitFor(() => screen.getByText("parse boom"))
      expect(notifyMessages(callbacks.onNotify.mock.calls)).toContain(
        "corrupt.pdf 分段失败",
      )
    } finally {
      restoreTimer()
    }
  })

  test("reports when a parsed document returns no chunks", async () => {
    const api = new KnowledgeApi()
    api.addDocuments(makeDocument({ id: "doc-1", filename: "empty.pdf" }))
    api.setChunks("doc-1", [])
    withFetch(api.handler)
    const restoreTimer = patchPollTimer()

    try {
      const { callbacks } = renderFlow({
        step: "segment",
        routeState: { documentIds: ["doc-1"], parseSettings: SMART_SETTINGS },
      })

      await waitFor(() =>
        expect(notifyMessages(callbacks.onNotify.mock.calls)).toContain(
          "empty.pdf 未返回分段片段",
        ),
      )
      expect(screen.getByText("生成分段预览后查看片段内容")).toBeTruthy()
    } finally {
      restoreTimer()
    }
  })

  test("reports when chunk loading fails", async () => {
    const api = new KnowledgeApi()
    api.addDocuments(makeDocument({ id: "doc-1", filename: "broken.pdf" }))
    api.failChunks("doc-1", "chunk boom")
    api.failChunksAfterFirstLoad = true
    withFetch(api.handler)
    const restoreTimer = patchPollTimer()

    try {
      const { callbacks } = renderFlow({
        step: "segment",
        routeState: { documentIds: ["doc-1"], parseSettings: SMART_SETTINGS },
      })

      await waitFor(() => screen.getByText("chunk boom"))
      expect(notifyMessages(callbacks.onNotify.mock.calls)).toContain(
        "broken.pdf 分段失败",
      )
    } finally {
      restoreTimer()
    }
  })

  test("times out parse tasks that never finish", async () => {
    const api = new KnowledgeApi()
    api.addDocuments(makeDocument({ id: "doc-1", filename: "slow.pdf" }))
    api.autoSucceedParses = false
    withFetch(api.handler)
    const restoreTimer = patchPollTimer()
    const realNow = Date.now
    let nowCalls = 0
    Date.now = () => {
      nowCalls += 1
      return realNow() + (nowCalls > 1 ? 5 * 60 * 1000 + 1 : 0)
    }

    try {
      const { callbacks } = renderFlow({
        step: "segment",
        routeState: { documentIds: ["doc-1"], parseSettings: SMART_SETTINGS },
      })

      await waitFor(() => screen.getByText("分段超时"))
      expect(notifyMessages(callbacks.onNotify.mock.calls)).toContain(
        "slow.pdf 分段失败",
      )
    } finally {
      Date.now = realNow
      restoreTimer()
    }
  })

  test("reports a plural failure notification for multiple documents", async () => {
    const api = new KnowledgeApi()
    api.addDocuments(
      makeDocument({ id: "doc-1", filename: "one.pdf" }),
      makeDocument({ id: "doc-2", filename: "two.pdf" }),
    )
    api.setTaskStatus("doc-1", "failed")
    api.setTaskStatus("doc-2", "failed")
    withFetch(api.handler)
    const restoreTimer = patchPollTimer()

    try {
      const { callbacks } = renderFlow({
        step: "segment",
        routeState: {
          documentIds: ["doc-1", "doc-2"],
          parseSettings: SMART_SETTINGS,
        },
      })

      await waitFor(() =>
        expect(notifyMessages(callbacks.onNotify.mock.calls)).toContain(
          "2 个文档分段失败",
        ),
      )
      expect(screen.getByText("one.pdf")).toBeTruthy()
      expect(screen.getByText("two.pdf")).toBeTruthy()
    } finally {
      restoreTimer()
    }
  })

  test("reports a plural empty-preview notification", async () => {
    const api = new KnowledgeApi()
    api.addDocuments(
      makeDocument({ id: "doc-1", filename: "one.pdf" }),
      makeDocument({ id: "doc-2", filename: "two.pdf" }),
    )
    api.setChunks("doc-1", [])
    api.setChunks("doc-2", [])
    withFetch(api.handler)
    const restoreTimer = patchPollTimer()

    try {
      const { callbacks } = renderFlow({
        step: "segment",
        routeState: {
          documentIds: ["doc-1", "doc-2"],
          parseSettings: SMART_SETTINGS,
        },
      })

      await waitFor(() =>
        expect(notifyMessages(callbacks.onNotify.mock.calls)).toContain(
          "2 个文档未返回分段片段",
        ),
      )
    } finally {
      restoreTimer()
    }
  })

  test("skips generation when routed settings are invalid", async () => {
    const api = new KnowledgeApi()
    api.addDocuments(makeDocument({ id: "doc-1", filename: "guide.md" }))
    withFetch(api.handler)

    const { callbacks } = renderFlow({
      step: "segment",
      routeState: {
        documentIds: ["doc-1"],
        parseSettings: {
          segmentMode: "advanced",
          chunkSize: 100,
          chunkOverlap: 200,
          splitSeparator: "。",
          cleaningRules: ["trim_lines"],
        },
      },
    })

    await waitFor(() => screen.getByText("生成分段预览后查看片段内容"))
    expect(api.parseRequests).toHaveLength(0)
    expect(notifyKinds(callbacks.onNotify.mock.calls)).not.toContain("success")
  })

  test("advanced segmentation settings, validation and regeneration", async () => {
    const api = new KnowledgeApi()
    api.addDocuments(...parsedDocuments(1))
    api.setChunks("doc-1", parsedChunks("doc-1", ["guide chunk one"]))
    withFetch(api.handler)
    const restoreTimer = patchPollTimer()

    try {
      const { callbacks } = renderFlow({
        step: "segment",
        routeState: { documentIds: ["doc-1"], parseSettings: SMART_SETTINGS },
      })
      await waitFor(() => screen.getByText("guide chunk one"))
      expect(screen.getByText("规则").parentElement?.textContent).toContain("智能")

      fireEvent.click(screen.getByRole("button", { name: /高级分段/ }))
      const chunkSizeInput = screen.getByLabelText("片段字符") as HTMLInputElement
      const overlapInput = screen.getByLabelText("重叠字符") as HTMLInputElement
      expect(chunkSizeInput.value).toBe("1200")
      expect(overlapInput.value).toBe("150")
      expect(screen.getByText("规则").parentElement?.textContent).toContain("高级")

      fireEvent.change(chunkSizeInput, { target: { value: "100" } })
      expect(screen.getByText("重叠字符必须小于片段字符")).toBeTruthy()
      expect(
        (screen.getByRole("button", { name: "重新生成预览" }) as HTMLButtonElement)
          .disabled,
      ).toBe(true)
      expect(
        (screen.getByRole("button", { name: "开始导入" }) as HTMLButtonElement)
          .disabled,
      ).toBe(true)
      expect(
        screen.getByText("分段规则已修改，请重新生成预览后再入库"),
      ).toBeTruthy()

      fireEvent.change(overlapInput, { target: { value: "50" } })
      expect(screen.queryByText("重叠字符必须小于片段字符")).toBeNull()

      const collapseCheckbox = screen.getByLabelText("合并连续空白") as HTMLInputElement
      fireEvent.click(collapseCheckbox)
      fireEvent.click(collapseCheckbox)
      fireEvent.click(collapseCheckbox)
      fireEvent.change(screen.getByLabelText("切分字符"), {
        target: { value: "。" },
      })

      fireEvent.click(screen.getByRole("button", { name: "重新生成预览" }))
      await waitFor(() =>
        expect(api.parseRequests[0]?.body).toEqual({
          strategy: "flat",
          chunk_size: 100,
          chunk_overlap: 50,
          split_separator: "。",
          cleaning_rules: ["trim_lines", "remove_empty_lines", "collapse_spaces"],
          auto_index: false,
        }),
      )
      await waitFor(() => screen.getByText("guide chunk one"))
      expect(notifyMessages(callbacks.onNotify.mock.calls)).toContain(
        "已生成分段预览",
      )
      expect(
        (screen.getByRole("button", { name: "开始导入" }) as HTMLButtonElement)
          .disabled,
      ).toBe(false)
    } finally {
      restoreTimer()
    }
  })

  test("surfaces unexpected errors thrown during preview generation", async () => {
    const api = new KnowledgeApi()
    api.addDocuments(makeDocument({ id: "doc-1", filename: "guide.md" }))
    api.setChunks("doc-1", parsedChunks("doc-1", ["guide chunk one"]))
    withFetch(api.handler)
    const restoreTimer = patchPollTimer()

    try {
      const { callbacks } = renderFlow(
        {
          step: "segment",
          routeState: {
            documentIds: ["doc-1"],
            parseSettings: SMART_SETTINGS,
          },
        },
        {
          // A throwing success notification exercises the generation's outer
          // catch, which reports the failure through the error channel.
          onNotify: createMock((kind: string, message: string) => {
            void message
            if (kind === "success") throw new Error("notify boom")
          }),
        },
      )

      await waitFor(() => screen.getByText("guide chunk one"))
      expect(notifyKinds(callbacks.onNotify.mock.calls)).toContain("error")
      expect(notifyMessages(callbacks.onNotify.mock.calls)).toContain(
        "notify boom",
      )
    } finally {
      restoreTimer()
    }
  })

  test("switch preview tab between documents", async () => {
    const api = new KnowledgeApi()
    api.addDocuments(...parsedDocuments(2))
    api.setChunks("doc-1", parsedChunks("doc-1", ["guide chunk one"]))
    api.setChunks("doc-2", parsedChunks("doc-2", ["notes chunk one"]))
    withFetch(api.handler)

    renderFlow({
      step: "segment",
      routeState: {
        documentIds: ["doc-1", "doc-2"],
        parseSettings: SMART_SETTINGS,
      },
    })
    await waitFor(() => screen.getByText("guide chunk one"))
    expect(screen.queryByText("notes chunk one")).toBeNull()

    fireEvent.click(screen.getByText("notes.txt"))
    expect(screen.getByText("notes chunk one")).toBeTruthy()
    expect(screen.queryByText("guide chunk one")).toBeNull()
  })

  test("shows status label fallback and indexed label", async () => {
    const api = new KnowledgeApi()
    api.addDocuments(
      makeDocument({
        id: "doc-1",
        filename: "archived.md",
        status: "archived",
        meta: { staged: false },
      }),
      makeDocument({
        id: "doc-2",
        filename: "done.md",
        status: "indexed",
        meta: { staged: false },
      }),
    )
    api.setChunks("doc-1", parsedChunks("doc-1", ["archived chunk"]))
    api.setChunks("doc-2", parsedChunks("doc-2", ["done chunk"]))
    withFetch(api.handler)

    renderFlow({
      step: "segment",
      routeState: {
        documentIds: ["doc-1", "doc-2"],
        parseSettings: SMART_SETTINGS,
      },
    })
    await waitFor(() => screen.getByText("archived chunk"))
    expect(screen.getByText("archived")).toBeTruthy()
    fireEvent.click(screen.getByText("done.md"))
    expect(screen.getByText("已向量化")).toBeTruthy()
  })
})

describe("knowledge upload flow: import and document management", () => {
  test("submits vectorization for every parsed document", async () => {
    const api = new KnowledgeApi()
    api.addDocuments(...parsedDocuments(2))
    api.setChunks("doc-1", parsedChunks("doc-1", ["guide chunk one"]))
    api.setChunks("doc-2", parsedChunks("doc-2", ["notes chunk one"]))
    withFetch(api.handler)

    const { callbacks } = renderFlow({
      step: "segment",
      routeState: {
        documentIds: ["doc-1", "doc-2"],
        parseSettings: SMART_SETTINGS,
      },
    })
    await waitFor(() =>
      expect(
        (screen.getByRole("button", { name: "开始导入" }) as HTMLButtonElement)
          .disabled,
      ).toBe(false),
    )

    fireEvent.click(screen.getByRole("button", { name: "开始导入" }))
    await waitFor(() => expect(callbacks.onDone.mock.calls.length).toBe(1))
    expect(api.indexRequests).toEqual(["doc-1", "doc-2"])
    expect(notifyMessages(callbacks.onNotify.mock.calls)).toContain(
      "已提交 2 个向量化任务",
    )
  })

  test("reports partial index submission failures", async () => {
    const api = new KnowledgeApi()
    api.addDocuments(...parsedDocuments(2))
    api.setChunks("doc-1", parsedChunks("doc-1", ["guide chunk one"]))
    api.setChunks("doc-2", parsedChunks("doc-2", ["notes chunk one"]))
    api.failIndex("doc-2", "idx boom")
    withFetch(api.handler)

    const { callbacks } = renderFlow({
      step: "segment",
      routeState: {
        documentIds: ["doc-1", "doc-2"],
        parseSettings: SMART_SETTINGS,
      },
    })
    await waitFor(() =>
      expect(
        (screen.getByRole("button", { name: "开始导入" }) as HTMLButtonElement)
          .disabled,
      ).toBe(false),
    )

    fireEvent.click(screen.getByRole("button", { name: "开始导入" }))
    await waitFor(() => expect(callbacks.onDone.mock.calls.length).toBe(1))
    expect(notifyMessages(callbacks.onNotify.mock.calls)).toContain(
      "已提交 1 个向量化任务，1 个提交失败",
    )
  })

  test("keeps the page when every index submission fails", async () => {
    const api = new KnowledgeApi()
    api.addDocuments(...parsedDocuments(1))
    api.setChunks("doc-1", parsedChunks("doc-1", ["guide chunk one"]))
    api.failIndex("doc-1", "idx boom")
    withFetch(api.handler)

    const { callbacks } = renderFlow({
      step: "segment",
      routeState: { documentIds: ["doc-1"], parseSettings: SMART_SETTINGS },
    })
    await waitFor(() =>
      expect(
        (screen.getByRole("button", { name: "开始导入" }) as HTMLButtonElement)
          .disabled,
      ).toBe(false),
    )

    fireEvent.click(screen.getByRole("button", { name: "开始导入" }))
    await waitFor(() =>
      expect(notifyMessages(callbacks.onNotify.mock.calls)).toContain(
        "idx boom",
      ),
    )
    expect(callbacks.onDone.mock.calls.length).toBe(0)
  })

  test("reports an error when finishing the import fails", async () => {
    const api = new KnowledgeApi()
    api.addDocuments(...parsedDocuments(1))
    api.setChunks("doc-1", parsedChunks("doc-1", ["guide chunk one"]))
    withFetch(api.handler)

    const { callbacks } = renderFlow(
      {
        step: "segment",
        routeState: { documentIds: ["doc-1"], parseSettings: SMART_SETTINGS },
      },
      {
        onDone: createMock(async () => {
          throw new Error("done boom")
        }),
      },
    )
    await waitFor(() =>
      expect(
        (screen.getByRole("button", { name: "开始导入" }) as HTMLButtonElement)
          .disabled,
      ).toBe(false),
    )

    fireEvent.click(screen.getByRole("button", { name: "开始导入" }))
    await waitFor(() =>
      expect(notifyMessages(callbacks.onNotify.mock.calls)).toContain(
        "done boom",
      ),
    )
    expect(notifyMessages(callbacks.onNotify.mock.calls)).toContain(
      "已提交 1 个向量化任务",
    )
  })

  test("removes a staged document and re-routes with the remaining ids", async () => {
    const api = new KnowledgeApi()
    api.addDocuments(...parsedDocuments(2))
    api.setChunks("doc-1", parsedChunks("doc-1", ["guide chunk one"]))
    api.setChunks("doc-2", parsedChunks("doc-2", ["notes chunk one"]))
    withFetch(api.handler)

    const { callbacks } = renderFlow({
      step: "segment",
      routeState: {
        documentIds: ["doc-1", "doc-2"],
        parseSettings: SMART_SETTINGS,
      },
    })
    await waitFor(() => screen.getByText("guide chunk one"))

    fireEvent.click(screen.getByRole("button", { name: "移除 guide.md" }))
    await waitFor(() =>
      expect(callbacks.onRouteSegment.mock.calls.length).toBe(1),
    )
    expect(api.deletedDocumentIds).toEqual(["doc-1"])
    const state = callbacks.onRouteSegment.mock.calls[0][0] as KnowledgeUploadRouteState
    expect(state.documentIds).toEqual(["doc-2"])
    expect(screen.queryByText("guide chunk one")).toBeNull()
    expect(screen.getByText("notes chunk one")).toBeTruthy()
  })

  test("backs out to files when the last staged document is removed", async () => {
    const api = new KnowledgeApi()
    api.addDocuments(...parsedDocuments(1))
    api.setChunks("doc-1", parsedChunks("doc-1", ["guide chunk one"]))
    withFetch(api.handler)

    const { callbacks } = renderFlow({
      step: "segment",
      routeState: { documentIds: ["doc-1"], parseSettings: SMART_SETTINGS },
    })
    await waitFor(() => screen.getByText("guide chunk one"))

    fireEvent.click(screen.getByRole("button", { name: "移除 guide.md" }))
    await waitFor(() =>
      expect(callbacks.onBackToFiles.mock.calls.length).toBeGreaterThan(0),)
    expect(api.deletedDocumentIds).toEqual(["doc-1"])
  })

  test("hides the remove button for non-staged documents", async () => {
    const api = new KnowledgeApi()
    api.addDocuments(
      makeDocument({ id: "doc-1", status: "parsed", meta: { staged: false } }),
    )
    api.setChunks("doc-1", parsedChunks("doc-1", ["guide chunk one"]))
    withFetch(api.handler)

    renderFlow({
      step: "segment",
      routeState: { documentIds: ["doc-1"], parseSettings: SMART_SETTINGS },
    })
    await waitFor(() => screen.getByText("guide chunk one"))
    expect(
      screen.queryByRole("button", { name: "移除 guide.md" }),
    ).toBeNull()
  })

  test("cancel discards staged documents and leaves the flow", async () => {
    const api = new KnowledgeApi()
    api.addDocuments(...parsedDocuments(2))
    api.setChunks("doc-1", parsedChunks("doc-1", ["guide chunk one"]))
    api.setChunks("doc-2", parsedChunks("doc-2", ["notes chunk one"]))
    withFetch(api.handler)

    const { callbacks } = renderFlow({
      step: "segment",
      routeState: {
        documentIds: ["doc-1", "doc-2"],
        parseSettings: SMART_SETTINGS,
      },
    })
    await waitFor(() => screen.getByText("guide chunk one"))

    fireEvent.click(screen.getByRole("button", { name: "取消" }))
    await waitFor(() => expect(callbacks.onCancel.mock.calls.length).toBeGreaterThan(0))
    expect(api.deletedDocumentIds.sort()).toEqual(["doc-1", "doc-2"])
  })

  test("back to files discards staged documents", async () => {
    const api = new KnowledgeApi()
    api.addDocuments(...parsedDocuments(1))
    api.setChunks("doc-1", parsedChunks("doc-1", ["guide chunk one"]))
    withFetch(api.handler)

    const { callbacks } = renderFlow({
      step: "segment",
      routeState: { documentIds: ["doc-1"], parseSettings: SMART_SETTINGS },
    })
    await waitFor(() => screen.getByText("guide chunk one"))

    fireEvent.click(screen.getByRole("button", { name: "上一步" }))
    await waitFor(() =>
      expect(callbacks.onBackToFiles.mock.calls.length).toBeGreaterThan(0),)
    expect(api.deletedDocumentIds).toEqual(["doc-1"])
  })

  test("back to files stays put when discarding staged documents fails", async () => {
    const api = new KnowledgeApi()
    api.addDocuments(...parsedDocuments(1))
    api.setChunks("doc-1", parsedChunks("doc-1", ["guide chunk one"]))
    api.failDelete("doc-1", "del boom")
    withFetch(api.handler)

    const { callbacks } = renderFlow({
      step: "segment",
      routeState: { documentIds: ["doc-1"], parseSettings: SMART_SETTINGS },
    })
    await waitFor(() => screen.getByText("guide chunk one"))

    fireEvent.click(screen.getByRole("button", { name: "上一步" }))
    await waitFor(() =>
      expect(notifyMessages(callbacks.onNotify.mock.calls)).toContain(
        "del boom",
      ),
    )
    expect(callbacks.onBackToFiles.mock.calls.length).toBe(0)
  })

  test("reports a failure when removing a staged document fails", async () => {
    const api = new KnowledgeApi()
    api.addDocuments(...parsedDocuments(1))
    api.setChunks("doc-1", parsedChunks("doc-1", ["guide chunk one"]))
    api.failDelete("doc-1", "del boom")
    withFetch(api.handler)

    const { callbacks } = renderFlow({
      step: "segment",
      routeState: { documentIds: ["doc-1"], parseSettings: SMART_SETTINGS },
    })
    await waitFor(() => screen.getByText("guide chunk one"))

    fireEvent.click(screen.getByRole("button", { name: "移除 guide.md" }))
    await waitFor(() =>
      expect(notifyMessages(callbacks.onNotify.mock.calls)).toContain(
        "del boom",
      ),
    )
    expect(callbacks.onRouteSegment.mock.calls.length).toBe(0)
    expect(screen.getByText("guide chunk one")).toBeTruthy()
  })

  test("deletes leftover attachments when fewer documents are created", async () => {
    const api = new KnowledgeApi()
    api.createLimit = 1
    withFetch(api.handler)
    const { rerender, container, callbacks } = renderFlow({ step: "files" })

    const fileInput = container.querySelectorAll('input[type="file"]')[0]
    fireEvent.change(fileInput, {
      target: {
        files: [
          new File(["# Guide"], "guide.md", { type: "text/markdown" }),
          new File(["notes"], "notes.txt", { type: "text/plain" }),
        ],
      },
    })
    fireEvent.click(screen.getByRole("button", { name: "下一步" }))
    const nextState = callbacks.onRouteSegment.mock.calls[0][0] as KnowledgeUploadRouteState

    rerender(flowElement({ step: "segment", routeState: nextState }, callbacks))
    await waitFor(() => expect(api.attachmentPosts).toBe(2))
    await act(async () => {
      api.resolveAttachmentGate(0)
      api.resolveAttachmentGate(1)
    })

    await waitFor(() =>
      expect(callbacks.onRouteSegment.mock.calls.length).toBe(2),
    )
    const restoreState = callbacks.onRouteSegment.mock.calls[1][0] as KnowledgeUploadRouteState
    expect(restoreState.documentIds).toEqual(["doc-1"])
    expect(api.deletedAttachmentIds).toEqual(["att-2"])
  })

  test("stays in the flow when discarding staged documents fails", async () => {
    const api = new KnowledgeApi()
    api.addDocuments(...parsedDocuments(2))
    api.setChunks("doc-1", parsedChunks("doc-1", ["guide chunk one"]))
    api.setChunks("doc-2", parsedChunks("doc-2", ["notes chunk one"]))
    api.failDelete("doc-2", "del boom")
    withFetch(api.handler)

    const { callbacks } = renderFlow({
      step: "segment",
      routeState: {
        documentIds: ["doc-1", "doc-2"],
        parseSettings: SMART_SETTINGS,
      },
    })
    await waitFor(() => screen.getByText("guide chunk one"))

    fireEvent.click(screen.getByRole("button", { name: "取消" }))
    await waitFor(() =>
      expect(notifyMessages(callbacks.onNotify.mock.calls)).toContain(
        "del boom",
      ),
    )
    expect(callbacks.onCancel.mock.calls.length).toBe(0)
    expect(api.deletedDocumentIds).toEqual(["doc-1"])
  })
})

describe("chunk preview list", () => {
  test("renders parent and child chunk titles with counts", () => {
    const chunks = [
      makeChunk({
        id: "c1",
        document_id: "doc-1",
        parent_id: null,
        chunk_index: 0,
        content: "first child",
        char_count: 11,
        token_count: 2,
      }),
      makeChunk({
        id: "c2",
        document_id: "doc-1",
        parent_id: "parent-1",
        parent_title: "Part 1",
        parent_index: 0,
        chunk_index: 1,
        content: "second child",
        char_count: 12,
        token_count: 2,
      }),
    ]
    renderPage(
      <ChunkPreviewList
        chunks={chunks}
        fileName="guide.md"
        token={TOKEN}
        workspaceId={WS_ID}
        knowledgeBaseId={KB_ID}
      />,
    )
    expect(screen.getByText("guide.md")).toBeTruthy()
    expect(screen.getByText("分段 2")).toBeTruthy()
    expect(screen.getByText("11 字符 / 2 tokens")).toBeTruthy()
    expect(screen.getByText("12 字符 / 2 tokens")).toBeTruthy()
    expect(screen.queryByText(/重叠/)).toBeNull()
  })

  test("shows the overlap badge between adjacent chunks", () => {
    const chunks = [
      makeChunk({
        id: "c1",
        document_id: "doc-1",
        parent_id: null,
        chunk_index: 0,
        content: "alpha beta gamma-delta-epsilon",
      }),
      makeChunk({
        id: "c2",
        document_id: "doc-1",
        parent_id: null,
        chunk_index: 1,
        content: "gamma-delta-epsilon omega",
      }),
    ]
    renderPage(
      <ChunkPreviewList
        chunks={chunks}
        fileName="guide.md"
        token={TOKEN}
        workspaceId={WS_ID}
        knowledgeBaseId={KB_ID}
      />,
    )
    expect(screen.getByText("重叠 19 字符")).toBeTruthy()
  })

  test("renders chunk images from asset blobs", async () => {
    const chunks = [
      makeChunk({
        id: "c1",
        document_id: "doc-1",
        parent_id: null,
        chunk_index: 0,
        content: "with image",
        images: [makeAsset({ id: "asset-1", alt_text: "示意图" })],
      }),
    ]
    withFetch((url) => {
      if (url.endsWith("/assets/asset-1")) {
        return new Response(new Blob(["png-bytes"]), {
          status: 200,
          headers: { "Content-Type": "image/png" },
        })
      }
      throw new Error(`Unhandled fetch: ${url}`)
    })

    renderPage(
      <ChunkPreviewList
        chunks={chunks}
        fileName="guide.md"
        token={TOKEN}
        workspaceId={WS_ID}
        knowledgeBaseId={KB_ID}
      />,
    )
    const image = await screen.findByAltText("示意图")
    expect(image.getAttribute("src")).toMatch(/^blob:/)
  })

  test("shows a failure state when an asset cannot be loaded", async () => {
    const chunks = [
      makeChunk({
        id: "c1",
        document_id: "doc-1",
        parent_id: null,
        chunk_index: 0,
        content: "with image",
        images: [makeAsset({ id: "asset-1", alt_text: "示意图" })],
      }),
    ]
    withFetch((url) => {
      if (url.endsWith("/assets/asset-1")) {
        return jsonResponse({ detail: "gone" }, 404)
      }
      throw new Error(`Unhandled fetch: ${url}`)
    })

    renderPage(
      <ChunkPreviewList
        chunks={chunks}
        fileName="guide.md"
        token={TOKEN}
        workspaceId={WS_ID}
        knowledgeBaseId={KB_ID}
      />,
    )
    expect(await screen.findByText("图片加载失败")).toBeTruthy()
  })

  test("registers and cleans up overlap highlights", async () => {
    const registryMap = new Map<string, unknown>()
    const originalHighlight = (
      globalThis as Record<string, unknown>
    ).Highlight
    ;(globalThis as Record<string, unknown>).Highlight = class FakeHighlight {
      ranges: Range[]
      constructor(...ranges: Range[]) {
        this.ranges = ranges
      }
    }
    const originalCSS = (globalThis as Record<string, unknown>).CSS
    Object.defineProperty(globalThis, "CSS", {
      configurable: true,
      value: {
        highlights: {
          set: (name: string, value: unknown) => registryMap.set(name, value),
          get: (name: string) => registryMap.get(name),
          delete: (name: string) => registryMap.delete(name),
        },
      },
    })
    try {
      const chunkList = (chunks: KnowledgeDocumentChunk[]) => (
        <LanguageProvider defaultLanguage="zh-Hans">
          <ChunkPreviewList
            chunks={chunks}
            fileName="guide.md"
            token={TOKEN}
            workspaceId={WS_ID}
            knowledgeBaseId={KB_ID}
          />
        </LanguageProvider>
      )
      const noOverlap = [makeChunk({ id: "c1", content: "solo text" })]
      const { rerender, unmount } = render(chunkList(noOverlap))
      expect(registryMap.size).toBe(0)

      const overlap = [
        makeChunk({
          id: "c1",
          parent_id: null,
          chunk_index: 0,
          content: "alpha beta gamma-delta-epsilon",
        }),
        makeChunk({
          id: "c2",
          parent_id: null,
          chunk_index: 1,
          content: "gamma-delta-epsilon omega",
        }),
      ]
      rerender(chunkList(overlap))
      const highlight = registryMap.get("knowledge-chunk-overlap") as {
        ranges: Range[]
      }
      expect(highlight).toBeTruthy()
      expect(highlight.ranges.length).toBe(1)

      unmount()
      expect(registryMap.has("knowledge-chunk-overlap")).toBe(false)
    } finally {
      if (originalHighlight === undefined) {
        delete (globalThis as Record<string, unknown>).Highlight
      } else {
        ;(globalThis as Record<string, unknown>).Highlight = originalHighlight
      }
      Object.defineProperty(globalThis, "CSS", {
        configurable: true,
        value: originalCSS,
      })
    }
  })
})

describe("knowledge upload state provider", () => {
  test("throws when used outside the provider", () => {
    function Probe() {
      useKnowledgeUploadState()
      return null
    }
    expect(() => renderPage(<Probe />)).toThrow(
      "KnowledgeUploadStateProvider is missing",
    )
  })

  test("stores files, prepares uploads and caches the upload promise", async () => {
    const capture: Record<string, unknown> = {}
    function Probe() {
      const state = useKnowledgeUploadState()
      capture.files = state.files
      capture.setFiles = () =>
        state.setFiles([new File(["x"], "x.txt", { type: "text/plain" })])
      capture.prepare = () =>
        state.prepareUpload(async () => [makeDocument({ id: "doc-9" })])
      capture.start = () => {
        capture.firstStart = state.startUpload()
        capture.secondStart = state.startUpload()
        return capture.firstStart
      }
      return <div data-testid="probe" />
    }
    renderPage(
      <KnowledgeUploadStateProvider>
        <Probe />
      </KnowledgeUploadStateProvider>,
    )

    act(() => {
      ;(capture.setFiles as () => void)()
    })
    await waitFor(() =>
      expect((capture.files as File[]).map((file) => file.name)).toEqual([
        "x.txt",
      ]),
    )

    act(() => {
      ;(capture.prepare as () => void)()
    })
    act(() => {
      void (capture.start as () => void)()
    })
    await waitFor(async () => {
      const first = await (capture.firstStart as Promise<KnowledgeDocument[]>)
      expect(first.map((document) => document.id)).toEqual(["doc-9"])
    })
    expect(capture.secondStart).toBe(capture.firstStart)
  })

  test("returns null from startUpload without a prepared upload", () => {
    const capture: Record<string, unknown> = {}
    function Probe() {
      const state = useKnowledgeUploadState()
      capture.start = () => state.startUpload()
      capture.clearAndStart = () => {
        state.setFiles([])
        capture.afterClear = state.startUpload()
      }
      return <div data-testid="probe" />
    }
    renderPage(
      <KnowledgeUploadStateProvider>
        <Probe />
      </KnowledgeUploadStateProvider>,
    )
    act(() => {
      capture.start = (capture.start as () => unknown)()
    })
    expect(capture.start).toBeNull()

    act(() => {
      ;(capture.clearAndStart as () => void)()
    })
    expect(capture.afterClear).toBeNull()
  })
})

describe("use infinite scroll", () => {
  class MockIntersectionObserver {
    static instances: MockIntersectionObserver[] = []
    callback: IntersectionObserverCallback
    options: IntersectionObserverInit | undefined
    observed: Element[] = []
    disconnected = false

    constructor(
      callback: IntersectionObserverCallback,
      options?: IntersectionObserverInit,
    ) {
      this.callback = callback
      this.options = options
      MockIntersectionObserver.instances.push(this)
    }

    observe(target: Element) {
      this.observed.push(target)
    }

    unobserve() {}

    disconnect() {
      this.disconnected = true
    }

    takeRecords() {
      return []
    }

    trigger(entries: Array<{ isIntersecting: boolean }>) {
      this.callback(
        entries as IntersectionObserverEntry[],
        this as unknown as IntersectionObserver,
      )
    }
  }

  const originalObserver = globalThis.IntersectionObserver

  function installObserverMock() {
    MockIntersectionObserver.instances = []
    globalThis.IntersectionObserver =
      MockIntersectionObserver as unknown as typeof IntersectionObserver
  }

  afterEach(() => {
    globalThis.IntersectionObserver = originalObserver
  })

  function ScrollProbe({ loadMore }: { loadMore: () => void }) {
    const ref = useInfiniteScroll(loadMore)
    return <div ref={ref} data-testid="sentinel" />
  }

  function scrollElement(loadMore: () => void) {
    return (
      <LanguageProvider defaultLanguage="zh-Hans">
        <ScrollProbe loadMore={loadMore} />
      </LanguageProvider>
    )
  }

  test("observes the sentinel and loads more on intersection", () => {
    installObserverMock()
    const loadMore = createMock(() => undefined)
    const { getByTestId } = render(scrollElement(loadMore))
    const sentinel = getByTestId("sentinel")

    expect(MockIntersectionObserver.instances).toHaveLength(1)
    const instance = MockIntersectionObserver.instances[0]
    expect(instance.observed).toEqual([sentinel])
    expect(instance.options?.rootMargin).toBe("200px 0px")

    act(() => {
      instance.trigger([{ isIntersecting: true }])
    })
    expect(loadMore.mock.calls.length).toBe(1)

    act(() => {
      instance.trigger([{ isIntersecting: false }])
    })
    expect(loadMore.mock.calls.length).toBe(1)
  })

  test("uses the latest loadMore callback after rerender", () => {
    installObserverMock()
    const first = createMock(() => undefined)
    const second = createMock(() => undefined)
    const { rerender } = render(scrollElement(first))
    rerender(scrollElement(second))

    const instance = MockIntersectionObserver.instances[0]
    act(() => {
      instance.trigger([{ isIntersecting: true }])
    })
    expect(first.mock.calls.length).toBe(0)
    expect(second.mock.calls.length).toBe(1)
  })

  test("disconnects the observer on unmount", () => {
    installObserverMock()
    const { unmount } = render(scrollElement(() => undefined))
    const instance = MockIntersectionObserver.instances[0]
    expect(instance.disconnected).toBe(false)
    unmount()
    expect(instance.disconnected).toBe(true)
  })
})
