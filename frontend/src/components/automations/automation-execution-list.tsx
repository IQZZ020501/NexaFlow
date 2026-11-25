"use client"

import * as React from "react"
import {
  CheckIcon,
  ChevronDownIcon,
  ChevronLeftIcon,
  ChevronRightIcon,
  ClockIcon,
  HandIcon,
  WebhookIcon,
} from "lucide-react"

import {
  dispatchStatusLabelKey,
  executionStatusDotClass,
  isExecutionFailed,
  isExecutionNeedsAction,
  runStatusMeta,
  triggerSourceLabelKey,
} from "@/components/automations/automation-badges"
import {
  SYSTEM_PAGE_SIZES,
  type SystemPageSize,
} from "@/components/system/pagination-footer"
import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import type { TFunction } from "@/i18n"
import type { AutomationExecutionSummary } from "@/lib/api/automations"
import { formatDateTime } from "@/lib/display"
import { getErrorMessage } from "@/lib/errors"
import { cn } from "@/lib/utils"

export type ExecutionListFilter = "all" | "needs_action" | "failed"

function TriggerSourceIcon({
  source,
}: {
  source: AutomationExecutionSummary["trigger_source"]
}) {
  if (source === "webhook") return <WebhookIcon className="size-3 shrink-0" />
  if (source === "manual") return <HandIcon className="size-3 shrink-0" />
  return <ClockIcon className="size-3 shrink-0" />
}

function executionRowStatusLabel(
  item: AutomationExecutionSummary,
  t: TFunction
) {
  if (
    !item.run_status &&
    (item.dispatch_status === "skipped" || item.dispatch_status === "rejected")
  ) {
    return t(dispatchStatusLabelKey(item.dispatch_status))
  }
  return t(runStatusMeta(item.run_status).key)
}

export function AutomationExecutionList({
  executions,
  selectedExecutionId,
  page,
  pageSize,
  total,
  locale,
  onSelectExecution,
  onPageChange,
  onPageSizeChange,
  t,
}: {
  executions: AutomationExecutionSummary[]
  selectedExecutionId: string | null
  page: number
  pageSize: SystemPageSize
  total: number
  locale: string
  onSelectExecution: (executionId: string) => void
  onPageChange: (page: number) => void
  onPageSizeChange: (pageSize: SystemPageSize) => void
  t: TFunction
}) {
  const [filter, setFilter] = React.useState<ExecutionListFilter>("all")

  const needsActionCount = React.useMemo(
    () =>
      executions.filter((item) =>
        isExecutionNeedsAction(item.dispatch_status, item.run_status)
      ).length,
    [executions]
  )
  const failedCount = React.useMemo(
    () =>
      executions.filter((item) =>
        isExecutionFailed(item.dispatch_status, item.run_status)
      ).length,
    [executions]
  )

  const filteredExecutions = React.useMemo(() => {
    if (filter === "needs_action") {
      return executions.filter((item) =>
        isExecutionNeedsAction(item.dispatch_status, item.run_status)
      )
    }
    if (filter === "failed") {
      return executions.filter((item) =>
        isExecutionFailed(item.dispatch_status, item.run_status)
      )
    }
    return executions
  }, [executions, filter])

  const totalPages = Math.max(1, Math.ceil(total / pageSize))
  const hasPrevious = page > 1
  const hasNext = page * pageSize < total

  return (
    <aside className="flex min-h-0 flex-col border-b bg-card lg:w-[300px] lg:shrink-0 lg:border-r lg:border-b-0">
      <div className="shrink-0 space-y-2 border-b px-3.5 py-3">
        <div className="flex items-center justify-between gap-2">
          <h2 className="text-xs font-medium text-muted-foreground">
            {t("执行历史")}
          </h2>
          <span className="text-[11px] text-muted-foreground tabular-nums">
            {t("共 {value} 条", { value: total })}
          </span>
        </div>

        <div
          role="group"
          aria-label={t("执行历史")}
          className="flex items-center gap-1"
        >
          {(
            [
              { id: "all", label: t("全部"), count: null },
              {
                id: "needs_action",
                label: t("待处理"),
                count: needsActionCount,
              },
              { id: "failed", label: t("失败"), count: failedCount },
            ] as const
          ).map((option) => {
            const active = filter === option.id
            return (
              <button
                key={option.id}
                type="button"
                aria-pressed={active}
                onClick={() => setFilter(option.id)}
                className={cn(
                  "inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs font-medium transition-colors",
                  active
                    ? "bg-muted text-foreground"
                    : "text-muted-foreground hover:bg-muted/50 hover:text-foreground"
                )}
              >
                <span>{option.label}</span>
                {option.count ? (
                  <span className="text-[11px] text-muted-foreground tabular-nums">
                    {option.count}
                  </span>
                ) : null}
              </button>
            )
          })}
        </div>
      </div>

      <div className="min-h-0 flex-1 divide-y divide-border/50 overflow-y-auto overscroll-contain">
        {executions.length === 0 ? (
          <p className="px-4 py-10 text-center text-sm text-muted-foreground">
            {t("暂无执行记录")}
          </p>
        ) : filteredExecutions.length === 0 ? (
          <p className="px-4 py-10 text-center text-sm text-muted-foreground">
            {t("无匹配的执行记录")}
          </p>
        ) : (
          filteredExecutions.map((item) => {
            const selected = item.id === selectedExecutionId
            return (
              <button
                key={item.id}
                type="button"
                aria-current={selected ? "true" : undefined}
                onClick={() => onSelectExecution(item.id)}
                className={cn(
                  "relative flex w-full flex-col gap-1 px-3.5 py-2.5 text-left transition-colors hover:bg-muted/40",
                  selected && "bg-primary/[0.06] hover:bg-primary/[0.08]"
                )}
              >
                {selected ? (
                  <span
                    aria-hidden="true"
                    className="absolute inset-y-1.5 left-0 w-0.5 rounded-r bg-primary"
                  />
                ) : null}
                <div className="flex items-center justify-between gap-2">
                  <div className="flex min-w-0 items-center gap-2">
                    <span
                      className={executionStatusDotClass(
                        item.dispatch_status,
                        item.run_status
                      )}
                    />
                    <span className="truncate text-[13px] font-medium text-foreground">
                      {executionRowStatusLabel(item, t)}
                    </span>
                  </div>
                  <span className="inline-flex shrink-0 items-center gap-1 text-[11px] text-muted-foreground">
                    <TriggerSourceIcon source={item.trigger_source} />
                    <span>{t(triggerSourceLabelKey(item.trigger_source))}</span>
                  </span>
                </div>

                <p className="pl-4 text-xs text-muted-foreground tabular-nums">
                  {formatDateTime(
                    item.scheduled_at ?? item.received_at,
                    locale
                  )}
                </p>

                {item.skip_reason ? (
                  <p className="line-clamp-2 pl-4 text-[11px] text-destructive">
                    {getErrorMessage(new Error(item.skip_reason), t)}
                  </p>
                ) : null}
              </button>
            )
          })
        )}
      </div>

      {total > 0 || page > 1 ? (
        <div className="flex shrink-0 items-center justify-between gap-2 border-t bg-muted/20 px-3 py-2 text-xs">
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                type="button"
                variant="outline"
                size="xs"
                className="gap-1.5"
              >
                <span>{t("每页 {value} 条", { value: pageSize })}</span>
                <ChevronDownIcon className="size-3" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start" className="w-32">
              {SYSTEM_PAGE_SIZES.map((option) => (
                <DropdownMenuItem
                  key={option}
                  className="justify-between"
                  onSelect={() => onPageSizeChange(option)}
                >
                  {t("每页 {value} 条", { value: option })}
                  {pageSize === option ? (
                    <CheckIcon className="size-3.5 text-primary" />
                  ) : null}
                </DropdownMenuItem>
              ))}
            </DropdownMenuContent>
          </DropdownMenu>

          <div className="flex items-center gap-1.5">
            <Button
              type="button"
              variant="outline"
              size="icon-xs"
              aria-label={t("上一页")}
              disabled={!hasPrevious}
              onClick={() => onPageChange(page - 1)}
            >
              <ChevronLeftIcon />
            </Button>
            <span className="min-w-10 text-center text-muted-foreground tabular-nums">
              {page} / {totalPages}
            </span>
            <Button
              type="button"
              variant="outline"
              size="icon-xs"
              aria-label={t("下一页")}
              disabled={!hasNext}
              onClick={() => onPageChange(page + 1)}
            >
              <ChevronRightIcon />
            </Button>
          </div>
        </div>
      ) : null}
    </aside>
  )
}
