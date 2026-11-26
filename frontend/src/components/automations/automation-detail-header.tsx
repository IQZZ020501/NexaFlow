"use client"

import Link from "next/link"
import {
  ArrowLeftIcon,
  KeyRoundIcon,
  PauseIcon,
  PencilIcon,
  PlayIcon,
  RefreshCwIcon,
} from "lucide-react"

import { AutomationStatusBadge } from "@/components/automations/automation-badges"
import { Button } from "@/components/ui/button"
import { CopyButton } from "@/components/ui/copy-button"
import type { TFunction } from "@/i18n"
import { automationWebhookUrl, type Automation } from "@/lib/api/automations"
import { cn } from "@/lib/utils"

export type AutomationDetailTab = "executions" | "config"

export function AutomationDetailHeader({
  automation,
  activeTab,
  totalExecutions,
  needsActionCount,
  isBusy,
  onTabChange,
  onRefresh,
  onEdit,
  onTogglePause,
  onExecuteNow,
  onRotateSecret,
  t,
}: {
  automation: Automation | null
  activeTab: AutomationDetailTab
  totalExecutions: number
  needsActionCount: number
  isBusy: boolean
  onTabChange: (tab: AutomationDetailTab) => void
  onRefresh: () => void
  onEdit: () => void
  onTogglePause: () => void
  onExecuteNow: () => void
  onRotateSecret: () => void
  t: TFunction
}) {
  return (
    <header className="shrink-0 space-y-2.5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-2.5">
          <Button
            variant="ghost"
            size="icon-sm"
            className="text-muted-foreground hover:text-foreground"
            asChild
          >
            <Link
              href="/app/automations"
              aria-label={t("返回自动化列表")}
              title={t("返回自动化列表")}
            >
              <ArrowLeftIcon />
            </Link>
          </Button>

          <h1 className="truncate text-lg font-semibold tracking-tight">
            {automation ? automation.name : t("自动化详情")}
          </h1>

          {automation ? (
            <AutomationStatusBadge status={automation.status} t={t} />
          ) : null}
        </div>

        {automation ? (
          <div className="flex flex-wrap items-center gap-2">
            <div
              role="tablist"
              aria-label={t("自动化详情")}
              className="inline-flex items-center rounded-lg bg-muted/60 p-0.5"
            >
              <button
                type="button"
                role="tab"
                aria-selected={activeTab === "executions"}
                onClick={() => onTabChange("executions")}
                className={cn(
                  "inline-flex items-center gap-1.5 rounded-md px-2.5 py-1 text-xs font-medium transition-colors",
                  activeTab === "executions"
                    ? "bg-background text-foreground shadow-xs"
                    : "text-muted-foreground hover:text-foreground"
                )}
              >
                <span>{t("执行记录")}</span>
                <span className="text-[11px] text-muted-foreground tabular-nums">
                  {totalExecutions}
                </span>
                {needsActionCount > 0 ? (
                  <span
                    className="size-1.5 rounded-full bg-amber-500"
                    aria-hidden="true"
                  />
                ) : null}
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={activeTab === "config"}
                onClick={() => onTabChange("config")}
                className={cn(
                  "inline-flex items-center gap-1.5 rounded-md px-2.5 py-1 text-xs font-medium transition-colors",
                  activeTab === "config"
                    ? "bg-background text-foreground shadow-xs"
                    : "text-muted-foreground hover:text-foreground"
                )}
              >
                <span>{t("配置与接入")}</span>
              </button>
            </div>

            <span
              aria-hidden="true"
              className="hidden h-4 w-px bg-border sm:block"
            />

            <Button
              type="button"
              variant="ghost"
              size="icon-sm"
              aria-label={t("刷新")}
              title={t("刷新")}
              disabled={isBusy}
              onClick={onRefresh}
            >
              <RefreshCwIcon />
            </Button>
            <Button
              type="button"
              variant="ghost"
              size="icon-sm"
              aria-label={t("编辑")}
              title={t("编辑")}
              disabled={isBusy}
              onClick={onEdit}
            >
              <PencilIcon />
            </Button>
            {automation.status !== "completed" ? (
              <Button
                type="button"
                variant="outline"
                size="sm"
                disabled={isBusy}
                onClick={onTogglePause}
              >
                {automation.status === "paused" ? <PlayIcon /> : <PauseIcon />}
                <span>
                  {t(automation.status === "paused" ? "恢复运行" : "暂停")}
                </span>
              </Button>
            ) : null}
            <Button
              type="button"
              size="sm"
              disabled={isBusy}
              onClick={onExecuteNow}
            >
              <PlayIcon />
              <span>{t("立即执行")}</span>
            </Button>
          </div>
        ) : null}
      </div>

      {automation?.trigger_type === "webhook" ? (
        <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 rounded-lg border bg-card/70 px-3 py-2 text-xs">
          <div className="flex min-w-0 flex-1 flex-wrap items-center gap-x-4 gap-y-1.5">
            {automation.webhook_url ? (
              <div className="flex min-w-0 items-center gap-1.5">
                <span className="shrink-0 font-medium text-muted-foreground">
                  {t("Webhook URL")}
                </span>
                <code className="max-w-xs truncate rounded bg-muted/60 px-1.5 py-0.5 font-mono text-[11px] sm:max-w-md">
                  {automationWebhookUrl(automation.webhook_url)}
                </code>
                <CopyButton
                  value={automationWebhookUrl(automation.webhook_url)}
                  t={t}
                />
              </div>
            ) : null}
            <div className="flex items-center gap-1.5">
              <span className="shrink-0 font-medium text-muted-foreground">
                {t("密钥提示")}
              </span>
              <code className="rounded bg-muted/60 px-1.5 py-0.5 font-mono text-[11px]">
                {automation.webhook_secret_hint ?? "—"}
              </code>
            </div>
          </div>
          <Button
            type="button"
            variant="ghost"
            size="xs"
            disabled={isBusy}
            onClick={onRotateSecret}
          >
            <KeyRoundIcon />
            <span>{t("轮换密钥")}</span>
          </Button>
        </div>
      ) : null}
    </header>
  )
}
