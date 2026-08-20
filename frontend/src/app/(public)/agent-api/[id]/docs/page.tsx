import { AgentApiDocumentation } from "@/components/agents/agent-api-documentation"

type AgentApiDocumentationPageProps = {
  params: Promise<{ id: string }>
}

/**
 * Renders the public API documentation page for an agent.
 *
 * @param params - Route parameters containing the agent ID
 * @returns The agent API documentation page
 */
export default async function AgentApiDocumentationPage({
  params,
}: AgentApiDocumentationPageProps) {
  const { id } = await params
  return <AgentApiDocumentation agentId={id} />
}
