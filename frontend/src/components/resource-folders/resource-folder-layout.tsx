"use client"

import * as React from "react"
import type { ReactNode } from "react"
import { FolderTreeIcon, XIcon } from "lucide-react"

import { Button } from "@/components/ui/button"
import { useLanguage } from "@/contexts/language-provider"
import { cn } from "@/lib/utils"

export function ResourceFolderLayout({
  sidebar,
  children,
}: {
  sidebar: ReactNode
  children: ReactNode
}) {
  const { t } = useLanguage()
  const [isFolderPanelOpen, setIsFolderPanelOpen] = React.useState(false)

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
      <div
        id="resource-folder-panel"
        className={cn("min-w-0 lg:contents", !isFolderPanelOpen && "hidden")}
      >
        {sidebar}
      </div>
      <div className="min-w-0 flex-1 space-y-4 lg:min-h-0 lg:overflow-y-auto lg:overscroll-contain">
        {children}
      </div>
    </div>
  )
}
