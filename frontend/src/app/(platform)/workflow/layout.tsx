"use client"

import * as React from "react"

import { SessionGate } from "@/components/app/session-gate"

/**
 * Wraps workflow content with session gating in a full-screen container.
 *
 * @param children - The workflow content to render
 */
export default function WorkflowLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <SessionGate>
      <div className="h-svh overflow-hidden">{children}</div>
    </SessionGate>
  )
}
