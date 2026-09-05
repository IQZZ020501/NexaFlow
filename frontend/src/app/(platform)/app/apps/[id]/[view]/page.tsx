import { redirect } from "next/navigation"

import { AgentsPage } from "@/components/agents/agents-page"
import { appViewPath, parseAgentDetailView } from "@/lib/agent-views"

/**
 * Renders an agent detail view or redirects overview requests to the canonical app path.
 *
 * @param params - The agent identifier and requested detail view.
 */
export default async function AgentDetailViewPage({
  params,
}: {
  params: Promise<{ id: string; view: string }>
}) {
  const { id, view } = await params
  const initialView = parseAgentDetailView(view)

  if (initialView === "overview") {
    redirect(appViewPath(id, "agent", "overview"))
  }

  return <AgentsPage initialView={initialView} />
}
