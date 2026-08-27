"use client"

import { redirect, useParams } from "next/navigation"

import { SystemShell } from "@/components/system/system-shell"

const SYSTEM_TABS = [
  "workspaces",
  "teams",
  "users",
  "audit",
  "permissions",
] as const

export type SystemTab = (typeof SYSTEM_TABS)[number]

/**
 * Renders the system page for the requested tab.
 *
 * Invalid tab values redirect to the workspaces tab.
 */
export default function SystemTabPage() {
  const params = useParams<{ tab: string }>()
  const tab = params.tab

  if (!SYSTEM_TABS.includes(tab as SystemTab)) {
    redirect("/system/workspaces")
  }

  return <SystemShell activeTab={tab as SystemTab} />
}
