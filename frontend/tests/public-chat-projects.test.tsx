/* @jsxImportSource react */
import { afterEach, beforeEach, expect, mock, test } from "bun:test"
import {
  cleanup,
  fireEvent,
  screen,
  waitFor,
  waitForElementToBeRemoved,
  within,
} from "@testing-library/react"
import { PublicAgentChat } from "@/components/agents/public-agent-chat"
import type { ChatProject } from "@/lib/api/public-chat-projects"
import { ApiError } from "@/lib/api-client"
import { getErrorMessage } from "@/lib/errors"
import { translate, type TFunction } from "@/i18n"
import {
  jsonResponse,
  makeSession,
  mockNextNavigation,
  renderPage,
  withFetch,
} from "./helpers/dom"

const agentId = "00000000-0000-4000-8000-000000000001"
const projectId = "00000000-0000-4000-8000-000000000002"
const artifactId = "00000000-0000-4000-8000-000000000003"
const base = `/api/v1/public/agents/${agentId}`
const timestamp = "2026-11-19T10:00:00Z"
const session = makeSession()
mock.module("@/contexts/session-context", () => ({
  useSession: () => session,
  useOptionalSession: () => session,
}))
mockNextNavigation()

let projects: ChatProject[]
let conversations: {
  conversation_id: string
  project_id?: string | null
  question: string
  result: string
  run_count: number
  status: string
  created_at: string
  updated_at: string
}[]
let files: {
  id: string
  path: string
  size_bytes: number
  content_hash: string
}[]
let requests: { url: string; init?: RequestInit }[]
let extra: (url: string, init?: RequestInit) => Response | null
const originalFetch = globalThis.fetch
beforeEach(() => {
  const testWindow = window as unknown as {
    happyDOM: { setURL: (url: string) => void }
  }
  testWindow.happyDOM.setURL(`https://nexaflow.example/chat/${agentId}`)
  window.localStorage.clear()
  projects = [
    {
      id: projectId,
      name: "Research",
      instructions: "Use sources",
      archived: false,
      created_at: timestamp,
      updated_at: timestamp,
    },
  ]
  conversations = [
    {
      conversation_id: "conversation-1",
      question: "Existing conversation",
      result: "",
      run_count: 0,
      status: "empty",
      created_at: timestamp,
      updated_at: timestamp,
    },
  ]
  files = []
  requests = []
  extra = () => null
  withFetch((url, init) => {
    requests.push({ url, init })
    const custom = extra(url, init)
    if (custom) return custom
    if (url === base + "/profile")
      return jsonResponse({
        id: agentId,
        name: "Assistant",
        description: "",
        interaction_config: {},
      })
    if (url === base + "/conversations")
      return jsonResponse({ items: conversations })
    if (url === base + "/projects" && (!init?.method || init.method === "GET"))
      return jsonResponse({ items: projects })
    if (
      url === base + `/projects/${projectId}/files` &&
      (!init?.method || init.method === "GET")
    )
      return jsonResponse({ items: files })
    if (url.startsWith(base + "/runs?"))
      return jsonResponse({ items: [], total: 0, offset: 0, limit: 200 })
    throw new Error(`Unhandled request: ${init?.method ?? "GET"} ${url}`)
  })
})
afterEach(() => {
  cleanup()
  globalThis.fetch = originalFetch
})

async function openProjectMenu(name = "Research") {
  const trigger = await screen.findByRole("button", {
    name: `更多项目操作：${name}`,
  })
  await waitFor(() =>
    expect((trigger as HTMLButtonElement).disabled).toBe(false)
  )
  fireEvent.pointerDown(trigger, { button: 0, ctrlKey: false })
  await screen.findByRole("menu")
  return trigger
}

async function editProject(name = "Research") {
  await openProjectMenu(name)
  fireEvent.click(await screen.findByRole("menuitem", { name: "编辑" }))
  return await screen.findByRole("dialog", { name: "编辑项目" })
}

test("selects a project through a durable route without reading its other conversations", async () => {
  renderPage(<PublicAgentChat agentId={agentId} />)
  fireEvent.click(await screen.findByRole("button", { name: "Research" }))
  expect(window.location.pathname).toBe(
    `/chat/${agentId}/projects/${projectId}`
  )
  expect(screen.getByRole("heading", { name: "Research" })).toBeTruthy()
  expect(requests.some(({ url }) => url.includes("/runs?"))).toBe(false)
  fireEvent.click(screen.getByRole("button", { name: "Existing conversation" }))
  await waitFor(() =>
    expect(
      requests.some(({ url }) => url.includes("conversation_id=conversation-1"))
    ).toBe(true)
  )
  expect(window.location.pathname).toBe(`/chat/${agentId}`)
})

test("creates a project and sends its first question in a server-owned project conversation", async () => {
  const template = projects[0]!
  projects = []
  extra = (url, init) => {
    if (url === base + "/projects" && init?.method === "POST") {
      const payload = JSON.parse(String(init.body))
      expect(payload).toEqual({
        name: "New research",
      })
      projects = [{ ...template, ...payload, instructions: "" }]
      return jsonResponse(projects[0], 201)
    }
    if (url === base + `/projects/${projectId}/conversations`) {
      conversations = [
        {
          ...conversations[0]!,
          conversation_id: "project-conversation",
          project_id: projectId,
        },
      ]
      return jsonResponse(
        { conversation_id: "project-conversation", project_id: projectId },
        201
      )
    }
    if (url === base + "/runs" && init?.method === "POST") {
      const payload = JSON.parse(String(init.body))
      expect(payload.conversation_id).toBe("project-conversation")
      return jsonResponse(
        {
          id: "run-1",
          conversation_id: "project-conversation",
          question: payload.goal,
          status: "succeeded",
          result: "Saved answer",
          error: null,
          progress: [],
          created_at: timestamp,
          updated_at: timestamp,
          started_at: timestamp,
          finished_at: timestamp,
        },
        201
      )
    }
    return null
  }
  renderPage(<PublicAgentChat agentId={agentId} />)
  fireEvent.click(await screen.findByRole("button", { name: "新建项目" }))
  const dialog = screen.getByRole("dialog")
  fireEvent.change(within(dialog).getByLabelText("项目名称"), {
    target: { value: "New research" },
  })
  expect(within(dialog).queryByLabelText("项目说明")).toBeNull()
  fireEvent.click(within(dialog).getByRole("button", { name: "创建项目" }))
  await screen.findByRole("heading", { name: "New research" })
  fireEvent.change(screen.getByLabelText("请输入问题"), {
    target: { value: "Start" },
  })
  fireEvent.click(screen.getByRole("button", { name: "发送问题" }))
  await screen.findByText("Saved answer")
  expect(window.location.search).toBe("?conversation_id=project-conversation")
  expect(window.location.pathname).toContain(`/projects/${projectId}`)
})

test("edits project names and sources without changing existing instructions", async () => {
  extra = (url, init) => {
    if (url === base + `/projects/${projectId}` && init?.method === "PUT") {
      projects[0] = { ...projects[0]!, ...JSON.parse(String(init.body)) }
      return jsonResponse(projects[0])
    }
    if (
      url === base + `/projects/${projectId}/files` &&
      init?.method === "POST"
    ) {
      expect(init.body).toBeInstanceOf(FormData)
      files = [
        {
          id: artifactId,
          path: "notes.txt",
          size_bytes: 4,
          content_hash: "hash",
        },
      ]
      return jsonResponse({ items: files }, 201)
    }
    if (url.endsWith(`/files/${artifactId}`) && init?.method === "DELETE")
      return new Response(null, { status: 204 })
    return null
  }
  renderPage(<PublicAgentChat agentId={agentId} initialProjectId={projectId} />)
  const dialog = await editProject()
  expect(screen.queryByRole("button", { name: "项目说明与资料" })).toBeNull()
  expect(within(dialog).queryByLabelText("项目说明")).toBeNull()
  expect(within(dialog).queryByText("从当前对话保存")).toBeNull()
  expect(within(dialog).queryByRole("button", { name: "解散项目" })).toBeNull()
  await waitFor(() =>
    expect(
      (screen.getByRole("button", { name: "上传资料" }) as HTMLButtonElement)
        .disabled
    ).toBe(false)
  )
  const sources = within(dialog)
  fireEvent.change(sources.getByLabelText("上传文件或 ZIP"), {
    target: { files: [new File(["data"], "notes.txt")] },
  })
  await screen.findByText("notes.txt")
  await waitFor(() =>
    expect(
      (
        screen.getByRole("button", {
          name: "移除项目资料：notes.txt",
        }) as HTMLButtonElement
      ).disabled
    ).toBe(false)
  )
  fireEvent.click(
    screen.getByRole("button", { name: "移除项目资料：notes.txt" })
  )
  await waitForElementToBeRemoved(() => sources.queryByText("notes.txt"))
  fireEvent.change(sources.getByLabelText("项目名称"), {
    target: { value: "Updated research" },
  })
  fireEvent.click(sources.getByRole("button", { name: "保存" }))
  await waitForElementToBeRemoved(dialog)
  expect(projects[0]!.name).toBe("Updated research")
  expect(projects[0]!.instructions).toBe("Use sources")
  expect(screen.getByLabelText("请输入问题")).toBeTruthy()
  expect(screen.getByRole("heading", { name: "Updated research" })).toBeTruthy()
}, 10000)

test("uploads a selected project folder with its relative paths intact", async () => {
  extra = (url, init) => {
    if (
      url === base + `/projects/${projectId}/files` &&
      init?.method === "POST"
    ) {
      const body = init.body as FormData
      expect((body.get("files") as File).name).toBe("research/notes.txt")
      files = [
        {
          id: artifactId,
          path: "research/notes.txt",
          size_bytes: 4,
          content_hash: "hash",
        },
      ]
      return jsonResponse({ items: files }, 201)
    }
    return null
  }
  renderPage(<PublicAgentChat agentId={agentId} initialProjectId={projectId} />)
  const sources = within(await editProject())
  await waitFor(() =>
    expect(
      (sources.getByRole("button", { name: "上传资料" }) as HTMLButtonElement)
        .disabled
    ).toBe(false)
  )
  const input = sources.getByLabelText("上传文件夹")
  expect(input.hasAttribute("webkitdirectory")).toBe(true)
  const file = new File(["data"], "notes.txt")
  Object.defineProperty(file, "webkitRelativePath", {
    value: "research/notes.txt",
  })
  fireEvent.change(input, { target: { files: [file] } })
  await sources.findByText("research/notes.txt")
}, 10000)

test("previews private HTML sources in an opaque pane while keeping the composer available", async () => {
  files = [
    {
      id: artifactId,
      path: "guide.html",
      size_bytes: 20,
      content_hash: "hash",
    },
  ]
  extra = (url) =>
    url.endsWith(`/files/${artifactId}/content`)
      ? new Response("<h1>Project guide</h1>", {
          headers: { "Content-Type": "text/html" },
        })
      : null
  renderPage(<PublicAgentChat agentId={agentId} initialProjectId={projectId} />)
  await editProject()
  fireEvent.click(
    await screen.findByRole("button", { name: "预览文件：guide.html" })
  )
  const frame = await screen.findByTitle("文件预览：guide.html")
  expect(frame.getAttribute("sandbox")).toBe("allow-scripts")
  expect(frame.getAttribute("srcdoc")).toContain("Project guide")
  expect(frame.getAttribute("srcdoc")).not.toContain(session.token)
  expect(screen.getByLabelText("请输入问题")).toBeTruthy()
  expect(screen.queryByRole("dialog", { name: "编辑项目" })).toBeNull()
  const download = requests.find(({ url }) =>
    url.endsWith(`/files/${artifactId}/content`)
  )!
  expect(new Headers(download.init?.headers).get("Authorization")).toBe(
    `Bearer ${session.token}`
  )
  expect(download.init?.credentials).toBe("omit")
})

test("dissolves a project and preserves its conversation in ordinary history", async () => {
  conversations[0]!.project_id = projectId
  extra = (url, init) =>
    url === base + `/projects/${projectId}` && init?.method === "DELETE"
      ? new Response(null, { status: 204 })
      : null
  renderPage(
    <PublicAgentChat
      agentId={agentId}
      initialProjectId={projectId}
      initialConversationId="conversation-1"
    />
  )
  await openProjectMenu()
  fireEvent.click(screen.getByRole("menuitem", { name: "解散项目" }))
  const confirmation = screen.getByRole("dialog")
  fireEvent.click(
    within(confirmation).getByRole("button", { name: "解散项目" })
  )
  await screen.findByRole("heading", { name: "Assistant" })
  expect(
    screen.getByRole("button", { name: "Existing conversation" })
  ).toBeTruthy()
  expect(window.location.pathname).toBe(`/chat/${agentId}`)
  expect(window.location.search).toBe("?conversation_id=conversation-1")
})

test("archives and dissolves another project without changing the active conversation", async () => {
  const otherId = "00000000-0000-4000-8000-000000000004"
  projects.push({ ...projects[0]!, id: otherId, name: "Other" })
  conversations[0]!.project_id = projectId
  extra = (url, init) => {
    if (url === base + `/projects/${otherId}`) {
      if (init?.method === "PUT") {
        projects[1] = { ...projects[1]!, ...JSON.parse(String(init.body)) }
        return jsonResponse(projects[1])
      }
      if (init?.method === "DELETE") return new Response(null, { status: 204 })
    }
    return null
  }
  renderPage(
    <PublicAgentChat
      agentId={agentId}
      initialProjectId={projectId}
      initialConversationId="conversation-1"
    />
  )
  await openProjectMenu("Other")
  fireEvent.click(screen.getByRole("menuitem", { name: "归档项目" }))
  await waitFor(() => expect(projects[1]!.archived).toBe(true))
  expect(projects[0]!.archived).toBe(false)
  fireEvent.click(await screen.findByRole("button", { name: "显示已归档项目" }))
  await openProjectMenu("Other")
  fireEvent.click(screen.getByRole("menuitem", { name: "解散项目" }))
  fireEvent.click(screen.getByRole("button", { name: "取消" }))
  expect(requests.some(({ init }) => init?.method === "DELETE")).toBe(false)
  await openProjectMenu("Other")
  fireEvent.click(screen.getByRole("menuitem", { name: "解散项目" }))
  fireEvent.click(
    within(screen.getByRole("dialog")).getByRole("button", { name: "解散项目" })
  )
  await waitFor(() =>
    expect(
      screen.queryByRole("button", { name: "更多项目操作：Other" }) === null
    ).toBe(true)
  )
  expect(screen.getByRole("heading", { name: "Research" })).toBeTruthy()
  expect(conversations[0]!.project_id).toBe(projectId)
  expect(window.location.pathname).toBe(
    `/chat/${agentId}/projects/${projectId}`
  )
  expect(window.location.search).toBe("?conversation_id=conversation-1")
})

test("moves an existing conversation into and out of a project", async () => {
  extra = (url, init) => {
    if (url.endsWith("/conversations/conversation-1/project")) {
      const payload = JSON.parse(String(init?.body))
      conversations[0] = {
        ...conversations[0]!,
        project_id: payload.project_id,
      }
      return jsonResponse({
        conversation_id: "conversation-1",
        project_id: payload.project_id,
      })
    }
    return null
  }
  renderPage(
    <PublicAgentChat agentId={agentId} initialConversationId="conversation-1" />
  )
  await screen.findByRole("button", { name: "Research" })
  fireEvent.pointerDown(screen.getByRole("button", { name: "更多" }), {
    button: 0,
    ctrlKey: false,
  })
  fireEvent.click(await screen.findByRole("menuitem", { name: "Research" }))
  await screen.findByRole("heading", { name: "Research" })
  fireEvent.pointerDown(screen.getByRole("button", { name: "更多" }), {
    button: 0,
    ctrlKey: false,
  })
  fireEvent.click(await screen.findByRole("menuitem", { name: "移出项目" }))
  await screen.findByRole("heading", { name: "Assistant" })
  expect(window.location.pathname).toBe(`/chat/${agentId}`)
})

test("archiving prevents new sends and restoring re-enables them", async () => {
  extra = (url, init) => {
    if (url === base + `/projects/${projectId}` && init?.method === "PUT") {
      projects[0] = { ...projects[0]!, ...JSON.parse(String(init.body)) }
      return jsonResponse(projects[0])
    }
    return null
  }
  renderPage(<PublicAgentChat agentId={agentId} initialProjectId={projectId} />)
  await openProjectMenu()
  fireEvent.click(screen.getByRole("menuitem", { name: "归档项目" }))
  await screen.findByText("已归档")
  fireEvent.change(screen.getByLabelText("请输入问题"), {
    target: { value: "Continue" },
  })
  expect(
    (screen.getByRole("button", { name: "发送问题" }) as HTMLButtonElement)
      .disabled
  ).toBe(true)
  const dialog = await editProject()
  expect(
    (within(dialog).getByLabelText("项目名称") as HTMLInputElement).disabled
  ).toBe(true)
  expect(
    (
      within(dialog).getByRole("button", {
        name: "上传资料",
      }) as HTMLButtonElement
    ).disabled
  ).toBe(true)
  fireEvent.click(within(dialog).getByRole("button", { name: "取消" }))
  await waitFor(() => expect(dialog.isConnected).toBe(false))
  await openProjectMenu()
  fireEvent.click(screen.getByRole("menuitem", { name: "恢复项目" }))
  await waitFor(() =>
    expect(
      (screen.getByRole("button", { name: "发送问题" }) as HTMLButtonElement)
        .disabled
    ).toBe(false)
  )
})

test("rejects an unknown project route without creating a conversation", async () => {
  renderPage(<PublicAgentChat agentId={agentId} initialProjectId="missing" />)
  await screen.findByText("项目不存在或不可访问")
  fireEvent.change(screen.getByLabelText("请输入问题"), {
    target: { value: "Continue" },
  })
  expect(
    (screen.getByRole("button", { name: "发送问题" }) as HTMLButtonElement)
      .disabled
  ).toBe(true)
  expect(requests.some(({ init }) => init?.method === "POST")).toBe(false)
})

test("edits an unselected project without leaving the current conversation and cancels unsaved changes", async () => {
  renderPage(
    <PublicAgentChat agentId={agentId} initialConversationId="conversation-1" />
  )
  const dialog = await editProject()
  expect(
    (within(dialog).getByLabelText("项目名称") as HTMLInputElement).value
  ).toBe("Research")
  fireEvent.change(within(dialog).getByLabelText("项目名称"), {
    target: { value: "Unsaved" },
  })
  expect(window.location.pathname).toBe(`/chat/${agentId}`)
  fireEvent.click(within(dialog).getByRole("button", { name: "取消" }))
  await waitFor(() => expect(dialog.isConnected).toBe(false))
  expect(projects[0]!.name).toBe("Research")
  expect(screen.getByRole("heading", { name: "Assistant" })).toBeTruthy()
  expect(requests.some(({ init }) => init?.method === "PUT")).toBe(false)
  await waitFor(() =>
    expect(
      document.activeElement ===
        screen.getByRole("button", { name: "更多项目操作：Research" })
    ).toBe(true)
  )
})

test("keeps failed edits open for retry and rejects blank names", async () => {
  let fail = true
  extra = (url, init) => {
    if (url === base + `/projects/${projectId}` && init?.method === "PUT") {
      if (fail) return jsonResponse({ detail: "Request failed" }, 500)
      projects[0] = { ...projects[0]!, ...JSON.parse(String(init.body)) }
      return jsonResponse(projects[0])
    }
    return null
  }
  renderPage(<PublicAgentChat agentId={agentId} initialProjectId={projectId} />)
  const dialog = await editProject()
  fireEvent.change(within(dialog).getByLabelText("项目名称"), {
    target: { value: "   " },
  })
  expect(
    (within(dialog).getByRole("button", { name: "保存" }) as HTMLButtonElement)
      .disabled
  ).toBe(true)
  fireEvent.change(within(dialog).getByLabelText("项目名称"), {
    target: { value: "Retried research" },
  })
  fireEvent.click(within(dialog).getByRole("button", { name: "保存" }))
  await within(dialog).findByRole("alert")
  expect(projects[0]!.name).toBe("Research")
  fail = false
  await waitFor(() =>
    expect(
      (
        within(dialog).getByRole("button", {
          name: "保存",
        }) as HTMLButtonElement
      ).disabled
    ).toBe(false)
  )
  fireEvent.click(within(dialog).getByRole("button", { name: "保存" }))
  await waitForElementToBeRemoved(dialog)
  expect(projects[0]!.name).toBe("Retried research")
})

test("opens the editor from mobile history and returns focus when it closes", async () => {
  renderPage(<PublicAgentChat agentId={agentId} />)
  const historyButton = await screen.findByRole("button", {
    name: "打开历史记录",
  })
  fireEvent.click(historyButton)
  const history = await screen.findByRole("dialog", { name: "历史记录" })
  fireEvent.pointerDown(
    within(history).getByRole("button", { name: "更多项目操作：Research" }),
    { button: 0, ctrlKey: false }
  )
  fireEvent.click(await screen.findByRole("menuitem", { name: "编辑" }))
  const editor = await screen.findByRole("dialog", { name: "编辑项目" })
  expect(screen.queryByRole("dialog", { name: "历史记录" })).toBeNull()
  fireEvent.click(within(editor).getByRole("button", { name: "关闭" }))
  await waitFor(() =>
    expect(document.activeElement === historyButton).toBe(true)
  )
  expect(screen.getByLabelText("请输入问题")).toBeTruthy()
})

test("localizes project API errors in all three languages", () => {
  for (const language of ["zh-Hans", "zh-Hant", "en"] as const) {
    const t: TFunction = (key, values) => translate(language, key, values)
    expect(
      getErrorMessage(new ApiError(409, "Chat project is archived."), t)
    ).toBe(translate(language, "项目已归档，请先恢复项目"))
  }
})
