"use client"

import * as React from "react"
import { CheckIcon, CircleAlertIcon, CopyIcon } from "lucide-react"

import type { TFunction } from "@/i18n"
import { copyText } from "@/lib/clipboard"
import { cn } from "@/lib/utils"

import { Button } from "./button"
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "./tooltip"

/** Copies text with brief success feedback and a visible, retryable failure. */
export function CopyButton({
  value,
  label,
  showLabel = false,
  t,
}: {
  value: string
  label?: string
  showLabel?: boolean
  t: TFunction
}) {
  const [feedback, setFeedback] = React.useState<{
    value: string
    status: "copied" | "error"
  } | null>(null)
  const timerRef = React.useRef<ReturnType<typeof setTimeout> | null>(null)
  const requestRef = React.useRef(0)
  const status = feedback?.value === value ? feedback.status : null
  const feedbackLabel = t(status === "error" ? "复制失败" : "已复制")
  const buttonLabel = status ? feedbackLabel : (label ?? t("复制"))

  React.useEffect(
    () => () => {
      requestRef.current++
      if (timerRef.current) clearTimeout(timerRef.current)
    },
    []
  )

  async function handleCopy() {
    const request = ++requestRef.current
    if (timerRef.current) clearTimeout(timerRef.current)
    let nextStatus: "copied" | "error" = "copied"
    try {
      await copyText(value)
    } catch {
      nextStatus = "error"
    }
    if (request !== requestRef.current) return
    setFeedback({ value, status: nextStatus })
    timerRef.current = setTimeout(() => setFeedback(null), 2000)
  }

  return (
    <TooltipProvider delayDuration={250}>
      <span className="inline-flex items-center gap-1">
        <span
          role="status"
          className={
            status === "error" && !showLabel
              ? "text-xs text-destructive"
              : "sr-only"
          }
        >
          {status ? feedbackLabel : ""}
        </span>
        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              type="button"
              variant="ghost"
              size={showLabel ? "xs" : "icon-xs"}
              className={cn(
                !showLabel && "text-muted-foreground",
                status === "error" && "text-destructive"
              )}
              aria-label={buttonLabel}
              title={buttonLabel}
              onClick={() => void handleCopy()}
            >
              {status === "copied" ? (
                <CheckIcon />
              ) : status === "error" ? (
                <CircleAlertIcon />
              ) : (
                <CopyIcon />
              )}
              {showLabel ? (status ? feedbackLabel : t("复制")) : null}
            </Button>
          </TooltipTrigger>
          <TooltipContent>{buttonLabel}</TooltipContent>
        </Tooltip>
      </span>
    </TooltipProvider>
  )
}
