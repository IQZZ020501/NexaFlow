import { ToolsPage as UnifiedToolsPage } from "@/components/tools/tools-page"

/**
 * Renders the tools page.
 */
export default async function ToolsPage({
  searchParams,
}: { searchParams?: Promise<{ tab?: string }> } = {}) {
  const tab = (await searchParams)?.tab
  const kind = tab === "mcp" ? "mcp" : "builtin"
  return <UnifiedToolsPage key={kind} initialKind={kind} />
}
