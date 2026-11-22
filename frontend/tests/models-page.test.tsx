/* @jsxImportSource react */
import { beforeEach, describe, expect, test } from "bun:test"

import { LlmPage } from "@/components/llm/llm-page"
import type { RegisteredModel } from "@/lib/api/llm"
import {
  fireEvent,
  jsonResponse,
  makeSession,
  mockUseSession,
  renderPage,
  screen,
  waitFor,
  within,
} from "./helpers/dom"

const session = makeSession()
mockUseSession(session)
const modelListUrls: string[] = []

function model(overrides: Partial<RegisteredModel>): RegisteredModel {
  return {
    id: "model-alpha",
    workspace_id: "ws-1",
    folder_id: null,
    name: "Alpha",
    provider: "model_custom_provider",
    provider_type: "openai_compatible",
    model_type: "LLM",
    model_name: "alpha-chat",
    status: "active",
    credential: {},
    api_base: "https://models.example.com/v1",
    has_api_key: false,
    visibility: "workspace",
    can_manage: true,
    api_key_hint: null,
    meta: {},
    created_by_user_id: "u-1",
    created_at: "2026-09-02T00:00:00Z",
    updated_at: "2026-09-01T00:00:00Z",
    ...overrides,
  }
}

beforeEach(() => {
  Object.assign(session, makeSession())
  modelListUrls.length = 0
  globalThis.fetch = ((input: RequestInfo | URL) => {
    const url = String(input)
    if (url.includes("/resource-folders")) {
      return Promise.resolve(
        jsonResponse([
          {
            id: "folder-1",
            workspace_id: "ws-1",
            resource_type: "model",
            parent_id: null,
            name: "归档模型",
            created_by_user_id: "u-1",
            created_at: "2026-09-01T00:00:00Z",
            updated_at: "2026-09-01T00:00:00Z",
          },
        ])
      )
    }
    if (url.includes("/model-providers/base-models")) {
      return Promise.resolve(
        jsonResponse([
          { name: "alpha-chat", desc: "Alpha Chat", model_type: "LLM" },
        ])
      )
    }
    if (url.includes("/model-providers/credential-form")) {
      return Promise.resolve(jsonResponse([]))
    }
    if (url.includes("/model-providers")) {
      return Promise.resolve(
        jsonResponse([
          {
            provider: "model_custom_provider",
            name: "Custom",
            provider_type: "openai_compatible",
            icon: "",
            model_types: ["LLM"],
            default_api_base: "",
            integration: {
              adapter: "langchain-openai",
              runtime_sdk: "openai",
              provider_sdk: null,
              api_protocol: "openai_compatible",
              model_catalog: "user_defined",
              docs_url: "https://platform.openai.com/docs/api-reference/chat",
              models_url: "https://platform.openai.com/docs/api-reference/chat",
              verified_at: "2026-09-10",
            },
          },
        ])
      )
    }
    if (url.includes("/models")) {
      modelListUrls.push(url)
      const params = new URL(url, "http://localhost").searchParams
      if (params.get("folder_id") === "folder-1") {
        return Promise.resolve(
          jsonResponse([
            model({
              id: "model-charlie",
              folder_id: "folder-1",
              name: "Charlie",
              model_name: "charlie-chat",
              updated_at: "2026-09-03T00:00:00Z",
            }),
          ])
        )
      }
      const rootModels = [
        model({}),
        model({
          id: "model-bravo",
          name: "Bravo",
          model_name: "bravo-chat",
          created_at: "2026-09-01T00:00:00Z",
          updated_at: "2026-09-02T00:00:00Z",
        }),
      ]
      return Promise.resolve(
        jsonResponse(
          params.get("sort") === "name" ? rootModels : rootModels.reverse()
        )
      )
    }
    return Promise.resolve(jsonResponse([]))
  }) as typeof fetch
})

describe("LlmPage", () => {
  test("members can add personal models and only manage their own cards", async () => {
    session.me.user.is_global_admin = false
    session.me.memberships[0].role = "member"
    let submitted: Record<string, unknown> | undefined
    const originalFetch = globalThis.fetch
    globalThis.fetch = ((input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input).includes("/models")) {
        if (init?.method === "POST") {
          submitted = JSON.parse(String(init.body))
          return Promise.resolve(
            jsonResponse(
              model({
                id: "created-mine",
                visibility: "personal",
                name: "Mine",
              })
            )
          )
        }
        return Promise.resolve(
          jsonResponse([
            model({ visibility: "personal", name: "Mine" }),
            model({ id: "shared", name: "Shared", can_manage: false }),
          ])
        )
      }
      return originalFetch(input, init)
    }) as typeof fetch
    renderPage(<LlmPage />)
    const mine = (await screen.findByText("Mine")).closest<HTMLElement>(
      "[data-slot='resource-card']"
    )!
    const shared = screen
      .getByText("Shared")
      .closest<HTMLElement>("[data-slot='resource-card']")!
    expect(within(mine).getByRole("button", { name: "编辑" })).toBeTruthy()
    expect(within(shared).queryByRole("button", { name: "编辑" })).toBeNull()
    fireEvent.click(screen.getByRole("button", { name: "批量管理" }))
    expect(screen.getAllByRole("checkbox")).toHaveLength(2)
    expect(within(shared).queryByRole("checkbox")).toBeNull()
    expect(shared.getAttribute("role")).not.toBe("button")

    fireEvent.click(screen.getByRole("button", { name: "接入模型" }))
    fireEvent.click(await screen.findByRole("button", { name: /Custom/ }))
    const dialog = await screen.findByRole("dialog", { name: "接入模型" })
    expect(within(dialog).getByText("仅自己")).toBeTruthy()
    expect(within(dialog).queryByRole("radio")).toBeNull()
    expect(within(dialog).queryByText("工作空间共享")).toBeNull()
    fireEvent.change(within(dialog).getByLabelText("名称"), {
      target: { value: "Mine" },
    })
    fireEvent.change(
      within(dialog).getByRole("textbox", { name: "基础模型" }),
      { target: { value: "alpha-chat" } }
    )
    fireEvent.submit(dialog.querySelector("form")!)
    await waitFor(() => expect(submitted?.visibility).toBe("personal"))
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull())
  })

  test("administrators choose personal or workspace scope, defaulting to personal", async () => {
    let submitted: Record<string, unknown> | undefined
    const originalFetch = globalThis.fetch
    globalThis.fetch = ((input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === "POST" && String(input).includes("/models")) {
        submitted = JSON.parse(String(init.body))
        return Promise.resolve(
          jsonResponse(
            model({ id: "created-team", name: "Team", visibility: "workspace" })
          )
        )
      }
      return originalFetch(input, init)
    }) as typeof fetch
    renderPage(<LlmPage />)
    await screen.findByText("Alpha")
    fireEvent.click(screen.getByRole("button", { name: "接入模型" }))
    fireEvent.click(await screen.findByRole("button", { name: /Custom/ }))
    const dialog = await screen.findByRole("dialog", { name: "接入模型" })
    const personal = within(dialog).getByRole("radio", {
      name: /仅自己/,
    }) as HTMLInputElement
    const shared = within(dialog).getByRole("radio", {
      name: /工作空间共享/,
    }) as HTMLInputElement
    expect(personal.checked).toBe(true)
    fireEvent.click(shared)
    expect(shared.checked).toBe(true)
    fireEvent.change(within(dialog).getByLabelText("名称"), {
      target: { value: "Team" },
    })
    fireEvent.change(
      within(dialog).getByRole("textbox", { name: "基础模型" }),
      { target: { value: "alpha-chat" } }
    )
    fireEvent.submit(dialog.querySelector("form")!)
    await waitFor(() => expect(submitted?.visibility).toBe("workspace"))
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull())
  })

  test("filters scope on the server and keeps the scope fixed when editing", async () => {
    const originalFetch = globalThis.fetch
    globalThis.fetch = ((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url.includes("/models")) {
        modelListUrls.push(url)
        return Promise.resolve(
          jsonResponse(
            url.includes("visibility=personal")
              ? [model({ visibility: "personal", name: "Mine" })]
              : [model({})]
          )
        )
      }
      return originalFetch(input, init)
    }) as typeof fetch
    renderPage(<LlmPage />)
    await screen.findByText("Alpha")
    fireEvent.click(screen.getByRole("button", { name: "我的模型" }))
    const heading = await screen.findByText("Mine")
    expect(screen.queryByText("Alpha")).toBeNull()
    expect(
      modelListUrls.some((url) => url.includes("visibility=personal"))
    ).toBe(true)
    expect(
      screen
        .getByRole("button", { name: "我的模型" })
        .getAttribute("aria-pressed")
    ).toBe("true")
    const card = heading.closest<HTMLElement>("[data-slot='resource-card']")!
    fireEvent.click(within(card).getByRole("button", { name: "编辑" }))
    const dialog = await screen.findByRole("dialog", { name: "编辑模型" })
    expect(within(dialog).queryByRole("radio")).toBeNull()
    expect(
      within(dialog).getByText(
        "使用范围创建后不可更改，如需其他范围请重新接入。"
      )
    ).toBeTruthy()
  })

  test("sorts models and filters them by directory", async () => {
    renderPage(<LlmPage />)

    await screen.findByText("Bravo")
    const visibleModelNames = () =>
      screen
        .getAllByRole("heading", { level: 2 })
        .map((heading) => heading.textContent)
    expect(visibleModelNames()).toEqual(["Bravo", "Alpha"])

    const sortTrigger = screen.getByRole("button", { name: "排序" })
    fireEvent.pointerDown(sortTrigger)
    fireEvent.click(await screen.findByRole("menuitem", { name: "名称" }))
    await screen.findByText("Alpha")
    expect(visibleModelNames()).toEqual(["Alpha", "Bravo"])

    fireEvent.click(screen.getByRole("button", { name: "归档模型" }))
    await screen.findByText("Charlie")
    expect(visibleModelNames()).toEqual(["Charlie"])
    expect(modelListUrls).toContain(
      "/api/v1/workspaces/ws-1/models?limit=50&offset=0&folder_id=&sort=updated_at"
    )
    expect(modelListUrls).toContain(
      "/api/v1/workspaces/ws-1/models?limit=50&offset=0&folder_id=&sort=name"
    )
    expect(modelListUrls).toContain(
      "/api/v1/workspaces/ws-1/models?limit=50&offset=0&folder_id=folder-1&sort=name"
    )
  })

  test("toggles a model by clicking its card during bulk management", async () => {
    renderPage(<LlmPage />)

    const alphaHeading = await screen.findByText("Alpha")
    expect(alphaHeading.closest("[role='button']")).toBeNull()
    fireEvent.click(screen.getByRole("button", { name: "批量管理" }))

    const alphaCard = alphaHeading.closest<HTMLElement>("[role='button']")!
    const alphaCheckbox = screen.getByRole("checkbox", {
      name: "选择 Alpha",
    }) as HTMLInputElement
    fireEvent.click(alphaCard)

    expect(alphaCheckbox.checked).toBe(true)
    expect(screen.getByText("已选择 1 项")).toBeTruthy()

    fireEvent.click(alphaCheckbox)
    expect(alphaCheckbox.checked).toBe(false)
    expect(screen.getByText("已选择 0 项")).toBeTruthy()

    fireEvent.click(alphaCard)
    globalThis.fetch = (() =>
      new Promise<Response>(() => {})) as unknown as typeof fetch
    fireEvent.click(within(alphaCard).getByRole("button", { name: "编辑" }))
    expect(screen.getByRole("dialog", { name: "编辑模型" })).toBeTruthy()
    expect(alphaCheckbox.checked).toBe(true)
    expect(screen.getByText("已选择 1 项")).toBeTruthy()
  })

  test("explains the bounded connection test and locks the dialog while saving", async () => {
    renderPage(<LlmPage />)

    const alphaHeading = await screen.findByText("Alpha")
    const alphaCard = alphaHeading.closest<HTMLElement>(
      "[data-slot='resource-card']"
    )!
    fireEvent.click(within(alphaCard).getByRole("button", { name: "编辑" }))
    const dialog = await screen.findByRole("dialog", { name: "编辑模型" })
    expect(
      within(dialog).getByText(
        "连接测试受系统超时限制；只有测试通过后才会保存模型。"
      )
    ).toBeTruthy()

    let resolveSave!: (response: Response) => void
    const previousFetch = globalThis.fetch
    globalThis.fetch = ((input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === "PATCH") {
        return new Promise<Response>((resolve) => {
          resolveSave = resolve
        })
      }
      return previousFetch(input, init)
    }) as typeof fetch

    fireEvent.click(within(dialog).getByRole("button", { name: "保存" }))

    expect((await within(dialog).findByRole("status")).textContent).toContain(
      "正在测试模型连接"
    )
    expect(
      (
        within(dialog).getByRole("button", {
          name: "取消",
        }) as HTMLButtonElement
      ).disabled
    ).toBe(true)
    const save = within(dialog).getByRole("button", {
      name: "测试并保存中...",
    }) as HTMLButtonElement
    expect(save.disabled).toBe(true)
    expect(save.getAttribute("aria-busy")).toBe("true")
    expect(save.querySelector("svg.animate-spin")).toBeTruthy()

    resolveSave(jsonResponse(model({})))
    await waitFor(() =>
      expect(screen.queryByRole("dialog") === null).toBe(true)
    )
  })
})
