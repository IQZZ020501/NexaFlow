import { MAX_KNOWLEDGE_UPLOAD_DOCUMENTS } from "@/lib/knowledge-upload-route"

/**
 * Appends new knowledge upload files while enforcing the maximum document limit.
 *
 * @param currentFiles - Files already selected for upload
 * @param nextFiles - Files to add to the selection
 * @returns The combined files, limited to the maximum allowed document count
 */
export function appendKnowledgeUploadFiles(
  currentFiles: ReadonlyArray<File>,
  nextFiles: ReadonlyArray<File>,
) {
  return [...currentFiles, ...nextFiles].slice(
    0,
    MAX_KNOWLEDGE_UPLOAD_DOCUMENTS,
  )
}
