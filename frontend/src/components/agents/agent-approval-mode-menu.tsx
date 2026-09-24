"use client"

import * as React from "react"
import {
  CheckIcon,
  ChevronDownIcon,
  HandIcon,
  ShieldAlertIcon,
  ShieldCheckIcon,
} from "lucide-react"

import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import type { TFunction } from "@/i18n"
import type { AgentApprovalMode } from "@/lib/api/agents"
import { cn } from "@/lib/utils"

type AgentApprovalModeMenuProps = {
  value: AgentApprovalMode
  onChange: (value: AgentApprovalMode) => void
  disabled?: boolean
  t: TFunction
}

const MODES: AgentApprovalMode[] = ["always_ask", "ask_risky", "full_access"]

function ModeIcon({
  mode,
  className,
}: {
  mode: AgentApprovalMode
  className?: string
}) {
  if (mode === "always_ask") {
    return <HandIcon aria-hidden="true" className={className} />
  }
  if (mode === "full_access") {
    return <ShieldAlertIcon aria-hidden="true" className={className} />
  }
  return <ShieldCheckIcon aria-hidden="true" className={className} />
}

function modeLabel(mode: AgentApprovalMode, t: TFunction) {
  if (mode === "always_ask") return t("请求批准")
  if (mode === "full_access") return t("完全访问")
  return t("按策略审批")
}

function modeDescription(mode: AgentApprovalMode, t: TFunction) {
  if (mode === "always_ask") {
    return t("外部读取或副作用操作前询问")
  }
  if (mode === "full_access") {
    return t("自动运行已授权工具，仍受安全限制")
  }
  return t("仅风险操作需批准")
}

export function AgentApprovalModeMenu({
  value,
  onChange,
  disabled = false,
  t,
}: AgentApprovalModeMenuProps) {
  const label = modeLabel(value, t)
  const [isConfirmingFullAccess, setIsConfirmingFullAccess] = React.useState(false)

  /** Full access stops the per-call prompts, so it only applies once confirmed. */
  const selectMode = (mode: AgentApprovalMode) => {
    if (mode === "full_access" && value !== "full_access") {
      setIsConfirmingFullAccess(true)
      return
    }
    onChange(mode)
  }

  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button
            type="button"
            variant={value === "full_access" ? "destructive" : "secondary"}
            size="sm"
            disabled={disabled}
            aria-label={t("执行权限：{mode}", { mode: label })}
            className="max-w-36 rounded-md px-2 font-normal"
          >
            <ModeIcon mode={value} className="size-3.5" />
            <span className="truncate">{label}</span>
            <ChevronDownIcon
              aria-hidden="true"
              className="size-3.5 opacity-60"
            />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent
          align="start"
          side="top"
          sideOffset={6}
          className="w-[min(21rem,calc(100vw-1rem))] p-1.5"
        >
          <DropdownMenuLabel className="px-2.5 py-2 text-xs text-muted-foreground">
            {t("应如何批准工具调用？")}
          </DropdownMenuLabel>
          <DropdownMenuSeparator />
          {MODES.map((mode) => (
            <DropdownMenuItem
              key={mode}
              variant={mode === "full_access" ? "destructive" : "default"}
              className={cn(
                "my-0.5 items-start gap-3 rounded-lg px-2.5 py-2.5 first:mt-0 last:mb-0",
                mode === value &&
                  (mode === "full_access" ? "bg-destructive/10" : "bg-muted/70")
              )}
              onSelect={() => selectMode(mode)}
            >
              <ModeIcon mode={mode} className="mt-0.5 size-4 text-current" />
              <span className="min-w-0 flex-1">
                <span className="block font-medium">{modeLabel(mode, t)}</span>
                <span className="mt-0.5 block truncate text-xs leading-5 text-muted-foreground">
                  {modeDescription(mode, t)}
                </span>
              </span>
              {mode === value ? (
                <CheckIcon
                  aria-hidden="true"
                  className="mt-0.5 size-4 shrink-0 text-current"
                />
              ) : null}
            </DropdownMenuItem>
          ))}
        </DropdownMenuContent>
      </DropdownMenu>
      <Dialog
        open={isConfirmingFullAccess}
        onOpenChange={setIsConfirmingFullAccess}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <ShieldAlertIcon
                aria-hidden="true"
                className="size-4 text-destructive"
              />
              {t("启用完全访问？")}
            </DialogTitle>
            <DialogDescription>
              {t(
                "完全访问会自动运行已授权的工具，不再逐步询问。请确认你了解该模式的安全影响。"
              )}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => setIsConfirmingFullAccess(false)}
            >
              {t("取消")}
            </Button>
            <Button
              type="button"
              variant="destructive"
              onClick={() => {
                setIsConfirmingFullAccess(false)
                onChange("full_access")
              }}
            >
              {t("启用完全访问")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}
