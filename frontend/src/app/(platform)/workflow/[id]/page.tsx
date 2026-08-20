import { AgentsPage } from "@/components/agents/agents-page"

/**
 * Renders the workflow canvas page in settings view.
 */
export default function WorkflowCanvasPage() {
  return <AgentsPage initialView="settings" workflowCanvasMode />
}
