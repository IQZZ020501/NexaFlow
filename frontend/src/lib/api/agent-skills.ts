import { listQuery, request } from "@/lib/api-client"
import type { ToolRef } from "@/lib/api/tools"

export type AgentSkillDefinition = {
  intents: string[]
  instructions: string
  input_schema: Record<string, unknown>
  output_schema: Record<string, unknown>
  knowledge_base_ids: string[]
  tools: ToolRef[]
  retrieval: {
    max_calls: number
    max_rounds: number
    min_evidence_items: number
    require_source_diversity: boolean
  }
  budgets: {
    max_runtime_seconds: number
    max_turns: number
    max_tool_calls: number
    max_model_tokens: number
  }
  stop: {
    max_no_progress_rounds: number
    allow_best_effort: boolean
  }
  guardrails: {
    allow_external_reads: boolean
    allow_external_writes: boolean
    require_approval_for_external_writes: boolean
  }
  evaluation: {
    require_grounding: boolean
    min_evidence_count: number
    max_tool_failures: number
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
