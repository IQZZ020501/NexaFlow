"use client"

import { useEffect, useRef, useState, type DragEvent } from "react"
import { droppedAgentFiles } from "@/lib/agent-upload"

export function useAgentFileDrop(
  scope: string,
  disabled: boolean,
  onFiles: (files: File[]) => void,
  onError: () => void
) {
  const request = useRef<AbortController | null>(null)
  const [readingScope, setReadingScope] = useState<string | null>(null)

  useEffect(
    () => () => {
      request.current?.abort()
      setReadingScope(null)
    },
    [scope]
  )

  async function onDrop(event: DragEvent) {
    event.preventDefault()
    if (disabled) return
    request.current?.abort()
    const current = new AbortController()
    request.current = current
    setReadingScope(scope)
    try {
      const files = await droppedAgentFiles(event.dataTransfer)
      if (!current.signal.aborted) onFiles(files)
    } catch {
      if (!current.signal.aborted) onError()
    } finally {
      if (!current.signal.aborted) setReadingScope(null)
    }
  }

  function cancel() {
    request.current?.abort()
    setReadingScope(null)
  }

  return { onDrop, cancel, isReadingFiles: readingScope === scope }
}
