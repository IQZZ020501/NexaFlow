"use client"

import * as React from "react"

type ResourceFolderPanelValue = {
  isCollapsed: boolean
  setCollapsed: (next: boolean) => void
}

export const ResourceFolderPanelContext =
  React.createContext<ResourceFolderPanelValue | null>(null)

/**
 * Reads the collapsible state of the resource folder panel.
 *
 * Returns `null` when the tree is rendered outside `ResourceFolderLayout`, in
 * which case it must not render a panel collapse control.
 */
export function useResourceFolderPanel() {
  return React.useContext(ResourceFolderPanelContext)
}
