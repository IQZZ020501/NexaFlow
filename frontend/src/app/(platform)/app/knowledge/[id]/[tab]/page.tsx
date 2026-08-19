import { redirect } from "next/navigation"

import { KnowledgeBasePage } from "@/components/knowledge/knowledge-base-page"
import {
  knowledgeBaseDetailPath,
  parseKnowledgeBaseDetailTab,
} from "@/lib/knowledge-views"

export default async function KnowledgeBaseDetailTabPage({
  params,
}: {
  params: Promise<{ id: string; tab: string }>
}) {
  const { id, tab } = await params
  const detailTab = parseKnowledgeBaseDetailTab(tab)

  if (!detailTab || detailTab === "documents") {
    redirect(knowledgeBaseDetailPath(id, "documents"))
  }

  return <KnowledgeBasePage initialDetailTab={detailTab} />
}
