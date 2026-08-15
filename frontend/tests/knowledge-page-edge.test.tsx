/* @jsxImportSource react */
import { afterEach, describe, expect, test } from "bun:test"
import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react"

import { ChunkPreviewList } from "@/components/knowledge/chunk-preview-list"
import { KnowledgeBasePage } from "@/components/knowledge/knowledge-base-page"
import { KnowledgeUploadStateProvider } from "@/components/knowledge/knowledge-upload-state"
import {
  DEFAULT_KNOWLEDGE_UPLOAD_PARSE_SETTINGS,
  type KnowledgeUploadRouteState,
} from "@/lib/knowledge-upload-route"
import type {
  KnowledgeAsset,
  KnowledgeDocument,
  KnowledgeDocumentChunk,
  KnowledgeTask,
} from "@/lib/api/knowledge"
import type { RegisteredModel } from "@/lib/api/llm"
import {
  jsonResponse,
  makeSession,
  mockNextNavigation,
  mockUseSession,
  render,
  renderPage,
  setFetch,
  resetFetch,
  type FetchHandler,
} from "./helpers/dom"
import { LanguageProvider } from "@/contexts/language-provider"

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const WS = "ws-1"
const KB_ID = "kb-1"

const adminUser = {
  id: "u-admin",
  username: "admin",
  email: "admin@app.local",
  name: "NexaFlow Admin",
  is_global_admin: true,
  must_change_password: false,
  is_active: true,
  created_at: "2026-01-01T00:00:00Z",
  workspaces: [{ id: WS, name: "Test Workspace", is_default: true, role: "admin" }],
  teams: [],
}

const session = makeSession({
  me: { user: adminUser, memberships: [{ workspace_id: WS, role: "admin" }] },
})

const notifications: Array<[string, string]> = []
session.notify = ((kind: string, message: string) => {
  notifications.push([kind, message])
}) as unknown as typeof session.notify

mockUseSession(session)

const routeParams: Record<string, string> = {}
const pushes: string[] = []
const replaces: string[] = []
mockNextNavigation({
  params: routeParams,
  push: (href) => pushes.push(href),
  replace: (href) => replaces.push(href),
})

afterEach(() => {
  cleanup()
  resetFetch()
  notifications.length = 0
  pushes.length = 0
  replaces.length = 0
  for (const key of Object.keys(routeParams)) delete routeParams[key]
})

function makeKnowledgeBase(overrides: Record<string, unknown> = {}) {
  return {
    id: KB_ID,
    workspace_id: WS,
    name: "KB Alpha",
    description: "Alpha docs",
    status: "active",
    embedding_model_id: "model-emb",
    reranker_model_id: null,
    created_by_user_id: "u-admin",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-02T00:00:00Z",
    permission: "edit",
    document_count: 3,
    char_count: 1200,
    ...overrides,
  }
}

const embeddingModel: RegisteredModel = {
  id: "model-emb",
  workspace_id: WS,
  name: "text-embedding-pro",
  provider: "openai",
  provider_type: "openai",
  model_type: "EMBEDDING",
  model_name: "text-embedding-3-small",
  status: "active",
  credential: {},
  api_base: "",
  has_api_key: true,
  api_key_hint: null,
  meta: {},
  created_by_user_id: "u-admin",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
}

const models = [embeddingModel]

function makeChunk(
  overrides: Record<string, unknown> = {},
): KnowledgeDocumentChunk {
  return {
    id: "chunk-1",
    workspace_id: WS,
    knowledge_base_id: KB_ID,
    document_id: "doc-1",
    parent_id: null,
    parent_title: null,
    parent_index: null,
    chunk_index: 0,
    start_offset: 0,
    end_offset: 24,
    content: "alpha beta gamma-delta-epsilon",
    kind: "document",
    question: null,
    source: null,
    row_number: null,
    char_count: 24,
    token_count: 5,
    vector_id: null,
    status: "parsed",
    images: [],
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  }
}

function makeAsset(overrides: Record<string, unknown> = {}): KnowledgeAsset {
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

function makeDocument(
  overrides: Record<string, unknown> = {},
): KnowledgeDocument {
  return {
    id: "doc-1",
    workspace_id: WS,
    knowledge_base_id: KB_ID,
    filename: "guide.md",
    content_type: "text/markdown",
    size_bytes: 2048,
    attachment_id: "att-1",
    meta: { staged: true },
    status: "parsed",
    is_active: true,
    chunk_count: 1,
    last_error: null,
    created_by_user_id: "u-admin",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-02T00:00:00Z",
    ...overrides,
  }
}

function makeTask(overrides: Record<string, unknown> = {}): KnowledgeTask {
  return {
    id: "task-1",
    workspace_id: WS,
    knowledge_base_id: KB_ID,
    document_id: "doc-1",
    task_type: "index",
    status: "succeeded",
    attempts: 1,
    max_attempts: 3,
    total_items: 10,
    processed_items: 10,
    last_error: null,
    created_by_user_id: "u-admin",
    started_at: null,
    finished_at: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-02T00:00:00Z",
    ...overrides,
  }
}

function renderChunkList(
  chunks: KnowledgeDocumentChunk[],
  fileName = "guide.md",
) {
  return renderPage(
    <ChunkPreviewList
      chunks={chunks}
      fileName={fileName}
      token="test-token"
      workspaceId={WS}
      knowledgeBaseId={KB_ID}
    />,
  )
}

// ---------------------------------------------------------------------------
// ChunkPreviewList
// ---------------------------------------------------------------------------

describe("ChunkPreviewList", () => {
  test("renders parent and child chunk titles with counts", () => {
    renderChunkList([
      makeChunk({
        id: "c1",
        parent_id: null,
        chunk_index: 0,
        content: "first child",
        char_count: 11,
        token_count: 2,
      }),
      makeChunk({
        id: "c2",
        parent_id: "parent-1",
        chunk_index: 1,
        content: "second child",
        char_count: 12,
        token_count: 2,
      }),
    ])

    expect(screen.getByText("guide.md")).toBeTruthy()
    expect(screen.getByText("分段 2")).toBeTruthy()
    expect(screen.getByText("11 字符 / 2 tokens")).toBeTruthy()
    expect(screen.getByText("12 字符 / 2 tokens")).toBeTruthy()
    expect(screen.queryByText(/重叠/)).toBeNull()
  })

  test("shows the overlap badge between adjacent chunks", () => {
    renderChunkList([
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
    ])
    expect(screen.getByText("重叠 19 字符")).toBeTruthy()
  })

  test("renders chunk images from asset blobs", async () => {
    setFetch((url) => {
      if (url.endsWith("/assets/asset-1")) {
        return new Response(new Blob(["png-bytes"]), {
          status: 200,
          headers: { "Content-Type": "image/png" },
        })
      }
      throw new Error(`Unhandled fetch: ${url}`)
    })

    renderChunkList([
      makeChunk({
        id: "c1",
        content: "with image",
        images: [makeAsset({ id: "asset-1", alt_text: "示意图" })],
      }),
    ])

    const image = await screen.findByAltText("示意图")
    expect(image.getAttribute("src")).toMatch(/^blob:/)
  })

  test("shows a failure state when an asset cannot be loaded", async () => {
    setFetch((url) => {
      if (url.endsWith("/assets/asset-1")) {
        return jsonResponse({ detail: "gone" }, 404)
      }
      throw new Error(`Unhandled fetch: ${url}`)
    })

    renderChunkList([
      makeChunk({
        id: "c1",
        content: "with image",
        images: [makeAsset({ id: "asset-1", alt_text: "示意图" })],
      }),
    ])

    expect(await screen.findByText("图片加载失败")).toBeTruthy()
  })

  test("revokes the object URL when the preview unmounts", async () => {
    setFetch((url) => {
      if (url.endsWith("/assets/asset-1")) {
        return new Response(new Blob(["png-bytes"]), {
          status: 200,
          headers: { "Content-Type": "image/png" },
        })
      }
      throw new Error(`Unhandled fetch: ${url}`)
    })

    const originalRevoke = URL.revokeObjectURL
    const revoked: string[] = []
    URL.revokeObjectURL = (url) => {
      revoked.push(url)
    }
    try {
      const { unmount } = renderChunkList([
        makeChunk({
          id: "c1",
          content: "with image",
          images: [makeAsset({ id: "asset-1", alt_text: "示意图" })],
        }),
      ])

      const image = await screen.findByAltText("示意图")
      const src = image.getAttribute("src")
      unmount()
      expect(revoked).toContain(src ?? "")
    } finally {
      URL.revokeObjectURL = originalRevoke
    }
  })

  test("ignores asset loads that resolve after unmount", async () => {
    let resolveAsset: ((response: Response) => void) | null = null
    setFetch(() => {
      return new Promise<Response>((resolve) => {
        resolveAsset = resolve
      })
    })

    const { unmount } = renderChunkList([
      makeChunk({
        id: "c1",
        content: "with image",
        images: [makeAsset({ id: "asset-1", alt_text: "示意图" })],
      }),
    ])
    unmount()
    ;(resolveAsset as ((response: Response) => void) | null)?.(
      new Response(new Blob(["png-bytes"]), {
        status: 200,
        headers: { "Content-Type": "image/png" },
      }),
    )
    await waitFor(() => expect(screen.queryByAltText("示意图")).toBeNull())
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
            token="test-token"
            workspaceId={WS}
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

  test("spans overlap ranges across multiple text nodes", async () => {
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
      const { unmount } = renderChunkList([
        makeChunk({
          id: "c1",
          parent_id: null,
          chunk_index: 0,
          content: "前文**ab**cdefgh-",
          char_count: 15,
        }),
        makeChunk({
          id: "c2",
          parent_id: null,
          chunk_index: 1,
          content: "**ab**cdefgh-xyz",
          char_count: 16,
        }),
      ])
      const highlight = registryMap.get("knowledge-chunk-overlap") as {
        ranges: Range[]
      }
      expect(highlight).toBeTruthy()
      expect(highlight.ranges.length).toBe(1)
      // Overlap (13 chars) spans "ab" (2) and "cdefgh-xyz" (10): the walker
      // exhausts the text nodes and ends the range at the last node.
      expect(highlight.ranges[0].startContainer.textContent).toBe("ab")
      expect(highlight.ranges[0].endContainer.textContent).toBe("cdefgh-xyz")
      expect(highlight.ranges[0].endOffset).toBe(10)
      unmount()
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

  test("skips the highlight when the chunk renders no text nodes", async () => {
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
      const { unmount } = renderChunkList([
        makeChunk({
          id: "c1",
          parent_id: null,
          chunk_index: 0,
          content: "前文 ![abcdefg",
          char_count: 9,
        }),
        makeChunk({
          id: "c2",
          parent_id: null,
          chunk_index: 1,
          content: "![abcdefg](https://example.com/x.png)",
          char_count: 9,
        }),
      ])
      // The overlapping chunk renders only an image → no text node →
      // no range is created and the highlight stays unregistered.
      try {
        await waitFor(() => {
          expect(registryMap.has("knowledge-chunk-overlap")).toBe(false)
        })
      } finally {
        unmount()
      }
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

// ---------------------------------------------------------------------------
// KnowledgeBasePage — upload flow callbacks
// ---------------------------------------------------------------------------

function renderUploadPage(options: {
  step: "files" | "segment"
  routeState?: KnowledgeUploadRouteState
  handler?: FetchHandler
}) {
  routeParams.id = KB_ID
  const handler: FetchHandler =
    options.handler ??
    ((url) => {
      if (url.includes("/models")) return jsonResponse(models)
      if (url.includes("/knowledge-bases?")) return jsonResponse([makeKnowledgeBase()])
      if (url.includes("/documents")) return jsonResponse([])
      return jsonResponse([])
    })
  setFetch(handler)
  return renderPage(
    <KnowledgeUploadStateProvider>
      <KnowledgeBasePage
        uploadStep={options.step}
        uploadRouteState={options.routeState}
      />
    </KnowledgeUploadStateProvider>,
  )
}

describe("KnowledgeBasePage upload flow callbacks", () => {
  test("cancels the upload flow back to the knowledge base", async () => {
    renderUploadPage({ step: "files" })

    await waitFor(() => {
      expect(screen.getByText("选择导入文件")).toBeTruthy()
    })
    fireEvent.click(screen.getByRole("button", { name: "取消" }))
    await waitFor(() => {
      expect(replaces).toContain(`/app/knowledge/${KB_ID}`)
    })
  })

  test("routes to the segment step when proceeding from the files step", async () => {
    const { container } = renderUploadPage({ step: "files" })
    await waitFor(() => {
      expect(screen.getByText("选择导入文件")).toBeTruthy()
    })

    const fileInput = container.querySelectorAll('input[type="file"]')[0]
    fireEvent.change(fileInput, {
      target: {
        files: [new File(["# Guide"], "guide.md", { type: "text/markdown" })],
      },
    })
    await waitFor(() => {
      expect(screen.getByText(/已选择 1 个文件/)).toBeTruthy()
    })
    fireEvent.click(screen.getByRole("button", { name: "下一步" }))

    await waitFor(() => {
      expect(
        replaces.some((href) => href.includes("/segment?")),
      ).toBe(true)
    })
    expect(replaces[replaces.length - 1]).toContain("/upload/segment?")
  })

  test("routes back to the files step from the segment step", async () => {
    const deletes: string[] = []
    const routeState: KnowledgeUploadRouteState = {
      documentIds: ["doc-1"],
      parseSettings: DEFAULT_KNOWLEDGE_UPLOAD_PARSE_SETTINGS,
    }
    renderUploadPage({
      step: "segment",
      routeState,
      handler: (url, init) => {
        const method = init?.method ?? "GET"
        if (method === "DELETE" && url.includes("/documents")) {
          deletes.push(url)
          return jsonResponse(null, 204)
        }
        if (url.includes("/models")) return jsonResponse(models)
        if (url.includes("/knowledge-bases?")) {
          return jsonResponse([makeKnowledgeBase()])
        }
        if (url.includes("/chunks")) {
          return jsonResponse([
            makeChunk({ id: "chunk-1", content: "guide chunk one" }),
          ])
        }
        if (url.includes("/documents") && url.includes("include_staged")) {
          return jsonResponse([makeDocument()])
        }
        if (url.includes("/documents")) return jsonResponse([])
        return jsonResponse([])
      },
    })

    await waitFor(() => {
      expect(screen.getByText("guide chunk one")).toBeTruthy()
    })
    fireEvent.click(screen.getByRole("button", { name: "上一步" }))

    await waitFor(() => {
      expect(deletes).toHaveLength(1)
    })
    expect(deletes[0]).toContain("/documents/doc-1")
    expect(replaces).toContain(`/app/knowledge/${KB_ID}/upload`)
  })

  test("runs the onDone callback when the import finishes", async () => {
    const indexCalls: string[] = []
    const routeState: KnowledgeUploadRouteState = {
      documentIds: ["doc-1"],
      parseSettings: DEFAULT_KNOWLEDGE_UPLOAD_PARSE_SETTINGS,
    }
    renderUploadPage({
      step: "segment",
      routeState,
      handler: (url, init) => {
        const method = init?.method ?? "GET"
        if (method === "POST" && url.includes("/index")) {
          indexCalls.push(url)
          return jsonResponse(makeTask())
        }
        if (url.includes("/models")) return jsonResponse(models)
        if (url.includes("/knowledge-bases?")) {
          return jsonResponse([makeKnowledgeBase()])
        }
        if (url.includes("/chunks")) {
          return jsonResponse([
            makeChunk({ id: "chunk-1", content: "guide chunk one" }),
          ])
        }
        if (url.includes("/documents") && url.includes("include_staged")) {
          return jsonResponse([makeDocument()])
        }
        if (url.includes("/documents")) return jsonResponse([])
        if (url.includes("/tasks")) return jsonResponse([])
        return jsonResponse([])
      },
    })

    await waitFor(() => {
      expect(
        (screen.getByRole("button", { name: "开始导入" }) as HTMLButtonElement)
          .disabled,
      ).toBe(false)
    })
    fireEvent.click(screen.getByRole("button", { name: "开始导入" }))

    await waitFor(() => {
      expect(indexCalls).toHaveLength(1)
    })
    expect(
      notifications.some(([, msg]) => msg === "已提交 1 个向量化任务"),
    ).toBe(true)
    await waitFor(() => {
      expect(replaces).toContain(`/app/knowledge/${KB_ID}`)
    })
  })
})
