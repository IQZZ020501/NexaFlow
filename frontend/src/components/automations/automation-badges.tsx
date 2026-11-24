"use client"

import type { TFunction, TranslationKey } from "@/i18n"
import type {
  AutomationDispatchStatus,
  AutomationStatus,
  AutomationTriggerType,
} from "@/lib/api/automations"
import { automationWebhookUrl } from "@/lib/api/automations"
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

export function isAutomationExecutionActive(
  dispatchStatus: AutomationDispatchStatus,
  runStatus: string | null
) {
  if (dispatchStatus === "queued" || dispatchStatus === "pending_dispatch") {
    return true
  }
  return Boolean(runStatus && ACTIVE_RUN_STATUSES.has(runStatus))
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
} {
  if (!status) {
    return { key: "待排队", variant: "outline" }
  }
  if (status === "succeeded" || status === "succeeded_v2") {
    return { key: "已成功", variant: "default" }
  }
  if (status === "failed" || status === "failed_v2") {
    return { key: "已失败", variant: "destructive" }
  }
  if (status === "cancelled" || status === "cancelled_v2") {
    return { key: "已取消", variant: "outline" }
  }
  if (status === "awaiting_approval") {
    return { key: "待审批", variant: "secondary" }
  }
  if (
    status === "awaiting_input" ||
    status === "awaiting_input_v2" ||
    status === "waiting" ||
    status === "paused_v2"
  ) {
    return { key: "等待填写表单", variant: "secondary" }
  }
  if (status === "queued" || status === "queued_v2") {
    return { key: "待排队", variant: "outline" }
  }
  return { key: "运行中", variant: "secondary" }
}

export function AutomationStatusBadge({
  status,
  t,
}: {
  status: AutomationStatus
  t: TFunction
}) {
  const variant =
    status === "active"
      ? "default"
      : status === "paused"
        ? "secondary"
        : "outline"
  return <Badge variant={variant}>{t(automationStatusLabelKey(status))}</Badge>
}

export function DispatchStatusBadge({
  status,
  t,
}: {
  status: AutomationDispatchStatus
  t: TFunction
}) {
  const variant =
    status === "dispatched"
      ? "default"
      : status === "rejected"
        ? "destructive"
        : "secondary"
  return <Badge variant={variant}>{t(dispatchStatusLabelKey(status))}</Badge>
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
  return <Badge variant={meta.variant}>{t(meta.key)}</Badge>
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
