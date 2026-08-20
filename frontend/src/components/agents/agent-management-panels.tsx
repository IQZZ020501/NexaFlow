"use client"

import * as React from "react"
import {
  ActivityIcon,
  BarChart3Icon,
  CheckIcon,
  ClipboardIcon,
  CopyIcon,
  EyeIcon,
  ExternalLinkIcon,
  KeyRoundIcon,
  LoaderCircleIcon,
  MessageSquareIcon,
  RefreshCwIcon,
  ShieldCheckIcon,
  Trash2Icon,
  ThumbsDownIcon,
  ThumbsUpIcon,
  UsersIcon,
} from "lucide-react"
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts"

import { FilterDropdown } from "@/components/app/filter-dropdown"
import { useConfirmDialog } from "@/components/app/confirm-dialog"
import { MarkdownContent } from "@/components/knowledge/markdown-content"
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
import { useLanguage } from "@/contexts/language-provider"
import {
  createAgentApiCredential,
  getAgentMonitoring,
  listAgentApiCredentials,
  listAgentConversationUsers,
  listAgentLogs,
  revokeAgentApiCredential,
  rotateAgentApiCredential,
  type Agent,
  type AgentApiCredential,
  type AgentConversationUser,
  type AgentLog,
  type AgentMonitoring,
  type PaginatedResponse,
} from "@/lib/api/agents"
import { copyText } from "@/lib/clipboard"
import { formatDateTime } from "@/lib/display"
import { getErrorMessage } from "@/lib/errors"
import type { TFunction } from "@/i18n"

type PanelProps = {
  agent: Agent
  token: string
  workspaceId: string
  t: TFunction
  notify: (kind: "success" | "error", message: string) => void
}

type AgentOverviewPanelProps = PanelProps & {
  canViewCredentials: boolean
  canManageCredentials: boolean
}

const EMPTY_PAGINATION = { limit: 20, offset: 0 }

function usePaginatedList<TItem>(
  fetcher: (
    pagination: { limit: number; offset: number }
  ) => Promise<PaginatedResponse<TItem>>,
  onError: (error: unknown) => void,
  deps: React.DependencyList
) {
  const [items, setItems] = React.useState<TItem[]>([])
  const [pagination, setPagination] = React.useState(EMPTY_PAGINATION)
  const [total, setTotal] = React.useState(0)
  const [loading, setLoading] = React.useState(true)
  const fetcherRef = React.useRef(fetcher)
  const onErrorRef = React.useRef(onError)
  const paginationRef = React.useRef(pagination)
  React.useEffect(() => {
    fetcherRef.current = fetcher
    onErrorRef.current = onError
    paginationRef.current = pagination
  })

  const load = React.useCallback(async (offset: number) => {
    setLoading(true)
    try {
      const response = await fetcherRef.current({
        limit: paginationRef.current.limit,
        offset,
      })
      setItems(response.items)
      setTotal(response.total)
      setPagination({ limit: response.limit, offset: response.offset })
    } catch (error) {
      onErrorRef.current(error)
    } finally {
      setLoading(false)
    }
  }, [])

  React.useEffect(() => {
    let current = true
    fetcher(EMPTY_PAGINATION)
      .then((response) => {
        if (!current) return
        setItems(response.items)
        setTotal(response.total)
        setPagination({ limit: response.limit, offset: response.offset })
      })
      .catch((error: unknown) => {
        if (current) onError(error)
      })
      .finally(() => {
        if (current) setLoading(false)
      })
    return () => {
      current = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)

  return { items, pagination, total, loading, load }
}

function localeFor(language: string) {
  return language === "en"
    ? "en-US"
    : language === "zh-Hant"
      ? "zh-TW"
      : "zh-CN"
}

function sourceLabel(source: AgentLog["access_source"], t: TFunction) {
  if (source === "public") return t("公开访问")
  if (source === "api") return t("API")
  return t("控制台")
}

/**
 * Resolves a localized label for a run status.
 *
 * @param status - The run status to label
 * @param t - The translation function used to localize recognized statuses
 * @returns The localized status label, or the original status when no label is defined
 */
function statusLabel(status: string, t: TFunction) {
  const labels: Record<string, string> = {
    queued: t("排队中"),
    running: t("运行中"),
    succeeded: t("成功"),
    failed: t("失败"),
    cancelled: t("已取消"),
    awaiting_approval: t("等待确认"),
  }
  return labels[status] ?? status
}

/**
 * Renders a localized indicator for positive, negative, or absent feedback.
 *
 * @param value - The feedback classification to display
 * @param t - The translation function used for feedback labels
 */
function FeedbackIndicator({
  value,
  t,
}: {
  value?: "positive" | "negative" | null
  t: TFunction
}) {
  const label =
    value === "positive"
      ? t("点赞")
      : value === "negative"
        ? t("点踩")
        : t("暂无反馈")
  const Icon = value === "positive" ? ThumbsUpIcon : ThumbsDownIcon

  return value ? (
    <span
      role="img"
      aria-label={label}
      title={label}
      className={`inline-flex items-center gap-1 ${value === "positive" ? "text-emerald-600 dark:text-emerald-400" : "text-destructive"}`}
    >
      <Icon className="size-4" aria-hidden="true" />
      <span>{label}</span>
    </span>
  ) : (
    <span
      role="img"
      aria-label={label}
      title={label}
      className="text-muted-foreground"
    >
      —
    </span>
  )
}

/**
 * Displays a labeled metric with an icon and styling tone.
 *
 * @param icon - The icon component to display
 * @param label - The metric label
 * @param value - The numeric metric value
 * @param tone - CSS classes that define the icon background styling
 */
function MetricCard({
  icon: Icon,
  label,
  value,
  tone,
}: {
  icon: React.ComponentType<{ className?: string }>
  label: string
  value: number
  tone: string
}) {
  return (
    <div className="rounded-lg border bg-background p-4">
      <div className="flex items-center gap-3">
        <span
          className={`flex size-9 items-center justify-center rounded-lg ${tone}`}
        >
          <Icon className="size-4" />
        </span>
        <div className="min-w-0">
          <p className="text-xs text-muted-foreground">{label}</p>
          <p className="mt-1 text-xl font-semibold tabular-nums">
            {value.toLocaleString()}
          </p>
        </div>
      </div>
    </div>
  )
}

export function AgentOverviewPanel({
  agent,
  token,
  workspaceId,
  canViewCredentials,
  canManageCredentials,
  t,
  notify,
}: AgentOverviewPanelProps) {
  const { language } = useLanguage()
  const [confirmAction, confirmDialog] = useConfirmDialog()
  const [origin, setOrigin] = React.useState("")
  const [credentials, setCredentials] = React.useState<AgentApiCredential[]>([])
  const [isKeyDialogOpen, setIsKeyDialogOpen] = React.useState(false)
  const [isLoadingKeys, setIsLoadingKeys] = React.useState(false)
  const [isKeySaving, setIsKeySaving] = React.useState(false)
  const [newKeyName, setNewKeyName] = React.useState("")
  const [oneTimeToken, setOneTimeToken] = React.useState<string | null>(null)
  const [oneTimeTokenName, setOneTimeTokenName] = React.useState("")
  const [keyAction, setKeyAction] = React.useState<string | null>(null)

  React.useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setOrigin(window.location.origin)
  }, [])

  const loadCredentials = React.useCallback(async () => {
    if (!canViewCredentials) return
    setIsLoadingKeys(true)
    try {
      const response = await listAgentApiCredentials(
        token,
        workspaceId,
        agent.id
      )
      setCredentials(response.items)
    } catch (error) {
      notify("error", getErrorMessage(error, t))
    } finally {
      setIsLoadingKeys(false)
    }
  }, [agent.id, canViewCredentials, notify, t, token, workspaceId])

  const publicUrl = origin ? `${origin}/chat/${agent.id}` : `/chat/${agent.id}`
  const apiKind = agent.app_type === "workflow" ? "workflow-api" : "agent-api"
  const apiBaseUrl = origin
    ? `${origin}/api/v1/${apiKind}/${agent.id}/runs`
    : `/api/v1/${apiKind}/${agent.id}/runs`
  const docsUrl = origin
    ? `${origin}/${apiKind}/${agent.id}/docs`
    : `/${apiKind}/${agent.id}/docs`

  async function handleCopy(value: string, successMessage = t("已复制")) {
    try {
      await copyText(value)
      notify("success", successMessage)
    } catch {
      notify("error", t("复制失败"))
    }
  }

  async function handleCreateKey(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const name = newKeyName.trim()
    if (!name || isKeySaving) return
    setIsKeySaving(true)
    try {
      const response = await createAgentApiCredential(
        token,
        workspaceId,
        agent.id,
        name
      )
      setOneTimeToken(response.token)
      setOneTimeTokenName(response.credential.name)
      setNewKeyName("")
      setCredentials((current) => [response.credential, ...current])
      notify("success", t("API Key 已创建"))
    } catch (error) {
      notify("error", getErrorMessage(error, t))
    } finally {
      setIsKeySaving(false)
    }
  }

  async function handleRotateKey(credential: AgentApiCredential) {
    if (keyAction) return
    setKeyAction(credential.id)
    try {
      const response = await rotateAgentApiCredential(
        token,
        workspaceId,
        agent.id,
        credential.id
      )
      setOneTimeToken(response.token)
      setOneTimeTokenName(response.credential.name)
      setCredentials((current) =>
        current.map((item) =>
          item.id === credential.id ? response.credential : item
        )
      )
      notify("success", t("API Key 已轮换"))
    } catch (error) {
      notify("error", getErrorMessage(error, t))
    } finally {
      setKeyAction(null)
    }
  }

  async function handleRevokeKey(credential: AgentApiCredential) {
    if (
      keyAction ||
      !(await confirmAction({
        description: t("确定撤销此 API Key 吗？"),
        confirmLabel: t("撤销"),
        destructive: true,
      }))
    ) {
      return
    }
    setKeyAction(credential.id)
    try {
      await revokeAgentApiCredential(
        token,
        workspaceId,
        agent.id,
        credential.id
      )
      setCredentials((current) =>
        current.map((item) =>
          item.id === credential.id
            ? { ...item, revoked_at: new Date().toISOString() }
            : item
        )
      )
      notify("success", t("API Key 已撤销"))
    } catch (error) {
      notify("error", getErrorMessage(error, t))
    } finally {
      setKeyAction(null)
    }
  }

  function closeKeyDialog(open: boolean) {
    setIsKeyDialogOpen(open)
    if (!open) {
      setOneTimeToken(null)
      setOneTimeTokenName("")
      setNewKeyName("")
    }
  }

  return (
    <div className="space-y-5 p-4 sm:p-6">
      <section className="mx-auto w-full max-w-6xl rounded-xl border bg-background p-5 shadow-xs">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
          <div className="flex min-w-0 items-start gap-3">
            <span className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary">
              <ShieldCheckIcon className="size-5" />
            </span>
            <div className="min-w-0">
              <h2 className="text-base font-semibold">{t("公开访问与 API")}</h2>
              <p className="mt-1 break-words text-sm text-muted-foreground [overflow-wrap:anywhere]">
                {agent.description || t("暂无描述")}
              </p>
            </div>
          </div>
          <Badge variant={agent.published ? "default" : "outline"}>
            {t(agent.published ? "已发布" : "未发布")}
          </Badge>
        </div>

        <div className="mt-5 divide-y overflow-hidden rounded-lg border lg:grid lg:grid-cols-2 lg:divide-x lg:divide-y-0">
          <div className="min-w-0 p-4 sm:p-5">
            <div className="flex items-center gap-2 text-sm font-medium">
              <ExternalLinkIcon className="size-4 text-primary" />
              {t("公开访问链接")}
            </div>
            <p
              className="mt-3 truncate rounded-md bg-muted/50 px-3 py-2 font-mono text-xs text-foreground"
              title={publicUrl}
            >
              {publicUrl}
            </p>
            <div className="mt-3 flex flex-wrap gap-2">
              {!agent.published ? (
                <p className="w-full text-xs text-muted-foreground">
                  {t("发布后此链接才可访问。")}
                </p>
              ) : null}
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => void handleCopy(publicUrl)}
              >
                <CopyIcon data-icon="inline-start" />
                {t("复制链接")}
              </Button>
              <Button type="button" variant="outline" size="sm" asChild>
                <a href={publicUrl} target="_blank" rel="noreferrer">
                  <ExternalLinkIcon data-icon="inline-start" />
                  {t("打开链接")}
                </a>
              </Button>
            </div>
          </div>

          <div className="min-w-0 p-4 sm:p-5">
            <div className="flex items-center gap-2 text-sm font-medium">
              <KeyRoundIcon className="size-4 text-primary" />
              {t("API 访问")}
            </div>
            <p
              className="mt-3 truncate rounded-md bg-muted/50 px-3 py-2 font-mono text-xs text-foreground"
              title={apiBaseUrl}
            >
              {apiBaseUrl}
            </p>
            <div className="mt-3 flex flex-wrap gap-2">
              <Button type="button" variant="outline" size="sm" asChild>
                <a href={docsUrl} target="_blank" rel="noreferrer">
                  <ExternalLinkIcon data-icon="inline-start" />
                  {t("API 文档")}
                </a>
              </Button>
              {canViewCredentials ? (
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => {
                    setIsKeyDialogOpen(true)
                    void loadCredentials()
                  }}
                >
                  <KeyRoundIcon data-icon="inline-start" />
                  {t(canManageCredentials ? "管理 API Key" : "查看 API Key")}
                </Button>
              ) : null}
            </div>
            {canViewCredentials ? (
              <Dialog open={isKeyDialogOpen} onOpenChange={closeKeyDialog}>
                <DialogContent className="max-h-[min(720px,calc(100svh-2rem))] overflow-y-auto sm:max-w-2xl">
                  <DialogHeader>
                    <DialogTitle>
                      {t(
                        canManageCredentials ? "管理 API Key" : "查看 API Key"
                      )}
                    </DialogTitle>
                    <DialogDescription>
                      {t(
                        canManageCredentials
                          ? "创建、轮换或撤销用于 API 访问的凭据。"
                          : "查看 API 凭据元信息。"
                      )}
                    </DialogDescription>
                  </DialogHeader>
                  {canManageCredentials && oneTimeToken ? (
                    <div className="rounded-lg border border-amber-500/40 bg-amber-500/10 p-4">
                      <p className="text-sm font-medium">
                        {t("一次性 API Key")}
                      </p>
                      <p className="mt-1 text-xs text-muted-foreground">
                        {t("请立即复制并妥善保存，关闭后将无法再次查看。")}
                      </p>
                      <div className="mt-3 flex items-center gap-2">
                        <code className="min-w-0 flex-1 break-all rounded-md bg-background px-3 py-2 text-xs">
                          {oneTimeToken}
                        </code>
                        <Button
                          type="button"
                          size="icon"
                          variant="outline"
                          aria-label={t("复制 API Key")}
                          title={t("复制 API Key")}
                          onClick={() =>
                            void handleCopy(oneTimeToken, t("API Key 已复制"))
                          }
                        >
                          <ClipboardIcon />
                        </Button>
                      </div>
                      <p className="mt-2 text-xs text-muted-foreground">
                        {oneTimeTokenName}
                      </p>
                    </div>
                  ) : null}
                  {canManageCredentials ? (
                    <form
                      className="flex flex-col gap-3 sm:flex-row sm:items-end"
                      onSubmit={handleCreateKey}
                    >
                      <label className="min-w-0 flex-1 text-sm font-medium">
                        {t("名称")}
                        <Input
                          className="mt-1.5"
                          value={newKeyName}
                          onChange={(event) =>
                            setNewKeyName(event.target.value)
                          }
                          placeholder={t("例如：生产服务")}
                          maxLength={120}
                        />
                      </label>
                      <Button
                        type="submit"
                        disabled={isKeySaving || !newKeyName.trim()}
                      >
                        {isKeySaving ? (
                          <LoaderCircleIcon className="animate-spin" />
                        ) : (
                          <KeyRoundIcon />
                        )}
                        {t("创建 Key")}
                      </Button>
                    </form>
                  ) : null}
                  <div className="space-y-2">
                    <div className="flex items-center justify-between">
                      <h3 className="text-sm font-medium">
                        {t("已有 API Key")}
                      </h3>
                      {isLoadingKeys ? (
                        <LoaderCircleIcon className="size-4 animate-spin text-muted-foreground" />
                      ) : null}
                    </div>
                    {credentials.length === 0 && !isLoadingKeys ? (
                      <p className="rounded-lg border border-dashed p-4 text-sm text-muted-foreground">
                        {t("暂无 API Key")}
                      </p>
                    ) : (
                      <div className="divide-y rounded-lg border">
                        {credentials.map((credential) => (
                          <div
                            key={credential.id}
                            className="flex flex-col gap-3 p-3 sm:flex-row sm:items-center sm:justify-between"
                          >
                            <div className="min-w-0">
                              <p className="truncate text-sm font-medium">
                                {credential.name}
                              </p>
                              <p className="mt-1 text-xs text-muted-foreground">
                                {credential.hint} ·{" "}
                                {formatDateTime(
                                  credential.created_at,
                                  localeFor(language)
                                )}
                              </p>
                              <p className="mt-1 text-xs text-muted-foreground">
                                {t("最近访问")}:{" "}
                                {credential.last_used_at
                                  ? formatDateTime(
                                      credential.last_used_at,
                                      localeFor(language)
                                    )
                                  : "-"}
                              </p>
                              {credential.revoked_at ? (
                                <Badge variant="secondary" className="mt-2">
                                  {t("已撤销")}
                                </Badge>
                              ) : null}
                            </div>
                            {canManageCredentials && !credential.revoked_at ? (
                              <div className="flex shrink-0 gap-2">
                                <Button
                                  type="button"
                                  variant="ghost"
                                  size="sm"
                                  disabled={Boolean(keyAction)}
                                  onClick={() =>
                                    void handleRotateKey(credential)
                                  }
                                >
                                  {keyAction === credential.id ? (
                                    <LoaderCircleIcon className="animate-spin" />
                                  ) : (
                                    <RefreshCwIcon />
                                  )}
                                  {t("轮换")}
                                </Button>
                                <Button
                                  type="button"
                                  variant="ghost"
                                  size="sm"
                                  className="text-destructive hover:text-destructive"
                                  disabled={Boolean(keyAction)}
                                  onClick={() =>
                                    void handleRevokeKey(credential)
                                  }
                                >
                                  <Trash2Icon />
                                  {t("撤销")}
                                </Button>
                              </div>
                            ) : null}
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                  <DialogFooter>
                    <Button
                      type="button"
                      variant="outline"
                      onClick={() => closeKeyDialog(false)}
                    >
                      {t("关闭")}
                    </Button>
                  </DialogFooter>
                </DialogContent>
              </Dialog>
            ) : (
              <p className="mt-4 text-xs text-muted-foreground">
                {t("仅工作空间管理员可管理 API Key。")}
              </p>
            )}
          </div>
        </div>
      </section>
      {confirmDialog}
    </div>
  )
}

function Pagination({
  offset,
  limit,
  total,
  onPrevious,
  onNext,
  t,
}: {
  offset: number
  limit: number
  total: number
  onPrevious: () => void
  onNext: () => void
  t: TFunction
}) {
  return (
    <div className="flex items-center justify-between gap-3 border-t pt-3 text-xs text-muted-foreground">
      <span>
        {t("显示 {from}-{to}，共 {total} 条", {
          from: total ? offset + 1 : 0,
          to: Math.min(offset + limit, total),
          total,
        })}
      </span>
      <div className="flex gap-2">
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={offset === 0}
          onClick={onPrevious}
        >
          {t("上一页")}
        </Button>
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={offset + limit >= total}
          onClick={onNext}
        >
          {t("下一页")}
        </Button>
      </div>
    </div>
  )
}

/**
 * Displays paginated conversation logs for an agent and provides detailed log views.
 *
 * @param agent - The agent whose conversation logs are displayed
 * @param token - The authentication token used to load logs
 * @param workspaceId - The workspace containing the agent
 * @param t - The translation function for localized text
 * @param notify - The function used to report loading errors
 */
export function AgentLogsPanel({
  agent,
  token,
  workspaceId,
  t,
  notify,
}: PanelProps) {
  const { language } = useLanguage()
  const [selectedLog, setSelectedLog] = React.useState<AgentLog | null>(null)
  const handleError = React.useCallback(
    (error: unknown) => notify("error", getErrorMessage(error, t)),
    [notify, t]
  )
  const { items, pagination, total, loading, load } =
    usePaginatedList<AgentLog>(
      (params) => listAgentLogs(token, workspaceId, agent.id, params),
      handleError,
      [agent.id, handleError, token, workspaceId]
    )
  return (
    <div className="space-y-4 p-4 sm:p-6">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold">{t("对话日志")}</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            {t("查看公开访问、API 和控制台产生的运行记录。")}
          </p>
        </div>
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => void load(pagination.offset)}
        >
          <RefreshCwIcon data-icon="inline-start" />
          {t("刷新")}
        </Button>
      </div>
      <div className="overflow-x-auto rounded-xl border bg-background">
        {loading ? (
          <div className="flex min-h-40 items-center justify-center text-sm text-muted-foreground">
            <LoaderCircleIcon className="mr-2 size-4 animate-spin" />
            {t("正在加载")}
          </div>
        ) : items.length === 0 ? (
          <p className="p-8 text-center text-sm text-muted-foreground">
            {t("暂无对话日志")}
          </p>
        ) : (
          <table className="w-full min-w-[760px] text-left text-sm">
            <thead className="border-b bg-muted/30 text-xs text-muted-foreground">
              <tr>
                <th className="px-4 py-3 font-medium">{t("问题")}</th>
                <th className="px-4 py-3 font-medium">{t("来源")}</th>
                <th className="px-4 py-3 font-medium">{t("用户")}</th>
                <th className="px-4 py-3 font-medium">{t("状态")}</th>
                <th className="px-4 py-3 font-medium">{t("反馈")}</th>
                <th className="px-4 py-3 font-medium">{t("时间")}</th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {items.map((item) => (
                <tr
                  key={item.id}
                  className="cursor-pointer align-top hover:bg-muted/30 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring"
                  role="button"
                  tabIndex={0}
                  aria-label={t("查看日志详情")}
                  onClick={() => setSelectedLog(item)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" || event.key === " ") {
                      event.preventDefault()
                      setSelectedLog(item)
                    }
                  }}
                >
                  <td className="max-w-[360px] px-4 py-3">
                    <p className="truncate" title={item.question}>
                      {item.question || t("未提供问题")}
                    </p>
                    {item.last_error ? (
                      <p
                        className="mt-1 truncate text-xs text-destructive"
                        title={item.last_error}
                      >
                        {item.last_error}
                      </p>
                    ) : null}
                  </td>
                  <td className="px-4 py-3">
                    <Badge variant="outline">
                      {sourceLabel(item.access_source, t)}
                    </Badge>
                  </td>
                  <td className="px-4 py-3">
                    {item.display_name || item.consumer_id}
                  </td>
                  <td className="px-4 py-3">{statusLabel(item.status, t)}</td>
                  <td className="px-4 py-3">
                    <FeedbackIndicator value={item.feedback} t={t} />
                  </td>
                  <td className="whitespace-nowrap px-4 py-3 text-xs text-muted-foreground">
                    <span className="inline-flex items-center gap-2">
                      {formatDateTime(item.created_at, localeFor(language))}
                      <EyeIcon className="size-3.5" />
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      <Pagination
        offset={pagination.offset}
        limit={pagination.limit}
        total={total}
        onPrevious={() =>
          void load(Math.max(0, pagination.offset - pagination.limit))
        }
        onNext={() => void load(pagination.offset + pagination.limit)}
        t={t}
      />
      <Dialog
        open={Boolean(selectedLog)}
        onOpenChange={(open) => {
          if (!open) setSelectedLog(null)
        }}
      >
        <DialogContent className="max-h-[min(760px,calc(100svh-2rem))] overflow-y-auto sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle>{t("对话详情")}</DialogTitle>
            <DialogDescription>
              {selectedLog
                ? `${sourceLabel(selectedLog.access_source, t)} · ${formatDateTime(selectedLog.created_at, localeFor(language))}`
                : ""}
            </DialogDescription>
          </DialogHeader>
          {selectedLog ? (
            <div className="space-y-4">
              <section>
                <h3 className="text-xs font-medium text-muted-foreground">
                  {t("问题")}
                </h3>
                <p className="mt-1 break-words whitespace-pre-wrap text-sm [overflow-wrap:anywhere]">
                  {selectedLog.question || t("未提供问题")}
                </p>
              </section>
              <section>
                <h3 className="text-xs font-medium text-muted-foreground">
                  {t("反馈")}
                </h3>
                <div className="mt-1">
                  <FeedbackIndicator value={selectedLog.feedback} t={t} />
                </div>
              </section>
              <section>
                <h3 className="text-xs font-medium text-muted-foreground">
                  {t("结果")}
                </h3>
                <div className="mt-1 rounded-lg border bg-muted/20 p-3">
                  {selectedLog.result ? (
                    <MarkdownContent
                      content={selectedLog.result}
                      className="break-words [overflow-wrap:anywhere]"
                    />
                  ) : (
                    <p className="text-sm text-muted-foreground">
                      {t(
                        agent.app_type === "workflow"
                          ? "工作流未返回结果"
                          : "Agent 未返回结果"
                      )}
                    </p>
                  )}
                </div>
              </section>
              <section>
                <h3 className="text-xs font-medium text-muted-foreground">
                  {t("错误")}
                </h3>
                <p
                  className={
                    selectedLog.last_error
                      ? "mt-1 break-words whitespace-pre-wrap text-sm text-destructive [overflow-wrap:anywhere]"
                      : "mt-1 text-sm text-muted-foreground"
                  }
                >
                  {selectedLog.last_error || t("暂无错误")}
                </p>
              </section>
              <section>
                <h3 className="text-xs font-medium text-muted-foreground">
                  {t("模型用量")}
                </h3>
                <pre className="mt-1 overflow-x-auto rounded-lg border bg-muted/30 p-3 text-xs">
                  {JSON.stringify(selectedLog.model_usage, null, 2)}
                </pre>
              </section>
            </div>
          ) : null}
        </DialogContent>
      </Dialog>
    </div>
  )
}

export function AgentMonitoringPanel({
  agent,
  token,
  workspaceId,
  t,
  notify,
}: PanelProps) {
  const [days, setDays] = React.useState<7 | 30 | 90>(7)
  const [data, setData] = React.useState<AgentMonitoring | null>(null)
  const [loading, setLoading] = React.useState(true)
  React.useEffect(() => {
    let current = true
    getAgentMonitoring(token, workspaceId, agent.id, days)
      .then((response) => {
        if (current) setData(response)
      })
      .catch((error: unknown) => {
        if (current) notify("error", getErrorMessage(error, t))
      })
      .finally(() => {
        if (current) setLoading(false)
      })
    return () => {
      current = false
    }
  }, [agent.id, days, notify, t, token, workspaceId])
  const summary = data?.summary
  const daily = data?.daily ?? []
  return (
    <div className="space-y-5 p-4 sm:p-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold">{t("监控统计")}</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            {t(
              agent.app_type === "workflow"
                ? "按时间范围查看工作流的使用与运行情况。"
                : "按时间范围查看 Agent 的使用与运行情况。"
            )}
          </p>
        </div>
        <div className="w-40 shrink-0">
          <FilterDropdown
            ariaLabel={t("统计周期")}
            value={String(days)}
            options={[
              { value: "7", label: t("过去 7 天") },
              { value: "30", label: t("过去 30 天") },
              { value: "90", label: t("过去 90 天") },
            ]}
            onChange={(value) => {
              setLoading(true)
              setDays(Number(value) as 7 | 30 | 90)
            }}
          />
        </div>
      </div>
      {loading || !summary ? (
        <div className="flex min-h-40 items-center justify-center text-sm text-muted-foreground">
          <LoaderCircleIcon className="mr-2 size-4 animate-spin" />
          {t("正在加载")}
        </div>
      ) : (
        <>
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
            <MetricCard
              icon={UsersIcon}
              label={t("活跃用户")}
              value={summary.active_users}
              tone="bg-blue-500/10 text-blue-600"
            />
            <MetricCard
              icon={MessageSquareIcon}
              label={t("对话次数")}
              value={summary.conversations}
              tone="bg-orange-500/10 text-orange-600"
            />
            <MetricCard
              icon={ActivityIcon}
              label={t("运行次数")}
              value={summary.runs}
              tone="bg-emerald-500/10 text-emerald-600"
            />
            <MetricCard
              icon={CheckIcon}
              label={t("成功运行")}
              value={summary.succeeded}
              tone="bg-teal-500/10 text-teal-600"
            />
            <MetricCard
              icon={BarChart3Icon}
              label={t("Tokens 总数")}
              value={summary.total_tokens}
              tone="bg-violet-500/10 text-violet-600"
            />
          </div>
          <section className="rounded-xl border bg-background p-4">
            <div className="flex items-center justify-between gap-3">
              <h3 className="text-sm font-semibold">{t("每日运行趋势")}</h3>
              <span className="text-xs text-muted-foreground">
                {t("失败 {value} 次", { value: summary.failed })}
              </span>
            </div>
            <div className="mt-5 h-64 min-w-0">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart
                  data={daily}
                  accessibilityLayer
                  desc={t("每日运行趋势")}
                  margin={{ top: 12, right: 16, left: 0, bottom: 0 }}
                >
                  <CartesianGrid
                    vertical={false}
                    stroke="var(--border)"
                    strokeDasharray="3 3"
                  />
                  <XAxis
                    dataKey="date"
                    axisLine={false}
                    tickLine={false}
                    minTickGap={24}
                    tickFormatter={(date: string) => date.slice(5)}
                    tick={{
                      fill: "var(--muted-foreground)",
                      fontSize: 11,
                    }}
                  />
                  <YAxis
                    allowDecimals={false}
                    axisLine={false}
                    tickLine={false}
                    width={32}
                    tick={{
                      fill: "var(--muted-foreground)",
                      fontSize: 11,
                    }}
                  />
                  <Tooltip
                    cursor={{
                      stroke: "var(--muted-foreground)",
                      strokeDasharray: "4 4",
                      strokeOpacity: 0.5,
                    }}
                    contentStyle={{
                      borderRadius: "var(--radius)",
                      borderColor: "var(--border)",
                      backgroundColor: "var(--popover)",
                      color: "var(--popover-foreground)",
                    }}
                    labelStyle={{
                      color: "var(--popover-foreground)",
                      fontWeight: 600,
                      marginBottom: 4,
                    }}
                    itemStyle={{ color: "var(--primary)" }}
                    formatter={(value) => [
                      Number(value ?? 0).toLocaleString(),
                      t("运行次数"),
                    ]}
                  />
                  <Line
                    type="monotone"
                    dataKey="runs"
                    name={t("运行次数")}
                    stroke="var(--primary)"
                    strokeWidth={2.5}
                    dot={{
                      r: 3,
                      fill: "var(--background)",
                      stroke: "var(--primary)",
                      strokeWidth: 2,
                    }}
                    activeDot={{
                      r: 6,
                      fill: "var(--primary)",
                      stroke: "var(--background)",
                      strokeWidth: 3,
                    }}
                    isAnimationActive
                    animationDuration={500}
                    connectNulls
                  />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </section>
        </>
      )}
    </div>
  )
}

export function AgentConversationUsersPanel({
  agent,
  token,
  workspaceId,
  t,
  notify,
}: PanelProps) {
  const { language } = useLanguage()
  const handleError = React.useCallback(
    (error: unknown) => notify("error", getErrorMessage(error, t)),
    [notify, t]
  )
  const { items, pagination, total, loading, load } =
    usePaginatedList<AgentConversationUser>(
      (params) =>
        listAgentConversationUsers(token, workspaceId, agent.id, params),
      handleError,
      [agent.id, handleError, token, workspaceId]
    )
  return (
    <div className="space-y-4 p-4 sm:p-6">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold">{t("对话用户")}</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            {t("了解参与对话的用户和访问来源。")}
          </p>
        </div>
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => void load(pagination.offset)}
        >
          <RefreshCwIcon data-icon="inline-start" />
          {t("刷新")}
        </Button>
      </div>
      <div className="overflow-x-auto rounded-xl border bg-background">
        {loading ? (
          <div className="flex min-h-40 items-center justify-center text-sm text-muted-foreground">
            <LoaderCircleIcon className="mr-2 size-4 animate-spin" />
            {t("正在加载")}
          </div>
        ) : items.length === 0 ? (
          <p className="p-8 text-center text-sm text-muted-foreground">
            {t("暂无对话用户")}
          </p>
        ) : (
          <table className="w-full min-w-[720px] text-left text-sm">
            <thead className="border-b bg-muted/30 text-xs text-muted-foreground">
              <tr>
                <th className="px-4 py-3 font-medium">{t("用户")}</th>
                <th className="px-4 py-3 font-medium">{t("来源")}</th>
                <th className="px-4 py-3 font-medium">{t("首次访问")}</th>
                <th className="px-4 py-3 font-medium">{t("最近访问")}</th>
                <th className="px-4 py-3 font-medium">{t("对话 / 运行")}</th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {items.map((item) => (
                <tr key={`${item.access_source}:${item.consumer_id}`}>
                  <td className="px-4 py-3">
                    <p className="font-medium">
                      {item.display_name || t("匿名用户")}
                    </p>
                    <p className="mt-1 truncate text-xs text-muted-foreground">
                      {item.consumer_id}
                    </p>
                  </td>
                  <td className="px-4 py-3">
                    <Badge variant="outline">
                      {sourceLabel(item.access_source, t)}
                    </Badge>
                  </td>
                  <td className="whitespace-nowrap px-4 py-3 text-xs text-muted-foreground">
                    {formatDateTime(item.first_seen_at, localeFor(language))}
                  </td>
                  <td className="whitespace-nowrap px-4 py-3 text-xs text-muted-foreground">
                    {formatDateTime(item.last_seen_at, localeFor(language))}
                  </td>
                  <td className="px-4 py-3 tabular-nums">
                    {item.conversation_count} / {item.run_count}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      <Pagination
        offset={pagination.offset}
        limit={pagination.limit}
        total={total}
        onPrevious={() =>
          void load(Math.max(0, pagination.offset - pagination.limit))
        }
        onNext={() => void load(pagination.offset + pagination.limit)}
        t={t}
      />
    </div>
  )
}
