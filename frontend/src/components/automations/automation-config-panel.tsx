"use client"

import Link from "next/link"
import { ArrowUpRightIcon, KeyRoundIcon, PencilIcon } from "lucide-react"

import {
  approvalModeLabelKey,
  formatScheduleSummary,
  triggerTypeLabelKey,
} from "@/components/automations/automation-badges"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { CopyButton } from "@/components/ui/copy-button"
import type { TFunction, TranslationKey } from "@/i18n"
import {
  automationWebhookUrl,
  type Automation,
  type AutomationNotificationPreferences,
} from "@/lib/api/automations"
import { formatDateTime } from "@/lib/display"
import { cn } from "@/lib/utils"

const NOTIFICATION_ITEMS: Array<{
  key: keyof AutomationNotificationPreferences
  labelKey: TranslationKey
}> = [
  { key: "on_succeeded", labelKey: "成功时通知" },
  { key: "on_failed", labelKey: "失败时通知" },
  { key: "on_cancelled", labelKey: "取消时通知" },
  { key: "on_awaiting_approval", labelKey: "待审批时通知" },
  { key: "on_awaiting_input", labelKey: "待填表单时通知" },
]

function buildWebhookExample(url: string) {
  return `import hashlib, hmac, json, os, time, urllib.request

event_id = "event-123"
timestamp = str(int(time.time()))
body = json.dumps({"message": "Hello NexaFlow"}, ensure_ascii=False).encode("utf-8")
signed = f"{timestamp}.{event_id}.".encode("utf-8") + body
sig = hmac.new(os.environ["WEBHOOK_SECRET"].encode(), signed, hashlib.sha256).hexdigest()

req = urllib.request.Request(
    "${url}",
    data=body,
    method="POST",
    headers={
        "Content-Type": "application/json",
        "X-NexaFlow-Timestamp": timestamp,
        "X-NexaFlow-Event-Id": event_id,
        "X-NexaFlow-Signature": f"sha256={sig}",
    },
)
with urllib.request.urlopen(req, timeout=10) as resp:
    print(json.load(resp)["execution_id"])`
}

export function AutomationConfigPanel({
  automation,
  locale,
  isActionBusy,
  onEdit,
  onRotateSecret,
  t,
}: {
  automation: Automation
  locale: string
  isActionBusy: boolean
  onEdit: () => void
  onRotateSecret: () => void
  t: TFunction
}) {
  const appHref =
    automation.target_app_type === "workflow"
      ? `/workflow/${automation.target_app_id}`
      : `/app/apps/${automation.target_app_id}`

  const resolvedWebhookUrl = automationWebhookUrl(automation.webhook_url)
  const exampleSnippet = buildWebhookExample(
    resolvedWebhookUrl || "https://your-host/api/v1/hooks/automations/<hook_id>"
  )

  return (
    <div className="grid gap-5 lg:grid-cols-2">
      <Card>
        <CardHeader className="flex flex-row items-center justify-between gap-3 border-b pb-4">
          <div className="min-w-0 space-y-1">
            <CardTitle className="text-base">{t("运行策略")}</CardTitle>
            <CardDescription>
              {automation.description ||
                t(triggerTypeLabelKey(automation.trigger_type))}
            </CardDescription>
          </div>
          <Button
            type="button"
            variant="outline"
            size="xs"
            disabled={isActionBusy}
            onClick={onEdit}
          >
            <PencilIcon />
            <span>{t("编辑配置")}</span>
          </Button>
        </CardHeader>
        <CardContent className="pt-4">
          <dl className="divide-y divide-border/60 text-xs">
            <div className="flex items-center justify-between gap-4 py-2.5">
              <dt className="text-muted-foreground">{t("目标应用")}</dt>
              <dd className="font-medium">
                <Link
                  href={appHref}
                  className="inline-flex items-center gap-1 hover:underline"
                >
                  <span>
                    {automation.target_app_type === "workflow"
                      ? "Workflow"
                      : "Agent"}{" "}
                    · {automation.target_app_name} v
                    {automation.target_version_number}
                  </span>
                  <ArrowUpRightIcon className="size-3 text-muted-foreground" />
                </Link>
              </dd>
            </div>
            <div className="flex items-center justify-between gap-4 py-2.5">
              <dt className="text-muted-foreground">{t("触发方式")}</dt>
              <dd className="text-right font-medium">
                {formatScheduleSummary(automation, locale, t)}
                {automation.trigger_config.timezone ? (
                  <span className="ml-1.5 text-muted-foreground">
                    ({automation.trigger_config.timezone})
                  </span>
                ) : null}
              </dd>
            </div>
            <div className="flex items-center justify-between gap-4 py-2.5">
              <dt className="text-muted-foreground">{t("审批模式")}</dt>
              <dd>
                <Badge variant="outline">
                  {t(approvalModeLabelKey(automation.approval_mode))}
                </Badge>
              </dd>
            </div>
            <div className="flex items-center justify-between gap-4 py-2.5">
              <dt className="text-muted-foreground">{t("下次执行时间")}</dt>
              <dd className="font-medium tabular-nums">
                {automation.next_run_at
                  ? formatDateTime(automation.next_run_at, locale)
                  : "—"}
              </dd>
            </div>
            <div className="flex items-center justify-between gap-4 py-2.5">
              <dt className="text-muted-foreground">{t("最近触发")}</dt>
              <dd className="font-medium tabular-nums">
                {automation.last_triggered_at
                  ? formatDateTime(automation.last_triggered_at, locale)
                  : "—"}
              </dd>
            </div>
            <div className="flex items-center justify-between gap-4 py-2.5">
              <dt className="text-muted-foreground">{t("累计错过")}</dt>
              <dd className="font-medium tabular-nums">
                {automation.missed_run_count}
              </dd>
            </div>
            {automation.trigger_type === "webhook" ? (
              <div className="flex items-center justify-between gap-4 py-2.5">
                <dt className="text-muted-foreground">{t("排队上限")}</dt>
                <dd className="font-medium tabular-nums">
                  {automation.trigger_config.max_pending ?? 20}
                </dd>
              </div>
            ) : null}
          </dl>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="border-b pb-4">
          <CardTitle className="text-base">{t("基本配置")}</CardTitle>
          <CardDescription>
            {t(
              automation.input_config.mode === "json"
                ? "结构化JSON"
                : "文本输入"
            )}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-5 pt-4 text-xs">
          <div className="space-y-2">
            <div className="flex items-center justify-between gap-2">
              <span className="font-medium text-muted-foreground">
                {t("默认输入")}
              </span>
              <Badge variant="secondary">
                {t(
                  automation.input_config.mode === "json"
                    ? "结构化JSON"
                    : "文本输入"
                )}
              </Badge>
            </div>
            <pre className="max-h-40 overflow-auto rounded-lg border bg-muted/20 p-3 font-mono text-xs break-words whitespace-pre-wrap">
              {automation.input_config.mode === "json"
                ? JSON.stringify(
                    automation.input_config.json_payload ?? {},
                    null,
                    2
                  )
                : automation.input_config.text || "—"}
            </pre>
            {automation.input_config.webhook_input_path ? (
              <p className="text-muted-foreground">
                {t("Webhook 提取路径（可选）")}:{" "}
                <code className="rounded bg-muted px-1.5 py-0.5 font-mono text-foreground">
                  {automation.input_config.webhook_input_path}
                </code>
              </p>
            ) : null}
            {automation.input_config.webhook_prompt_template ? (
              <p className="text-muted-foreground">
                {t("Webhook 提示词模板（可选）")}:{" "}
                <code className="rounded bg-muted px-1.5 py-0.5 font-mono text-foreground">
                  {automation.input_config.webhook_prompt_template}
                </code>
              </p>
            ) : null}
          </div>

          <div className="space-y-2.5 border-t pt-4">
            <span className="font-medium text-muted-foreground">
              {t("通知偏好")}
            </span>
            <div className="grid gap-2 sm:grid-cols-2">
              {NOTIFICATION_ITEMS.map(({ key, labelKey }) => {
                const enabled = automation.notification_config[key]
                return (
                  <div
                    key={key}
                    className="flex items-center justify-between gap-2 rounded-lg border bg-muted/20 px-3 py-2"
                  >
                    <span>{t(labelKey)}</span>
                    <span
                      className={cn(
                        "rounded-full px-2 py-0.5 text-[11px] font-medium",
                        enabled
                          ? "bg-emerald-500/10 text-emerald-700 dark:text-emerald-400"
                          : "bg-muted text-muted-foreground"
                      )}
                    >
                      {t(enabled ? "已开启" : "未开启")}
                    </span>
                  </div>
                )
              })}
            </div>
          </div>
        </CardContent>
      </Card>

      {automation.trigger_type === "webhook" ? (
        <Card className="lg:col-span-2">
          <CardHeader className="flex flex-row flex-wrap items-center justify-between gap-3 border-b pb-4">
            <div className="space-y-1">
              <CardTitle className="text-base">
                {t("Webhook 地址与签名密钥")}
              </CardTitle>
              <CardDescription>
                {t(
                  "请填写请求头 X-NexaFlow-Timestamp、X-NexaFlow-Event-Id 与 X-NexaFlow-Signature (HMAC-SHA256)。"
                )}
              </CardDescription>
            </div>
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={isActionBusy}
              onClick={onRotateSecret}
            >
              <KeyRoundIcon />
              <span>{t("轮换密钥")}</span>
            </Button>
          </CardHeader>
          <CardContent className="space-y-4 pt-4 text-xs">
            <div className="grid gap-3 sm:grid-cols-2">
              {automation.webhook_url ? (
                <div className="space-y-1.5">
                  <p className="font-medium text-muted-foreground">
                    {t("Webhook URL")}
                  </p>
                  <div className="flex items-center gap-2 rounded-lg border bg-muted/20 px-3 py-2 font-mono break-all">
                    <span className="min-w-0 flex-1">
                      {resolvedWebhookUrl}
                    </span>
                    <CopyButton value={resolvedWebhookUrl} t={t} />
                  </div>
                </div>
              ) : null}
              <div className="space-y-1.5">
                <p className="font-medium text-muted-foreground">
                  {t("密钥提示")}
                </p>
                <div className="rounded-lg border bg-muted/20 px-3 py-2.5 font-mono">
                  {automation.webhook_secret_hint ?? "—"}
                </div>
              </div>
            </div>

            <div className="space-y-1.5">
              <div className="flex items-center justify-between gap-2">
                <span className="font-medium text-muted-foreground">
                  {t("调用示例")} (Python)
                </span>
                <CopyButton value={exampleSnippet} showLabel t={t} />
              </div>
              <pre className="overflow-x-auto rounded-lg border bg-muted/20 p-3.5 font-mono text-[11px] leading-relaxed">
                {exampleSnippet}
              </pre>
            </div>
          </CardContent>
        </Card>
      ) : null}
    </div>
  )
}
