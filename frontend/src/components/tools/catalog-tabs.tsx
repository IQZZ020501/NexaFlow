"use client"

import Link from "next/link"

import { useLanguage } from "@/contexts/language-provider"
import type { ToolKind } from "@/lib/api/tools"
import { cn } from "@/lib/utils"

export function ToolsCatalogTabs({
  activeKind,
  onKindChange,
}: {
  activeKind: ToolKind
  onKindChange?: (kind: ToolKind) => void
}) {
  const { t } = useLanguage()
  const tabs = [
    { kind: "builtin", label: "技能", href: "/app/tools" },
    { kind: "mcp", label: "MCP", href: "/app/tools?tab=mcp" },
    { kind: "integration", label: "集成", href: "/app/tools/integrations" },
  ] as const
  return (
    <div
      role="group"
      aria-label={t("工具")}
      className="grid w-fit shrink-0 grid-cols-3 gap-0.5 rounded-lg bg-muted/70 p-0.5 max-sm:w-full sm:h-[var(--theme-control-large-height)]"
    >
      {tabs.map((tab) => {
        const active = activeKind === tab.kind
        const className = cn(
          "inline-flex min-w-18 items-center justify-center rounded-md px-3 text-sm font-medium whitespace-nowrap transition-[background-color,color,box-shadow] duration-150 outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1 focus-visible:ring-offset-background motion-reduce:transition-none max-sm:h-11",
          active
            ? "bg-background text-foreground shadow-xs"
            : "text-muted-foreground hover:bg-background/60 hover:text-foreground"
        )
        return onKindChange && tab.kind !== "integration" ? (
          <button
            key={tab.kind}
            type="button"
            aria-pressed={active}
            className={className}
            onClick={() => onKindChange(tab.kind)}
          >
            {t(tab.label)}
          </button>
        ) : (
          <Link
            key={tab.kind}
            href={tab.href}
            aria-current={active ? "page" : undefined}
            className={className}
          >
            {t(tab.label)}
          </Link>
        )
      })}
    </div>
  )
}
