import { type KnowledgeBase } from "@/lib/api"

export type KnowledgeBaseForm = {
  name: string
  description: string
}

export type KnowledgeBaseEditForm = KnowledgeBaseForm & {
  id: string
}

export type KnowledgeBasePermissionForm = {
  knowledgeBase: KnowledgeBase
  userId: string
  permission: "view" | "edit"
}

export type KnowledgeBaseDetailTab =
  "documents" | "questions" | "hit-test" | "settings"
