import { WorkflowApiDocumentation } from "@/components/workflows/workflow-api-documentation"

/**
 * Renders API documentation for the workflow identified by the route parameters.
 *
 * @param params - Route parameters containing the workflow identifier
 */
export default async function WorkflowApiDocumentationPage({
  params,
}: {
  params: Promise<{ id: string }>
}) {
  const { id } = await params
  return <WorkflowApiDocumentation workflowId={id} />
}
