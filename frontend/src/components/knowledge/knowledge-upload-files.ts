import { MAX_KNOWLEDGE_UPLOAD_DOCUMENTS } from "@/lib/knowledge-upload-route"

export function appendKnowledgeUploadFiles(
  currentFiles: ReadonlyArray<File>,
  nextFiles: ReadonlyArray<File>,
) {
  return [...currentFiles, ...nextFiles].slice(
    0,
    MAX_KNOWLEDGE_UPLOAD_DOCUMENTS,
  )
}
