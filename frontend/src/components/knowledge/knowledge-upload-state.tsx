"use client"

import * as React from "react"
import type { KnowledgeDocument } from "@/lib/api/knowledge"

type Upload = () => Promise<KnowledgeDocument[]>

const KnowledgeUploadStateContext = React.createContext<{
  files: File[]
  setFiles: React.Dispatch<React.SetStateAction<File[]>>
  prepareUpload: (upload: Upload) => void
  startUpload: () => Promise<KnowledgeDocument[]> | null
} | null>(null)

/**
 * Provides shared state and upload controls for knowledge-file uploads.
 *
 * @param children - The descendant components that can access the upload state
 */
export function KnowledgeUploadStateProvider({
  children,
}: {
  children: React.ReactNode
}) {
  const [files, setFilesState] = React.useState<File[]>([])
  const uploadRef = React.useRef<Upload | null>(null)
  const uploadPromiseRef = React.useRef<Promise<KnowledgeDocument[]> | null>(
    null,
  )

  const setFiles = React.useCallback<React.Dispatch<React.SetStateAction<File[]>>>(
    (nextFiles) => {
      uploadRef.current = null
      uploadPromiseRef.current = null
      setFilesState(nextFiles)
    },
    [],
  )
  const prepareUpload = React.useCallback((upload: Upload) => {
    uploadRef.current = upload
    uploadPromiseRef.current = null
  }, [])
  const startUpload = React.useCallback(() => {
    if (!uploadPromiseRef.current && uploadRef.current) {
      uploadPromiseRef.current = uploadRef.current()
    }
    return uploadPromiseRef.current
  }, [])

  const value = React.useMemo(
    () => ({ files, setFiles, prepareUpload, startUpload }),
    [files, prepareUpload, setFiles, startUpload],
  )

  return (
    <KnowledgeUploadStateContext.Provider value={value}>
      {children}
    </KnowledgeUploadStateContext.Provider>
  )
}

/**
 * Retrieves the knowledge-upload state from the nearest provider.
 *
 * @returns The current knowledge-upload state
 * @throws If called outside a `KnowledgeUploadStateProvider`
 */
export function useKnowledgeUploadState() {
  const state = React.useContext(KnowledgeUploadStateContext)
  if (!state) {
    throw new Error("KnowledgeUploadStateProvider is missing")
  }
  return state
}
