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
    api_key_hint: null,
    meta: {},
    created_by_user_id: "u-1",
    created_at: "2026-09-02T00:00:00Z",
    updated_at: "2026-09-01T00:00:00Z",
    ...overrides,
  }
}

beforeEach(() => {
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
})
