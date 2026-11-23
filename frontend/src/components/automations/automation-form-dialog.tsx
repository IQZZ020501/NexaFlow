"use client"

import * as React from "react"
import { LoaderCircleIcon } from "lucide-react"

import { AgentApprovalModeMenu } from "@/components/agents/agent-approval-mode-menu"
import { DateTimeField } from "@/components/app/date-time-field"
import { FilterDropdown } from "@/components/app/filter-dropdown"
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
  Field,
  FieldDescription,
  FieldGroup,
  FieldLabel,
} from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import { useLanguage } from "@/contexts/language-provider"
import { useSession } from "@/contexts/session-context"
import { languageLocales, type TranslationKey } from "@/i18n"
import { listAllAgents, type Agent } from "@/lib/api/agents"
import {
  createAutomation,
  listAgentPublicationVersions,
  updateAutomation,
  type AgentPublicationVersionItem,
  type Automation,
  type AutomationApprovalMode,
  type AutomationCreateResponse,
  type AutomationInputMode,
  type AutomationNotificationPreferences,
  type AutomationTriggerConfig,
  type AutomationTriggerType,
} from "@/lib/api/automations"
import { listWorkflowVersions, type WorkflowVersion } from "@/lib/api/workflows"
import {
  appDateTimeInputToIso,
  formatDateTime,
  toAppDateTimeInput,
} from "@/lib/display"
import { getErrorMessage } from "@/lib/errors"

type VersionOption = {
  id: string
  versionNumber: number
  createdAt: string
}

const WEEKDAY_KEYS: Array<{ value: number; labelKey: TranslationKey }> = [
  { value: 1, labelKey: "周一" },
  { value: 2, labelKey: "周二" },
  { value: 3, labelKey: "周三" },
  { value: 4, labelKey: "周四" },
  { value: 5, labelKey: "周五" },
  { value: 6, labelKey: "周六" },
  { value: 7, labelKey: "周日" },
]

const NOTIFICATION_FIELDS: Array<{
  key: keyof AutomationNotificationPreferences
  labelKey: TranslationKey
}> = [
  { key: "on_succeeded", labelKey: "成功时通知" },
  { key: "on_failed", labelKey: "失败时通知" },
  { key: "on_cancelled", labelKey: "取消时通知" },
  { key: "on_awaiting_approval", labelKey: "待审批时通知" },
  { key: "on_awaiting_input", labelKey: "待填表单时通知" },
]

function defaultNotifications(): AutomationNotificationPreferences {
  return {
    on_succeeded: true,
    on_failed: true,
    on_cancelled: true,
    on_awaiting_approval: true,
    on_awaiting_input: true,
  }
}

function defaultOnceDateTimeInput() {
  return toAppDateTimeInput(new Date(Date.now() + 30 * 60 * 1000).toISOString())
}

function formatHourMinute(hour?: number, minute?: number) {
  const safeHour = String(Math.min(23, Math.max(0, hour ?? 9))).padStart(2, "0")
  const safeMinute = String(Math.min(59, Math.max(0, minute ?? 0))).padStart(
    2,
    "0"
  )
  return `${safeHour}:${safeMinute}`
}

function parseHourMinute(value: string) {
  const [hRaw, mRaw] = value.split(":")
  const hour = Number(hRaw)
  const minute = Number(mRaw)
  if (
    !Number.isInteger(hour) ||
    !Number.isInteger(minute) ||
    hour < 0 ||
    hour > 23 ||
    minute < 0 ||
    minute > 59
  ) {
    return null
  }
  return { hour, minute }
}

function normalizeVersionOption(
  item: AgentPublicationVersionItem | WorkflowVersion
): VersionOption {
  return {
    id: item.id,
    versionNumber: item.version_number,
    createdAt: item.created_at,
  }
}

function appOptionLabel(app: Agent) {
  const kind = app.app_type === "workflow" ? "Workflow" : "Agent"
  return `${app.name} (${kind})`
}

export function AutomationFormDialog({
  open,
  onOpenChange,
  automation,
  initialAppId,
  onSaved,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  automation?: Automation | null
  initialAppId?: string | null
  onSaved: (saved: AutomationCreateResponse | Automation) => void
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      {open ? (
        <AutomationFormDialogBody
          key={`${automation?.id ?? "new"}:${initialAppId ?? ""}`}
          onOpenChange={onOpenChange}
          automation={automation}
          initialAppId={initialAppId}
          onSaved={onSaved}
        />
      ) : null}
    </Dialog>
  )
}

function AutomationFormDialogBody({
  onOpenChange,
  automation,
  initialAppId,
  onSaved,
}: {
  onOpenChange: (open: boolean) => void
  automation?: Automation | null
  initialAppId?: string | null
  onSaved: (saved: AutomationCreateResponse | Automation) => void
}) {
  const { token, selectedWorkspaceId, notify } = useSession()
  const { language, t } = useLanguage()
  const isEditing = Boolean(automation)

  const [apps, setApps] = React.useState<Agent[]>([])
  const [versions, setVersions] = React.useState<VersionOption[]>([])
  const [isLoadingApps, setIsLoadingApps] = React.useState(false)
  const [isLoadingVersions, setIsLoadingVersions] = React.useState(false)
  const [isSubmitting, setIsSubmitting] = React.useState(false)
  const [formError, setFormError] = React.useState<string | null>(null)

  const [name, setName] = React.useState(automation?.name ?? "")
  const [description, setDescription] = React.useState(
    automation?.description ?? ""
  )
  const [targetAppId, setTargetAppId] = React.useState(
    automation?.target_app_id ?? initialAppId ?? ""
  )
  const [selectedVersionId, setSelectedVersionId] = React.useState(
    automation
      ? automation.target_app_type === "workflow"
        ? (automation.workflow_version_id ?? "")
        : (automation.publication_version_id ?? "")
      : ""
  )
  const [approvalMode, setApprovalMode] =
    React.useState<AutomationApprovalMode>(
      automation?.approval_mode ?? "ask_risky"
    )
  const [triggerType, setTriggerType] = React.useState<AutomationTriggerType>(
    automation?.trigger_type ?? "daily"
  )
  const [onceRunAt, setOnceRunAt] = React.useState(() =>
    automation?.trigger_config.run_at
      ? toAppDateTimeInput(automation.trigger_config.run_at)
      : defaultOnceDateTimeInput()
  )
  const [dailyTime, setDailyTime] = React.useState(() =>
    automation
      ? formatHourMinute(
          automation.trigger_config.hour,
          automation.trigger_config.minute
        )
      : "09:00"
  )
  const [weekdays, setWeekdays] = React.useState<number[]>(() =>
    automation?.trigger_config.weekdays?.length
      ? automation.trigger_config.weekdays
      : [1, 3, 5]
  )
  const [maxPending, setMaxPending] = React.useState(
    String(automation?.trigger_config.max_pending ?? 20)
  )
  const [inputMode, setInputMode] = React.useState<AutomationInputMode>(
    automation?.input_config.mode ?? "text"
  )
  const [inputText, setInputText] = React.useState(
    automation?.input_config.text ?? ""
  )
  const [jsonText, setJsonText] = React.useState(() =>
    automation
      ? JSON.stringify(automation.input_config.json_payload ?? {}, null, 2)
      : "{}"
  )
  const [webhookInputPath, setWebhookInputPath] = React.useState(
    automation?.input_config.webhook_input_path ?? ""
  )
  const [webhookPromptTemplate, setWebhookPromptTemplate] = React.useState(
    automation?.input_config.webhook_prompt_template ?? ""
  )
  const [notifications, setNotifications] =
    React.useState<AutomationNotificationPreferences>(() =>
      automation
        ? { ...automation.notification_config }
        : defaultNotifications()
    )

  const selectedApp = React.useMemo(
    () => apps.find((item) => item.id === targetAppId) ?? null,
    [apps, targetAppId]
  )

  const effectiveAppType =
    automation?.target_app_type ?? selectedApp?.app_type ?? "agent"
  const effectiveAppId = automation?.target_app_id ?? targetAppId

  React.useEffect(() => {
    if (!token || !selectedWorkspaceId || automation) return
    let active = true
    const timer = window.setTimeout(() => {
      setIsLoadingApps(true)
      void listAllAgents(token, selectedWorkspaceId)
        .then((items) => {
          if (!active) return
          const publishedApps = items.filter(
            (item) => item.published && item.status === "active"
          )
          setApps(publishedApps)
          setTargetAppId((current) => {
            if (current && publishedApps.some((item) => item.id === current)) {
              return current
            }
            if (
              initialAppId &&
              publishedApps.some((item) => item.id === initialAppId)
            ) {
              return initialAppId
            }
            return publishedApps[0]?.id ?? ""
          })
        })
        .catch((error) => {
          if (!active) return
          setFormError(getErrorMessage(error, t))
        })
        .finally(() => {
          if (active) setIsLoadingApps(false)
        })
    }, 0)
    return () => {
      active = false
      window.clearTimeout(timer)
    }
  }, [automation, initialAppId, selectedWorkspaceId, t, token])

  React.useEffect(() => {
    if (!token || !selectedWorkspaceId || !effectiveAppId) {
      return
    }
    let active = true
    const timer = window.setTimeout(() => {
      setIsLoadingVersions(true)
      const loader =
        effectiveAppType === "workflow"
          ? listWorkflowVersions(
              token,
              selectedWorkspaceId,
              effectiveAppId
            ).then((res) => res.items.map(normalizeVersionOption))
          : listAgentPublicationVersions(
              token,
              selectedWorkspaceId,
              effectiveAppId
            ).then((res) => res.items.map(normalizeVersionOption))

      void loader
        .then((items) => {
          if (!active) return
          setVersions(items)
          setSelectedVersionId((current) => {
            if (current && items.some((item) => item.id === current)) {
              return current
            }
            const preferred = selectedApp?.current_published_version_id
            if (preferred && items.some((item) => item.id === preferred)) {
              return preferred
            }
            return items[0]?.id ?? ""
          })
        })
        .catch((error) => {
          if (!active) return
          setVersions([])
          setFormError(getErrorMessage(error, t))
        })
        .finally(() => {
          if (active) setIsLoadingVersions(false)
        })
    }, 0)
    return () => {
      active = false
      window.clearTimeout(timer)
    }
  }, [
    effectiveAppId,
    effectiveAppType,
    selectedApp?.current_published_version_id,
    selectedWorkspaceId,
    t,
    token,
  ])

  function toggleWeekday(day: number) {
    setWeekdays((current) =>
      current.includes(day)
        ? current.filter((item) => item !== day)
        : [...current, day].sort((a, b) => a - b)
    )
  }

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!token || !selectedWorkspaceId || isSubmitting) return

    const trimmedName = name.trim()
    if (!trimmedName) {
      setFormError(t("自动化名称不能为空"))
      return
    }
    if (!effectiveAppId || !selectedVersionId) {
      setFormError(t("请选择目标应用和发布版本"))
      return
    }

    let triggerConfig: AutomationTriggerConfig
    if (triggerType === "once") {
      const isoRunAt = appDateTimeInputToIso(onceRunAt)
      if (!isoRunAt) {
        setFormError(t("请设置正确的执行时间"))
        return
      }
      triggerConfig = { run_at: isoRunAt, timezone: "Asia/Shanghai" }
    } else if (triggerType === "daily") {
      const parsed = parseHourMinute(dailyTime)
      if (!parsed) {
        setFormError(t("请设置正确的执行时间"))
        return
      }
      triggerConfig = { ...parsed, timezone: "Asia/Shanghai" }
    } else if (triggerType === "weekly") {
      const parsed = parseHourMinute(dailyTime)
      if (!parsed) {
        setFormError(t("请设置正确的执行时间"))
        return
      }
      if (!weekdays.length) {
        setFormError(t("请至少选择一个星期"))
        return
      }
      triggerConfig = { ...parsed, weekdays, timezone: "Asia/Shanghai" }
    } else {
      const parsedPending = Number(maxPending)
      triggerConfig = {
        max_pending:
          Number.isInteger(parsedPending) && parsedPending >= 1
            ? Math.min(100, parsedPending)
            : 10,
      }
    }

    let jsonPayload: Record<string, unknown> = {}
    if (inputMode === "json") {
      try {
        const parsed = JSON.parse(jsonText.trim() || "{}")
        if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
          setFormError(t("结构化JSON格式无效"))
          return
        }
        jsonPayload = parsed as Record<string, unknown>
      } catch {
        setFormError(t("结构化JSON格式无效"))
        return
      }
    }

    const versionFields =
      effectiveAppType === "workflow"
        ? {
            workflow_version_id: selectedVersionId,
            publication_version_id: null,
          }
        : {
            publication_version_id: selectedVersionId,
            workflow_version_id: null,
          }

    const inputConfig = {
      mode: inputMode,
      text: inputMode === "text" ? inputText : "",
      json_payload: inputMode === "json" ? jsonPayload : {},
      webhook_input_path:
        triggerType === "webhook" && webhookInputPath.trim()
          ? webhookInputPath.trim()
          : null,
      webhook_prompt_template:
        triggerType === "webhook" && webhookPromptTemplate.trim()
          ? webhookPromptTemplate.trim()
          : null,
    }

    setFormError(null)
    setIsSubmitting(true)
    try {
      const result = automation
        ? await updateAutomation(token, selectedWorkspaceId, automation.id, {
            name: trimmedName,
            description: description.trim(),
            ...versionFields,
            approval_mode: approvalMode,
            trigger_type: triggerType,
            trigger_config: triggerConfig,
            input_config: inputConfig,
            notification_config: notifications,
          })
        : await createAutomation(token, selectedWorkspaceId, {
            name: trimmedName,
            description: description.trim(),
            target_app_id: effectiveAppId,
            ...versionFields,
            approval_mode: approvalMode,
            trigger_type: triggerType,
            trigger_config: triggerConfig,
            input_config: inputConfig,
            notification_config: notifications,
          })
      notify("success", t(automation ? "自动化已更新" : "自动化已创建"))
      onOpenChange(false)
      onSaved(result)
    } catch (error) {
      setFormError(getErrorMessage(error, t))
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <DialogContent className="sm:max-w-2xl">
      <DialogHeader>
        <DialogTitle>{t(isEditing ? "编辑自动化" : "创建自动化")}</DialogTitle>
        <DialogDescription>
          {t("管理定时触发与 Webhook 事件驱动的后台运行任务。")}
        </DialogDescription>
      </DialogHeader>

      <form
        className="grid gap-5"
        onSubmit={(event) => void handleSubmit(event)}
      >
        <FieldGroup>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field>
              <FieldLabel htmlFor="automation-name">{t("名称")}</FieldLabel>
              <Input
                id="automation-name"
                value={name}
                onChange={(event) => setName(event.target.value)}
                maxLength={120}
                required
              />
            </Field>
            <Field>
              <FieldLabel>{t("请求批准")}</FieldLabel>
              <AgentApprovalModeMenu
                value={approvalMode}
                onChange={setApprovalMode}
                t={t}
              />
            </Field>
          </div>

          <Field>
            <FieldLabel htmlFor="automation-description">
              {t("描述")}
            </FieldLabel>
            <Input
              id="automation-description"
              value={description}
              onChange={(event) => setDescription(event.target.value)}
              maxLength={500}
            />
          </Field>

          <div className="grid gap-4 sm:grid-cols-2">
            <Field>
              <FieldLabel>{t("目标应用")}</FieldLabel>
              {isEditing && automation ? (
                <Input
                  readOnly
                  value={`${automation.target_app_name} (${automation.target_app_type === "workflow" ? "Workflow" : "Agent"})`}
                />
              ) : (
                <FilterDropdown
                  ariaLabel={t("选择已发布应用")}
                  value={targetAppId}
                  disabled={isLoadingApps || !apps.length}
                  options={
                    apps.length
                      ? apps.map((app) => ({
                          value: app.id,
                          label: appOptionLabel(app),
                        }))
                      : [{ value: "", label: t("选择已发布应用") }]
                  }
                  onChange={(nextAppId) => {
                    setTargetAppId(nextAppId)
                    setSelectedVersionId("")
                  }}
                />
              )}
              <FieldDescription>
                {t("仅可选择已激活且已发布的 Agent 或工作流。")}
              </FieldDescription>
            </Field>

            <Field>
              <FieldLabel>{t("发布版本")}</FieldLabel>
              <FilterDropdown
                ariaLabel={t("发布版本")}
                value={selectedVersionId}
                disabled={isLoadingVersions || !versions.length}
                options={
                  versions.length
                    ? versions.map((item) => ({
                        value: item.id,
                        label: `v${item.versionNumber} · ${formatDateTime(
                          item.createdAt,
                          languageLocales[language]
                        )}`,
                      }))
                    : [{ value: "", label: t("发布版本") }]
                }
                onChange={setSelectedVersionId}
              />
            </Field>
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <Field>
              <FieldLabel>{t("触发方式")}</FieldLabel>
              <FilterDropdown
                ariaLabel={t("触发方式")}
                value={triggerType}
                options={[
                  { value: "once", label: t("单次定时") },
                  { value: "daily", label: t("每天定时") },
                  { value: "weekly", label: t("每周定时") },
                  { value: "webhook", label: t("Webhook事件") },
                ]}
                onChange={(value) =>
                  setTriggerType(value as AutomationTriggerType)
                }
              />
            </Field>

            {triggerType === "once" ? (
              <DateTimeField
                id="automation-once-at"
                label={t("执行时间")}
                value={onceRunAt}
                onChange={setOnceRunAt}
                clearable={false}
              />
            ) : triggerType === "webhook" ? (
              <Field>
                <FieldLabel htmlFor="automation-max-pending">
                  {t("最大排队数")}
                </FieldLabel>
                <Input
                  id="automation-max-pending"
                  type="number"
                  min={1}
                  max={100}
                  value={maxPending}
                  onChange={(event) => setMaxPending(event.target.value)}
                />
              </Field>
            ) : (
              <Field>
                <FieldLabel htmlFor="automation-daily-time">
                  {t("触发时刻")}
                </FieldLabel>
                <Input
                  id="automation-daily-time"
                  type="text"
                  inputMode="numeric"
                  placeholder="HH:mm"
                  maxLength={5}
                  value={dailyTime}
                  onChange={(event) => setDailyTime(event.target.value)}
                />
              </Field>
            )}
          </div>

          {triggerType === "weekly" ? (
            <Field>
              <FieldLabel>{t("执行星期")}</FieldLabel>
              <div className="flex flex-wrap gap-1.5">
                {WEEKDAY_KEYS.map((day) => {
                  const selected = weekdays.includes(day.value)
                  return (
                    <Button
                      key={day.value}
                      type="button"
                      size="xs"
                      variant={selected ? "default" : "outline"}
                      aria-pressed={selected}
                      onClick={() => toggleWeekday(day.value)}
                    >
                      {t(day.labelKey)}
                    </Button>
                  )
                })}
              </div>
            </Field>
          ) : null}

          {triggerType !== "webhook" ? (
            <p className="text-xs text-muted-foreground">
              {t("所有定时时间均按北京时间 (Asia/Shanghai) 计算。")}
            </p>
          ) : null}

          <div className="grid gap-3">
            <Field>
              <FieldLabel>{t("输入模式")}</FieldLabel>
              <FilterDropdown
                ariaLabel={t("输入模式")}
                value={inputMode}
                options={[
                  { value: "text", label: t("文本输入") },
                  { value: "json", label: t("结构化JSON") },
                ]}
                onChange={(value) => setInputMode(value as AutomationInputMode)}
              />
            </Field>

            {inputMode === "text" ? (
              <Field>
                <FieldLabel htmlFor="automation-input-text">
                  {t("任务提示词")}
                </FieldLabel>
                <textarea
                  id="automation-input-text"
                  rows={3}
                  value={inputText}
                  onChange={(event) => setInputText(event.target.value)}
                  className="resize-y rounded-md border bg-background px-3 py-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
                />
              </Field>
            ) : (
              <Field>
                <FieldLabel htmlFor="automation-json-payload">
                  {t("JSON载荷")}
                </FieldLabel>
                <textarea
                  id="automation-json-payload"
                  rows={4}
                  value={jsonText}
                  onChange={(event) => setJsonText(event.target.value)}
                  className="resize-y rounded-md border bg-background px-3 py-2 font-mono text-xs outline-none focus-visible:ring-2 focus-visible:ring-ring"
                />
              </Field>
            )}

            {triggerType === "webhook" ? (
              <div className="grid gap-3 rounded-lg border bg-muted/20 p-3">
                <Field>
                  <FieldLabel htmlFor="automation-webhook-path">
                    {t("Webhook 提取路径（可选）")}
                  </FieldLabel>
                  <Input
                    id="automation-webhook-path"
                    placeholder="data.payload"
                    value={webhookInputPath}
                    onChange={(event) =>
                      setWebhookInputPath(event.target.value)
                    }
                  />
                </Field>
                <Field>
                  <FieldLabel htmlFor="automation-webhook-template">
                    {t("Webhook 提示词模板（可选）")}
                  </FieldLabel>
                  <textarea
                    id="automation-webhook-template"
                    rows={2}
                    value={webhookPromptTemplate}
                    onChange={(event) =>
                      setWebhookPromptTemplate(event.target.value)
                    }
                    className="resize-y rounded-md border bg-background px-3 py-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  />
                </Field>
                <p className="text-xs text-muted-foreground">
                  {t(
                    "外部 Webhook 数据仅会注入任务输入，不会修改目标应用、模型或权限配置。"
                  )}
                </p>
              </div>
            ) : null}
          </div>

          <Field>
            <FieldLabel>{t("通知偏好")}</FieldLabel>
            <div className="grid gap-2 sm:grid-cols-3">
              {NOTIFICATION_FIELDS.map((item) => (
                <label
                  key={item.key}
                  className="flex cursor-pointer items-center gap-2 rounded-md border px-2.5 py-2 text-xs"
                >
                  <input
                    type="checkbox"
                    checked={notifications[item.key]}
                    onChange={(event) =>
                      setNotifications((current) => ({
                        ...current,
                        [item.key]: event.target.checked,
                      }))
                    }
                  />
                  <span>{t(item.labelKey)}</span>
                </label>
              ))}
            </div>
          </Field>
        </FieldGroup>

        {formError ? (
          <p role="alert" className="text-sm text-destructive">
            {formError}
          </p>
        ) : null}

        <DialogFooter>
          <Button
            type="button"
            variant="outline"
            disabled={isSubmitting}
            onClick={() => onOpenChange(false)}
          >
            {t("取消")}
          </Button>
          <Button type="submit" disabled={isSubmitting}>
            {isSubmitting ? (
              <LoaderCircleIcon className="animate-spin motion-reduce:animate-none" />
            ) : null}
            {t(isEditing ? "保存" : "创建")}
          </Button>
        </DialogFooter>
      </form>
    </DialogContent>
  )
}
