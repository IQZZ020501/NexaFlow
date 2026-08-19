import { KnowledgeBasePage } from "@/components/knowledge/knowledge-base-page"
import {
  parseKnowledgeUploadRouteState,
  type KnowledgeUploadSearchParams,
} from "@/lib/knowledge-upload-route"

/**
 * Renders the knowledge upload page for the segment step.
 *
 * @param searchParams - Search parameters that define the upload route state.
 */
export default async function KnowledgeUploadSegmentPage({
  searchParams,
}: {
  searchParams: Promise<KnowledgeUploadSearchParams>
}) {
  return (
    <KnowledgeBasePage
      uploadStep="segment"
      uploadRouteState={parseKnowledgeUploadRouteState(await searchParams)}
    />
  )
}
