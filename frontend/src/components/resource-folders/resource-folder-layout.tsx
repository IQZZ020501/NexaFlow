"use client"

import * as React from "react"
import type { ReactNode } from "react"
import { FolderTreeIcon, PanelLeftOpenIcon, XIcon } from "lucide-react"

import { Button } from "@/components/ui/button"
import { IconButton } from "@/components/ui/icon-button"
import { ResourceFolderPanelContext } from "@/components/resource-folders/resource-folder-panel"
import { useLanguage } from "@/contexts/language-provider"
import { FOLDER_PANEL_COLLAPSED_KEY } from "@/lib/storage"
import { cn } from "@/lib/utils"

// Collapse before paint so a restored panel never flashes open.
const useLayoutOrEffect =
  typeof window === "undefined" ? React.useEffect : React.useLayoutEffect

export function ResourceFolderLayout({
  sidebar,
  children,
}: {
  sidebar: ReactNode
  children: ReactNode
}) {
  const { t } = useLanguage()
  const [isFolderPanelOpen, setIsFolderPanelOpen] = React.useState(false)
  const [isPanelCollapsed, setIsPanelCollapsed] = React.useState(false)
  const shouldFocusToggleRef = React.useRef(false)
  const railToggleRef = React.useRef<HTMLButtonElement>(null)
  const panelRef = React.useRef<HTMLDivElement>(null)

  useLayoutOrEffect(() => {
    setIsPanelCollapsed(
      localStorage.getItem(FOLDER_PANEL_COLLAPSED_KEY) === "1"
    )
  }, [])

  // Collapsing swaps the control for its counterpart, so hand focus over
  // instead of dropping it on the document.
  useLayoutOrEffect(() => {
    if (!shouldFocusToggleRef.current) return
    shouldFocusToggleRef.current = false
    const nextToggle = isPanelCollapsed
      ? railToggleRef.current
      : panelRef.current?.querySelector<HTMLElement>(
          '[data-slot="folder-panel-collapse"]'
        )
    nextToggle?.focus()
  }, [isPanelCollapsed])

  const panelValue = React.useMemo(
    () => ({
      isCollapsed: isPanelCollapsed,
      setCollapsed: (next: boolean) => {
        shouldFocusToggleRef.current = true
        setIsPanelCollapsed(next)
        localStorage.setItem(FOLDER_PANEL_COLLAPSED_KEY, next ? "1" : "0")
      },
    }),
    [isPanelCollapsed]
  )

  return (
    <div className="flex min-w-0 flex-col gap-4 lg:h-[calc(100svh-11rem)] lg:min-h-0 lg:flex-row lg:items-stretch lg:overflow-hidden">
      <Button
        type="button"
        variant="outline"
        aria-expanded={isFolderPanelOpen}
        aria-controls="resource-folder-panel"
        className="w-full justify-start lg:hidden"
        onClick={() => setIsFolderPanelOpen((current) => !current)}
      >
        {isFolderPanelOpen ? <XIcon /> : <FolderTreeIcon />}
        {t(isFolderPanelOpen ? "收起目录" : "展开目录")}
      </Button>
      {isPanelCollapsed ? (
        <div className="hidden w-11 shrink-0 flex-col items-center rounded-lg border bg-background p-1.5 shadow-sm lg:flex lg:h-full">
          <IconButton
            ref={railToggleRef}
            label={t("展开目录")}
            aria-expanded={false}
            aria-controls="resource-folder-panel"
            onClick={() => panelValue.setCollapsed(false)}
          >
            <PanelLeftOpenIcon />
          </IconButton>
        </div>
      ) : null}
      <div
        id="resource-folder-panel"
        ref={panelRef}
        data-theme-sidebar-panel="true"
        className={cn(
          "min-w-0",
          !isFolderPanelOpen && "hidden",
          isPanelCollapsed ? "lg:hidden" : "lg:contents"
        )}
      >
        <ResourceFolderPanelContext.Provider value={panelValue}>
          {sidebar}
        </ResourceFolderPanelContext.Provider>
      </div>
      <div className="min-w-0 flex-1 space-y-4 lg:min-h-0 lg:overflow-y-auto lg:overscroll-contain">
        {children}
      </div>
    </div>
  )
}
