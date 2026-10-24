"use client"

import type { ReactNode } from "react"

import { cn } from "@/lib/utils"

import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "./tooltip"

/** Keeps the reason for a disabled action available to pointer and keyboard users. */
export function DisabledButtonHint({
  reason,
  className,
  children,
}: {
  reason?: string
  className?: string
  children: ReactNode
}) {
  return (
    <TooltipProvider delayDuration={250}>
      <Tooltip>
        <TooltipTrigger asChild>
          <span
            className={cn(
              "inline-flex rounded-lg outline-none focus-visible:ring-2 focus-visible:ring-ring",
              className
            )}
            tabIndex={reason ? 0 : undefined}
          >
            {children}
          </span>
        </TooltipTrigger>
        {reason ? <TooltipContent>{reason}</TooltipContent> : null}
      </Tooltip>
    </TooltipProvider>
  )
}
