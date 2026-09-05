import { afterEach, describe, expect, test } from "bun:test"

import {
  createResourceFolder,
  deleteResourceFolder,
  listResourceFolders,
  moveResourceToFolder,
  moveResourcesToFolder,
  updateResourceFolder,
  type ResourceFolder,
} from "@/lib/api/resource-folders"
import { ApiError } from "@/lib/api-client"
import { jsonResponse, resetFetch, withFetch } from "./helpers/dom"

const TOKEN = "tok-1"
const WS = "ws-1"

type RecordedCall = { url: string; method: string; body: string | null }
let calls: RecordedCall[] = []

function install(respond: (url: string, init: RequestInit) => Response) {
  calls = []
  withFetch((url, init) => {
    const options = init ?? {}
    calls.push({
      url,
      method: options.method ?? "GET",
      body: typeof options.body === "string" ? options.body : null,
    })
    return respond(url, options)
  })
}

afterEach(() => {
  resetFetch()
})

const folder: ResourceFolder = {
  id: "folder-1",
  workspace_id: WS,
  resource_type: "knowledge",
  parent_id: null,
  name: "规章制度",
  created_by_user_id: "u-1",
  created_at: "2026-08-27T00:00:00Z",
  updated_at: "2026-08-27T00:00:00Z",
}

describe("resource folder API", () => {
  test("lists folders for a resource type", async () => {
    install(() => jsonResponse([folder]))
    const folders = await listResourceFolders(TOKEN, WS, "knowledge")
    expect(folders).toEqual([folder])
    expect(calls[0].url).toBe(
      "/api/v1/workspaces/ws-1/resource-folders?resource_type=knowledge"
    )
    expect(calls[0].method).toBe("GET")
  })

  test("creates, updates, deletes, and moves folders", async () => {
    install((url, init) => {
      if (init?.method === "POST") return jsonResponse(folder, 201)
      if (init?.method === "PATCH") return jsonResponse({ ...folder, name: "新名" })
      if (init?.method === "DELETE") return new Response(null, { status: 204 })
      if (init?.method === "PUT") return new Response(null, { status: 204 })
      throw new Error(`Unexpected request: ${url}`)
    })

    await createResourceFolder(TOKEN, WS, {
      name: "规章制度",
      resource_type: "knowledge",
      parent_id: null,
    })
    expect(calls[0].method).toBe("POST")
    expect(JSON.parse(calls[0].body ?? "null")).toEqual({
      name: "规章制度",
      resource_type: "knowledge",
      parent_id: null,
    })

    await updateResourceFolder(TOKEN, WS, "folder-1", { name: "新名" })
    expect(calls[1].method).toBe("PATCH")
    expect(calls[1].url).toContain("/resource-folders/folder-1")

    await deleteResourceFolder(TOKEN, WS, "folder-1")
    expect(calls[2].method).toBe("DELETE")

    await moveResourceToFolder(TOKEN, WS, {
      resource_type: "knowledge",
      resource_id: "kb-1",
      folder_id: "folder-1",
    })
    expect(calls[3].method).toBe("PUT")
    expect(calls[3].url).toContain("/resource-folders/resources/move")
    expect(JSON.parse(calls[3].body ?? "null")).toEqual({
      resource_type: "knowledge",
      resource_id: "kb-1",
      folder_id: "folder-1",
    })

    await moveResourcesToFolder(TOKEN, WS, {
      resource_type: "knowledge",
      resource_ids: ["kb-1", "kb-2"],
      folder_id: "folder-1",
    })
    expect(calls[4].method).toBe("PUT")
    expect(calls[4].url).toContain("/resource-folders/resources/move-batch")
    expect(JSON.parse(calls[4].body ?? "null")).toEqual({
      resource_type: "knowledge",
      resource_ids: ["kb-1", "kb-2"],
      folder_id: "folder-1",
    })
  })

  test("surfaces API errors", async () => {
    install(() =>
      jsonResponse({ detail: "Folder name already exists." }, 409)
    )
    await expect(
      createResourceFolder(TOKEN, WS, {
        name: "规章制度",
        resource_type: "knowledge",
        parent_id: null,
      })
    ).rejects.toThrow(ApiError)
  })
})
