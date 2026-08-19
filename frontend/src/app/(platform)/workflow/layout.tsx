"use client"

import * as React from "react"

import { SessionGate } from "@/components/app/session-gate"

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
