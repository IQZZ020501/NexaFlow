"use client"

import * as React from "react"
import type { PreviewArtifact } from "@/lib/agent-artifacts"

type Selection = {
  artifact: PreviewArtifact
  opener: HTMLButtonElement
}

export const AgentArtifactPreviewContext = React.createContext<ReturnType<
  typeof useAgentArtifactPreview
> | null>(null)

/** One preview per conversation, shared by current and historical answers. */
export function useAgentArtifactPreview(scopeKey: string) {
  const panelId = React.useId()
  const sources = React.useRef(new Map<string, string[]>())
  const prunePending = React.useRef(false)
  const [state, setState] = React.useState<{
    scopeKey: string
    selection: Selection | null
  }>({ scopeKey, selection: null })
  if (state.scopeKey !== scopeKey) {
    setState({ scopeKey, selection: null })
  }
  const selection = state.scopeKey === scopeKey ? state.selection : null

  const open = React.useCallback(
    (artifact: PreviewArtifact, opener: HTMLButtonElement) => {
      setState({ scopeKey, selection: { artifact, opener } })
    },
    [scopeKey]
  )
  const close = React.useCallback(() => {
    const opener = selection?.opener.isConnected
      ? selection.opener
      : document.querySelector<HTMLButtonElement>(
          `[aria-controls="${panelId}"][aria-expanded="true"]`
        )
    setState((current) => ({ ...current, selection: null }))
    requestAnimationFrame(() => {
      if (opener?.isConnected) opener.focus({ preventScroll: true })
    })
  }, [panelId, selection])
  const updateSource = React.useCallback(
    (ownerId: string, urls: string[] = []) => {
      if (urls.length) sources.current.set(ownerId, urls)
      else sources.current.delete(ownerId)
      if (prunePending.current) return
      prunePending.current = true
      // Answer handoffs can move a card between components in the same commit.
      // Wait until every source has registered before discarding its preview.
      queueMicrotask(() => {
        prunePending.current = false
        setState((current) => {
          const url = current.selection?.artifact.downloadUrl
          return url &&
            !Array.from(sources.current.values()).some((available) =>
              available.includes(url)
            )
            ? { ...current, selection: null }
            : current
        })
      })
    },
    []
  )

  return { selection, panelId, open, close, updateSource }
}
