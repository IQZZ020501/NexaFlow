"use client"

import * as React from "react"
import Link from "next/link"
import { usePathname } from "next/navigation"

import { useLanguage } from "@/contexts/language-provider"
import { useSession } from "@/contexts/session-context"
import { getPages } from "@/lib/pages"
import { PHONE_NAV_QUERY, useMediaQuery } from "@/lib/use-media-query"
import { cn } from "@/lib/utils"
import {
  canAccessWorkspaceAnalytics,
} from "@/components/system/system-utils"
import { BarChart3Icon } from "lucide-react"

const PAGE_HREFS: Record<string, string> = {
  apps: "/app/apps",
  knowledge: "/app/knowledge",
  models: "/app/models",
  tools: "/app/tools",
}

type TabItem = {
  key: string
  href: string
  label: string
  icon: React.ComponentType<{ className?: string }>
}

/**
 * Renders the phone-sized primary navigation as a fixed bottom tab bar.
 *
 * The desktop top navigation does not fit inside a phone header, so below the
 * `sm` breakpoint the workspace entry points move to this bar and the header
 * keeps only identity, workspace switching, messages, and the account menu.
 *
 * @returns The bottom tab bar, or `null` when no authenticated user is available.
 */
export function MobileTabBar() {
  const { t } = useLanguage()
  const { me } = useSession()
  const pathname = usePathname()
  const isCompactNav = useMediaQuery(PHONE_NAV_QUERY)

  if (!me || !isCompactNav) {
    return null
  }

  const featurePages = getPages(t)
  const items: TabItem[] = featurePages.map((page) => ({
    key: page.key,
    href: PAGE_HREFS[page.key],
    label: page.label,
    icon: page.icon,
  }))

  if (canAccessWorkspaceAnalytics(me)) {
    items.push({
      key: "analytics",
      href: "/system/analytics",
      label: t("数据大屏"),
      icon: BarChart3Icon,
    })
  }

  return (
    <nav
      aria-label={t("主导航")}
      className="fixed inset-x-0 bottom-0 z-30 border-t bg-background/95 pb-safe backdrop-blur"
    >
      <ul className="flex items-stretch justify-around px-1">
        {items.map((item) => {
          const Icon = item.icon
          const isActive = pathname.startsWith(item.href)

          return (
            <li key={item.key} className="flex-1">
              <Link
                href={item.href}
                aria-current={isActive ? "page" : undefined}
                className={cn(
                  "flex min-h-14 flex-col items-center justify-center gap-0.5 rounded-md px-1 py-1.5 text-[0.6875rem] leading-none font-medium",
                  isActive
                    ? "text-foreground"
                    : "text-muted-foreground hover:text-foreground"
                )}
              >
                <Icon
                  className={cn("size-5", isActive ? "text-primary" : undefined)}
                />
                <span className="truncate">{item.label}</span>
              </Link>
            </li>
          )
        })}
      </ul>
    </nav>
  )
}
