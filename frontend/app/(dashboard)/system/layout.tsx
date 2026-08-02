"use client"

import * as React from "react"

import { SessionGate } from "@/components/app/session-gate"

export default function SystemLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <SessionGate>
      <main className="flex min-h-svh w-full min-w-0 flex-col gap-4 overflow-x-hidden bg-muted/20 px-4 py-6 sm:px-6 lg:px-8">
        {children}
      </main>
    </SessionGate>
  )
}
