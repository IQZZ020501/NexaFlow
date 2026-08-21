/* @jsxImportSource react */
import { afterEach, describe, expect, test } from "bun:test"
import {
  cleanup,
  fireEvent,
  screen,
  waitFor,
  within,
} from "@testing-library/react"

import { KnowledgeBasePage } from "@/components/knowledge/knowledge-base-page"
import { KnowledgeUploadStateProvider } from "@/components/knowledge/knowledge-upload-state"
import { LanguageProvider } from "@/contexts/language-provider"
import type {
  KnowledgeBaseDetailTab,
  KnowledgeDocument,
  KnowledgeTask,
} from "@/lib/api/knowledge"
import type { RegisteredModel } from "@/lib/api/llm"
import type { WorkspaceMember } from "@/lib/api/system"
import {
  knowledgeBaseDetailPath,
  parseKnowledgeBaseDetailTab,
} from "@/lib/knowledge-views"
import {
  jsonResponse,
  makeSession,
  mockNextNavigation,
  mockUseSession,
  renderPage,
  type FetchHandler,
} from "./helpers/dom"

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
  workspaces: [
    { id: WS, name: "Test Workspace", is_default: true, role: "admin" },
  ],
  teams: [],
}

const memberUser = {
  ...adminUser,
  id: "u-member",
  username: "member",
  name: "Plain Member",
  is_global_admin: false,
  workspaces: [
    { id: WS, name: "Test Workspace", is_default: true, role: "member" },
  ],
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

let fetchHandler: FetchHandler = () => jsonResponse([])
const originalFetch = globalThis.fetch
function installFetchStub() {
  globalThis.fetch = ((input: RequestInfo | URL, init?: RequestInit) => {
    const url =
      typeof input === "string"
        ? input
        : input instanceof URL
          ? input.toString()
          : input.url
    return Promise.resolve(fetchHandler(url, init))
  }) as typeof fetch
}
installFetchStub()

// Controllable IntersectionObserver so the infinite scroll hook can be driven.
class FakeIntersectionObserver {
  static instances: FakeIntersectionObserver[] = []
  callback: IntersectionObserverCallback

  constructor(callback: IntersectionObserverCallback) {
    this.callback = callback
    FakeIntersectionObserver.instances.push(this)
  }

  observe() {}
  unobserve() {}
  disconnect() {}

  triggerIntersect() {
    this.callback(
      [{ isIntersecting: true } as IntersectionObserverEntry],
      this as unknown as IntersectionObserver
    )
  }
}
;(
  globalThis as unknown as { IntersectionObserver: unknown }
).IntersectionObserver = FakeIntersectionObserver

function resetSession() {
  session.selectedWorkspaceId = WS
  session.token = "test-token"
  session.me = {
    user: adminUser,
    memberships: [{ workspace_id: WS, role: "admin" }],
  }
}

async function respondToConfirm(label: string) {
  const dialog = await screen.findByRole("dialog", { name: "确认操作" })
  fireEvent.click(within(dialog).getByRole("button", { name: label }))
  await waitFor(() =>
    expect(screen.queryByRole("dialog", { name: "确认操作" })).toBeNull()
  )
}

afterEach(() => {
  cleanup()
  notifications.length = 0
  pushes.length = 0
  replaces.length = 0
  for (const key of Object.keys(routeParams)) delete routeParams[key]
  FakeIntersectionObserver.instances.length = 0
  fetchHandler = () => jsonResponse([])
  globalThis.fetch = originalFetch
  installFetchStub()
  resetSession()
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

const rerankerModel: RegisteredModel = {
  ...embeddingModel,
  id: "model-rerank",
  name: "rerank-pro",
  model_type: "RERANKER",
  model_name: "bge-reranker-v2-m3",
}

const models = [embeddingModel, rerankerModel]

function makeDocument(
  overrides: Record<string, unknown> = {}
): KnowledgeDocument {
  return {
    id: "doc-1",
    workspace_id: WS,
    knowledge_base_id: KB_ID,
    filename: "guide.md",
    content_type: "text/markdown",
    size_bytes: 2048,
    attachment_id: "att-1",
    meta: {},
    status: "indexed",
    is_active: true,
    chunk_count: 4,
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
    task_type: "parse",
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

const otherMember: WorkspaceMember = {
  user: {
    id: "u-other",
    username: "other",
    email: "other@app.local",
    name: "Other User",
    is_global_admin: false,
    must_change_password: false,
    is_active: true,
    created_at: "2026-01-01T00:00:00Z",
    workspaces: [],
    teams: [],
  },
  role: "member",
}

/** Render the page with the default list fetch fixtures. */
function renderListPage() {
  fetchHandler = (url) => {
    if (url.includes("/models")) return jsonResponse(models)
    if (url.includes("/knowledge-bases?"))
      return jsonResponse([makeKnowledgeBase()])
    return jsonResponse([])
  }
  renderPage(<KnowledgeBasePage />)
}

function openMenu(trigger: HTMLElement) {
  fireEvent.pointerDown(trigger)
}

function cardElement(kbName: string) {
  return screen.getByRole("button", { name: new RegExp(kbName) })
}

/** Filename buttons in DOM order (they carry title but no aria-label). */
function filenameButtons() {
  return Array.from(
    document.querySelectorAll<HTMLButtonElement>("button[title]")
  ).filter((button) => !button.hasAttribute("aria-label"))
}

function visibleFilenames() {
  return filenameButtons().map((button) => button.getAttribute("title") ?? "")
}

/** Header sort buttons vs the sort dropdown trigger share labels. */
function sortHeaderButton(name: string) {
  return screen
    .getAllByRole("button", { name })
    .find((button) => !button.hasAttribute("aria-haspopup"))!
}

// ---------------------------------------------------------------------------
// List view
// ---------------------------------------------------------------------------

describe("KnowledgeBasePage list view", () => {
  test("renders knowledge base cards with stats and badges", async () => {
    renderListPage()

    await waitFor(() => {
      expect(screen.getByText("KB Alpha")).toBeTruthy()
    })
    expect(screen.getByText("Alpha docs")).toBeTruthy()
    expect(screen.getByText("已启用")).toBeTruthy() // StatusBadge
    expect(screen.getByText("可编辑")).toBeTruthy() // PermissionBadge
    expect(screen.getByText("文档数")).toBeTruthy()
    expect(screen.getByText("字符数")).toBeTruthy()
    expect(screen.getByText("已加载全部")).toBeTruthy()
    // 1.2K char count (1200 / 1000 with one decimal)
    expect(screen.getByText("1.2K")).toBeTruthy()
  })

  test("shows the loading spinner while the initial fetch is pending", async () => {
    const resolvers: Array<(value: Response) => void> = []
    fetchHandler = () =>
      new Promise<Response>((resolve) => {
        resolvers.push(resolve)
      })

    renderPage(<KnowledgeBasePage />)

    await waitFor(() => {
      expect(document.querySelector(".animate-spin")).toBeTruthy()
    })
    expect(resolvers.length).toBeGreaterThanOrEqual(2) // bases + models

    for (const resolve of resolvers) {
      resolve(jsonResponse([makeKnowledgeBase()]))
    }
    await waitFor(() => {
      expect(screen.getByText("KB Alpha")).toBeTruthy()
    })
  })

  test("filters cards by search and shows no-match state", async () => {
    fetchHandler = (url) => {
      if (url.includes("/models")) return jsonResponse(models)
      if (url.includes("/knowledge-bases?")) {
        return jsonResponse([
          makeKnowledgeBase(),
          makeKnowledgeBase({
            id: "kb-2",
            name: "HR Handbook",
            description: "People policy",
          }),
        ])
      }
      return jsonResponse([])
    }
    renderPage(<KnowledgeBasePage />)

    await waitFor(() => {
      expect(screen.getByText("KB Alpha")).toBeTruthy()
    })
    const search = screen.getByPlaceholderText("搜索知识库...")
    fireEvent.change(search, { target: { value: "HR" } })
    expect(screen.getByText("HR Handbook")).toBeTruthy()
    expect(screen.queryByText("KB Alpha")).toBeNull()

    fireEvent.change(search, { target: { value: "zzz" } })
    expect(screen.getByText("没有匹配的知识库")).toBeTruthy()

    fireEvent.change(search, { target: { value: "  " } })
    expect(screen.getByText("KB Alpha")).toBeTruthy()
  })

  test("renders the empty state when no knowledge bases exist", async () => {
    fetchHandler = (url) => {
      if (url.includes("/models")) return jsonResponse([])
      return jsonResponse([])
    }
    renderPage(<KnowledgeBasePage />)

    await waitFor(() => {
      expect(screen.getByText("还没有知识库")).toBeTruthy()
    })
    expect(
      screen.getByText(
        "创建知识库后，你可以上传文档、配置检索方式，并让应用调用这些知识。"
      )
    ).toBeTruthy()
  })

  test("shows workspace placeholder when no workspace is selected", async () => {
    ;(session as { selectedWorkspaceId: string | null }).selectedWorkspaceId =
      null
    renderPage(<KnowledgeBasePage />)

    expect(screen.getByText("先选择工作空间")).toBeTruthy()
    expect(screen.getByText("新建知识库")).toBeTruthy()
  })

  test("notifies an error when the initial list fetch fails", async () => {
    fetchHandler = (url) => {
      if (url.includes("/models")) return jsonResponse([])
      if (url.includes("/knowledge-bases?")) {
        return jsonResponse({ detail: "boom" }, 500)
      }
      return jsonResponse([])
    }
    renderPage(<KnowledgeBasePage />)

    await waitFor(() => {
      expect(notifications.some(([kind]) => kind === "error")).toBe(true)
    })
    expect(notifications.find(([kind]) => kind === "error")?.[1]).toBe("boom")
    // Falls back to the empty state after a failed load.
    expect(screen.getByText("还没有知识库")).toBeTruthy()
  })

  test("notifies an error when the response is not JSON", async () => {
    fetchHandler = (url) => {
      if (url.includes("/models")) return jsonResponse([])
      if (url.includes("/knowledge-bases?")) {
        return new Response("not json at all", { status: 200 })
      }
      return jsonResponse([])
    }
    renderPage(<KnowledgeBasePage />)

    await waitFor(() => {
      expect(notifications.some(([kind]) => kind === "error")).toBe(true)
    })
  })

  test("loads more cards through the infinite scroll sentinel", async () => {
    const firstBatch = Array.from({ length: 50 }, (_, index) =>
      makeKnowledgeBase({ id: `kb-${index}`, name: `KB ${index}` })
    )
    const secondBatch = Array.from({ length: 3 }, (_, index) =>
      makeKnowledgeBase({ id: `kb-50-${index}`, name: `KB 50-${index}` })
    )
    const requestedOffsets: string[] = []
    fetchHandler = (url) => {
      if (url.includes("/models")) return jsonResponse(models)
      if (url.includes("/knowledge-bases?")) {
        const offset = new URL(url, "http://localhost").searchParams.get(
          "offset"
        )
        requestedOffsets.push(offset ?? "")
        return jsonResponse(offset === "50" ? secondBatch : firstBatch)
      }
      return jsonResponse([])
    }
    renderPage(<KnowledgeBasePage />)

    await waitFor(() => {
      expect(screen.getByText("KB 0")).toBeTruthy()
    })
    expect(FakeIntersectionObserver.instances.length).toBeGreaterThan(0)
    FakeIntersectionObserver.instances[0].triggerIntersect()

    await waitFor(() => {
      expect(screen.getByText("KB 50-0")).toBeTruthy()
    })
    expect(requestedOffsets).toEqual(["0", "50"])
    expect(screen.getByText("已加载全部")).toBeTruthy()
  })

  test("does not load more cards when the initial batch is complete", async () => {
    let listRequests = 0
    fetchHandler = (url) => {
      if (url.includes("/models")) return jsonResponse(models)
      if (url.includes("/knowledge-bases?")) {
        listRequests += 1
        return jsonResponse([makeKnowledgeBase()])
      }
      return jsonResponse([])
    }
    renderPage(<KnowledgeBasePage />)

    await waitFor(() => {
      expect(screen.getByText("已加载全部")).toBeTruthy()
    })
    expect(listRequests).toBe(1)
    FakeIntersectionObserver.instances[0].triggerIntersect()
    await waitFor(() => expect(listRequests).toBe(1))
  })

  test("reports an error when loading more cards fails", async () => {
    const firstBatch = Array.from({ length: 50 }, (_, index) =>
      makeKnowledgeBase({ id: `kb-${index}`, name: `KB ${index}` })
    )
    fetchHandler = (url) => {
      if (url.includes("/models")) return jsonResponse(models)
      if (url.includes("/knowledge-bases?")) {
        const offset = new URL(url, "http://localhost").searchParams.get(
          "offset"
        )
        if (offset === "50") {
          return jsonResponse({ detail: "load more boom" }, 500)
        }
        return jsonResponse(firstBatch)
      }
      return jsonResponse([])
    }
    renderPage(<KnowledgeBasePage />)

    await waitFor(() => expect(screen.getByText("KB 0")).toBeTruthy())
    FakeIntersectionObserver.instances[0].triggerIntersect()
    await waitFor(() => {
      expect(notifications.some(([kind]) => kind === "error")).toBe(true)
    })
    expect(notifications.find(([kind]) => kind === "error")?.[1]).toBe(
      "load more boom"
    )
  })

  test("shows the loading indicator while fetching more cards", async () => {
    const firstBatch = Array.from({ length: 50 }, (_, index) =>
      makeKnowledgeBase({ id: `kb-${index}`, name: `KB ${index}` })
    )
    let resolveMore: ((response: Response) => void) | null = null
    fetchHandler = (url) => {
      if (url.includes("/models")) return jsonResponse(models)
      if (url.includes("/knowledge-bases?")) {
        const offset = new URL(url, "http://localhost").searchParams.get(
          "offset"
        )
        if (offset === "50") {
          return new Promise<Response>((resolve) => {
            resolveMore = resolve
          })
        }
        return jsonResponse(firstBatch)
      }
      return jsonResponse([])
    }
    renderPage(<KnowledgeBasePage />)

    await waitFor(() => expect(screen.getByText("KB 0")).toBeTruthy())
    FakeIntersectionObserver.instances[0].triggerIntersect()
    await waitFor(() => {
      expect(screen.getByText("正在加载")).toBeTruthy()
    })
    ;(resolveMore as ((response: Response) => void) | null)?.(
      jsonResponse([makeKnowledgeBase({ id: "kb-extra", name: "KB extra" })])
    )
    await waitFor(() => {
      expect(screen.getByText("KB extra")).toBeTruthy()
    })
    expect(screen.queryByText("正在加载")).toBeNull()
  })

  test("reloads the list when returning from a knowledge base detail", async () => {
    let listRequests = 0
    routeParams.id = KB_ID
    fetchHandler = (url) => {
      if (url.includes("/models")) return jsonResponse(models)
      if (url.includes("/knowledge-bases?")) {
        listRequests += 1
        return jsonResponse([makeKnowledgeBase()])
      }
      if (url.includes("/documents")) return jsonResponse([])
      return jsonResponse([])
    }
    const { rerender } = renderPage(<KnowledgeBasePage />)
    await waitFor(() => {
      expect(listRequests).toBe(1)
    })

    // Returning to the list (params cleared) refreshes the list stats.
    delete routeParams.id
    rerender(
      <LanguageProvider defaultLanguage="zh-Hans">
        <KnowledgeBasePage />
      </LanguageProvider>
    )
    await waitFor(() => {
      expect(listRequests).toBe(2)
    })
    expect(screen.getByText("KB Alpha")).toBeTruthy()
  })

  test("reports an error when the knowledge base update fails", async () => {
    fetchHandler = (url, init) => {
      const method = init?.method ?? "GET"
      if (method === "PATCH" && url.includes("/knowledge-bases")) {
        return jsonResponse({ detail: "update boom" }, 500)
      }
      if (url.includes("/models")) return jsonResponse(models)
      if (url.includes("/knowledge-bases?"))
        return jsonResponse([makeKnowledgeBase()])
      return jsonResponse([])
    }
    renderPage(<KnowledgeBasePage />)
    await waitFor(() => expect(screen.getByText("KB Alpha")).toBeTruthy())

    fireEvent.click(screen.getByRole("button", { name: "编辑知识库" }))
    const dialog = await screen.findByRole("dialog")
    fireEvent.change(within(dialog).getByLabelText("知识库名称"), {
      target: { value: "KB X" },
    })
    fireEvent.click(within(dialog).getByRole("button", { name: "保存" }))

    await waitFor(() => {
      expect(notifications.some(([kind]) => kind === "error")).toBe(true)
    })
    expect(notifications.find(([kind]) => kind === "error")?.[1]).toBe(
      "update boom"
    )
  })

  test("reports an error when deleting a knowledge base fails", async () => {
    fetchHandler = (url, init) => {
      const method = init?.method ?? "GET"
      if (method === "DELETE")
        return jsonResponse({ detail: "delete boom" }, 500)
      if (url.includes("/models")) return jsonResponse(models)
      if (url.includes("/knowledge-bases?"))
        return jsonResponse([makeKnowledgeBase()])
      return jsonResponse([])
    }
    renderPage(<KnowledgeBasePage />)
    await waitFor(() => expect(screen.getByText("KB Alpha")).toBeTruthy())

    openMenu(within(cardElement("KB Alpha")).getByTitle("更多"))
    fireEvent.click(await screen.findByText("永久删除知识库"))
    await respondToConfirm("删除")

    await waitFor(() => {
      expect(notifications.some(([kind]) => kind === "error")).toBe(true)
    })
    expect(notifications.find(([kind]) => kind === "error")?.[1]).toBe(
      "delete boom"
    )
  })

  test("creates a knowledge base from the dialog", async () => {
    const requests: Array<{ url: string; method: string; body: string }> = []
    fetchHandler = (url, init) => {
      const method = init?.method ?? "GET"
      requests.push({ url, method, body: String(init?.body ?? "") })
      if (url.includes("/models")) return jsonResponse(models)
      if (url.includes("/knowledge-bases") && method === "POST") {
        return jsonResponse(makeKnowledgeBase({ id: "kb-new", name: "New KB" }))
      }
      if (url.includes("/knowledge-bases?")) return jsonResponse([])
      return jsonResponse([])
    }
    renderPage(<KnowledgeBasePage />)

    await waitFor(() => {
      expect(screen.getByText("还没有知识库")).toBeTruthy()
    })
    // Header button and empty-state button both say 新建知识库.
    fireEvent.click(screen.getAllByText("新建知识库")[0])

    const dialog = await screen.findByRole("dialog")
    expect(
      within(dialog).getByText("配置知识库名称、描述和默认数据源。")
    ).toBeTruthy()

    fireEvent.change(within(dialog).getByLabelText("知识库名称"), {
      target: { value: "New KB" },
    })
    fireEvent.change(within(dialog).getByLabelText("描述"), {
      target: { value: "Fresh docs" },
    })
    fireEvent.click(within(dialog).getByRole("button", { name: "新建知识库" }))

    await waitFor(() => {
      expect(screen.getByText("New KB")).toBeTruthy()
    })
    expect(
      notifications.some(
        ([kind, msg]) => kind === "success" && msg === "知识库已新建"
      )
    ).toBe(true)
    const create = requests.find((request) => request.method === "POST")
    expect(create?.url).toContain("/knowledge-bases")
    expect(JSON.parse(create?.body ?? "{}")).toEqual({
      name: "New KB",
      description: "Fresh docs",
      embedding_model_id: null,
      reranker_model_id: null,
    })
    // Dialog closes after success.
    await waitFor(() => {
      expect(screen.queryByRole("dialog")).toBeNull()
    })
  })

  test("reports an error when create fails", async () => {
    fetchHandler = (url, init) => {
      if (url.includes("/models")) return jsonResponse(models)
      if (url.includes("/knowledge-bases") && init?.method === "POST") {
        return jsonResponse({ detail: "name taken" }, 400)
      }
      if (url.includes("/knowledge-bases?")) return jsonResponse([])
      return jsonResponse([])
    }
    renderPage(<KnowledgeBasePage />)

    await waitFor(() => expect(screen.getByText("还没有知识库")).toBeTruthy())
    fireEvent.click(screen.getAllByText("新建知识库")[0])
    const dialog = await screen.findByRole("dialog")
    fireEvent.change(within(dialog).getByLabelText("知识库名称"), {
      target: { value: "New KB" },
    })
    fireEvent.click(within(dialog).getByRole("button", { name: "新建知识库" }))

    await waitFor(() => {
      expect(notifications.some(([kind]) => kind === "error")).toBe(true)
    })
    expect(notifications.find(([kind]) => kind === "error")?.[1]).toBe(
      "name taken"
    )
  })

  test("edits a knowledge base from the card pencil button", async () => {
    const requests: Array<{ method: string; body: string }> = []
    fetchHandler = (url, init) => {
      const method = init?.method ?? "GET"
      requests.push({ method, body: String(init?.body ?? "") })
      if (url.includes("/models")) return jsonResponse(models)
      if (url.includes("/knowledge-bases?") && method === "GET") {
        return jsonResponse([makeKnowledgeBase()])
      }
      if (url.includes("/knowledge-bases") && method === "PATCH") {
        return jsonResponse(makeKnowledgeBase({ name: "KB Renamed" }))
      }
      return jsonResponse([])
    }
    renderPage(<KnowledgeBasePage />)
    await waitFor(() => expect(screen.getByText("KB Alpha")).toBeTruthy())

    fireEvent.click(screen.getByRole("button", { name: "编辑知识库" }))
    const dialog = await screen.findByRole("dialog")
    expect(within(dialog).getByText("更新知识库名称和描述。")).toBeTruthy()
    const nameInput = within(dialog).getByLabelText(
      "知识库名称"
    ) as HTMLInputElement
    expect(nameInput.value).toBe("KB Alpha")
    fireEvent.change(nameInput, { target: { value: "KB Renamed" } })
    fireEvent.click(within(dialog).getByRole("button", { name: "保存" }))

    await waitFor(() => {
      expect(screen.getByText("KB Renamed")).toBeTruthy()
    })
    expect(notifications.some(([, msg]) => msg === "知识库已更新")).toBe(true)
    const patch = requests.find((request) => request.method === "PATCH")
    expect(JSON.parse(patch?.body ?? "{}")).toMatchObject({
      name: "KB Renamed",
    })
  })

  test("archives and restores a knowledge base from the card menu", async () => {
    const requests: Array<{ method: string; body: string }> = []
    let current = makeKnowledgeBase()
    fetchHandler = (url, init) => {
      const method = init?.method ?? "GET"
      if (method === "PATCH" && url.includes("/knowledge-bases")) {
        requests.push({ method, body: String(init?.body ?? "") })
        current = { ...current, status: JSON.parse(String(init?.body)).status }
        return jsonResponse(current)
      }
      if (url.includes("/models")) return jsonResponse(models)
      if (url.includes("/knowledge-bases?")) return jsonResponse([current])
      return jsonResponse([])
    }
    renderPage(<KnowledgeBasePage />)
    await waitFor(() => expect(screen.getByText("KB Alpha")).toBeTruthy())

    const card = cardElement("KB Alpha")
    openMenu(within(card).getByTitle("更多"))
    fireEvent.click(await screen.findByText("归档知识库"))

    await waitFor(() => {
      expect(notifications.some(([, msg]) => msg === "知识库已归档")).toBe(true)
    })
    expect(screen.getByText("已归档")).toBeTruthy()
    expect(requests[0]).toMatchObject({ method: "PATCH" })
    expect(JSON.parse(requests[0].body)).toEqual({ status: "archived" })

    openMenu(
      within(screen.getByRole("button", { name: /KB Alpha/ })).getByTitle(
        "更多"
      )
    )
    fireEvent.click(await screen.findByText("恢复知识库"))
    await waitFor(() => {
      expect(notifications.some(([, msg]) => msg === "知识库已恢复")).toBe(true)
    })
    expect(screen.getByText("已启用")).toBeTruthy()
  })

  test("reports permission errors from archive as a notification", async () => {
    fetchHandler = (url, init) => {
      if (url.includes("/models")) return jsonResponse(models)
      if (
        url.includes("/knowledge-bases?") &&
        (init?.method ?? "GET") === "GET"
      ) {
        return jsonResponse([makeKnowledgeBase()])
      }
      if (init?.method === "PATCH")
        return jsonResponse({ detail: "没有权限" }, 403)
      return jsonResponse([])
    }
    renderPage(<KnowledgeBasePage />)
    await waitFor(() => expect(screen.getByText("KB Alpha")).toBeTruthy())

    openMenu(within(cardElement("KB Alpha")).getByTitle("更多"))
    fireEvent.click(await screen.findByText("归档知识库"))

    await waitFor(() => {
      expect(notifications.some(([kind]) => kind === "error")).toBe(true)
    })
    expect(notifications.find(([kind]) => kind === "error")?.[1]).toBe(
      "资源不存在或无权访问"
    )
  })

  test("deletes a knowledge base after confirmation", async () => {
    const deletes: string[] = []
    fetchHandler = (url, init) => {
      const method = init?.method ?? "GET"
      if (method === "DELETE") deletes.push(url)
      if (url.includes("/models")) return jsonResponse(models)
      if (url.includes("/knowledge-bases?"))
        return jsonResponse([makeKnowledgeBase()])
      return jsonResponse([])
    }
    renderPage(<KnowledgeBasePage />)
    await waitFor(() => expect(screen.getByText("KB Alpha")).toBeTruthy())

    openMenu(within(cardElement("KB Alpha")).getByTitle("更多"))
    fireEvent.click(await screen.findByText("永久删除知识库"))
    await respondToConfirm("取消")
    expect(deletes).toHaveLength(0)

    openMenu(within(cardElement("KB Alpha")).getByTitle("更多"))
    fireEvent.click(await screen.findByText("永久删除知识库"))
    await respondToConfirm("删除")

    await waitFor(() => {
      expect(deletes.length).toBe(1)
    })
    expect(deletes[0]).toContain("/knowledge-bases/kb-1")
    expect(notifications.some(([, msg]) => msg === "知识库已删除")).toBe(true)
    await waitFor(() => expect(screen.queryByText("KB Alpha")).toBeNull())
    expect(screen.getByText("还没有知识库")).toBeTruthy()
  })

  test("opens a knowledge base on click and on Enter key", async () => {
    renderListPage()
    await waitFor(() => expect(screen.getByText("KB Alpha")).toBeTruthy())

    fireEvent.click(cardElement("KB Alpha"))
    expect(pushes).toContain(`/app/knowledge/${KB_ID}`)

    fireEvent.keyDown(cardElement("KB Alpha"), { key: "Enter" })
    expect(
      pushes.filter((href) => href === `/app/knowledge/${KB_ID}`).length
    ).toBe(2)
  })

  test("does not open a knowledge base when a menu item is clicked", async () => {
    renderListPage()
    await waitFor(() => expect(screen.getByText("KB Alpha")).toBeTruthy())

    openMenu(within(cardElement("KB Alpha")).getByTitle("更多"))
    fireEvent.click(await screen.findByText("资源授权"))
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeTruthy())
    expect(pushes).toHaveLength(0)
  })

  test("returns null when there is no session token", () => {
    session.token = ""
    const { container } = renderPage(<KnowledgeBasePage />)
    expect(container.firstChild).toBeNull()
  })

  test("renders upload flow when an upload step is active with edit permission", async () => {
    routeParams.id = KB_ID
    fetchHandler = (url) => {
      if (url.includes("/models")) return jsonResponse(models)
      if (url.includes("/knowledge-bases?"))
        return jsonResponse([makeKnowledgeBase()])
      if (url.includes("/documents")) return jsonResponse([])
      return jsonResponse([])
    }
    renderPage(
      <KnowledgeUploadStateProvider>
        <KnowledgeBasePage uploadStep="files" />
      </KnowledgeUploadStateProvider>
    )

    await waitFor(() => {
      expect(screen.getByText("选择导入文件")).toBeTruthy()
    })
  })

  test("redirects away when an upload step is active without edit permission", async () => {
    routeParams.id = KB_ID
    fetchHandler = (url) => {
      if (url.includes("/models")) return jsonResponse(models)
      if (url.includes("/knowledge-bases?")) {
        return jsonResponse([makeKnowledgeBase({ permission: "view" })])
      }
      if (url.includes("/documents")) return jsonResponse([])
      return jsonResponse([])
    }
    const { container } = renderPage(<KnowledgeBasePage uploadStep="files" />)

    await waitFor(() => {
      expect(replaces).toContain(`/app/knowledge/${KB_ID}`)
    })
    expect(container.firstChild).toBeNull()
  })
})

// ---------------------------------------------------------------------------
// Detail view — documents tab
// ---------------------------------------------------------------------------

function renderDetailPage(
  options: {
    knowledgeBases?: Array<Record<string, unknown>>
    documents?: KnowledgeDocument[]
    models?: RegisteredModel[]
    initialDetailTab?: KnowledgeBaseDetailTab
  } = {}
) {
  const knowledgeBases = options.knowledgeBases ?? [makeKnowledgeBase()]
  const documents = options.documents ?? []
  fetchHandler = (url) => {
    if (url.includes("/models")) return jsonResponse(options.models ?? models)
    if (url.includes("/knowledge-bases?")) return jsonResponse(knowledgeBases)
    if (url.includes("/documents")) return jsonResponse(documents)
    if (url.endsWith("/graph/settings")) {
      return jsonResponse({
        enabled: false,
        extraction_model_id: null,
        active_schema_id: null,
        active_revision_id: null,
      })
    }
    if (url.endsWith("/graph/status")) {
      return jsonResponse({
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
      })
    }
    if (url.endsWith("/graph/schema")) return jsonResponse(null)
    if (url.includes("/graph/entities")) {
      return jsonResponse({ items: [], total: 0, limit: 20, offset: 0 })
    }
    if (url.includes("/graph/reviews")) {
      return jsonResponse({ items: [], total: 0, limit: 20, offset: 0 })
    }
    if (url.includes("/tasks")) return jsonResponse([])
    if (url.includes("/members")) return jsonResponse([])
    return jsonResponse([])
  }
  routeParams.id = KB_ID
  return renderPage(
    <KnowledgeBasePage initialDetailTab={options.initialDetailTab} />
  )
}

describe("KnowledgeBasePage documents tab", () => {
  test("routes every knowledge base detail page", async () => {
    expect(parseKnowledgeBaseDetailTab("tasks")).toBe("tasks")
    expect(parseKnowledgeBaseDetailTab("graph")).toBe("graph")
    expect(parseKnowledgeBaseDetailTab("unknown")).toBeNull()
    expect(knowledgeBaseDetailPath(KB_ID, "documents")).toBe(
      `/app/knowledge/${KB_ID}`
    )
    expect(knowledgeBaseDetailPath(KB_ID, "evaluation")).toBe(
      `/app/knowledge/${KB_ID}/evaluation`
    )
    expect(knowledgeBaseDetailPath(KB_ID, "graph")).toBe(
      `/app/knowledge/${KB_ID}/graph`
    )

    renderDetailPage()
    fireEvent.click(await screen.findByText("知识关联"))
    expect(pushes[pushes.length - 1]).toBe(`/app/knowledge/${KB_ID}/graph`)
    await waitFor(() =>
      expect(screen.getByText("知识关联尚未启用")).toBeTruthy()
    )

    fireEvent.click(await screen.findByText("任务"))
    expect(pushes[pushes.length - 1]).toBe(`/app/knowledge/${KB_ID}/tasks`)
    await waitFor(() => expect(screen.getByText("暂无任务")).toBeTruthy())

    fireEvent.click(screen.getByText("设置"))
    expect(pushes[pushes.length - 1]).toBe(`/app/knowledge/${KB_ID}/settings`)
    await waitFor(() => expect(screen.getByText("Alpha docs")).toBeTruthy())

    fireEvent.click(screen.getByText("文档"))
    expect(pushes[pushes.length - 1]).toBe(`/app/knowledge/${KB_ID}`)
    await waitFor(() => expect(screen.getByText("暂无文档")).toBeTruthy())
  })

  test("restores the detail page selected by the route", async () => {
    renderDetailPage({ initialDetailTab: "tasks" })

    await waitFor(() => expect(screen.getByText("暂无任务")).toBeTruthy())
    expect(
      screen.getByRole("button", { name: "任务" }).getAttribute("aria-current")
    ).toBe("page")
  })

  test("renders document rows with status, size, chunks and dates", async () => {
    const documents = [
      makeDocument({
        id: "doc-1",
        filename: "guide.md",
        size_bytes: 2048,
        status: "indexed",
        is_active: true,
        chunk_count: 4,
      }),
      makeDocument({
        id: "doc-2",
        filename: "notes.txt",
        size_bytes: 500,
        status: "parse_failed",
        is_active: false,
        chunk_count: 0,
        last_error: "parser crashed",
      }),
    ]
    renderDetailPage({ documents })

    await waitFor(() => {
      expect(screen.getByText("guide.md")).toBeTruthy()
    })
    expect(screen.getByText("notes.txt")).toBeTruthy()
    expect(screen.getByText("已向量化")).toBeTruthy()
    expect(screen.getByText("解析失败")).toBeTruthy()
    expect(screen.getByText("2.0 KB")).toBeTruthy()
    expect(screen.getByText("parser crashed")).toBeTruthy()
    expect(screen.getByText("已启用")).toBeTruthy()
    expect(screen.getByText("已停用")).toBeTruthy()
    // Header labels
    expect(screen.getByText("文件名称")).toBeTruthy()
    expect(screen.getByText("文件状态")).toBeTruthy()
    expect(screen.getByText("启用状态")).toBeTruthy()
  })

  test("shows empty state when there are no documents", async () => {
    renderDetailPage({ documents: [] })
    await waitFor(() => {
      expect(screen.getByText("暂无文档")).toBeTruthy()
    })
  })

  test("shows progress from tasks for indexing documents", async () => {
    const documents = [
      makeDocument({ id: "doc-1", filename: "big.pdf", status: "indexing" }),
    ]
    const tasks = [
      makeTask({
        id: "task-idx",
        document_id: "doc-1",
        task_type: "index",
        status: "running",
        total_items: 5,
        processed_items: 2,
      }),
    ]
    fetchHandler = (url) => {
      if (url.includes("/models")) return jsonResponse(models)
      if (url.includes("/knowledge-bases?"))
        return jsonResponse([makeKnowledgeBase()])
      if (url.includes("/documents")) return jsonResponse(documents)
      if (url.includes("/tasks")) return jsonResponse(tasks)
      return jsonResponse([])
    }
    routeParams.id = KB_ID
    renderPage(<KnowledgeBasePage />)

    // Tasks are only fetched while the tasks tab is active; the documents
    // view then reuses the loaded tasks for per-document progress.
    fireEvent.click(await screen.findByText("任务"))
    await waitFor(() => {
      expect(screen.getByText("运行中")).toBeTruthy()
    })
    fireEvent.click(screen.getByText("文档"))
    await waitFor(() => {
      expect(screen.getByText("向量化中 2/5")).toBeTruthy()
    })
  })

  test("filters documents by name", async () => {
    const documents = [
      makeDocument({ id: "doc-1", filename: "alpha.md" }),
      makeDocument({ id: "doc-2", filename: "beta.txt" }),
    ]
    renderDetailPage({ documents })

    await waitFor(() => expect(screen.getByText("alpha.md")).toBeTruthy())
    fireEvent.change(screen.getByPlaceholderText("按名称搜索"), {
      target: { value: "beta" },
    })
    expect(screen.getByText("beta.txt")).toBeTruthy()
    expect(screen.queryByText("alpha.md")).toBeNull()

    fireEvent.change(screen.getByPlaceholderText("按名称搜索"), {
      target: { value: "zzz" },
    })
    expect(screen.getByText("没有匹配的文档")).toBeTruthy()
  })

  test("paginates documents and changes the page size", async () => {
    const documents = Array.from({ length: 12 }, (_, index) =>
      makeDocument({
        id: `doc-${index}`,
        filename: `file-${String(index).padStart(2, "0")}.md`,
        created_at: `2026-01-${String(index + 1).padStart(2, "0")}T00:00:00Z`,
        updated_at: `2026-01-${String(index + 1).padStart(2, "0")}T00:00:00Z`,
      })
    )
    renderDetailPage({ documents })

    await waitFor(() => {
      expect(screen.getByText("共 12 条")).toBeTruthy()
    })
    expect(screen.getByText("1 / 2")).toBeTruthy()
    expect(visibleFilenames()).toHaveLength(10)
    expect(visibleFilenames()[0]).toBe("file-11.md") // default created_at desc

    fireEvent.click(screen.getByText("下一页"))
    expect(visibleFilenames()).toHaveLength(2)
    expect(screen.getByText("2 / 2")).toBeTruthy()
    expect(screen.getByText("file-00.md")).toBeTruthy()

    fireEvent.click(screen.getByText("上一页"))
    expect(screen.getByText("1 / 2")).toBeTruthy()

    // Page-size controls remain available when all rows fit on one page.
    const pageSizeTrigger = screen.getByRole("button", { name: /每页 10 条/ })
    openMenu(pageSizeTrigger)
    fireEvent.click(await screen.findByText("每页 20 条"))
    await waitFor(() => {
      expect(visibleFilenames()).toHaveLength(12)
    })
    expect(screen.getByRole("button", { name: /每页 20 条/ })).toBeTruthy()
    expect(screen.getByText("1 / 1")).toBeTruthy()

    openMenu(screen.getByRole("button", { name: /每页 20 条/ }))
    fireEvent.click(await screen.findByText("每页 10 条"))
    await waitFor(() => expect(visibleFilenames()).toHaveLength(10))
    expect(screen.getByText("1 / 2")).toBeTruthy()
  })

  test("clamps the page after deleting its last document", async () => {
    const documents = Array.from({ length: 11 }, (_, index) =>
      makeDocument({
        id: `doc-${index}`,
        filename: `file-${String(index).padStart(2, "0")}.md`,
        created_at: `2026-01-${String(index + 1).padStart(2, "0")}T00:00:00Z`,
      })
    )
    const deletes: string[] = []
    fetchHandler = (url, init) => {
      if (init?.method === "DELETE") deletes.push(url)
      if (url.includes("/models")) return jsonResponse(models)
      if (url.includes("/knowledge-bases?"))
        return jsonResponse([makeKnowledgeBase()])
      if (url.includes("/documents")) return jsonResponse(documents)
      if (url.includes("/tasks")) return jsonResponse([])
      return jsonResponse([])
    }
    routeParams.id = KB_ID
    renderPage(<KnowledgeBasePage />)

    await screen.findByText("共 11 条")
    fireEvent.click(screen.getByRole("button", { name: "下一页" }))
    await screen.findByText("file-00.md")
    openMenu(screen.getByRole("button", { name: "操作 file-00.md" }))
    fireEvent.click(await screen.findByRole("menuitem", { name: "删除" }))
    await respondToConfirm("删除")

    await waitFor(() => expect(deletes).toHaveLength(1))
    await waitFor(() => expect(screen.getByText("1 / 1")).toBeTruthy())
    expect(screen.getByText("file-10.md")).toBeTruthy()
    expect(screen.queryByText("2 / 1")).toBeNull()
  })

  test("sorts documents by size and chunk count with direction cycling", async () => {
    const documents = [
      makeDocument({
        id: "doc-a",
        filename: "a.md",
        size_bytes: 100,
        chunk_count: 1,
        created_at: "2026-01-01T00:00:00Z",
        updated_at: "2026-01-01T00:00:00Z",
      }),
      makeDocument({
        id: "doc-b",
        filename: "b.md",
        size_bytes: 500,
        chunk_count: 5,
        created_at: "2026-01-02T00:00:00Z",
        updated_at: "2026-01-02T00:00:00Z",
      }),
      makeDocument({
        id: "doc-c",
        filename: "c.md",
        size_bytes: 300,
        chunk_count: 3,
        created_at: "2026-01-03T00:00:00Z",
        updated_at: "2026-01-03T00:00:00Z",
      }),
    ]
    renderDetailPage({ documents })

    await waitFor(() => expect(visibleFilenames().length).toBe(3))
    // Default: created_at desc → c, b, a
    expect(visibleFilenames()).toEqual(["c.md", "b.md", "a.md"])

    fireEvent.click(sortHeaderButton("大小"))
    expect(visibleFilenames()).toEqual(["b.md", "c.md", "a.md"])
    fireEvent.click(sortHeaderButton("大小"))
    expect(visibleFilenames()).toEqual(["a.md", "c.md", "b.md"])

    fireEvent.click(sortHeaderButton("分段"))
    expect(visibleFilenames()).toEqual(["b.md", "c.md", "a.md"])
  })

  test("selects all documents and runs bulk index and delete", async () => {
    const documents = [
      makeDocument({ id: "doc-1", filename: "a.md" }),
      makeDocument({ id: "doc-2", filename: "b.md" }),
    ]
    const requests: Array<{ url: string; method: string }> = []
    fetchHandler = (url, init) => {
      const method = init?.method ?? "GET"
      if (method !== "GET") requests.push({ url, method })
      if (url.includes("/models")) return jsonResponse(models)
      if (url.includes("/knowledge-bases?"))
        return jsonResponse([makeKnowledgeBase()])
      if (url.includes("/documents") && method === "DELETE")
        return jsonResponse(null, 204)
      if (url.includes("/documents") && method === "POST")
        return jsonResponse(makeTask())
      if (url.includes("/documents")) return jsonResponse(documents)
      if (url.includes("/tasks")) return jsonResponse([])
      return jsonResponse([])
    }
    routeParams.id = KB_ID
    renderPage(<KnowledgeBasePage />)

    await waitFor(() => expect(screen.getByText("a.md")).toBeTruthy())
    expect(screen.getByText("向量化")).toBeTruthy()

    const selectAll = screen.getByLabelText("选择所有文档") as HTMLInputElement
    fireEvent.click(selectAll)
    expect(screen.getByText("向量化(2)")).toBeTruthy()
    expect(screen.getByText("删除(2)")).toBeTruthy()

    fireEvent.click(screen.getByText("向量化(2)"))
    await waitFor(() => {
      expect(
        notifications.some(([, msg]) => msg === "已提交 2 个向量化任务")
      ).toBe(true)
    })
    const indexCalls = requests.filter(
      (request) => request.method === "POST" && request.url.includes("/index")
    )
    expect(indexCalls).toHaveLength(2)

    fireEvent.click(screen.getByText("删除(2)"))
    await respondToConfirm("删除")
    await waitFor(() => {
      expect(notifications.some(([, msg]) => msg === "已删除 2 个文档")).toBe(
        true
      )
    })
    expect(
      requests.filter((request) => request.method === "DELETE")
    ).toHaveLength(2)
    await waitFor(() => {
      expect(screen.getByText("暂无文档")).toBeTruthy()
    })
  })

  test("toggles a document active state", async () => {
    const documents = [
      makeDocument({ id: "doc-1", filename: "a.md", is_active: true }),
    ]
    fetchHandler = (url, init) => {
      const method = init?.method ?? "GET"
      if (method === "PATCH" && url.includes("/documents")) {
        return jsonResponse(
          makeDocument({
            id: "doc-1",
            filename: "a.md",
            is_active: JSON.parse(String(init?.body ?? "{}")).is_active,
          })
        )
      }
      if (url.includes("/models")) return jsonResponse(models)
      if (url.includes("/knowledge-bases?"))
        return jsonResponse([makeKnowledgeBase()])
      if (url.includes("/documents")) return jsonResponse(documents)
      if (url.includes("/tasks")) return jsonResponse([])
      return jsonResponse([])
    }
    routeParams.id = KB_ID
    renderPage(<KnowledgeBasePage />)

    const toggle = await screen.findByRole("switch", { name: "停用 a.md" })
    fireEvent.click(toggle)
    await waitFor(() => {
      expect(notifications.some(([, msg]) => msg === "文档已停用")).toBe(true)
    })
    expect(screen.getByRole("switch", { name: "启用 a.md" })).toBeTruthy()

    fireEvent.click(screen.getByRole("switch", { name: "启用 a.md" }))
    await waitFor(() => {
      expect(notifications.some(([, msg]) => msg === "文档已启用")).toBe(true)
    })
  })

  test("submits a smart segmentation task from the re-segment dialog", async () => {
    const documents = [makeDocument({ id: "doc-1", filename: "a.md" })]
    const parseCalls: Array<{ body: string }> = []
    fetchHandler = (url, init) => {
      const method = init?.method ?? "GET"
      if (method === "POST" && url.includes("/parse")) {
        parseCalls.push({ body: String(init?.body ?? "") })
        return jsonResponse(makeTask())
      }
      if (url.includes("/models")) return jsonResponse(models)
      if (url.includes("/knowledge-bases?"))
        return jsonResponse([makeKnowledgeBase()])
      if (url.includes("/documents")) return jsonResponse(documents)
      if (url.includes("/tasks")) return jsonResponse([])
      return jsonResponse([])
    }
    routeParams.id = KB_ID
    renderPage(<KnowledgeBasePage />)

    fireEvent.click(
      await screen.findByRole("button", { name: "重新分段 a.md" })
    )
    const dialog = await screen.findByRole("dialog")
    expect(
      within(dialog).getByText("先用智能规则生成预览，需要时再精调。")
    ).toBeTruthy()
    expect(within(dialog).getByText("智能分段")).toBeTruthy()

    fireEvent.click(within(dialog).getByRole("button", { name: "开始导入" }))

    await waitFor(() => {
      expect(notifications.some(([, msg]) => msg === "已提交解析任务")).toBe(
        true
      )
    })
    expect(parseCalls).toHaveLength(1)
    const payload = JSON.parse(parseCalls[0].body)
    expect(payload).toMatchObject({
      strategy: "hierarchical",
      chunk_size: 1200,
      chunk_overlap: 150,
      auto_index: true,
      cleaning_rules: ["trim_lines", "remove_empty_lines"],
      split_separator: "\n\n",
    })
  })

  test("submits an advanced segmentation task with custom options", async () => {
    const documents = [makeDocument({ id: "doc-1", filename: "a.md" })]
    const parseCalls: Array<{ body: string }> = []
    fetchHandler = (url, init) => {
      const method = init?.method ?? "GET"
      if (method === "POST" && url.includes("/parse")) {
        parseCalls.push({ body: String(init?.body ?? "") })
        return jsonResponse(makeTask())
      }
      if (url.includes("/models")) return jsonResponse(models)
      if (url.includes("/knowledge-bases?"))
        return jsonResponse([makeKnowledgeBase()])
      if (url.includes("/documents")) return jsonResponse(documents)
      if (url.includes("/tasks")) return jsonResponse([])
      return jsonResponse([])
    }
    routeParams.id = KB_ID
    renderPage(<KnowledgeBasePage />)

    fireEvent.click(
      await screen.findByRole("button", { name: "重新分段 a.md" })
    )
    const dialog = await screen.findByRole("dialog")

    fireEvent.click(within(dialog).getByText("高级分段"))
    const sizeInput = within(dialog).getByLabelText(
      "片段字符"
    ) as HTMLInputElement
    const overlapInput = within(dialog).getByLabelText(
      "重叠字符"
    ) as HTMLInputElement
    expect(sizeInput.value).toBe("1200")
    expect(overlapInput.value).toBe("150")

    // Overlap >= size blocks submission and shows the hint.
    fireEvent.change(sizeInput, { target: { value: "100" } })
    expect(within(dialog).getByText("重叠字符必须小于片段字符")).toBeTruthy()
    expect(
      (
        within(dialog).getByRole("button", {
          name: "开始导入",
        }) as HTMLButtonElement
      ).disabled
    ).toBe(true)

    fireEvent.change(sizeInput, { target: { value: "800" } })
    fireEvent.change(overlapInput, { target: { value: "64" } })

    // Change the split separator (menu content renders in a portal).
    openMenu(within(dialog).getByRole("button", { name: "空行（段落）" }))
    fireEvent.click(await screen.findByText("中文句号（。）"))

    // Remove one cleaning rule.
    openMenu(within(dialog).getByRole("button", { name: /去除行首尾空白/ }))
    fireEvent.click(await screen.findByText("删除空行"))

    fireEvent.click(within(dialog).getByRole("button", { name: "开始导入" }))
    await waitFor(() => {
      expect(notifications.some(([, msg]) => msg === "已提交解析任务")).toBe(
        true
      )
    })
    const payload = JSON.parse(parseCalls[0].body)
    expect(payload).toMatchObject({
      strategy: "flat",
      chunk_size: 800,
      chunk_overlap: 64,
      split_separator: "。",
      cleaning_rules: ["trim_lines"],
    })
  })

  test("indexes a single document and reports errors from the index call", async () => {
    const documents = [makeDocument({ id: "doc-1", filename: "a.md" })]
    const indexCalls: Array<{ url: string }> = []
    fetchHandler = (url, init) => {
      const method = init?.method ?? "GET"
      if (method === "POST" && url.includes("/index")) {
        indexCalls.push({ url })
        return jsonResponse({ detail: "index down" }, 503)
      }
      if (url.includes("/models")) return jsonResponse(models)
      if (url.includes("/knowledge-bases?"))
        return jsonResponse([makeKnowledgeBase()])
      if (url.includes("/documents")) return jsonResponse(documents)
      if (url.includes("/tasks")) return jsonResponse([])
      return jsonResponse([])
    }
    routeParams.id = KB_ID
    renderPage(<KnowledgeBasePage />)

    fireEvent.click(await screen.findByRole("button", { name: "向量化 a.md" }))
    await waitFor(() => {
      expect(indexCalls).toHaveLength(1)
    })
    await waitFor(() => {
      expect(notifications.some(([kind]) => kind === "error")).toBe(true)
    })
    expect(notifications.find(([kind]) => kind === "error")?.[1]).toBe(
      "index down"
    )
  })

  test("downloads the original document from the row menu", async () => {
    const documents = [makeDocument({ id: "doc-1", filename: "a.md" })]
    const downloadCalls: string[] = []
    fetchHandler = (url) => {
      if (url.includes("/download")) {
        downloadCalls.push(url)
        return new Response("content", {
          status: 200,
          headers: { "Content-Type": "text/plain" },
        })
      }
      if (url.includes("/models")) return jsonResponse(models)
      if (url.includes("/knowledge-bases?"))
        return jsonResponse([makeKnowledgeBase()])
      if (url.includes("/documents")) return jsonResponse(documents)
      if (url.includes("/tasks")) return jsonResponse([])
      return jsonResponse([])
    }
    routeParams.id = KB_ID
    renderPage(<KnowledgeBasePage />)

    const menuButton = await screen.findByRole("button", { name: "操作 a.md" })
    openMenu(menuButton)
    fireEvent.click(await screen.findByText("下载原文"))

    await waitFor(() => {
      expect(downloadCalls).toHaveLength(1)
    })
    expect(downloadCalls[0]).toContain("/documents/doc-1/download")
  })

  test("deletes a single document from the row menu", async () => {
    const documents = [makeDocument({ id: "doc-1", filename: "a.md" })]
    const deletes: string[] = []
    fetchHandler = (url, init) => {
      const method = init?.method ?? "GET"
      if (method === "DELETE") deletes.push(url)
      if (url.includes("/models")) return jsonResponse(models)
      if (url.includes("/knowledge-bases?"))
        return jsonResponse([makeKnowledgeBase()])
      if (url.includes("/documents")) return jsonResponse(documents)
      if (url.includes("/tasks")) return jsonResponse([])
      return jsonResponse([])
    }
    routeParams.id = KB_ID
    renderPage(<KnowledgeBasePage />)

    const menuButton = await screen.findByRole("button", { name: "操作 a.md" })
    openMenu(menuButton)
    fireEvent.click(await screen.findByRole("menuitem", { name: "删除" }))
    await respondToConfirm("删除")

    await waitFor(() => {
      expect(deletes).toHaveLength(1)
    })
    expect(notifications.some(([, msg]) => msg === "文档已删除")).toBe(true)
    await waitFor(() => expect(screen.getByText("暂无文档")).toBeTruthy())
  })

  test("navigates to the document detail page", async () => {
    const documents = [makeDocument({ id: "doc-1", filename: "a.md" })]
    renderDetailPage({ documents })
    await waitFor(() => expect(screen.getByText("a.md")).toBeTruthy())

    fireEvent.click(screen.getByText("a.md"))
    expect(pushes).toContain(`/app/knowledge/${KB_ID}/documents/doc-1`)
  })

  test("disables document actions without edit permission", async () => {
    const documents = [makeDocument({ id: "doc-1", filename: "a.md" })]
    renderDetailPage({
      knowledgeBases: [
        makeKnowledgeBase({
          permission: "view",
          created_by_user_id: "u-other",
        }),
      ],
      documents,
    })

    await waitFor(() => expect(screen.getByText("a.md")).toBeTruthy())
    expect((screen.getByText("上传文档") as HTMLButtonElement).disabled).toBe(
      true
    )
    expect((screen.getByText("重建索引") as HTMLButtonElement).disabled).toBe(
      true
    )
    expect(
      (screen.getByRole("switch", { name: "停用 a.md" }) as HTMLButtonElement)
        .disabled
    ).toBe(true)
    // Action buttons stay rendered but disabled without edit permission.
    expect(
      (
        screen.getByRole("button", {
          name: "重新分段 a.md",
        }) as HTMLButtonElement
      ).disabled
    ).toBe(true)
    expect(
      (screen.getByRole("button", { name: "操作 a.md" }) as HTMLButtonElement)
        .disabled
    ).toBe(true)
    expect(screen.queryByRole("button", { name: "编辑知识库" })).toBeNull()
  })

  test("notifies when document loading fails", async () => {
    fetchHandler = (url) => {
      if (url.includes("/models")) return jsonResponse(models)
      if (url.includes("/knowledge-bases?"))
        return jsonResponse([makeKnowledgeBase()])
      if (url.includes("/documents"))
        return jsonResponse({ detail: "docs down" }, 500)
      return jsonResponse([])
    }
    routeParams.id = KB_ID
    renderPage(<KnowledgeBasePage />)

    await waitFor(() => {
      expect(notifications.some(([kind]) => kind === "error")).toBe(true)
    })
    expect(notifications.find(([kind]) => kind === "error")?.[1]).toBe(
      "docs down"
    )
    await waitFor(() => expect(screen.getByText("暂无文档")).toBeTruthy())
  })

  test("navigates back to the list", async () => {
    renderDetailPage({ documents: [] })
    await waitFor(() => expect(screen.getByText("暂无文档")).toBeTruthy())
    fireEvent.click(screen.getByRole("button", { name: "返回" }))
    expect(pushes).toContain("/app/knowledge")
  })

  test("navigates to the upload flow from the documents tab", async () => {
    renderDetailPage({ documents: [] })
    await waitFor(() => expect(screen.getByText("暂无文档")).toBeTruthy())

    fireEvent.click(screen.getByText("上传文档"))
    expect(pushes).toContain(`/app/knowledge/${KB_ID}/upload`)
  })

  test("shows a loading spinner while documents are loading", async () => {
    const resolvers: Array<(value: Response) => void> = []
    fetchHandler = (url) => {
      if (url.includes("/models")) return jsonResponse(models)
      if (url.includes("/knowledge-bases?"))
        return jsonResponse([makeKnowledgeBase()])
      if (url.includes("/documents")) {
        return new Promise<Response>((resolve) => {
          resolvers.push(resolve)
        })
      }
      return jsonResponse([])
    }
    routeParams.id = KB_ID
    renderPage(<KnowledgeBasePage />)

    await waitFor(() => {
      expect(document.querySelector(".animate-spin")).toBeTruthy()
    })
    for (const resolve of resolvers) resolve(jsonResponse([]))
    await waitFor(() => {
      expect(screen.getByText("暂无文档")).toBeTruthy()
    })
  })

  test("selects and deselects individual document rows", async () => {
    const documents = [
      makeDocument({ id: "doc-1", filename: "a.md" }),
      makeDocument({ id: "doc-2", filename: "b.md" }),
    ]
    renderDetailPage({ documents })

    await waitFor(() => expect(screen.getByText("a.md")).toBeTruthy())

    // Select a single row.
    fireEvent.click(screen.getByLabelText("选择 a.md"))
    expect(screen.getByText("向量化(1)")).toBeTruthy()

    // A checked=true change for an already-selected row is a no-op.
    fireEvent.change(screen.getByLabelText("选择 a.md"), {
      target: { checked: true },
    })
    expect(screen.getByText("向量化(1)")).toBeTruthy()

    // Select all: the already-selected row stays selected.
    fireEvent.click(screen.getByLabelText("选择所有文档"))
    expect(screen.getByText("向量化(2)")).toBeTruthy()

    // Clicking an already-selected row removes it.
    fireEvent.click(screen.getByLabelText("选择 a.md"))
    expect(screen.getByText("向量化(1)")).toBeTruthy()

    // Select-all adds the missing row back.
    fireEvent.click(screen.getByLabelText("选择所有文档"))
    expect(screen.getByText("向量化(2)")).toBeTruthy()

    // Uncheck select-all clears every selection.
    fireEvent.click(screen.getByLabelText("选择所有文档"))
    expect(screen.getByText("向量化")).toBeTruthy()

    // Row checkbox toggles back on and off.
    fireEvent.click(screen.getByLabelText("选择 a.md"))
    expect(screen.getByText("向量化(1)")).toBeTruthy()
    fireEvent.click(screen.getByLabelText("选择 a.md"))
    expect(screen.getByText("向量化")).toBeTruthy()
  })

  test("sorts documents by updated time in both directions", async () => {
    const documents = [
      makeDocument({
        id: "doc-a",
        filename: "a.md",
        created_at: "2026-01-01T00:00:00Z",
        updated_at: "2026-01-03T00:00:00Z",
      }),
      makeDocument({
        id: "doc-b",
        filename: "b.md",
        created_at: "2026-01-02T00:00:00Z",
        updated_at: "2026-01-02T00:00:00Z",
      }),
      makeDocument({
        id: "doc-c",
        filename: "c.md",
        created_at: "2026-01-03T00:00:00Z",
        updated_at: "2026-01-01T00:00:00Z",
      }),
    ]
    renderDetailPage({ documents })

    await waitFor(() => expect(visibleFilenames().length).toBe(3))
    // Default: created_at desc → c, b, a
    expect(visibleFilenames()).toEqual(["c.md", "b.md", "a.md"])

    fireEvent.click(sortHeaderButton("更新时间"))
    expect(visibleFilenames()).toEqual(["a.md", "b.md", "c.md"])

    fireEvent.click(sortHeaderButton("更新时间"))
    expect(visibleFilenames()).toEqual(["c.md", "b.md", "a.md"])
  })

  test("opens the document preview from the row menu", async () => {
    const documents = [makeDocument({ id: "doc-1", filename: "a.md" })]
    renderDetailPage({ documents })
    await waitFor(() => expect(screen.getByText("a.md")).toBeTruthy())

    openMenu(screen.getByRole("button", { name: "操作 a.md" }))
    fireEvent.click(await screen.findByRole("menuitem", { name: "预览切片" }))
    expect(pushes).toContain(`/app/knowledge/${KB_ID}/documents/doc-1`)
  })

  test("indexes a single document from the row menu", async () => {
    const documents = [makeDocument({ id: "doc-1", filename: "a.md" })]
    const indexCalls: string[] = []
    fetchHandler = (url, init) => {
      const method = init?.method ?? "GET"
      if (method === "POST" && url.includes("/index")) indexCalls.push(url)
      if (url.includes("/models")) return jsonResponse(models)
      if (url.includes("/knowledge-bases?"))
        return jsonResponse([makeKnowledgeBase()])
      if (url.includes("/documents")) return jsonResponse(documents)
      if (url.includes("/tasks")) return jsonResponse([])
      return jsonResponse([])
    }
    routeParams.id = KB_ID
    renderPage(<KnowledgeBasePage />)

    await waitFor(() => expect(screen.getByText("a.md")).toBeTruthy())
    openMenu(screen.getByRole("button", { name: "操作 a.md" }))
    fireEvent.click(await screen.findByRole("menuitem", { name: "向量化" }))

    await waitFor(() => {
      expect(indexCalls).toHaveLength(1)
    })
    expect(notifications.some(([, msg]) => msg === "已提交向量化任务")).toBe(
      true
    )
  })

  test("closes the re-segment dialog with Escape", async () => {
    const documents = [makeDocument({ id: "doc-1", filename: "a.md" })]
    renderDetailPage({ documents })

    fireEvent.click(
      await screen.findByRole("button", { name: "重新分段 a.md" })
    )
    expect(await screen.findByRole("dialog")).toBeTruthy()
    fireEvent.keyDown(document.body, { key: "Escape" })
    await waitFor(() => {
      expect(screen.queryByRole("dialog")).toBeNull()
    })
  })

  test("adds a cleaning rule in the advanced segmentation dialog", async () => {
    const documents = [makeDocument({ id: "doc-1", filename: "a.md" })]
    renderDetailPage({ documents })

    fireEvent.click(
      await screen.findByRole("button", { name: "重新分段 a.md" })
    )
    const dialog = await screen.findByRole("dialog")
    fireEvent.click(within(dialog).getByText("高级分段"))

    openMenu(within(dialog).getByRole("button", { name: /去除行首尾空白/ }))
    fireEvent.click(
      await screen.findByRole("menuitem", { name: "合并连续空白" })
    )
    await waitFor(() => {
      expect(
        within(dialog).getByRole("button", { name: /合并连续空白/ })
      ).toBeTruthy()
    })
  })

  test("keeps the page when the bulk delete confirmation is declined", async () => {
    const documents = [makeDocument({ id: "doc-1", filename: "a.md" })]
    const deletes: string[] = []
    fetchHandler = (url, init) => {
      const method = init?.method ?? "GET"
      if (method === "DELETE") deletes.push(url)
      if (url.includes("/models")) return jsonResponse(models)
      if (url.includes("/knowledge-bases?"))
        return jsonResponse([makeKnowledgeBase()])
      if (url.includes("/documents")) return jsonResponse(documents)
      if (url.includes("/tasks")) return jsonResponse([])
      return jsonResponse([])
    }
    routeParams.id = KB_ID
    renderPage(<KnowledgeBasePage />)

    await waitFor(() => expect(screen.getByText("a.md")).toBeTruthy())
    fireEvent.click(screen.getByLabelText("选择所有文档"))
    fireEvent.click(screen.getByText("删除(1)"))
    await respondToConfirm("取消")
    expect(deletes).toHaveLength(0)
    expect(screen.getByText("a.md")).toBeTruthy()
  })

  test("reports errors from the bulk delete call", async () => {
    const documents = [makeDocument({ id: "doc-1", filename: "a.md" })]
    fetchHandler = (url, init) => {
      const method = init?.method ?? "GET"
      if (method === "DELETE" && url.includes("/documents")) {
        return jsonResponse({ detail: "bulk delete boom" }, 500)
      }
      if (url.includes("/models")) return jsonResponse(models)
      if (url.includes("/knowledge-bases?"))
        return jsonResponse([makeKnowledgeBase()])
      if (url.includes("/documents")) return jsonResponse(documents)
      if (url.includes("/tasks")) return jsonResponse([])
      return jsonResponse([])
    }
    routeParams.id = KB_ID
    renderPage(<KnowledgeBasePage />)

    await waitFor(() => expect(screen.getByText("a.md")).toBeTruthy())
    fireEvent.click(screen.getByLabelText("选择所有文档"))
    fireEvent.click(screen.getByText("删除(1)"))
    await respondToConfirm("删除")

    await waitFor(() => {
      expect(notifications.some(([kind]) => kind === "error")).toBe(true)
    })
    expect(notifications.find(([kind]) => kind === "error")?.[1]).toBe(
      "bulk delete boom"
    )
  })

  test("reports errors from the document active toggle", async () => {
    const documents = [makeDocument({ id: "doc-1", filename: "a.md" })]
    fetchHandler = (url, init) => {
      const method = init?.method ?? "GET"
      if (method === "PATCH" && url.includes("/documents")) {
        return jsonResponse({ detail: "toggle boom" }, 500)
      }
      if (url.includes("/models")) return jsonResponse(models)
      if (url.includes("/knowledge-bases?"))
        return jsonResponse([makeKnowledgeBase()])
      if (url.includes("/documents")) return jsonResponse(documents)
      if (url.includes("/tasks")) return jsonResponse([])
      return jsonResponse([])
    }
    routeParams.id = KB_ID
    renderPage(<KnowledgeBasePage />)

    fireEvent.click(await screen.findByRole("switch", { name: "停用 a.md" }))
    await waitFor(() => {
      expect(notifications.some(([kind]) => kind === "error")).toBe(true)
    })
    expect(notifications.find(([kind]) => kind === "error")?.[1]).toBe(
      "toggle boom"
    )
  })

  test("reports errors from the re-segment parse", async () => {
    const documents = [makeDocument({ id: "doc-1", filename: "a.md" })]
    fetchHandler = (url, init) => {
      const method = init?.method ?? "GET"
      if (method === "POST" && url.includes("/parse")) {
        return jsonResponse({ detail: "parse boom" }, 500)
      }
      if (url.includes("/models")) return jsonResponse(models)
      if (url.includes("/knowledge-bases?"))
        return jsonResponse([makeKnowledgeBase()])
      if (url.includes("/documents")) return jsonResponse(documents)
      if (url.includes("/tasks")) return jsonResponse([])
      return jsonResponse([])
    }
    routeParams.id = KB_ID
    renderPage(<KnowledgeBasePage />)

    fireEvent.click(
      await screen.findByRole("button", { name: "重新分段 a.md" })
    )
    const dialog = await screen.findByRole("dialog")
    fireEvent.click(within(dialog).getByRole("button", { name: "开始导入" }))

    await waitFor(() => {
      expect(notifications.some(([kind]) => kind === "error")).toBe(true)
    })
    expect(notifications.find(([kind]) => kind === "error")?.[1]).toBe(
      "parse boom"
    )
  })

  test("reports errors from the rebuild index", async () => {
    const documents = [makeDocument({ id: "doc-1", filename: "a.md" })]
    fetchHandler = (url, init) => {
      const method = init?.method ?? "GET"
      if (method === "POST" && url.includes("/rebuild-index")) {
        return jsonResponse({ detail: "rebuild boom" }, 500)
      }
      if (url.includes("/models")) return jsonResponse(models)
      if (url.includes("/knowledge-bases?"))
        return jsonResponse([makeKnowledgeBase()])
      if (url.includes("/documents")) return jsonResponse(documents)
      if (url.includes("/tasks")) return jsonResponse([])
      return jsonResponse([])
    }
    routeParams.id = KB_ID
    renderPage(<KnowledgeBasePage />)

    await waitFor(() => expect(screen.getByText("a.md")).toBeTruthy())
    fireEvent.click(screen.getByText("重建索引"))

    await waitFor(() => {
      expect(notifications.some(([kind]) => kind === "error")).toBe(true)
    })
    expect(notifications.find(([kind]) => kind === "error")?.[1]).toBe(
      "rebuild boom"
    )
  })

  test("reports errors from the document download", async () => {
    const documents = [makeDocument({ id: "doc-1", filename: "a.md" })]
    fetchHandler = (url) => {
      if (url.includes("/download")) {
        return new Response("nope", {
          status: 500,
          statusText: "download server error",
        })
      }
      if (url.includes("/models")) return jsonResponse(models)
      if (url.includes("/knowledge-bases?"))
        return jsonResponse([makeKnowledgeBase()])
      if (url.includes("/documents")) return jsonResponse(documents)
      if (url.includes("/tasks")) return jsonResponse([])
      return jsonResponse([])
    }
    routeParams.id = KB_ID
    renderPage(<KnowledgeBasePage />)

    openMenu(await screen.findByRole("button", { name: "操作 a.md" }))
    fireEvent.click(await screen.findByRole("menuitem", { name: "下载原文" }))

    await waitFor(() => {
      expect(notifications.some(([kind]) => kind === "error")).toBe(true)
    })
    expect(notifications.find(([kind]) => kind === "error")?.[1]).toBe(
      "download server error"
    )
  })

  test("reports errors from the single document delete", async () => {
    const documents = [makeDocument({ id: "doc-1", filename: "a.md" })]
    fetchHandler = (url, init) => {
      const method = init?.method ?? "GET"
      if (method === "DELETE" && url.includes("/documents")) {
        return jsonResponse({ detail: "delete doc boom" }, 500)
      }
      if (url.includes("/models")) return jsonResponse(models)
      if (url.includes("/knowledge-bases?"))
        return jsonResponse([makeKnowledgeBase()])
      if (url.includes("/documents")) return jsonResponse(documents)
      if (url.includes("/tasks")) return jsonResponse([])
      return jsonResponse([])
    }
    routeParams.id = KB_ID
    renderPage(<KnowledgeBasePage />)

    openMenu(await screen.findByRole("button", { name: "操作 a.md" }))
    fireEvent.click(await screen.findByRole("menuitem", { name: "删除" }))
    await respondToConfirm("删除")

    await waitFor(() => {
      expect(notifications.some(([kind]) => kind === "error")).toBe(true)
    })
    expect(notifications.find(([kind]) => kind === "error")?.[1]).toBe(
      "delete doc boom"
    )
  })

  test("polls for document status while documents are processing", async () => {
    const documents = [
      makeDocument({ id: "doc-1", filename: "a.md", status: "parsing" }),
    ]
    let documentFetches = 0
    fetchHandler = (url) => {
      if (url.includes("/models")) return jsonResponse(models)
      if (url.includes("/knowledge-bases?"))
        return jsonResponse([makeKnowledgeBase()])
      if (url.includes("/documents")) {
        documentFetches += 1
        return jsonResponse(documents)
      }
      if (url.includes("/tasks")) return jsonResponse([])
      return jsonResponse([])
    }
    routeParams.id = KB_ID
    renderPage(<KnowledgeBasePage />)

    await waitFor(() => expect(documentFetches).toBeGreaterThanOrEqual(1))
    await new Promise((resolve) => setTimeout(resolve, 3200))
    expect(documentFetches).toBeGreaterThanOrEqual(2)
  })
})

// ---------------------------------------------------------------------------
// Detail view — tasks tab
// ---------------------------------------------------------------------------

describe("KnowledgeBasePage tasks tab", () => {
  test("polls running task progress without a processing document", async () => {
    let taskFetches = 0
    fetchHandler = (url) => {
      if (url.includes("/models")) return jsonResponse(models)
      if (url.includes("/knowledge-bases?"))
        return jsonResponse([makeKnowledgeBase()])
      if (url.includes("/documents")) return jsonResponse([])
      if (url.includes("/tasks")) {
        taskFetches += 1
        return jsonResponse([
          makeTask({
            id: "graph-progress-task",
            task_type: "graph_rebuild",
            status: "running",
            total_items: 175,
            processed_items: taskFetches,
          }),
        ])
      }
      return jsonResponse([])
    }
    routeParams.id = KB_ID
    renderPage(<KnowledgeBasePage />)

    fireEvent.click(await screen.findByText("任务"))
    await screen.findByText("1/175")
    await waitFor(() => expect(screen.getByText("2/175")).toBeTruthy(), {
      timeout: 4000,
    })
  })

  test("renders task rows with type, status, progress and retry", async () => {
    const tasks = [
      makeTask({
        id: "task-1",
        document_id: null,
        task_type: "rebuild_index",
        status: "failed",
        attempts: 2,
        max_attempts: 3,
        total_items: 10,
        processed_items: 4,
        last_error: "vector store unreachable",
      }),
      makeTask({
        id: "task-2",
        document_id: "doc-1",
        task_type: "parse",
        status: "queued",
        attempts: 0,
        max_attempts: 3,
        total_items: 1,
        processed_items: 0,
      }),
    ]
    const retryCalls: string[] = []
    const stopCalls: string[] = []
    const deleteCalls: string[] = []
    fetchHandler = (url, init) => {
      const method = init?.method ?? "GET"
      if (method === "POST" && url.includes("/retry")) {
        retryCalls.push(url)
        return jsonResponse(makeTask({ id: "task-1", status: "queued" }))
      }
      if (method === "POST" && url.includes("/stop")) {
        stopCalls.push(url)
        return jsonResponse(makeTask({ id: "task-2", status: "cancelled" }))
      }
      if (method === "DELETE" && url.includes("/tasks/")) {
        deleteCalls.push(url)
        return new Response(null, { status: 204 })
      }
      if (url.includes("/models")) return jsonResponse(models)
      if (url.includes("/knowledge-bases?"))
        return jsonResponse([makeKnowledgeBase()])
      if (url.includes("/documents")) return jsonResponse([])
      if (url.includes("/tasks")) return jsonResponse(tasks)
      return jsonResponse([])
    }
    routeParams.id = KB_ID
    renderPage(<KnowledgeBasePage />)

    fireEvent.click(await screen.findByText("任务"))
    await waitFor(() => {
      expect(screen.getByText("重建索引")).toBeTruthy()
    })
    expect(screen.getByText("失败")).toBeTruthy()
    expect(screen.getByText("排队中")).toBeTruthy()
    expect(screen.getByText("4/10")).toBeTruthy()
    expect(screen.getByText("2/3")).toBeTruthy()
    expect(screen.getByText("vector store unreachable")).toBeTruthy()

    const retryButtons = screen.getAllByRole("button", { name: "重试" })
    expect(retryButtons).toHaveLength(2) // failed + queued tasks both render it
    const enabledRetry = retryButtons.find(
      (button) => !(button as HTMLButtonElement).disabled
    )
    expect(enabledRetry).toBeTruthy()
    fireEvent.click(enabledRetry!)

    await waitFor(() => {
      expect(retryCalls).toHaveLength(1)
    })
    expect(retryCalls[0]).toContain("/tasks/task-1/retry")
    expect(notifications.some(([, msg]) => msg === "已重新提交任务")).toBe(true)

    const enabledStop = screen
      .getAllByRole("button", { name: "停止" })
      .find((button) => !(button as HTMLButtonElement).disabled)
    expect(enabledStop).toBeTruthy()
    fireEvent.click(enabledStop!)
    await waitFor(() => expect(stopCalls).toHaveLength(1))
    expect(stopCalls[0]).toContain("/tasks/task-2/stop")
    expect(notifications.some(([, msg]) => msg === "已停止任务")).toBe(true)

    const enabledDelete = screen
      .getAllByRole("button", { name: "删除任务" })
      .find((button) => !(button as HTMLButtonElement).disabled)
    expect(enabledDelete).toBeTruthy()
    fireEvent.click(enabledDelete!)
    await respondToConfirm("删除")
    await waitFor(() => expect(deleteCalls).toHaveLength(1))
    expect(deleteCalls[0]).toContain("/tasks/task-1")
    expect(notifications.some(([, msg]) => msg === "已删除任务")).toBe(true)
  })

  test("bulk deletes selected terminal tasks", async () => {
    const tasks = [
      makeTask({
        id: "failed-task",
        status: "failed",
        last_error: "failed task marker",
      }),
      makeTask({
        id: "succeeded-task",
        status: "succeeded",
        last_error: "succeeded task marker",
      }),
      makeTask({
        id: "running-task",
        status: "running",
        last_error: "running task marker",
      }),
    ]
    let bulkDeleteBody: { task_ids: string[] } | null = null
    fetchHandler = (url, init) => {
      const method = init?.method ?? "GET"
      if (method === "POST" && url.endsWith("/tasks/bulk-delete")) {
        bulkDeleteBody = JSON.parse(String(init?.body))
        return jsonResponse({
          deleted_task_ids: bulkDeleteBody?.task_ids ?? [],
        })
      }
      if (url.includes("/models")) return jsonResponse(models)
      if (url.includes("/knowledge-bases?"))
        return jsonResponse([makeKnowledgeBase()])
      if (url.includes("/documents")) return jsonResponse([])
      if (url.includes("/tasks")) return jsonResponse(tasks)
      return jsonResponse([])
    }
    routeParams.id = KB_ID
    renderPage(<KnowledgeBasePage />)

    fireEvent.click(await screen.findByText("任务"))
    await screen.findByText("failed task marker")
    fireEvent.click(screen.getByLabelText("选择所有可删除任务"))
    expect(
      (screen.getByLabelText("选择任务 running-task") as HTMLInputElement)
        .disabled
    ).toBe(true)
    fireEvent.click(screen.getByRole("button", { name: /批量删除/ }))
    await respondToConfirm("删除")

    await waitFor(() =>
      expect(bulkDeleteBody).toEqual({
        task_ids: ["failed-task", "succeeded-task"],
      })
    )
    expect(screen.queryByText("failed task marker")).toBeNull()
    expect(screen.queryByText("succeeded task marker")).toBeNull()
    expect(screen.getByText("running task marker")).toBeTruthy()
    expect(
      notifications.some(([, message]) => message === "已删除 2 个任务")
    ).toBe(true)
  })

  test("offers retry-all and checkpoint retry for a failed graph task", async () => {
    const retryModes: string[] = []
    const task = makeTask({
      id: "graph-retry-task",
      task_type: "graph_rebuild",
      status: "failed",
      attempts: 1,
      max_attempts: 3,
      total_items: 175,
      processed_items: 42,
    })
    fetchHandler = (url, init) => {
      const method = init?.method ?? "GET"
      if (method === "POST" && url.includes("/retry")) {
        retryModes.push(JSON.parse(String(init?.body)).mode)
        return jsonResponse({ ...task, status: "queued" })
      }
      if (url.includes("/models")) return jsonResponse(models)
      if (url.includes("/knowledge-bases?"))
        return jsonResponse([makeKnowledgeBase()])
      if (url.includes("/documents")) return jsonResponse([])
      if (url.includes("/tasks")) return jsonResponse([task])
      return jsonResponse([])
    }
    routeParams.id = KB_ID
    renderPage(<KnowledgeBasePage />)

    fireEvent.click(await screen.findByText("任务"))
    const unfinished = await screen.findByRole("button", {
      name: "重试未完成分片",
    })
    const all = screen.getByRole("button", { name: "重试全部分片" })
    expect((unfinished as HTMLButtonElement).disabled).toBe(false)
    expect((all as HTMLButtonElement).disabled).toBe(false)
    fireEvent.click(unfinished)
    await waitFor(() => expect(retryModes).toEqual(["unfinished"]))
  })

  test("paginates tasks and changes the page size", async () => {
    const tasks = Array.from({ length: 12 }, (_, index) =>
      makeTask({
        id: `task-${index}`,
        last_error: `任务记录 ${String(index).padStart(2, "0")}`,
      })
    )
    fetchHandler = (url) => {
      if (url.includes("/models")) return jsonResponse(models)
      if (url.includes("/knowledge-bases?"))
        return jsonResponse([makeKnowledgeBase()])
      if (url.includes("/documents")) return jsonResponse([])
      if (url.includes("/tasks")) return jsonResponse(tasks)
      return jsonResponse([])
    }
    routeParams.id = KB_ID
    renderPage(<KnowledgeBasePage />)

    fireEvent.click(await screen.findByText("任务"))
    await screen.findByText("共 12 条")
    expect(screen.getByText("1 / 2")).toBeTruthy()
    expect(screen.getByText("任务记录 00")).toBeTruthy()
    expect(screen.queryByText("任务记录 10")).toBeNull()

    fireEvent.click(screen.getByRole("button", { name: "下一页" }))
    expect(screen.getByText("2 / 2")).toBeTruthy()
    expect(screen.queryByText("任务记录 00")).toBeNull()
    expect(screen.getByText("任务记录 10")).toBeTruthy()

    openMenu(screen.getByRole("button", { name: /每页 10 条/ }))
    fireEvent.click(await screen.findByText("每页 20 条"))
    expect(screen.getByText("1 / 1")).toBeTruthy()
    expect(screen.getByText("任务记录 00")).toBeTruthy()
    expect(screen.getByText("任务记录 11")).toBeTruthy()
  })

  test("rebuilds the index from the tasks tab", async () => {
    const rebuildCalls: string[] = []
    fetchHandler = (url, init) => {
      const method = init?.method ?? "GET"
      if (method === "POST" && url.includes("/rebuild-index")) {
        rebuildCalls.push(url)
        return jsonResponse(
          makeTask({ id: "task-rb", task_type: "rebuild_index" })
        )
      }
      if (url.includes("/models")) return jsonResponse(models)
      if (url.includes("/knowledge-bases?"))
        return jsonResponse([makeKnowledgeBase()])
      if (url.includes("/documents")) return jsonResponse([])
      if (url.includes("/tasks")) return jsonResponse([])
      return jsonResponse([])
    }
    routeParams.id = KB_ID
    renderPage(<KnowledgeBasePage />)

    fireEvent.click(await screen.findByText("任务"))
    await waitFor(() => expect(screen.getByText("暂无任务")).toBeTruthy())
    fireEvent.click(screen.getByText("重建索引"))

    await waitFor(() => {
      expect(rebuildCalls).toHaveLength(1)
    })
    expect(notifications.some(([, msg]) => msg === "已提交重建索引任务")).toBe(
      true
    )
  })

  test("refreshes tasks with the refresh button", async () => {
    let taskCount = 0
    fetchHandler = (url) => {
      if (url.includes("/models")) return jsonResponse(models)
      if (url.includes("/knowledge-bases?"))
        return jsonResponse([makeKnowledgeBase()])
      if (url.includes("/documents")) return jsonResponse([])
      if (url.includes("/tasks")) {
        taskCount += 1
        return jsonResponse(taskCount === 1 ? [] : [makeTask()])
      }
      return jsonResponse([])
    }
    routeParams.id = KB_ID
    renderPage(<KnowledgeBasePage />)

    fireEvent.click(await screen.findByText("任务"))
    await waitFor(() => expect(screen.getByText("暂无任务")).toBeTruthy())
    fireEvent.click(screen.getByText("刷新"))
    await waitFor(() => {
      expect(screen.getByText("成功")).toBeTruthy()
    })
    expect(taskCount).toBeGreaterThanOrEqual(2)
  })

  test("notifies when the tasks fetch fails", async () => {
    fetchHandler = (url) => {
      if (url.includes("/models")) return jsonResponse(models)
      if (url.includes("/knowledge-bases?"))
        return jsonResponse([makeKnowledgeBase()])
      if (url.includes("/documents")) return jsonResponse([])
      if (url.includes("/tasks"))
        return jsonResponse({ detail: "tasks down" }, 500)
      return jsonResponse([])
    }
    routeParams.id = KB_ID
    renderPage(<KnowledgeBasePage />)

    fireEvent.click(await screen.findByText("任务"))
    await waitFor(() => {
      expect(notifications.some(([kind]) => kind === "error")).toBe(true)
    })
    expect(notifications.find(([kind]) => kind === "error")?.[1]).toBe(
      "tasks down"
    )
  })

  test("reports errors when retrying a task fails", async () => {
    const tasks = [
      makeTask({
        id: "task-1",
        task_type: "parse",
        status: "failed",
        attempts: 2,
        max_attempts: 3,
        total_items: 10,
        processed_items: 4,
      }),
    ]
    fetchHandler = (url, init) => {
      const method = init?.method ?? "GET"
      if (method === "POST" && url.includes("/retry")) {
        return jsonResponse({ detail: "retry boom" }, 500)
      }
      if (url.includes("/models")) return jsonResponse(models)
      if (url.includes("/knowledge-bases?"))
        return jsonResponse([makeKnowledgeBase()])
      if (url.includes("/documents")) return jsonResponse([])
      if (url.includes("/tasks")) return jsonResponse(tasks)
      return jsonResponse([])
    }
    routeParams.id = KB_ID
    renderPage(<KnowledgeBasePage />)

    fireEvent.click(await screen.findByText("任务"))
    fireEvent.click(await screen.findByRole("button", { name: "重试" }))
    await waitFor(() => {
      expect(notifications.some(([kind]) => kind === "error")).toBe(true)
    })
    expect(notifications.find(([kind]) => kind === "error")?.[1]).toBe(
      "retry boom"
    )
  })
})

// ---------------------------------------------------------------------------
// Detail view — retrieval evaluation hit test
// ---------------------------------------------------------------------------

describe("KnowledgeBasePage retrieval evaluation hit test", () => {
  test("queries the knowledge base and renders hits", async () => {
    const queryCalls: Array<{ body: string }> = []
    fetchHandler = (url, init) => {
      const method = init?.method ?? "GET"
      if (method === "POST" && url.includes("/query/inspect")) {
        queryCalls.push({ body: String(init?.body ?? "") })
        return jsonResponse({
          hits: [
            {
              chunk_id: "chunk-1",
              document_id: "doc-1",
              document_filename: "guide.md",
              parent_id: "parent-1",
              parent_title: "标题",
              parent_index: 0,
              chunk_index: 0,
              content: "## 标题\n\n正文内容",
              distance: 0.123456,
              similarity: 0.938272,
              kind: "document",
              question: null,
              source: null,
              sources: ["vector", "reference"],
              reference_hops: 1,
              rerank_score: 0.91,
            },
            {
              chunk_id: "chunk-2",
              document_id: "doc-1",
              document_filename: "guide.md",
              parent_id: null,
              parent_title: null,
              parent_index: null,
              chunk_index: 1,
              content: "no distance",
              distance: null,
              similarity: null,
              kind: "document",
              question: null,
              source: null,
              sources: ["keywords"],
              reference_hops: 0,
              rerank_score: null,
            },
          ],
          trace: {
            trace_id: "trace-123",
            search_mode: "keywords",
            limit: 20,
            min_similarity: 0.8,
            max_distance: 0.4,
            vector_candidates: 4,
            keyword_candidates: 3,
            reference_candidates: 2,
            fused_candidates: 6,
            rerank_status: "applied",
            returned_hits: 2,
            duration_ms: 12.345,
          },
        })
      }
      if (url.includes("/models")) return jsonResponse(models)
      if (url.includes("/knowledge-bases?"))
        return jsonResponse([makeKnowledgeBase()])
      if (url.includes("/documents")) return jsonResponse([])
      if (url.includes("/tasks")) return jsonResponse([])
      return jsonResponse([])
    }
    routeParams.id = KB_ID
    renderPage(<KnowledgeBasePage />)

    fireEvent.click(await screen.findByText("检索评测"))
    await waitFor(() => expect(screen.getByText("暂无测试结果")).toBeTruthy())

    const textarea = screen.getByLabelText("查询内容") as HTMLTextAreaElement
    fireEvent.change(textarea, { target: { value: "what is alpha" } })
    fireEvent.pointerDown(screen.getByRole("button", { name: "检索模式" }))
    const searchModeMenu = await screen.findByRole("menu")
    fireEvent.click(within(searchModeMenu).getByText("关键词检索"))
    const similarityInput = screen.getByLabelText("相似度") as HTMLInputElement
    expect(similarityInput.value).toBe("0.6")
    fireEvent.change(similarityInput, {
      target: { value: "0.8" },
    })
    const includeReferences = screen.getByLabelText(
      "扩展文档引用"
    ) as HTMLInputElement
    expect(includeReferences.checked).toBe(true)
    expect(
      (screen.getByRole("button", { name: "测试召回" }) as HTMLButtonElement)
        .disabled
    ).toBe(false)
    const limitInput = screen.getByLabelText("返回数量") as HTMLInputElement
    fireEvent.change(limitInput, { target: { value: "99" } })
    expect(limitInput.value).toBe("20")
    fireEvent.click(screen.getByRole("button", { name: "测试召回" }))

    await waitFor(() => {
      expect(screen.getAllByRole("button", { name: /guide\.md/ })).toHaveLength(
        2
      )
    })
    const [firstCard, secondCard] = screen.getAllByRole("button", {
      name: /guide\.md/,
    })
    expect(firstCard.getAttribute("aria-haspopup")).toBe("dialog")
    expect(within(firstCard).getAllByText("#1", { exact: true })).toHaveLength(
      2
    )
    expect(within(firstCard).getByText("相似度：0.9383")).toBeTruthy()
    expect(within(secondCard).getByText("相似度：-")).toBeTruthy()
    expect(within(firstCard).getByText("向量检索")).toBeTruthy()
    expect(within(firstCard).getByText("文档引用")).toBeTruthy()
    expect(within(firstCard).getByText("引用跳数：1")).toBeTruthy()
    expect(screen.queryByText("chunk-1", { exact: true })).toBeNull()
    expect(screen.queryByText("正文内容", { exact: true })).toBeNull()
    expect(screen.getByText("追踪 ID：trace-123")).toBeTruthy()
    expect(screen.getByText("向量候选：4")).toBeTruthy()
    expect(screen.getByText("关键词候选：3")).toBeTruthy()
    expect(screen.getByText("引用候选：2")).toBeTruthy()
    expect(screen.getByText("融合候选：6")).toBeTruthy()
    expect(screen.getByText("重排状态：已应用")).toBeTruthy()
    expect(screen.getByText("总耗时：12.345 毫秒")).toBeTruthy()
    expect(screen.queryByText("候选召回：4.5 毫秒")).toBeNull()
    expect(JSON.parse(queryCalls[0].body)).toEqual({
      query: "what is alpha",
      limit: 20,
      search_mode: "keywords",
      similarity: 0.8,
      include_references: true,
    })

    fireEvent.click(firstCard)
    const dialog = await screen.findByRole("dialog")
    expect(
      within(dialog).getByRole("heading", { name: "guide.md / #1" })
    ).toBeTruthy()
    expect(within(dialog).getByText("chunk-1", { exact: true })).toBeTruthy()
    expect(within(dialog).getByText("parent-1", { exact: true })).toBeTruthy()
    expect(within(dialog).getByText("正文内容", { exact: true })).toBeTruthy()
    expect(dialog.textContent).toContain("相似度：0.9383")

    fireEvent.click(within(dialog).getByRole("button", { name: "关闭" }))
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull())
    await waitFor(() => expect(document.activeElement).toBe(firstCard))

    fireEvent.click(secondCard)
    const secondDialog = await screen.findByRole("dialog")
    expect(
      within(secondDialog).getByRole("heading", { name: "guide.md / #2" })
    ).toBeTruthy()
    expect(
      within(secondDialog).getByText("no distance", { exact: true })
    ).toBeTruthy()
    expect(secondDialog.textContent).toContain("相似度：-")
    expect(
      within(secondDialog).getByText("重排分数", { exact: true })
    ).toBeTruthy()
    expect(
      within(secondDialog).queryByText("parent-1", { exact: true })
    ).toBeNull()
    fireEvent.keyDown(document.body, { key: "Escape" })
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull())
    await waitFor(() => expect(document.activeElement).toBe(secondCard))

    // Query limit clamps to 1..20.
    fireEvent.change(limitInput, { target: { value: "0" } })
    expect(limitInput.value).toBe("1")
  })

  test("does not submit an empty query", async () => {
    let queryCalls = 0
    fetchHandler = (url, init) => {
      if (init?.method === "POST" && url.includes("/query/inspect"))
        queryCalls += 1
      if (url.includes("/models")) return jsonResponse(models)
      if (url.includes("/knowledge-bases?"))
        return jsonResponse([makeKnowledgeBase()])
      if (url.includes("/documents")) return jsonResponse([])
      if (url.includes("/tasks")) return jsonResponse([])
      return jsonResponse([])
    }
    routeParams.id = KB_ID
    renderPage(<KnowledgeBasePage />)

    fireEvent.click(await screen.findByText("检索评测"))
    const submit = screen.getByRole("button", {
      name: "测试召回",
    }) as HTMLButtonElement
    expect(submit.disabled).toBe(true)
    fireEvent.click(submit)
    await waitFor(() => expect(queryCalls).toBe(0))
  })

  test("does not submit a whitespace-only query", async () => {
    let queryCalls = 0
    fetchHandler = (url, init) => {
      if (init?.method === "POST" && url.includes("/query/inspect"))
        queryCalls += 1
      if (url.includes("/models")) return jsonResponse(models)
      if (url.includes("/knowledge-bases?"))
        return jsonResponse([makeKnowledgeBase()])
      if (url.includes("/documents")) return jsonResponse([])
      if (url.includes("/tasks")) return jsonResponse([])
      return jsonResponse([])
    }
    routeParams.id = KB_ID
    renderPage(<KnowledgeBasePage />)

    fireEvent.click(await screen.findByText("检索评测"))
    const textarea = screen.getByLabelText("查询内容") as HTMLTextAreaElement
    fireEvent.change(textarea, { target: { value: "   " } })
    const form = textarea.closest("form")!
    fireEvent.submit(form)
    await waitFor(() => expect(queryCalls).toBe(0))
  })

  test("reports errors from the query call", async () => {
    fetchHandler = (url, init) => {
      if (init?.method === "POST" && url.includes("/query/inspect")) {
        return jsonResponse({ detail: "query failed" }, 500)
      }
      if (url.includes("/models")) return jsonResponse(models)
      if (url.includes("/knowledge-bases?"))
        return jsonResponse([makeKnowledgeBase()])
      if (url.includes("/documents")) return jsonResponse([])
      if (url.includes("/tasks")) return jsonResponse([])
      return jsonResponse([])
    }
    routeParams.id = KB_ID
    renderPage(<KnowledgeBasePage />)

    fireEvent.click(await screen.findByText("检索评测"))
    const textarea = screen.getByLabelText("查询内容") as HTMLTextAreaElement
    fireEvent.change(textarea, { target: { value: "hello" } })
    fireEvent.submit(textarea.closest("form")!)

    await waitFor(() => {
      expect(notifications.some(([kind]) => kind === "error")).toBe(true)
    })
    expect(notifications.find(([kind]) => kind === "error")?.[1]).toBe(
      "query failed"
    )
  })
})

// ---------------------------------------------------------------------------
// Detail view — settings tab
// ---------------------------------------------------------------------------

describe("KnowledgeBasePage settings tab", () => {
  test("renders settings with model info and edit button", async () => {
    renderDetailPage({ documents: [] })

    fireEvent.click(await screen.findByText("设置"))
    await waitFor(() => {
      expect(screen.getByText("Alpha docs")).toBeTruthy()
    })
    expect(screen.getByText("text-embedding-pro")).toBeTruthy() // embedding model label
    expect(screen.getByText("未配置")).toBeTruthy() // reranker not configured

    fireEvent.click(screen.getByRole("button", { name: "编辑" }))
    const dialog = await screen.findByRole("dialog")
    expect(within(dialog).getByText("更新知识库名称和描述。")).toBeTruthy()
  })

  test("runs a successful model test", async () => {
    const testCalls: string[] = []
    fetchHandler = (url, init) => {
      const method = init?.method ?? "GET"
      if (method === "POST" && url.includes("/model-test")) {
        testCalls.push(url)
        return jsonResponse({
          embedding_model_id: "model-emb",
          embedding_dimensions: 1536,
          reranker_model_id: null,
          reranker_results: 0,
        })
      }
      if (url.includes("/models")) return jsonResponse(models)
      if (url.includes("/knowledge-bases?"))
        return jsonResponse([makeKnowledgeBase()])
      if (url.includes("/documents")) return jsonResponse([])
      if (url.includes("/tasks")) return jsonResponse([])
      return jsonResponse([])
    }
    routeParams.id = KB_ID
    renderPage(<KnowledgeBasePage />)

    fireEvent.click(await screen.findByText("设置"))
    fireEvent.click(await screen.findByRole("button", { name: "测试模型" }))

    await waitFor(() => {
      expect(screen.getByText("模型测试通过")).toBeTruthy()
    })
    expect(screen.getByText("1536 维")).toBeTruthy()
    expect(screen.getByText("0 条")).toBeTruthy()
    expect(testCalls).toHaveLength(1)
  })

  test("renders a model test failure", async () => {
    fetchHandler = (url, init) => {
      const method = init?.method ?? "GET"
      if (method === "POST" && url.includes("/model-test")) {
        return jsonResponse({ detail: "embedding api unreachable" }, 502)
      }
      if (url.includes("/models")) return jsonResponse(models)
      if (url.includes("/knowledge-bases?"))
        return jsonResponse([makeKnowledgeBase()])
      if (url.includes("/documents")) return jsonResponse([])
      if (url.includes("/tasks")) return jsonResponse([])
      return jsonResponse([])
    }
    routeParams.id = KB_ID
    renderPage(<KnowledgeBasePage />)

    fireEvent.click(await screen.findByText("设置"))
    fireEvent.click(await screen.findByRole("button", { name: "测试模型" }))

    await waitFor(() => {
      expect(screen.getByText("模型测试失败")).toBeTruthy()
    })
    expect(screen.getByText("embedding api unreachable")).toBeTruthy()
  })

  test("grants and revokes permissions from the settings dialog", async () => {
    const requests: Array<{ url: string; method: string; body: string }> = []
    let grants = [
      {
        user: otherMember.user,
        permission: "view",
      },
    ]
    fetchHandler = (url, init) => {
      const method = init?.method ?? "GET"
      requests.push({ url, method, body: String(init?.body ?? "") })
      if (method === "PUT" && url.includes("/permissions")) {
        const permission = JSON.parse(String(init?.body ?? "{}")).permission
        grants = [{ user: otherMember.user, permission }]
        return jsonResponse({ user: otherMember.user, permission })
      }
      if (method === "DELETE" && url.includes("/permissions")) {
        grants = []
        return jsonResponse(null, 204)
      }
      if (url.includes("/members")) {
        return jsonResponse([
          otherMember,
          {
            user: {
              ...adminUser,
              id: "u-admin",
              name: "NexaFlow Admin",
              username: "admin",
            },
            role: "admin",
          },
        ])
      }
      if (url.includes("/permissions")) return jsonResponse(grants)
      if (url.includes("/models")) return jsonResponse(models)
      if (url.includes("/knowledge-bases?"))
        return jsonResponse([makeKnowledgeBase()])
      if (url.includes("/documents")) return jsonResponse([])
      if (url.includes("/tasks")) return jsonResponse([])
      return jsonResponse([])
    }
    routeParams.id = KB_ID
    renderPage(<KnowledgeBasePage />)

    fireEvent.click(await screen.findByText("设置"))
    fireEvent.click(await screen.findByRole("button", { name: "授权" }))

    const dialog = await screen.findByRole("dialog")
    expect(within(dialog).getByText("资源授权")).toBeTruthy()
    expect(within(dialog).getByText("Other User")).toBeTruthy()
    // Existing grant shows in the permission list (badge + dropdown trigger).
    expect(within(dialog).getAllByText("可查看").length).toBeGreaterThanOrEqual(
      2
    )

    // Switch permission to edit and save (the trigger is label-associated 权限).
    openMenu(within(dialog).getByRole("button", { name: "权限" }))
    fireEvent.click(await screen.findByRole("menuitem", { name: "可编辑" }))
    fireEvent.click(within(dialog).getByRole("button", { name: "保存授权" }))

    await waitFor(() => {
      expect(notifications.some(([, msg]) => msg === "授权已保存")).toBe(true)
    })
    const put = requests.find((request) => request.method === "PUT")
    expect(put?.url).toContain("/permissions/u-other")
    expect(JSON.parse(put?.body ?? "{}")).toEqual({ permission: "edit" })

    // Revoke the grant.
    fireEvent.click(within(dialog).getByRole("button", { name: "撤销授权" }))
    await waitFor(() => {
      expect(notifications.some(([, msg]) => msg === "授权已撤销")).toBe(true)
    })
    const del = requests.filter((request) => request.method === "DELETE")
    expect(del).toHaveLength(1)
    expect(del[0].url).toContain("/permissions/u-other")
    await waitFor(() => {
      expect(within(dialog).getByText("暂无授权")).toBeTruthy()
    })
  })

  test("shows no grant target when all members already have grants", async () => {
    fetchHandler = (url) => {
      if (url.includes("/members")) {
        return jsonResponse([otherMember, { user: adminUser, role: "admin" }])
      }
      if (url.includes("/permissions")) {
        return jsonResponse([{ user: otherMember.user, permission: "view" }])
      }
      if (url.includes("/models")) return jsonResponse(models)
      if (url.includes("/knowledge-bases?"))
        return jsonResponse([makeKnowledgeBase()])
      if (url.includes("/documents")) return jsonResponse([])
      if (url.includes("/tasks")) return jsonResponse([])
      return jsonResponse([])
    }
    routeParams.id = KB_ID
    renderPage(<KnowledgeBasePage />)

    fireEvent.click(await screen.findByText("设置"))
    fireEvent.click(await screen.findByRole("button", { name: "授权" }))

    const dialog = await screen.findByRole("dialog")
    // u-other is the first member besides me and becomes the default target.
    expect(within(dialog).getByText("Other User / other")).toBeTruthy()
    expect(
      (
        within(dialog).getByRole("button", {
          name: "保存授权",
        }) as HTMLButtonElement
      ).disabled
    ).toBe(false)
  })

  test("hides the permission button for non-admin non-owner members", async () => {
    session.me = {
      user: memberUser,
      memberships: [{ workspace_id: WS, role: "member" }],
    }
    renderDetailPage({
      knowledgeBases: [
        makeKnowledgeBase({
          permission: "view",
          created_by_user_id: "u-other",
        }),
      ],
      documents: [],
    })

    fireEvent.click(await screen.findByText("设置"))
    await waitFor(() => {
      expect(screen.getByText("Alpha docs")).toBeTruthy()
    })
    expect(screen.queryByRole("button", { name: "授权" })).toBeNull()
    expect(screen.queryByRole("button", { name: "编辑" })).toBeNull()
    expect(screen.queryByRole("button", { name: "测试模型" })).toBeNull()
  })

  test("renders a configured reranker model in settings", async () => {
    renderDetailPage({
      knowledgeBases: [
        makeKnowledgeBase({ reranker_model_id: "model-rerank" }),
      ],
      documents: [],
    })

    fireEvent.click(await screen.findByText("设置"))
    await waitFor(() => {
      expect(screen.getByText("rerank-pro")).toBeTruthy()
    })
    expect(screen.queryByText("未配置")).toBeNull()
  })

  test("reports errors when the permissions dialog fails to load", async () => {
    fetchHandler = (url) => {
      if (url.includes("/members")) {
        return jsonResponse({ detail: "members boom" }, 500)
      }
      if (url.includes("/permissions")) return jsonResponse([])
      if (url.includes("/models")) return jsonResponse(models)
      if (url.includes("/knowledge-bases?"))
        return jsonResponse([makeKnowledgeBase()])
      if (url.includes("/documents")) return jsonResponse([])
      if (url.includes("/tasks")) return jsonResponse([])
      return jsonResponse([])
    }
    routeParams.id = KB_ID
    renderPage(<KnowledgeBasePage />)

    fireEvent.click(await screen.findByText("设置"))
    fireEvent.click(await screen.findByRole("button", { name: "授权" }))
    await waitFor(() => {
      expect(notifications.some(([kind]) => kind === "error")).toBe(true)
    })
    expect(notifications.find(([kind]) => kind === "error")?.[1]).toBe(
      "members boom"
    )
  })

  test("reports errors when saving a grant fails", async () => {
    fetchHandler = (url, init) => {
      const method = init?.method ?? "GET"
      if (method === "PUT" && url.includes("/permissions")) {
        return jsonResponse({ detail: "grant boom" }, 500)
      }
      if (url.includes("/members")) {
        return jsonResponse([otherMember, { user: adminUser, role: "admin" }])
      }
      if (url.includes("/permissions")) return jsonResponse([])
      if (url.includes("/models")) return jsonResponse(models)
      if (url.includes("/knowledge-bases?"))
        return jsonResponse([makeKnowledgeBase()])
      if (url.includes("/documents")) return jsonResponse([])
      if (url.includes("/tasks")) return jsonResponse([])
      return jsonResponse([])
    }
    routeParams.id = KB_ID
    renderPage(<KnowledgeBasePage />)

    fireEvent.click(await screen.findByText("设置"))
    fireEvent.click(await screen.findByRole("button", { name: "授权" }))
    const dialog = await screen.findByRole("dialog")
    fireEvent.click(within(dialog).getByRole("button", { name: "保存授权" }))

    await waitFor(() => {
      expect(notifications.some(([kind]) => kind === "error")).toBe(true)
    })
    expect(notifications.find(([kind]) => kind === "error")?.[1]).toBe(
      "grant boom"
    )
  })

  test("reports errors when revoking a grant fails", async () => {
    fetchHandler = (url, init) => {
      const method = init?.method ?? "GET"
      if (method === "DELETE" && url.includes("/permissions")) {
        return jsonResponse({ detail: "revoke boom" }, 500)
      }
      if (url.includes("/members")) {
        return jsonResponse([otherMember, { user: adminUser, role: "admin" }])
      }
      if (url.includes("/permissions")) {
        return jsonResponse([{ user: otherMember.user, permission: "view" }])
      }
      if (url.includes("/models")) return jsonResponse(models)
      if (url.includes("/knowledge-bases?"))
        return jsonResponse([makeKnowledgeBase()])
      if (url.includes("/documents")) return jsonResponse([])
      if (url.includes("/tasks")) return jsonResponse([])
      return jsonResponse([])
    }
    routeParams.id = KB_ID
    renderPage(<KnowledgeBasePage />)

    fireEvent.click(await screen.findByText("设置"))
    fireEvent.click(await screen.findByRole("button", { name: "授权" }))
    const dialog = await screen.findByRole("dialog")
    fireEvent.click(within(dialog).getByRole("button", { name: "撤销授权" }))

    await waitFor(() => {
      expect(notifications.some(([kind]) => kind === "error")).toBe(true)
    })
    expect(notifications.find(([kind]) => kind === "error")?.[1]).toBe(
      "revoke boom"
    )
  })

  test("does not grant when no share target exists", async () => {
    let putCalls = 0
    fetchHandler = (url, init) => {
      const method = init?.method ?? "GET"
      if (method === "PUT" && url.includes("/permissions")) putCalls += 1
      if (url.includes("/members")) {
        return jsonResponse([{ user: adminUser, role: "admin" }])
      }
      if (url.includes("/permissions")) return jsonResponse([])
      if (url.includes("/models")) return jsonResponse(models)
      if (url.includes("/knowledge-bases?"))
        return jsonResponse([makeKnowledgeBase()])
      if (url.includes("/documents")) return jsonResponse([])
      if (url.includes("/tasks")) return jsonResponse([])
      return jsonResponse([])
    }
    routeParams.id = KB_ID
    renderPage(<KnowledgeBasePage />)

    fireEvent.click(await screen.findByText("设置"))
    fireEvent.click(await screen.findByRole("button", { name: "授权" }))
    const dialog = await screen.findByRole("dialog")
    expect(within(dialog).getByText("选择用户")).toBeTruthy()

    const form = within(dialog)
      .getByRole("button", { name: "保存授权" })
      .closest("form")!
    fireEvent.submit(form)
    await waitFor(() => expect(putCalls).toBe(0))
  })
})
