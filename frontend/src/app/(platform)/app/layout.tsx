"use client"

import * as React from "react"

import { SessionGate } from "@/components/app/session-gate"
import { TopBar } from "@/components/app/top-bar"

/**
 * Provides the shared layout for platform pages.
 *
 * @param children - The platform page content to render.
 */
export default function PlatformLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <SessionGate>
      <div className="min-h-svh overflow-x-clip bg-muted/20">
        <TopBar />
        <main className="theme-page-main flex w-full min-w-0 flex-col overflow-x-clip sm:pb-6">
          {children}
        </main>
      </div>
    </SessionGate>
  )
}
