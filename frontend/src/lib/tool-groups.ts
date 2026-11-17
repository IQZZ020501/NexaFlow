import type { TFunction, TranslationKey } from "@/i18n"
import type { ToolDetail, ToolRef, ToolSummary } from "@/lib/api/tools"
import { toolDisplayName } from "@/lib/tool-display"

export type ToolGroup<T extends ToolSummary = ToolSummary> = {
  id: string
  tools: T[]
}

/** MCP services share one entry; built-in tools retain their own entries. */
export function groupTools<T extends ToolSummary>(tools: T[]): ToolGroup<T>[] {
  const groups = new Map<string, ToolGroup<T>>()
  for (const tool of tools) {
    const id = tool.kind === "mcp" ? `mcp:${tool.source.id}` : `tool:${tool.id}`
    const group = groups.get(id)
    if (group) group.tools.push(tool)
    else groups.set(id, { id, tools: [tool] })
  }
  return [...groups.values()]
}

export function toolGroupName(group: ToolGroup, t: TFunction) {
  const tool = group.tools[0]!
  return tool.kind === "mcp" ? tool.source.name : toolDisplayName(tool, t)
}

/** Add only the supplied eligible tools, preserving existing pinned versions. */
export function selectToolGroup(
  value: ToolRef[],
  tools: ToolSummary[],
  checked: boolean
) {
  const ids = new Set(tools.map((tool) => tool.id))
  if (!checked) return value.filter((reference) => !ids.has(reference.tool_id))
  const selectedIds = new Set(value.map((reference) => reference.tool_id))
  return [
    ...value,
    ...tools.flatMap((tool) =>
      tool.current_version_id && !selectedIds.has(tool.id)
        ? [{ tool_id: tool.id, version_id: tool.current_version_id }]
        : []
    ),
  ]
}

/** Summarize existing bindings without expanding a service or adding permissions. */
export function toolBindingGroups(
  value: ToolRef[],
  tools: ToolSummary[],
  t: TFunction
) {
  const catalog = new Map(tools.map((tool) => [tool.id, tool]))
  const groups = new Map<
    string,
    { id: string; name: string; references: ToolRef[] }
  >()
  for (const reference of value) {
    const tool = catalog.get(reference.tool_id)
    const id =
      tool?.kind === "mcp"
        ? `mcp:${tool.source.id}`
        : `tool:${reference.tool_id}`
    const group = groups.get(id)
    if (group) group.references.push(reference)
    else
      groups.set(id, {
        id,
        name: tool
          ? toolGroupName({ id, tools: [tool] }, t)
          : reference.tool_id,
        references: [reference],
      })
  }
  return [...groups.values()]
}

export function workflowToolDisabledReason(
  tool: ToolDetail
): TranslationKey | null {
  if (!tool.can_use) return "没有使用权限"
  if (
    tool.status !== "active" ||
    tool.availability !== "available" ||
    !tool.current_version_id
  ) {
    return "工具当前不可用"
  }
  if (tool.approval === "disabled") return "工具调用已禁用"
  if (!tool.workflow_callable) return "不支持工作流调用"
  return null
}
