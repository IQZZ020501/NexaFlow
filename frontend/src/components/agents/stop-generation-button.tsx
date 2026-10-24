"use client"

import * as React from "react"
import { LoaderCircleIcon, SquareIcon } from "lucide-react"

import { Button } from "@/components/ui/button"
import type { TFunction } from "@/i18n"

/** Shows a consistent stop action while a chat run is active. */
export function StopGenerationButton({
  onStop,
  t,
}: {
  onStop: () => void | Promise<void>
  t: TFunction
}) {
  const [stopping, setStopping] = React.useState(false)
  const stoppingRef = React.useRef(false)

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
      type="button"
      variant="destructive"
      size="sm"
      className="gap-1.5 rounded-full px-3 disabled:opacity-70 motion-reduce:transition-none"
      aria-label={t("停止生成")}
      aria-busy={stopping}
      title={t(stopping ? "停止中" : "停止生成")}
      disabled={stopping}
      onClick={() => void handleStop()}
    >
      {stopping ? (
        <LoaderCircleIcon
          aria-hidden="true"
          className="size-3 animate-spin motion-reduce:animate-none"
        />
      ) : (
        <SquareIcon
          aria-hidden="true"
          className="size-2.5 fill-current"
          strokeWidth={0}
        />
      )}
      <span>{t(stopping ? "停止中" : "停止")}</span>
    </Button>
  )
}
