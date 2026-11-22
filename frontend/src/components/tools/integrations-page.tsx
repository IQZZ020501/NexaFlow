"use client"

import * as React from "react"
import Image from "next/image"
import { CheckIcon, LoaderCircleIcon, SearchIcon } from "lucide-react"

import { useConfirmDialog } from "@/components/app/confirm-dialog"
import { ToolsCatalogTabs } from "@/components/tools/catalog-tabs"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import {
  ResourceCard,
  ResourceCardFooter,
  ResourceCardHeader,
  ResourceCardTitle,
  resourceCardGridClass,
} from "@/components/ui/resource-card"
import { useLanguage } from "@/contexts/language-provider"
import { useSession } from "@/contexts/session-context"
import {
  authorizeIntegration,
  completeIntegrationAuthorization,
  listIntegrations,
  syncIntegrationTools,
  uninstallIntegration,
  type Integration,
  type IntegrationAuthorization,
  type IntegrationProvider,
} from "@/lib/api/integrations"
import { getErrorMessage } from "@/lib/errors"
import { integrationCatalog, integrationName } from "@/lib/integrations"

type DeviceAuthorization = IntegrationAuthorization & {
  provider: IntegrationProvider
}

export function IntegrationsPage() {
  const { token, me, selectedWorkspaceId } = useSession()
  if (!token || !me || !selectedWorkspaceId) return null
  return (
    <IntegrationsCatalog
      key={`${me.user.id}:${selectedWorkspaceId}`}
      token={token}
      workspaceId={selectedWorkspaceId}
    />
  )
}

export function IntegrationsCatalog({
  token,
  workspaceId,
}: {
  token: string
  workspaceId: string
}) {
  const { t } = useLanguage()
  const { notify } = useSession()
  const [confirmAction, confirmDialog] = useConfirmDialog()
  const [integrations, setIntegrations] = React.useState<Integration[]>([])
  const [loading, setLoading] = React.useState(true)
  const [error, setError] = React.useState<string | null>(null)
  const [query, setQuery] = React.useState("")
  const [busy, setBusy] = React.useState<IntegrationProvider | null>(null)
  const [device, setDevice] = React.useState<DeviceAuthorization | null>(null)
  const popup = React.useRef<Window | null>(null)
  const active = React.useRef(true)
  const requestId = React.useRef(0)
  const actionPending = React.useRef(false)

  const load = React.useCallback(async () => {
    const id = ++requestId.current
    setLoading(true)
    setError(null)
    try {
      const result = await listIntegrations(token, workspaceId)
      if (active.current && id === requestId.current) setIntegrations(result)
    } catch (nextError) {
      if (active.current && id === requestId.current)
        setError(getErrorMessage(nextError, t))
    } finally {
      if (active.current && id === requestId.current) setLoading(false)
    }
  }, [token, workspaceId, t])

  React.useEffect(() => {
    active.current = true
    // Load persisted installation state when this account context mounts.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load()
    return () => {
      active.current = false
      requestId.current += 1
      popup.current?.close()
    }
  }, [load])

  function replaceIntegration(result: Integration) {
    setIntegrations((current) =>
      current.map((entry) =>
        entry.provider === result.provider ? result : entry
      )
    )
  }

  const navigatePopup = React.useCallback((url: string, focus = false) => {
    try {
      if (popup.current && !popup.current.closed) {
        popup.current.location.href = url
        if (focus) popup.current.focus()
      }
    } catch {
      // Provider isolation can block window navigation. Keep the dialog's
      // authorization link available so the next step can still complete.
      popup.current = null
    }
  }, [])

  React.useEffect(() => {
    if (!device) return
    let cancelled = false
    let timer: ReturnType<typeof setTimeout>
    const deadline = Date.now() + (device.expires_in ?? 300) * 1000
    async function poll() {
      try {
        if (Date.now() >= deadline)
          throw new Error(t("授权已超时，请重新安装。"))
        const result = await completeIntegrationAuthorization(
          token,
          workspaceId,
          device!.provider,
          { state: device!.state }
        )
        if (cancelled || !active.current) return
        if (result.authorization) {
          setDevice({ ...result.authorization, provider: device!.provider })
          navigatePopup(result.authorization.authorization_url, true)
        } else if (result.status === "connected") {
          replaceIntegration(result)
          setDevice(null)
          setBusy(null)
          actionPending.current = false
          popup.current?.close()
          popup.current = null
          notify("success", t("集成已安装"))
        } else {
          timer = setTimeout(
            () => void poll(),
            Math.max(5, device!.poll_seconds) * 1000
          )
        }
      } catch (nextError) {
        if (cancelled || !active.current) return
        setDevice(null)
        setBusy(null)
        actionPending.current = false
        popup.current?.close()
        popup.current = null
        notify("error", getErrorMessage(nextError, t))
      }
    }
    timer = setTimeout(
      () => void poll(),
      Math.max(5, device.poll_seconds) * 1000
    )
    return () => {
      cancelled = true
      clearTimeout(timer)
    }
  }, [device, token, workspaceId, notify, t, navigatePopup])

  async function install(integration: Integration) {
    if (actionPending.current) return
    actionPending.current = true
    setBusy(integration.provider)
    if (integration.provider !== "dida") {
      popup.current = window.open("about:blank", "_blank")
      // Feishu advances this same window from app setup to account consent.
      // Disowning it here makes browsers reject the second cross-site navigation.
      if (popup.current && integration.provider !== "feishu")
        popup.current.opener = null
    }
    try {
      const authorization = await authorizeIntegration(
        token,
        workspaceId,
        integration.provider
      )
      if (!active.current) {
        popup.current?.close()
        return
      }
      if (authorization.mode === "device") {
        setDevice({ ...authorization, provider: integration.provider })
        navigatePopup(authorization.authorization_url)
      } else {
        window.location.assign(authorization.authorization_url)
      }
    } catch (nextError) {
      popup.current?.close()
      popup.current = null
      if (active.current) {
        setBusy(null)
        actionPending.current = false
        notify("error", getErrorMessage(nextError, t))
      }
    }
  }

  async function remove(provider: IntegrationProvider, cancel = false) {
    if (!cancel && actionPending.current) return
    if (
      !cancel &&
      !(await confirmAction({
        title: t("卸载 {name}？", { name: t(integrationName(provider)) }),
        description: t(
          "卸载后将清除本地授权信息，并停止使用此账号执行新的工具调用。"
        ),
        confirmLabel: t("卸载"),
        destructive: true,
      }))
    )
      return
    actionPending.current = true
    setBusy(provider)
    // Stop polling before invalidating the attempt on the server.
    setDevice(null)
    popup.current?.close()
    popup.current = null
    try {
      const result = await uninstallIntegration(token, workspaceId, provider)
      if (!active.current) return
      replaceIntegration(result)
      if (!cancel) notify("success", t("集成已卸载"))
    } catch (nextError) {
      if (active.current) notify("error", getErrorMessage(nextError, t))
    } finally {
      if (active.current) {
        setBusy(null)
        actionPending.current = false
      }
    }
  }

  async function updateTools(provider: IntegrationProvider) {
    if (actionPending.current) return
    actionPending.current = true
    setBusy(provider)
    try {
      const result = await syncIntegrationTools(token, workspaceId, provider)
      if (!active.current) return
      replaceIntegration(result)
      notify(
        "success",
        t("工具已更新，请在 Agent 中取消并重新勾选此集成，然后保存。")
      )
    } catch (nextError) {
      if (active.current) notify("error", getErrorMessage(nextError, t))
    } finally {
      if (active.current) {
        setBusy(null)
        actionPending.current = false
      }
    }
  }

  const filtered = integrationCatalog.filter((entry) =>
    `${t(entry.name)} ${t(entry.description)}`
      .toLocaleLowerCase()
      .includes(query.trim().toLocaleLowerCase())
  )
  return (
    <main className="min-w-0 space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">{t("工具")}</h1>
        <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
          {t("连接你的第三方账号，为 Agent 安装所需的集成。")}
        </p>
      </div>
      <div
        role="search"
        className="flex min-w-0 flex-col gap-3 rounded-lg border bg-background p-3 shadow-sm sm:flex-row sm:items-center sm:justify-between"
      >
        <div className="relative min-w-0 sm:w-[320px]">
          <SearchIcon className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            role="searchbox"
            aria-label={t("搜索集成")}
            placeholder={t("搜索集成")}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            className="pl-9"
          />
        </div>
        <ToolsCatalogTabs activeKind="integration" />
      </div>
      {loading ? (
        <p role="status" className="text-sm text-muted-foreground">
          {t("正在加载集成")}
        </p>
      ) : error ? (
        <div role="alert" className="space-y-3 text-sm text-destructive">
          <p>{error}</p>
          <Button variant="outline" onClick={() => void load()}>
            {t("重试")}
          </Button>
        </div>
      ) : (
        <div className={resourceCardGridClass}>
          {filtered.map((entry) => {
            const integration = integrations.find(
              (item) => item.provider === entry.provider
            )
            const installed = integration?.status === "connected"
            const needsAuthorization =
              integration?.status === "reauthorization_required"
            return (
              <ResourceCard
                key={entry.provider}
                as="article"
                aria-label={t(entry.name)}
              >
                <ResourceCardHeader>
                  <div className="flex min-w-0 items-center gap-3">
                    <Image
                      src={entry.icon}
                      alt=""
                      aria-hidden="true"
                      width={24}
                      height={24}
                      className="size-6 shrink-0 object-contain"
                    />
                    <ResourceCardTitle as="h2">
                      {t(entry.name)}
                    </ResourceCardTitle>
                  </div>
                </ResourceCardHeader>
                <p className="mt-3 min-h-10 text-sm leading-5 text-muted-foreground">
                  {t(entry.description)}
                </p>
                <ResourceCardFooter className="flex-wrap items-center">
                  <Badge variant={installed ? "secondary" : "outline"}>
                    {installed ? <CheckIcon className="size-3" /> : null}
                    {t(
                      installed
                        ? "已安装"
                        : needsAuthorization
                          ? "需要重新认证"
                          : "未安装"
                    )}
                  </Badge>
                  <div className="flex items-center gap-2">
                    {installed ? (
                      <Button
                        variant="ghost"
                        size="sm"
                        disabled={Boolean(busy)}
                        onClick={() => void updateTools(entry.provider)}
                      >
                        {t("更新工具")}
                      </Button>
                    ) : null}
                    {needsAuthorization ? (
                      <Button
                        variant="ghost"
                        size="sm"
                        disabled={Boolean(busy)}
                        onClick={() => void remove(entry.provider)}
                      >
                        {t("卸载")}
                      </Button>
                    ) : null}
                    <Button
                      size="sm"
                      variant={installed ? "outline" : "default"}
                      disabled={!integration || Boolean(busy)}
                      onClick={() =>
                        integration &&
                        void (installed
                          ? remove(entry.provider)
                          : install(integration))
                      }
                    >
                      {busy === entry.provider ? (
                        <LoaderCircleIcon className="animate-spin" />
                      ) : null}
                      {t(
                        installed
                          ? "卸载"
                          : needsAuthorization
                            ? "重新认证"
                            : "安装"
                      )}
                    </Button>
                  </div>
                </ResourceCardFooter>
              </ResourceCard>
            )
          })}
          {!filtered.length ? (
            <p className="text-sm text-muted-foreground">
              {t("未找到匹配的集成")}
            </p>
          ) : null}
        </div>
      )}
      {device ? (
        <Dialog
          open
          onOpenChange={(open) => {
            if (!open) void remove(device.provider, true)
          }}
        >
          <DialogContent className="sm:max-w-md">
            <DialogHeader>
              <DialogTitle>
                {t("安装 {name}", {
                  name: t(integrationName(device.provider)),
                })}
              </DialogTitle>
              <DialogDescription>
                {t(
                  device.phase === "application"
                    ? "请在飞书或 Lark 页面创建个人应用，完成后继续授权你的账号。无需填写应用凭据。"
                    : device.phase === "login"
                      ? "个人应用已创建，请继续登录飞书或 Lark 并授权个人数据访问。不支持豆包账号。"
                      : "请在平台页面登录并确认授权，完成后会自动更新安装状态。"
                )}
              </DialogDescription>
            </DialogHeader>
            <p
              role="status"
              className="flex items-center gap-2 text-sm text-muted-foreground"
            >
              <LoaderCircleIcon className="size-4 animate-spin" />
              {t("等待平台授权")}
            </p>
            <DialogFooter>
              <Button
                variant="outline"
                onClick={() => void remove(device.provider, true)}
              >
                {t("取消")}
              </Button>
              <Button asChild>
                <a
                  href={device.authorization_url}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  {t("前往授权")}
                </a>
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      ) : null}
      {confirmDialog}
    </main>
  )
}
