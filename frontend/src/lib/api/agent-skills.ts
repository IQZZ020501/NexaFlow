import { listQuery, request } from "@/lib/api-client"
import type { ToolRef } from "@/lib/api/tools"

export type AgentSkillDefinition = {
  intents: string[]
  instructions: string
  input_schema: Record<string, unknown>
  output_schema: Record<string, unknown>
  knowledge_base_ids: string[]
  tools: ToolRef[]
  files: Record<string, string>
  execution_timeout_seconds: number
  guardrails: {
    allow_external_reads: boolean
    allow_external_writes: boolean
    require_approval_for_external_writes: boolean
  }
}

export type AgentSkillRef = {
  skill_id: string
  version_id: string
}

export type AgentSkill = {
  id: string
  workspace_id: string
  name: string
  description: string
  definition: AgentSkillDefinition
  status: "active" | "disabled"
  current_published_version_id: string | null
  current_version_number: number | null
  has_unpublished_changes: boolean
  permission: "owner" | "admin" | "view" | "use"
  can_manage: boolean
  can_use: boolean
  created_by_user_id: string
  created_at: string
  updated_at: string
}

function skillsPath(workspaceId: string, suffix = "") {
  return `/api/v1/workspaces/${workspaceId}/agent-skills${suffix}`
}

export type SkillDraft = {
  name: string
  description: string
  definition: AgentSkillDefinition
}

export type AgentSkillVersion = SkillDraft & {
  id: string
  version_number: number
  definition_hash: string
  created_at: string
}

export function inspectSkillImport(
  token: string,
  workspaceId: string,
  file: File
) {
  const body = new FormData()
  body.set("file", file)
  return request<SkillDraft>(skillsPath(workspaceId, "/imports/inspect"), {
    token,
    method: "POST",
    body,
  })
}

export function createAgentSkill(
  token: string,
  workspaceId: string,
  draft: SkillDraft
) {
  return request<AgentSkill>(skillsPath(workspaceId), {
    token,
    method: "POST",
    body: JSON.stringify(draft),
  })
}

export function updateAgentSkill(
  token: string,
  workspaceId: string,
  skillId: string,
  payload: Partial<SkillDraft> & { status?: "active" | "disabled" }
) {
  return request<AgentSkill>(skillsPath(workspaceId, `/${skillId}`), {
    token,
    method: "PATCH",
    body: JSON.stringify(payload),
  })
}

export function publishAgentSkill(
  token: string,
  workspaceId: string,
  skillId: string
) {
  return request<AgentSkillVersion>(
    skillsPath(workspaceId, `/${skillId}/publish`),
    { token, method: "POST" }
  )
}

export function listAgentSkillVersions(
  token: string,
  workspaceId: string,
  skillId: string
) {
  return request<AgentSkillVersion[]>(
    skillsPath(workspaceId, `/${skillId}/versions`),
    { token }
  )
}

export function listAgentSkills(
  token: string,
  workspaceId: string,
  options: { limit?: number; offset?: number } = {}
) {
  return request<AgentSkill[]>(
    `${skillsPath(workspaceId)}${listQuery(options)}`,
    { token }
  )
}

export async function listAllAgentSkills(token: string, workspaceId: string) {
  const skills: AgentSkill[] = []
  let offset = 0
  const pageSize = 200
  while (true) {
    const page = await listAgentSkills(token, workspaceId, {
      limit: pageSize,
      offset,
    })
    skills.push(...page)
    if (page.length < pageSize) return skills
    offset += page.length
  }
}
