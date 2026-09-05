import { AgentsPage } from "@/components/agents/agents-page"
import { parseAgentDetailView } from "@/lib/agent-views"

type AgentDetailPageProps = {
  searchParams: Promise<{
    view?: string | string[]
  }>
}

/**
 * Renders the agent detail page for the requested view.
 *
 * @param searchParams - Query parameters containing the optional legacy view.
 * @returns The agent page configured with the requested detail view.
 */
export default async function AgentDetailPage({
  searchParams,
}: AgentDetailPageProps) {
  const params = await searchParams
  return (
    <AgentsPage
      hasLegacyView={params.view !== undefined}
      initialView={parseAgentDetailView(params.view)}
    />
  )
}
