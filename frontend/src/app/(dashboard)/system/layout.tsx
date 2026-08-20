"use client"

import * as React from "react"

import { SessionGate } from "@/components/app/session-gate"
import { TopBar } from "@/components/app/top-bar"

export default function SystemLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <SessionGate>
      <div className="min-h-svh overflow-x-clip bg-muted/20">
        <TopBar />
        <main className="flex w-full min-w-0 flex-col gap-4 overflow-x-clip px-4 py-6 sm:px-6 lg:px-8">
          {children}
        </main>
      </div>
    </SessionGate>
  )
}
