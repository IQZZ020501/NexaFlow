"use client"

import type { TFunction, TranslationKey } from "@/i18n"
import type { AgentToolCall } from "@/lib/api/agents"
import type {
  Automation,
  AutomationApprovalMode,
  AutomationDispatchStatus,
  AutomationStatus,
  AutomationTriggerType,
} from "@/lib/api/automations"
import { automationWebhookUrl } from "@/lib/api/automations"
import { formatDateTime } from "@/lib/display"
import { cn } from "@/lib/utils"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { CopyButton } from "@/components/ui/copy-button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Field, FieldLabel } from "@/components/ui/field"

export type WebhookSecretDisclosure = {
  name: string
  webhookUrl: string | null
  secret: string
}

type SemanticTone = "success" | "info" | "warning" | "danger" | "neutral"

const TONE_BADGE_CLASS: Record<SemanticTone, string> = {
  success:
    "border-emerald-500/25 bg-emerald-500/10 text-emerald-700 dark:text-emerald-400",
  info: "border-sky-500/25 bg-sky-500/10 text-sky-700 dark:text-sky-400",
  warning:
    "border-amber-500/25 bg-amber-500/10 text-amber-700 dark:text-amber-400",
  danger: "border-destructive/25 bg-destructive/10 text-destructive",
  neutral: "border-border bg-muted/60 text-muted-foreground",
}

const TONE_DOT_CLASS: Record<SemanticTone, string> = {
  success: "bg-emerald-500",
  info: "bg-sky-500",
  warning: "bg-amber-500",
  danger: "bg-destructive",
  neutral: "bg-muted-foreground/70",
}

const ACTIVE_RUN_STATUSES = new Set([
  "queued",
  "running",
  "waiting",
  "awaiting_approval",
  "awaiting_input",
  "queued_v2",
  "running_v2",
  "awaiting_input_v2",
  "paused_v2",
])

const NEEDS_ACTION_STATUSES = new Set([
  "awaiting_approval",
  "awaiting_input",
  "awaiting_input_v2",
  "waiting",
  "paused_v2",
])

const WEEKDAY_LABEL_KEYS: Record<number, TranslationKey> = {
  1: "周一",
  2: "周二",
  3: "周三",
  4: "周四",
  5: "周五",
  6: "周六",
  7: "周日",
}

export function isAutomationExecutionActive(
  dispatchStatus: AutomationDispatchStatus,
  runStatus: string | null
) {
  if (dispatchStatus === "queued" || dispatchStatus === "pending_dispatch") {
    return true
  }
  return Boolean(runStatus && ACTIVE_RUN_STATUSES.has(runStatus))
}

export function isExecutionNeedsAction(
  dispatchStatus: AutomationDispatchStatus,
  runStatus: string | null
) {
  void dispatchStatus
  return Boolean(runStatus && NEEDS_ACTION_STATUSES.has(runStatus))
}

export function isExecutionFailed(
  dispatchStatus: AutomationDispatchStatus,
  runStatus: string | null
) {
  return (
    dispatchStatus === "rejected" ||
    runStatus === "failed" ||
    runStatus === "failed_v2"
  )
}

export function triggerTypeLabelKey(
  triggerType: AutomationTriggerType
): TranslationKey {
  if (triggerType === "once") return "单次定时"
  if (triggerType === "daily") return "每天定时"
  if (triggerType === "weekly") return "每周定时"
  return "Webhook事件"
}

export function triggerSourceLabelKey(
  triggerSource: "schedule" | "webhook" | "manual"
): TranslationKey {
  if (triggerSource === "schedule") return "定时触发"
  if (triggerSource === "webhook") return "Webhook事件"
  return "手动触发"
}

export function automationStatusLabelKey(
  status: AutomationStatus
): TranslationKey {
  if (status === "paused") return "已暂停"
  if (status === "completed") return "已完成"
  return "运行"
}

export function approvalModeLabelKey(
  mode: AutomationApprovalMode
): TranslationKey {
  if (mode === "always_ask") return "请求批准"
  if (mode === "full_access") return "完全访问"
  return "按策略自动执行"
}

export function dispatchStatusLabelKey(
  status: AutomationDispatchStatus
): TranslationKey {
  if (status === "queued") return "待排队"
  if (status === "pending_dispatch") return "待派发"
  if (status === "dispatched") return "已派发"
  if (status === "skipped") return "已跳过"
  return "已拒绝"
}

export function runStatusMeta(status: string | null): {
  key: TranslationKey
  variant: "default" | "secondary" | "outline" | "destructive"
  tone: SemanticTone
  pulse?: boolean
} {
  if (!status) {
    return { key: "待排队", variant: "outline", tone: "info", pulse: true }
  }
  if (status === "succeeded" || status === "succeeded_v2") {
    return { key: "已成功", variant: "default", tone: "success" }
  }
  if (status === "failed" || status === "failed_v2") {
    return { key: "已失败", variant: "destructive", tone: "danger" }
  }
  if (status === "cancelled" || status === "cancelled_v2") {
    return { key: "已取消", variant: "outline", tone: "neutral" }
  }
  if (status === "awaiting_approval") {
    return { key: "待审批", variant: "secondary", tone: "warning" }
  }
  if (
    status === "awaiting_input" ||
    status === "awaiting_input_v2" ||
    status === "waiting" ||
    status === "paused_v2"
  ) {
    return { key: "等待填写表单", variant: "secondary", tone: "warning" }
  }
  if (status === "queued" || status === "queued_v2") {
    return { key: "待排队", variant: "outline", tone: "info", pulse: true }
  }
  return { key: "运行中", variant: "secondary", tone: "info", pulse: true }
}

function resolveExecutionTone(
  dispatchStatus: AutomationDispatchStatus,
  runStatus: string | null
): { tone: SemanticTone; pulse?: boolean } {
  if (!runStatus) {
    if (dispatchStatus === "rejected") return { tone: "danger" }
    if (dispatchStatus === "skipped") return { tone: "neutral" }
    if (dispatchStatus === "queued" || dispatchStatus === "pending_dispatch") {
      return { tone: "info", pulse: true }
    }
  }
  const meta = runStatusMeta(runStatus)
  return { tone: meta.tone, pulse: meta.pulse }
}

export function executionStatusDotClass(
  dispatchStatus: AutomationDispatchStatus,
  runStatus: string | null
) {
  const { tone, pulse } = resolveExecutionTone(dispatchStatus, runStatus)
  return cn(
    "size-2 shrink-0 rounded-full",
    TONE_DOT_CLASS[tone],
    pulse && "animate-pulse motion-reduce:animate-none"
  )
}

export function formatExecutionDuration(
  startedAt: string | null | undefined,
  finishedAt: string | null | undefined,
  fallbackStart?: string | null,
  fallbackEnd?: string | null
) {
  const startRaw = startedAt ?? fallbackStart
  const endRaw = finishedAt ?? fallbackEnd
  if (!startRaw || !endRaw) return null
  const startMs = Date.parse(startRaw)
  const endMs = Date.parse(endRaw)
  if (!Number.isFinite(startMs) || !Number.isFinite(endMs) || endMs < startMs) {
    return null
  }
  const diffMs = endMs - startMs
  if (diffMs < 1000) return `${diffMs}ms`
  const totalSeconds = diffMs / 1000
  if (totalSeconds < 60) return `${totalSeconds.toFixed(1)}s`
  const wholeSeconds = Math.floor(totalSeconds)
  const minutes = Math.floor(wholeSeconds / 60)
  const seconds = wholeSeconds % 60
  if (minutes < 60) return `${minutes}m ${String(seconds).padStart(2, "0")}s`
  const hours = Math.floor(minutes / 60)
  const remainingMinutes = minutes % 60
  return `${hours}h ${String(remainingMinutes).padStart(2, "0")}m`
}

export function formatScheduleSummary(
  automation: Pick<Automation, "trigger_type" | "trigger_config">,
  locale: string,
  t: TFunction
) {
  const cfg = automation.trigger_config ?? {}
  if (automation.trigger_type === "webhook") {
    return t("Webhook事件")
  }
  const hhmm =
    cfg.hour !== undefined && cfg.minute !== undefined
      ? `${String(cfg.hour).padStart(2, "0")}:${String(cfg.minute).padStart(2, "0")}`
      : null
  if (automation.trigger_type === "daily") {
    return hhmm ? `${t("每天定时")} · ${hhmm}` : t("每天定时")
  }
  if (automation.trigger_type === "weekly") {
    const days = (cfg.weekdays ?? [])
      .map((day) => WEEKDAY_LABEL_KEYS[day])
      .filter((key): key is TranslationKey => Boolean(key))
      .map((key) => t(key))
      .join(" / ")
    const parts = [t("每周定时"), days, hhmm].filter(Boolean)
    return parts.join(" · ")
  }
  if (cfg.run_at) {
    return `${t("单次定时")} · ${formatDateTime(cfg.run_at, locale)}`
  }
  return t("单次定时")
}

export function toolCallStatusMeta(
  status: AgentToolCall["status"],
  t: TFunction
): { label: string; className: string } {
  switch (status) {
    case "succeeded":
      return { label: t("已成功"), className: TONE_BADGE_CLASS.success }
    case "failed":
      return { label: t("已失败"), className: TONE_BADGE_CLASS.danger }
    case "rejected":
      return { label: t("已拒绝"), className: TONE_BADGE_CLASS.neutral }
    case "awaiting_approval":
      return { label: t("待审批"), className: TONE_BADGE_CLASS.warning }
    case "uncertain":
      return {
        label: t("工具执行结果不确定"),
        className: TONE_BADGE_CLASS.warning,
      }
    case "approved":
      return { label: t("工具调用已批准"), className: TONE_BADGE_CLASS.info }
    case "running":
      return { label: t("运行中"), className: TONE_BADGE_CLASS.info }
    default:
      return { label: t("待排队"), className: TONE_BADGE_CLASS.neutral }
  }
}

export function AutomationStatusBadge({
  status,
  t,
}: {
  status: AutomationStatus
  t: TFunction
}) {
  const tone: SemanticTone =
    status === "active" ? "success" : status === "paused" ? "warning" : "neutral"
  return (
    <Badge
      variant="outline"
      className={cn("gap-1.5 rounded-full font-medium", TONE_BADGE_CLASS[tone])}
    >
      <span className={cn("size-1.5 rounded-full", TONE_DOT_CLASS[tone])} />
      <span>{t(automationStatusLabelKey(status))}</span>
    </Badge>
  )
}

export function DispatchStatusBadge({
  status,
  t,
}: {
  status: AutomationDispatchStatus
  t: TFunction
}) {
  const tone: SemanticTone =
    status === "dispatched"
      ? "success"
      : status === "rejected"
        ? "danger"
        : status === "skipped"
          ? "neutral"
          : "info"
  const pulse = status === "queued" || status === "pending_dispatch"
  return (
    <Badge
      variant="outline"
      className={cn("gap-1.5 rounded-full font-medium", TONE_BADGE_CLASS[tone])}
    >
      <span
        className={cn(
          "size-1.5 rounded-full",
          TONE_DOT_CLASS[tone],
          pulse && "animate-pulse motion-reduce:animate-none"
        )}
      />
      <span>{t(dispatchStatusLabelKey(status))}</span>
    </Badge>
  )
}

export function ExecutionRunStatusBadge({
  runStatus,
  dispatchStatus,
  t,
}: {
  runStatus: string | null
  dispatchStatus: AutomationDispatchStatus
  t: TFunction
}) {
  if (
    !runStatus &&
    (dispatchStatus === "skipped" || dispatchStatus === "rejected")
  ) {
    return <DispatchStatusBadge status={dispatchStatus} t={t} />
  }
  const meta = runStatusMeta(runStatus)
  return (
    <Badge
      variant="outline"
      className={cn(
        "gap-1.5 rounded-full font-medium",
        TONE_BADGE_CLASS[meta.tone]
      )}
    >
      <span
        className={cn(
          "size-1.5 rounded-full",
          TONE_DOT_CLASS[meta.tone],
          meta.pulse && "animate-pulse motion-reduce:animate-none"
        )}
      />
      <span>{t(meta.key)}</span>
    </Badge>
  )
}

export function WebhookSecretDialog({
  disclosure,
  onClose,
  t,
}: {
  disclosure: WebhookSecretDisclosure | null
  onClose: () => void
  t: TFunction
}) {
  return (
    <Dialog
      open={Boolean(disclosure)}
      onOpenChange={(open) => {
        if (!open) onClose()
      }}
    >
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{t("Webhook 地址与签名密钥")}</DialogTitle>
          <DialogDescription>
            {t("Webhook 密钥仅展示一次，请妥善保存。")}
          </DialogDescription>
        </DialogHeader>
        <p className="text-xs text-muted-foreground">
          {t(
            "签名内容为 timestamp.event_id.原始请求正文，使用密钥计算 HMAC-SHA256，签名头加 sha256= 前缀。"
          )}
        </p>
        {disclosure ? (
          <div className="grid gap-4">
            <p className="text-sm font-medium">{disclosure.name}</p>
            {disclosure.webhookUrl ? (
              <Field>
                <FieldLabel>{t("Webhook URL")}</FieldLabel>
                <div className="flex items-center gap-2 rounded-md border bg-muted/30 px-3 py-2 font-mono text-xs break-all">
                  <span className="min-w-0 flex-1">
                    {automationWebhookUrl(disclosure.webhookUrl)}
                  </span>
                  <CopyButton
                    value={automationWebhookUrl(disclosure.webhookUrl)}
                    t={t}
                  />
                </div>
              </Field>
            ) : null}
            <Field>
              <FieldLabel>HMAC-SHA256 Secret</FieldLabel>
              <div className="flex items-center gap-2 rounded-md border bg-muted/30 px-3 py-2 font-mono text-xs break-all">
                <span className="min-w-0 flex-1">{disclosure.secret}</span>
                <CopyButton value={disclosure.secret} t={t} />
              </div>
            </Field>
            <p className="text-xs text-muted-foreground">
              {t(
                "请填写请求头 X-NexaFlow-Timestamp、X-NexaFlow-Event-Id 与 X-NexaFlow-Signature (HMAC-SHA256)。"
              )}
            </p>
          </div>
        ) : null}
        <DialogFooter>
          <Button type="button" onClick={onClose}>
            {t("关闭")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
