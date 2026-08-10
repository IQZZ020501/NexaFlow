import { AgentApiDocumentation } from "@/components/agents/agent-api-documentation"

type AgentApiDocumentationPageProps = {
  params: Promise<{ id: string }>
}

export default async function AgentApiDocumentationPage({
  params,
}: AgentApiDocumentationPageProps) {
  const { id } = await params
  return <AgentApiDocumentation agentId={id} />
}
