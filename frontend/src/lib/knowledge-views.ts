import type { KnowledgeBaseDetailTab } from "@/lib/api/knowledge"

const KNOWLEDGE_BASE_DETAIL_TABS = [
  "documents",
  "tasks",
  "evaluation",
  "settings",
] as const satisfies readonly KnowledgeBaseDetailTab[]

/**
 * Parses a knowledge-base detail tab value.
 *
 * @param value - The tab value or query value array to parse
 * @returns The first valid detail tab, or `null` when the value is invalid or undefined
 */
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

/**
 * Builds the detail-page path for a knowledge base and tab.
 *
 * @param knowledgeBaseId - The knowledge-base identifier to include in the path
 * @param tab - The detail tab represented by the path
 * @returns The URL path for the knowledge-base detail page
 */
export function knowledgeBaseDetailPath(
  knowledgeBaseId: string,
  tab: KnowledgeBaseDetailTab
) {
  const basePath = `/app/knowledge/${encodeURIComponent(knowledgeBaseId)}`
  return tab === "documents" ? basePath : `${basePath}/${tab}`
}
