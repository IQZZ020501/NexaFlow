/* @jsxImportSource react */
import { describe, expect, test } from "bun:test"
import { SkillDialog } from "@/components/tools/skill-dialog"
import { fireEvent, jsonResponse, renderPage, screen, waitFor } from "./helpers/dom"

const definition = {
  instructions: "Run the bundled script only when needed.", intents: [],
  input_schema: { type: "object" }, output_schema: { type: "object" },
  knowledge_base_ids: [], tools: [], files: { "scripts/main.py": "cHJpbnQoMSk=" },
  execution_timeout_seconds: 30,
  guardrails: { allow_external_reads: false, allow_external_writes: false, require_approval_for_external_writes: true },
}

describe("SkillDialog", () => {
  test("rejects oversized imports locally and leaves server import errors retryable", async () => {
    let imports = 0
    globalThis.fetch = (async (input) => {
      expect(String(input)).toContain("/imports/inspect")
      imports++
      return jsonResponse({ detail: "Malformed package" }, 422)
    }) as typeof fetch
    let closed = false
    renderPage(<SkillDialog open token="test" workspaceId="ws-1" onSaved={() => undefined} onOpenChange={(value) => { closed = !value }} />)
    const input = screen.getByLabelText("选择 Skill 文件")
    fireEvent.change(input, { target: { files: [new File([new Uint8Array(2 * 1024 * 1024 + 1)], "large.zip")] } })
    expect(screen.getByRole("alert").textContent).toBe("Skill 包不能超过 2 MiB")
    expect(imports).toBe(0)
    fireEvent.change(input, { target: { files: [new File(["bad"], "bad.zip")] } })
    await waitFor(() => expect(screen.getByRole("alert").textContent).toBe("Malformed package"))
    expect(imports).toBe(1)
    expect((screen.getByRole("button", { name: "导入 Skill" }) as HTMLButtonElement).disabled).toBe(false)
    fireEvent.click(screen.getByRole("button", { name: "取消" }))
    expect(closed).toBe(true)
  })

  test("persists and publishes an imported package without discarding assets", async () => {
    const calls: { url: string; method?: string; body?: unknown }[] = []
    globalThis.fetch = (async (input, options) => {
      const url = String(input)
      calls.push({ url, method: options?.method, body: typeof options?.body === "string" ? JSON.parse(options.body) : options?.body })
      if (url.endsWith("/imports/inspect")) return jsonResponse({ name: "research", description: "Research tasks", definition })
      if (url.endsWith("/publish")) return jsonResponse({ id: "version-1" })
      return jsonResponse({ id: "skill-1" })
    }) as typeof fetch
    let saved = 0
    let closed = false
    renderPage(<SkillDialog open token="test" workspaceId="ws-1" onSaved={() => saved++} onOpenChange={(value) => { closed = !value }} />)
    fireEvent.change(screen.getByLabelText("选择 Skill 文件"), { target: { files: [new File(["zip"], "research.zip")] } })
    await waitFor(() => expect((screen.getByLabelText("显示名称") as HTMLInputElement).value).toBe("research"))
    fireEvent.click(screen.getByRole("button", { name: "保存并发布" }))
    await waitFor(() => expect(closed).toBe(true))
    expect(saved).toBe(2)
    const create = calls.find((call) => call.url.endsWith("/agent-skills"))!
    expect((create.body as { definition: typeof definition }).definition.files["scripts/main.py"]).toBe("cHJpbnQoMSk=")
    expect(calls.filter((call) => call.url.endsWith("/publish"))).toHaveLength(1)
  })

  test("retains the saved draft ID when publishing fails", async () => {
    let creates = 0
    let publishes = 0
    globalThis.fetch = (async (input) => {
      const url = String(input)
      if (url.endsWith("/imports/inspect")) return jsonResponse({ name: "research", description: "Research tasks", definition })
      if (url.endsWith("/publish")) { publishes++; return publishes === 1 ? jsonResponse({ detail: "failed publication" }, 409) : jsonResponse({ id: "v1" }) }
      if (url.endsWith("/agent-skills")) creates++
      return jsonResponse({ id: "skill-1" })
    }) as typeof fetch
    renderPage(<SkillDialog open token="test" workspaceId="ws-1" onSaved={() => undefined} onOpenChange={() => undefined} />)
    fireEvent.change(screen.getByLabelText("显示名称"), { target: { value: "research" } })
    fireEvent.change(screen.getByLabelText("描述"), { target: { value: "Research tasks" } })
    fireEvent.change(screen.getByLabelText("技能指令"), { target: { value: "Do the task." } })
    fireEvent.click(screen.getByRole("button", { name: "保存并发布" }))
    await screen.findByRole("alert")
    fireEvent.click(screen.getByRole("button", { name: "保存并发布" }))
    await waitFor(() => expect(publishes).toBe(2))
    expect(creates).toBe(1)
  })
})
