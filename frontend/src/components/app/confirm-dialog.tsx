"use client"

import * as React from "react"

import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { useLanguage } from "@/contexts/language-provider"

type ConfirmDialogOptions = {
  description: string
  title?: string
  confirmLabel?: string
  destructive?: boolean
}

/**
 * Provides a promise-based confirmation dialog and its control function.
 *
 * @returns A tuple containing a function that opens the dialog and a dialog element to render
 */
export function useConfirmDialog() {
  const { t } = useLanguage()
  const [options, setOptions] = React.useState<ConfirmDialogOptions | null>(null)
  const resolveRef = React.useRef<((confirmed: boolean) => void) | null>(null)

  const close = React.useCallback((confirmed: boolean) => {
    const resolve = resolveRef.current
    resolveRef.current = null
    setOptions(null)
    resolve?.(confirmed)
  }, [])

  const confirm = React.useCallback(
    (nextOptions: ConfirmDialogOptions) =>
      new Promise<boolean>((resolve) => {
        resolveRef.current?.(false)
        resolveRef.current = resolve
        setOptions(nextOptions)
      }),
    [],
  )

  React.useEffect(
    () => () => {
      resolveRef.current?.(false)
      resolveRef.current = null
    },
    [],
  )

  const dialog = (
    <Dialog
      open={options !== null}
      onOpenChange={(open) => {
        if (!open) close(false)
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{options?.title ?? t("确认操作")}</DialogTitle>
          <DialogDescription>{options?.description}</DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button type="button" variant="outline" onClick={() => close(false)}>
            {t("取消")}
          </Button>
          <Button
            type="button"
            variant={options?.destructive ? "destructive" : "default"}
            onClick={() => close(true)}
          >
            {options?.confirmLabel ?? t("确认")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )

  return [confirm, dialog] as const
}
