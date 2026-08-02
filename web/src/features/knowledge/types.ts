import type { User } from "@/features/auth/types"

export type KnowledgeBase = {
  id: string
  workspace_id: string
  name: string
  description: string
  status: string
  created_by_user_id: string
  created_at: string
  updated_at: string
  permission: "view" | "edit" | "none"
}

export type ResourcePermission = {
  user: User
  permission: "view" | "edit"
}

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
