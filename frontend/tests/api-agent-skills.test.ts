import { afterEach, describe, expect, test } from "bun:test"
import {
  createAgentSkill,
  inspectSkillImport,
  listAgentSkillVersions,
  listAgentSkills,
  listAllAgentSkills,
  publishAgentSkill,
  updateAgentSkill,
  type SkillDraft,
} from "@/lib/api/agent-skills"

const originalFetch = globalThis.fetch
afterEach(() => { globalThis.fetch = originalFetch })

describe("workspace Skill API", () => {
  test("paginates every Skill in the workspace catalog", async () => {
    const offsets: string[] = []
    globalThis.fetch = (async (input) => {
      const url = new URL(String(input), "http://localhost")
      const offset = url.searchParams.get("offset") ?? "0"
      offsets.push(offset)
      expect(url.pathname).toBe("/api/v1/workspaces/ws-1/agent-skills")
      return Response.json(offset === "0" ? Array.from({ length: 200 }, (_, i) => ({ id: `skill-${i}` })) : [{ id: "last" }])
    }) as typeof fetch
    expect(await listAllAgentSkills("token", "ws-1")).toHaveLength(201)
    expect(offsets).toEqual(["0", "200"])
  })

  test("uses authenticated workspace routes and sends imports as multipart", async () => {
    const calls: { path: string; method: string; body: unknown }[] = []
    globalThis.fetch = (async (input, options) => {
      expect(new Headers(options?.headers).get("Authorization")).toBe("Bearer token")
      calls.push({ path: new URL(String(input), "http://localhost").pathname, method: options?.method ?? "GET", body: options?.body instanceof FormData ? options.body : options?.body ? JSON.parse(String(options.body)) : undefined })
      return Response.json({})
    }) as typeof fetch
    const draft: SkillDraft = { name: "research", description: "Research", definition: { instructions: "Body", intents: [], input_schema: {}, output_schema: {}, knowledge_base_ids: [], tools: [], files: {}, execution_timeout_seconds: 30, guardrails: { allow_external_reads: false, allow_external_writes: false, require_approval_for_external_writes: true } } }
    await createAgentSkill("token", "ws-1", draft)
    await updateAgentSkill("token", "ws-1", "skill-1", { status: "disabled" })
    await publishAgentSkill("token", "ws-1", "skill-1")
    await listAgentSkillVersions("token", "ws-1", "skill-1")
    await listAgentSkills("token", "ws-1")
    await inspectSkillImport("token", "ws-1", new File(["zip"], "research.zip"))
    expect(calls.map(({ path, method }) => [path, method])).toEqual([
      ["/api/v1/workspaces/ws-1/agent-skills", "POST"],
      ["/api/v1/workspaces/ws-1/agent-skills/skill-1", "PATCH"],
      ["/api/v1/workspaces/ws-1/agent-skills/skill-1/publish", "POST"],
      ["/api/v1/workspaces/ws-1/agent-skills/skill-1/versions", "GET"],
      ["/api/v1/workspaces/ws-1/agent-skills", "GET"],
      ["/api/v1/workspaces/ws-1/agent-skills/imports/inspect", "POST"],
    ])
    expect(calls[0].body).toEqual(draft)
    expect(calls[1].body).toEqual({ status: "disabled" })
    expect(((calls[5].body as FormData).get("file") as File).name).toBe("research.zip")
  })
})
