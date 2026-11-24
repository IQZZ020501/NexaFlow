"use client"

import * as React from "react"
import Link from "next/link"
import { useRouter, useSearchParams } from "next/navigation"
import {
  OrbitIcon,
  PauseIcon,
  PencilIcon,
  PlayIcon,
  PlusIcon,
  RefreshCwIcon,
} from "lucide-react"

import {
  AutomationStatusBadge,
  ExecutionRunStatusBadge,
  triggerTypeLabelKey,
  WebhookSecretDialog,
  type WebhookSecretDisclosure,
} from "@/components/automations/automation-badges"
import { AutomationFormDialog } from "@/components/automations/automation-form-dialog"
import {
  SystemPagination,
  type SystemPageSize,
} from "@/components/system/pagination-footer"
import { TopLoadingBar } from "@/components/app/top-progress"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { useLanguage } from "@/contexts/language-provider"
import { useOptionalMessageCenter } from "@/contexts/message-center-context"
import { useSession } from "@/contexts/session-context"
import { languageLocales } from "@/i18n"
import {
  executeAutomationNow,
  listAutomations,
  pauseAutomation,
  resumeAutomation,
  type Automation,
  type AutomationCreateResponse,
} from "@/lib/api/automations"
import { formatDateTime } from "@/lib/display"
import { getErrorMessage } from "@/lib/errors"

export function AutomationsPage() {
  const { selectedWorkspaceId } = useSession()
  return <AutomationsWorkspace key={selectedWorkspaceId ?? "none"} />
}

function AutomationsWorkspace() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const { token, selectedWorkspaceId, notify } = useSession()
  const { language, t } = useLanguage()
  const messageCenter = useOptionalMessageCenter()
  const locale = languageLocales[language]

  const [page, setPage] = React.useState(1)
  const [pageSize, setPageSize] = React.useState<SystemPageSize>(50)
  const [total, setTotal] = React.useState(0)
  const executeKeys = React.useRef<Record<string, string>>({})
  const [items, setItems] = React.useState<Automation[]>([])
  const [isLoading, setIsLoading] = React.useState(true)
  const [error, setError] = React.useState<string | null>(null)
  const [busyId, setBusyId] = React.useState<string | null>(null)

  const createParam = searchParams.get("create")
  const appIdParam = searchParams.get("app_id")
  const urlCreateKey = createParam === "1" ? `create:${appIdParam ?? ""}` : null

  const [manualDialogOpen, setManualDialogOpen] = React.useState(false)
  const [dismissedUrlCreateKey, setDismissedUrlCreateKey] = React.useState<
    string | null
  >(null)
  const [editingAutomation, setEditingAutomation] =
    React.useState<Automation | null>(null)
  const [initialAppId, setInitialAppId] = React.useState<string | null>(null)
  const [secretDisclosure, setSecretDisclosure] =
    React.useState<WebhookSecretDisclosure | null>(null)

  const urlDialogActive =
    Boolean(urlCreateKey) && dismissedUrlCreateKey !== urlCreateKey
  const dialogOpen = manualDialogOpen || urlDialogActive
  const effectiveInitialAppId = manualDialogOpen ? initialAppId : appIdParam

  const loadAutomations = React.useCallback(async () => {
    if (!token || !selectedWorkspaceId) {
      setItems([])
      setIsLoading(false)
      return
    }
    setIsLoading(true)
    setError(null)
    try {
      const response = await listAutomations(token, selectedWorkspaceId, {
        limit: pageSize,
        offset: (page - 1) * pageSize,
      })
      setItems(response.items)
      setTotal(response.total)
    } catch (nextError) {
      setError(getErrorMessage(nextError, t))
    } finally {
      setIsLoading(false)
    }
  }, [selectedWorkspaceId, t, token, page, pageSize])

  React.useEffect(() => {
    const timer = window.setTimeout(() => {
      void loadAutomations()
    }, 0)
    return () => window.clearTimeout(timer)
  }, [loadAutomations, messageCenter?.refreshVersion])

  function handleDialogOpenChange(nextOpen: boolean) {
    setManualDialogOpen(nextOpen)
    if (!nextOpen) {
      setEditingAutomation(null)
      setInitialAppId(null)
      if (urlCreateKey) {
        setDismissedUrlCreateKey(urlCreateKey)
        router.replace("/app/automations")
      }
    }
  }

  function handleSaved(saved: AutomationCreateResponse | Automation) {
    if ("webhook_secret" in saved && saved.webhook_secret) {
      setSecretDisclosure({
        name: saved.name,
        webhookUrl: saved.webhook_url,
        secret: saved.webhook_secret,
      })
    }
    void loadAutomations()
  }

  async function handleToggleStatus(item: Automation) {
    if (!token || !selectedWorkspaceId || busyId) return
    setBusyId(item.id)
    try {
      const updated =
        item.status === "paused"
          ? await resumeAutomation(token, selectedWorkspaceId, item.id)
          : await pauseAutomation(token, selectedWorkspaceId, item.id)
      setItems((current) =>
        current.map((entry) => (entry.id === updated.id ? updated : entry))
      )
      notify(
        "success",
        t(item.status === "paused" ? "自动化已恢复" : "自动化已暂停")
      )
    } catch (nextError) {
      notify("error", getErrorMessage(nextError, t))
    } finally {
      setBusyId(null)
    }
  }

  async function handleExecuteNow(item: Automation) {
    if (!token || !selectedWorkspaceId || busyId) return
    setBusyId(item.id)
    try {
      const execution = await executeAutomationNow(
        token,
        selectedWorkspaceId,
        item.id,
        (executeKeys.current[item.id] ??= crypto.randomUUID())
      )
      delete executeKeys.current[item.id]
      notify("success", t("已触发立即执行"))
      router.push(`/app/automations/${item.id}?execution=${execution.id}`)
    } catch (nextError) {
      notify("error", getErrorMessage(nextError, t))
    } finally {
      setBusyId(null)
    }
  }

  return (
    <div className="flex min-h-full flex-col">
      {isLoading ? <TopLoadingBar /> : null}
      <div className="mx-auto flex w-full max-w-6xl flex-1 flex-col gap-6 px-4 py-6 sm:px-6">
        <header className="flex flex-wrap items-center justify-between gap-4">
          <div className="min-w-0 space-y-1">
            <h1 className="text-xl font-semibold tracking-tight">
              {t("自动化")}
            </h1>
            <p className="text-sm text-muted-foreground">
              {t("管理定时触发与 Webhook 事件驱动的后台运行任务。")}
            </p>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            <Button
              type="button"
              variant="outline"
              onClick={() => void loadAutomations()}
              disabled={isLoading}
            >
              <RefreshCwIcon />
              <span className="hidden sm:inline">{t("刷新")}</span>
            </Button>
            <Button
              type="button"
              disabled={!selectedWorkspaceId}
              onClick={() => {
                setEditingAutomation(null)
                setInitialAppId(null)
                setManualDialogOpen(true)
              }}
            >
              <PlusIcon />
              <span>{t("创建自动化")}</span>
            </Button>
          </div>
        </header>

        {error ? (
          <div
            role="alert"
            className="rounded-lg border border-destructive/40 bg-destructive/5 px-4 py-3 text-sm text-destructive"
          >
            {error}
          </div>
        ) : null}

        {!isLoading && items.length === 0 ? (
          <div className="flex flex-1 flex-col items-center justify-center rounded-xl border border-dashed bg-muted/20 px-6 py-16 text-center">
            <OrbitIcon className="mb-3 size-10 text-muted-foreground" />
            <h2 className="text-base font-medium">{t("暂无自动化")}</h2>
            <p className="mt-1 max-w-md text-sm text-muted-foreground">
              {t(
                "为已发布的应用创建定时或 Webhook 自动化任务后，任务会在后台自动执行。"
              )}
            </p>
            <Button
              type="button"
              className="mt-5"
              disabled={!selectedWorkspaceId}
              onClick={() => {
                setEditingAutomation(null)
                setInitialAppId(null)
                setManualDialogOpen(true)
              }}
            >
              <PlusIcon />
              <span>{t("创建自动化")}</span>
            </Button>
          </div>
        ) : (
          <div className="grid gap-4 md:grid-cols-2">
            {items.map((item) => {
              const isBusy = busyId === item.id
              const latest = item.latest_execution
              return (
                <Card key={item.id} className="flex flex-col justify-between">
                  <CardHeader className="gap-2">
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0 space-y-1">
                        <CardTitle className="truncate text-base">
                          <Link
                            href={`/app/automations/${item.id}`}
                            className="hover:underline"
                          >
                            {item.name}
                          </Link>
                        </CardTitle>
                        <CardDescription className="line-clamp-2">
                          {item.description ||
                            `${item.target_app_name} · v${item.target_version_number}`}
                        </CardDescription>
                      </div>
                      <AutomationStatusBadge status={item.status} t={t} />
                    </div>
                    <div className="flex flex-wrap gap-1.5">
                      <Badge variant="outline">
                        {item.target_app_type === "workflow"
                          ? "Workflow"
                          : "Agent"}
                        : {item.target_app_name} v{item.target_version_number}
                      </Badge>
                      <Badge variant="secondary">
                        {t(triggerTypeLabelKey(item.trigger_type))}
                      </Badge>
                    </div>
                  </CardHeader>

                  <CardContent className="grid gap-2 text-xs">
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-muted-foreground">
                        {t("下次执行时间")}
                      </span>
                      <span className="font-medium tabular-nums">
                        {item.next_run_at
                          ? formatDateTime(item.next_run_at, locale)
                          : "—"}
                      </span>
                    </div>
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-muted-foreground">
                        {t("最近结果")}
                      </span>
                      {latest ? (
                        <Link
                          href={`/app/automations/${item.id}?execution=${latest.id}`}
                          className="inline-flex items-center gap-1.5 hover:underline"
                        >
                          <ExecutionRunStatusBadge
                            runStatus={latest.run_status}
                            dispatchStatus={latest.dispatch_status}
                            t={t}
                          />
                          <span className="text-muted-foreground tabular-nums">
                            {formatDateTime(latest.received_at, locale)}
                          </span>
                        </Link>
                      ) : (
                        <span className="text-muted-foreground">
                          {t("暂无执行记录")}
                        </span>
                      )}
                    </div>
                    {latest?.skip_reason ? (
                      <p className="rounded bg-muted/40 px-2 py-1 text-[11px] text-muted-foreground">
                        {getErrorMessage(new Error(latest.skip_reason), t)}
                      </p>
                    ) : null}
                  </CardContent>

                  <CardFooter className="flex flex-wrap items-center justify-between gap-2 border-t pt-3">
                    <div className="flex flex-wrap items-center gap-1.5">
                      <Button
                        type="button"
                        size="xs"
                        variant="outline"
                        disabled={isBusy}
                        onClick={() => void handleExecuteNow(item)}
                      >
                        <PlayIcon />
                        <span>{t("立即执行")}</span>
                      </Button>
                      {item.status !== "completed" ? (
                        <Button
                          type="button"
                          size="xs"
                          variant="outline"
                          disabled={isBusy}
                          onClick={() => void handleToggleStatus(item)}
                        >
                          {item.status === "paused" ? (
                            <PlayIcon />
                          ) : (
                            <PauseIcon />
                          )}
                          <span>
                            {t(item.status === "paused" ? "恢复运行" : "暂停")}
                          </span>
                        </Button>
                      ) : null}
                      <Button
                        type="button"
                        size="xs"
                        variant="ghost"
                        disabled={isBusy}
                        onClick={() => {
                          setEditingAutomation(item)
                          setInitialAppId(null)
                          setManualDialogOpen(true)
                        }}
                      >
                        <PencilIcon />
                        <span>{t("编辑")}</span>
                      </Button>
                    </div>
                    <Button size="xs" variant="ghost" asChild>
                      <Link href={`/app/automations/${item.id}`}>
                        {t("查看执行详情")}
                      </Link>
                    </Button>
                  </CardFooter>
                </Card>
              )
            })}
          </div>
        )}
        <SystemPagination
          page={page}
          pageSize={pageSize}
          itemCount={items.length}
          total={total}
          hasNext={page * pageSize < total}
          onPageChange={setPage}
          onPageSizeChange={(size) => {
            setPageSize(size)
            setPage(1)
          }}
        />
      </div>

      <AutomationFormDialog
        open={dialogOpen}
        onOpenChange={handleDialogOpenChange}
        automation={editingAutomation}
        initialAppId={effectiveInitialAppId}
        onSaved={handleSaved}
      />
      <WebhookSecretDialog
        disclosure={secretDisclosure}
        onClose={() => setSecretDisclosure(null)}
        t={t}
      />
    </div>
  )
}
