"use client"

import * as React from "react"
import {
  LoaderCircleIcon,
  RefreshCwIcon,
  SendIcon,
  ShieldCheckIcon,
} from "lucide-react"
import { useRouter } from "next/navigation"

import { useLanguage } from "@/contexts/language-provider"
import { useSession } from "@/contexts/session-context"
import {
  getSmtpSettings,
  sendSmtpTest,
  updateSmtpSettings,
  type SmtpSecurity,
  type SmtpSettings,
} from "@/lib/api/system"
import { getErrorMessage } from "@/lib/errors"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Field, FieldDescription, FieldLabel } from "@/components/ui/field"
import { FilterDropdown } from "@/components/app/filter-dropdown"
import { Input } from "@/components/ui/input"
import { cn } from "@/lib/utils"

type SmtpForm = {
  host: string
  port: string
  username: string
  password: string
  security: SmtpSecurity
  fromEmail: string
  fromName: string
  timeoutSeconds: string
  siteUrl: string
  enabled: boolean
  clearPassword: boolean
}

const EMPTY_FORM: SmtpForm = {
  host: "",
  port: "587",
  username: "",
  password: "",
  security: "starttls",
  fromEmail: "",
  fromName: "",
  timeoutSeconds: "10",
  siteUrl: "",
  enabled: false,
  clearPassword: false,
}

function formFromSettings(settings: SmtpSettings): SmtpForm {
  return {
    host: settings.host,
    port: String(settings.port),
    username: settings.username,
    password: "",
    security: settings.security,
    fromEmail: settings.from_email,
    fromName: settings.from_name,
    timeoutSeconds: String(settings.timeout_seconds),
    siteUrl: settings.site_url,
    enabled: settings.enabled,
    clearPassword: false,
  }
}

/**
 * Provides the global SMTP configuration and delivery test controls.
 * Only global administrators may access this page; the API enforces the same boundary.
 */
export function SmtpSettingsPage() {
  const { t } = useLanguage()
  const session = useSession()
  const { token, notify } = session
  const router = useRouter()
  const isGlobalAdmin = Boolean(session.me?.user.is_global_admin)
  const [settings, setSettings] = React.useState<SmtpSettings | null>(null)
  const [form, setForm] = React.useState<SmtpForm>(EMPTY_FORM)
  const [recipient, setRecipient] = React.useState("")
  const [isLoading, setIsLoading] = React.useState(true)
  const [isSaving, setIsSaving] = React.useState(false)
  const [isTesting, setIsTesting] = React.useState(false)
  const [loadError, setLoadError] = React.useState<string | null>(null)
  const [formError, setFormError] = React.useState<string | null>(null)
  const [testError, setTestError] = React.useState<string | null>(null)

  React.useEffect(() => {
    if (session.me && !isGlobalAdmin) {
      router.replace("/system/teams")
    }
  }, [isGlobalAdmin, router, session.me])

  const load = React.useCallback(async () => {
    if (!token || !isGlobalAdmin) return
    setIsLoading(true)
    setLoadError(null)
    try {
      const next = await getSmtpSettings(token)
      setSettings(next)
      setForm(formFromSettings(next))
    } catch (error) {
      const message = getErrorMessage(error, t)
      setLoadError(message)
      notify("error", message)
    } finally {
      setIsLoading(false)
    }
  }, [isGlobalAdmin, notify, t, token])

  React.useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load()
  }, [load])

  function updateForm<K extends keyof SmtpForm>(key: K, value: SmtpForm[K]) {
    setForm((current) => ({ ...current, [key]: value }))
    setFormError(null)
  }

  async function save(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!token || !settings) return
    if (!event.currentTarget.reportValidity()) return

    const port = Number(form.port)
    const timeoutSeconds = Number(form.timeoutSeconds)
    if (!Number.isInteger(port) || port < 1 || port > 65535) {
      setFormError(t("端口必须是 1 到 65535 之间的整数"))
      return
    }
    if (
      !Number.isFinite(timeoutSeconds) ||
      timeoutSeconds <= 0 ||
      timeoutSeconds > 120
    ) {
      setFormError(t("超时时间必须大于 0 且不超过 120 秒"))
      return
    }

    setIsSaving(true)
    setFormError(null)
    try {
      const next = await updateSmtpSettings(token, {
        host: form.host,
        port,
        username: form.username,
        ...(form.password ? { password: form.password } : {}),
        ...(form.clearPassword ? { clear_password: true } : {}),
        security: form.security,
        from_email: form.fromEmail,
        from_name: form.fromName,
        enabled: form.enabled,
        timeout_seconds: timeoutSeconds,
        site_url: form.siteUrl,
      })
      setSettings(next)
      setForm(formFromSettings(next))
      notify("success", t("SMTP 配置已保存"))
    } catch (error) {
      const message = getErrorMessage(error, t)
      setFormError(message)
      notify("error", message)
    } finally {
      setIsSaving(false)
    }
  }

  async function sendTest(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (
      !token ||
      !settings?.configured ||
      !event.currentTarget.reportValidity()
    ) {
      return
    }

    setIsTesting(true)
    setTestError(null)
    try {
      await sendSmtpTest(token, recipient)
      notify("success", t("测试邮件已发送"))
    } catch (error) {
      const message = getErrorMessage(error, t)
      setTestError(message)
      notify("error", message)
    } finally {
      setIsTesting(false)
    }
  }

  if (!session.me || !session.token || !isGlobalAdmin) return null

  return (
    <div className="mx-auto grid w-full max-w-5xl gap-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">
            {t("SMTP 邮件")}
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            {t("配置系统邮件发送服务")}
          </p>
        </div>
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => void load()}
          disabled={isLoading || isSaving}
          aria-label={t("刷新 SMTP 配置")}
        >
          <RefreshCwIcon
            className={cn("size-4", isLoading && "animate-spin")}
          />
          {t("刷新")}
        </Button>
      </div>

      <Card aria-busy={isLoading}>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <ShieldCheckIcon className="size-4" />
            {t("SMTP 配置")}
          </CardTitle>
          <CardDescription>
            {t("SMTP 密码会加密保存，仅显示脱敏提示")}
          </CardDescription>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <div
              className="flex min-h-48 items-center justify-center"
              role="status"
              aria-label={t("正在加载 SMTP 配置")}
            >
              <LoaderCircleIcon className="size-6 animate-spin text-muted-foreground" />
            </div>
          ) : loadError ? (
            <div
              className="grid gap-3 rounded-lg border border-destructive/40 bg-destructive/5 p-4 text-sm"
              role="alert"
            >
              <p>{loadError}</p>
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="w-fit"
                onClick={() => void load()}
              >
                {t("重试")}
              </Button>
            </div>
          ) : (
            <>
              <div
                className={cn(
                  "mb-5 rounded-lg border p-3",
                  settings?.identity_configured
                    ? "border-emerald-500/40 bg-emerald-500/5"
                    : "border-amber-500/40 bg-amber-500/5"
                )}
                role="status"
                aria-live="polite"
              >
                <p className="text-sm font-medium">
                  {settings?.identity_configured
                    ? t("身份邮件已就绪")
                    : t("身份邮件尚未就绪")}
                </p>
                <p className="mt-1 text-xs text-muted-foreground">
                  {settings?.identity_configured
                    ? t("系统可以发送邀请和密码重置邮件")
                    : t("请启用 SMTP 并完成服务器、发件人和站点地址配置")}
                </p>
              </div>
              <form className="grid gap-5" onSubmit={save}>
                <Field>
                  <FieldLabel htmlFor="smtp-site-url">
                    {t("站点地址")}
                  </FieldLabel>
                  <Input
                    id="smtp-site-url"
                    type="url"
                    value={form.siteUrl}
                    onChange={(event) =>
                      updateForm("siteUrl", event.target.value)
                    }
                    required={form.enabled}
                    maxLength={2048}
                    disabled={isSaving}
                    autoComplete="url"
                  />
                  <FieldDescription>
                    {t("用于邀请和密码重置邮件中的链接")}
                  </FieldDescription>
                </Field>
                <div className="grid gap-4 sm:grid-cols-[minmax(0,1fr)_9rem]">
                  <Field>
                    <FieldLabel htmlFor="smtp-host">
                      {t("SMTP 主机")}
                    </FieldLabel>
                    <Input
                      id="smtp-host"
                      value={form.host}
                      onChange={(event) =>
                        updateForm("host", event.target.value)
                      }
                      required={form.enabled}
                      maxLength={255}
                      disabled={isSaving}
                      autoComplete="off"
                    />
                  </Field>
                  <Field>
                    <FieldLabel htmlFor="smtp-port">{t("端口")}</FieldLabel>
                    <Input
                      id="smtp-port"
                      type="number"
                      min={1}
                      max={65535}
                      step={1}
                      value={form.port}
                      onChange={(event) =>
                        updateForm("port", event.target.value)
                      }
                      required
                      disabled={isSaving}
                      inputMode="numeric"
                    />
                  </Field>
                </div>
                <div className="grid gap-4 sm:grid-cols-2">
                  <Field>
                    <FieldLabel htmlFor="smtp-username">
                      {t("SMTP 用户名")}
                    </FieldLabel>
                    <Input
                      id="smtp-username"
                      value={form.username}
                      onChange={(event) =>
                        updateForm("username", event.target.value)
                      }
                      maxLength={255}
                      disabled={isSaving}
                      autoComplete="off"
                    />
                  </Field>
                  <Field>
                    <FieldLabel htmlFor="smtp-password">
                      {t("SMTP 密码")}
                    </FieldLabel>
                    <Input
                      id="smtp-password"
                      type="password"
                      value={form.password}
                      onChange={(event) => {
                        setForm((current) => ({
                          ...current,
                          password: event.target.value,
                          clearPassword: false,
                        }))
                        setFormError(null)
                      }}
                      placeholder={
                        settings?.has_password
                          ? t("留空以保留当前密码")
                          : t("请输入 SMTP 密码")
                      }
                      maxLength={4096}
                      disabled={isSaving}
                      autoComplete="new-password"
                    />
                    {settings?.password_hint ? (
                      <FieldDescription>
                        {t("当前密码提示：{hint}", {
                          hint: settings.password_hint,
                        })}
                      </FieldDescription>
                    ) : null}
                    {settings?.has_password ? (
                      <label className="flex items-center gap-2 text-sm text-muted-foreground">
                        <input
                          type="checkbox"
                          checked={form.clearPassword}
                          onChange={(event) => {
                            setForm((current) => ({
                              ...current,
                              clearPassword: event.target.checked,
                              password: event.target.checked
                                ? ""
                                : current.password,
                            }))
                            setFormError(null)
                          }}
                          disabled={isSaving}
                        />
                        {t("清除已保存的密码")}
                      </label>
                    ) : null}
                  </Field>
                </div>
                <div className="grid gap-4 sm:grid-cols-2">
                  <Field>
                    <FieldLabel htmlFor="smtp-security">
                      {t("加密方式")}
                    </FieldLabel>
                    <FilterDropdown
                      id="smtp-security"
                      className="h-9 rounded-lg border-input bg-transparent px-3"
                      value={form.security}
                      onChange={(value) =>
                        updateForm("security", value as SmtpSecurity)
                      }
                      ariaLabel={t("加密方式")}
                      disabled={isSaving}
                      options={[
                        { value: "none", label: t("不加密") },
                        { value: "starttls", label: t("STARTTLS") },
                        { value: "ssl", label: t("SSL/TLS") },
                      ]}
                    />
                  </Field>
                  <Field>
                    <FieldLabel htmlFor="smtp-timeout">
                      {t("连接超时（秒）")}
                    </FieldLabel>
                    <Input
                      id="smtp-timeout"
                      type="number"
                      max={120}
                      step="any"
                      value={form.timeoutSeconds}
                      onChange={(event) =>
                        updateForm("timeoutSeconds", event.target.value)
                      }
                      required
                      disabled={isSaving}
                      inputMode="decimal"
                    />
                  </Field>
                </div>
                <div className="grid gap-4 sm:grid-cols-2">
                  <Field>
                    <FieldLabel htmlFor="smtp-from-email">
                      {t("发件人邮箱")}
                    </FieldLabel>
                    <Input
                      id="smtp-from-email"
                      type="email"
                      value={form.fromEmail}
                      onChange={(event) =>
                        updateForm("fromEmail", event.target.value)
                      }
                      required={form.enabled}
                      maxLength={255}
                      disabled={isSaving}
                      autoComplete="email"
                    />
                  </Field>
                  <Field>
                    <FieldLabel htmlFor="smtp-from-name">
                      {t("发件人名称")}
                    </FieldLabel>
                    <Input
                      id="smtp-from-name"
                      value={form.fromName}
                      onChange={(event) =>
                        updateForm("fromName", event.target.value)
                      }
                      maxLength={120}
                      disabled={isSaving}
                    />
                  </Field>
                </div>
                <div className="flex flex-wrap items-center justify-between gap-3 border-t pt-4">
                  <button
                    type="button"
                    role="switch"
                    aria-checked={form.enabled}
                    aria-label={t("启用 SMTP")}
                    onClick={() => updateForm("enabled", !form.enabled)}
                    disabled={isSaving}
                    className="inline-flex items-center gap-2 rounded-md text-sm font-medium focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    <span
                      className={cn(
                        "relative h-5 w-9 rounded-full bg-muted transition-colors",
                        form.enabled && "bg-primary"
                      )}
                    >
                      <span
                        className={cn(
                          "absolute top-0.5 left-0.5 size-4 rounded-full bg-background shadow transition-transform",
                          form.enabled && "translate-x-4"
                        )}
                      />
                    </span>
                    {form.enabled ? t("已启用") : t("已停用")}
                  </button>
                  <Button type="submit" disabled={isSaving}>
                    {isSaving ? (
                      <LoaderCircleIcon className="animate-spin" />
                    ) : null}
                    {t("保存 SMTP 配置")}
                  </Button>
                </div>
                {formError ? (
                  <p className="text-sm text-destructive" role="alert">
                    {formError}
                  </p>
                ) : null}
              </form>
            </>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{t("发送测试邮件")}</CardTitle>
          <CardDescription>
            {t("使用已保存的 SMTP 配置发送测试邮件")}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form
            className="grid gap-4 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-end"
            onSubmit={sendTest}
          >
            <Field>
              <FieldLabel htmlFor="smtp-test-recipient">
                {t("收件人邮箱")}
              </FieldLabel>
              <Input
                id="smtp-test-recipient"
                type="email"
                value={recipient}
                onChange={(event) => {
                  setRecipient(event.target.value)
                  setTestError(null)
                }}
                required
                maxLength={255}
                disabled={isTesting}
                autoComplete="email"
                placeholder={t("admin@example.com")}
              />
              {!settings?.configured ? (
                <FieldDescription>
                  {t("请先填写主机和发件人邮箱并保存")}
                </FieldDescription>
              ) : null}
            </Field>
            <Button
              type="submit"
              variant="outline"
              disabled={isLoading || isTesting || !settings?.configured}
            >
              {isTesting ? (
                <LoaderCircleIcon className="animate-spin" />
              ) : (
                <SendIcon />
              )}
              {t("发送测试邮件")}
            </Button>
          </form>
          {testError ? (
            <p className="mt-3 text-sm text-destructive" role="alert">
              {testError}
            </p>
          ) : null}
          {settings?.configured ? (
            <p className="mt-3 text-sm text-muted-foreground">
              {settings.enabled
                ? t("SMTP 已启用")
                : t("SMTP 当前未启用，但仍可发送测试邮件")}
            </p>
          ) : null}
        </CardContent>
      </Card>
    </div>
  )
}
