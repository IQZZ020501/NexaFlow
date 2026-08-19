import type { KnowledgeBaseDetailTab } from "@/lib/api/knowledge"

const KNOWLEDGE_BASE_DETAIL_TABS = [
  "documents",
  "tasks",
  "evaluation",
  "settings",
] as const satisfies readonly KnowledgeBaseDetailTab[]

export function parseKnowledgeBaseDetailTab(
  value: string | string[] | undefined
): KnowledgeBaseDetailTab | null {
  const candidate = Array.isArray(value) ? value[0] : value
  return KNOWLEDGE_BASE_DETAIL_TABS.includes(
    candidate as KnowledgeBaseDetailTab
  )
    ? (candidate as KnowledgeBaseDetailTab)
    : null
}

export function knowledgeBaseDetailPath(
  knowledgeBaseId: string,
  tab: KnowledgeBaseDetailTab
) {
  const basePath = `/app/knowledge/${encodeURIComponent(knowledgeBaseId)}`
  return tab === "documents" ? basePath : `${basePath}/${tab}`
}
