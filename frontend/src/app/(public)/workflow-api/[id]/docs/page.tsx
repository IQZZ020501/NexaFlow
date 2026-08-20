import { WorkflowApiDocumentation } from "@/components/workflows/workflow-api-documentation"

export default async function WorkflowApiDocumentationPage({
  params,
}: {
  params: Promise<{ id: string }>
}) {
  const { id } = await params
  return <WorkflowApiDocumentation workflowId={id} />
}
