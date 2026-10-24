"use client"

import * as React from "react"
import { ArrowUpIcon, LoaderCircleIcon, SquareIcon } from "lucide-react"

import { Button } from "@/components/ui/button"
import type { TFunction } from "@/i18n"

/** Uses one action for sending drafts and stopping an active chat run. */
export function AgentChatSubmitButton({
  isRunning,
  hasInput,
  sendDisabled = false,
  onStop,
  t,
}: {
  isRunning: boolean
  hasInput: boolean
  sendDisabled?: boolean
  onStop: () => void | Promise<void>
  t: TFunction
}) {
  const [stopping, setStopping] = React.useState(false)
  const stoppingRef = React.useRef(false)
  const showStop = isRunning && !hasInput
  const label = t(
    showStop ? "停止生成" : isRunning ? "追加后续任务" : "发送问题"
  )

  async function handleStop() {
    if (stoppingRef.current) return
    stoppingRef.current = true
    setStopping(true)
    try {
      await onStop()
    } finally {
      stoppingRef.current = false
      setStopping(false)
    }
  }

  return (
    <Button
      type={showStop ? "button" : "submit"}
      variant={showStop ? "destructive" : "default"}
      size="icon"
      className="rounded-full motion-reduce:transition-none"
      aria-label={label}
      aria-busy={stopping}
      title={showStop && stopping ? t("停止中") : label}
      disabled={stopping || (!showStop && (!hasInput || sendDisabled))}
      onClick={showStop ? () => void handleStop() : undefined}
    >
      {!showStop ? (
        <ArrowUpIcon aria-hidden="true" />
      ) : stopping ? (
        <LoaderCircleIcon
          aria-hidden="true"
          className="size-4 animate-spin motion-reduce:animate-none"
        />
      ) : (
        <SquareIcon
          aria-hidden="true"
          className="size-3 fill-current"
          strokeWidth={0}
        />
      )}
    </Button>
  )
}
