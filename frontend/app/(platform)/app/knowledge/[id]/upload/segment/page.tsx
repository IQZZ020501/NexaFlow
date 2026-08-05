import { KnowledgeBasePage } from "@/components/knowledge/knowledge-base-page"
import {
  parseKnowledgeUploadRouteState,
  type KnowledgeUploadSearchParams,
} from "@/lib/knowledge-upload-route"

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
