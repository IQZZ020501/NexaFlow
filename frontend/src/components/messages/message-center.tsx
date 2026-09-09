"use client"

import * as React from "react"
import {
  BellIcon,
  CheckCheckIcon,
  CircleAlertIcon,
  InfoIcon,
  MegaphoneIcon,
  TriangleAlertIcon,
} from "lucide-react"
import { useRouter } from "next/navigation"

import { MarkdownContent } from "@/components/knowledge/markdown-content"
import {
  SystemPagination,
  type SystemPageSize,
} from "@/components/system/pagination-footer"
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
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { useLanguage } from "@/contexts/language-provider"
import {
  useMessageCenter,
  useOptionalMessageCenter,
} from "@/contexts/message-center-context"
import { useSession } from "@/contexts/session-context"
import { languageLocales } from "@/i18n"
import {
  listMessages,
  type MessageItem,
  type MessageSeverity,
} from "@/lib/api/messages"
import { cn } from "@/lib/utils"

function formatMessageTime(value: string, locale: string) {
  return new Intl.DateTimeFormat(locale, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value))
}

function severityClass(severity: MessageSeverity) {
  if (severity === "critical") return "text-destructive"
  if (severity === "warning") return "text-amber-600 dark:text-amber-400"
  return "text-sky-600 dark:text-sky-400"
}

function SeverityIcon({
  severity,
  className,
}: {
  severity: MessageSeverity
  className?: string
}) {
  if (severity === "critical") return <CircleAlertIcon className={className} />
  if (severity === "warning") return <TriangleAlertIcon className={className} />
  return <InfoIcon className={className} />
}

function MessagePreview({
  message,
  onSelect,
}: {
  message: MessageItem
  onSelect: () => void
}) {
  const { t } = useLanguage()
  return (
    <DropdownMenuItem
      onSelect={onSelect}
      className={cn(
        "items-start gap-3 rounded-lg py-3 whitespace-normal transition-colors",
        !message.is_read && "bg-muted/50"
      )}
    >
      <SeverityIcon
        severity={message.severity}
        className={cn(
          "mt-0.5 size-4 shrink-0",
          severityClass(message.severity)
        )}
      />
      <span className="min-w-0 flex-1">
        <span className="flex items-center gap-2">
          <span className="truncate font-medium">{message.title}</span>
          {!message.is_read ? (
            <>
              <span
                className="size-1.5 shrink-0 rounded-full bg-primary"
                aria-hidden="true"
              />
              <span className="sr-only">{t("未读消息")}</span>
            </>
          ) : null}
        </span>
      </span>
    </DropdownMenuItem>
  )
}

function MessageDetailsDialog({
  message,
  onOpenChange,
}: {
  message: MessageItem | null
  onOpenChange: (open: boolean) => void
}) {
  const { language, t } = useLanguage()

  return (
    <Dialog open={Boolean(message)} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[min(80svh,48rem)] gap-0 overflow-hidden p-0 sm:max-w-2xl">
        {message ? (
          <>
            <DialogHeader className="border-b px-6 py-5">
              <div className="flex items-start gap-3 pr-6">
                <SeverityIcon
                  severity={message.severity}
                  className={cn(
                    "mt-0.5 size-5 shrink-0",
                    severityClass(message.severity)
                  )}
                />
                <div className="min-w-0 flex-1">
                  <DialogTitle className="text-xl leading-snug">
                    {message.title}
                  </DialogTitle>
                  <DialogDescription className="mt-2 flex flex-wrap items-center gap-2">
                    <Badge variant="outline">
                      {message.scope_type === "global"
                        ? t("单条全局公告")
                        : t("单条工作空间公告")}
                    </Badge>
                    <Badge variant="secondary">
                      {t(
                        message.severity === "info"
                          ? "信息"
                          : message.severity === "warning"
                            ? "警告"
                            : "严重"
                      )}
                    </Badge>
                    {message.pinned ? (
                      <Badge variant="outline">{t("置顶")}</Badge>
                    ) : null}
                    <span>
                      {formatMessageTime(
                        message.published_at,
                        languageLocales[language]
                      )}
                    </span>
                  </DialogDescription>
                </div>
              </div>
            </DialogHeader>
            <div className="min-h-0 overflow-y-auto px-6 py-5">
              <MarkdownContent content={message.body} />
            </div>
            <DialogFooter className="border-t px-6 py-4">
              <Button
                type="button"
                variant="outline"
                onClick={() => onOpenChange(false)}
              >
                {t("关闭")}
              </Button>
            </DialogFooter>
          </>
        ) : null}
      </DialogContent>
    </Dialog>
  )
}

export function MessageCenter() {
  const { t } = useLanguage()
  const router = useRouter()
  const messageCenter = useOptionalMessageCenter()
  const [selectedMessage, setSelectedMessage] =
    React.useState<MessageItem | null>(null)

  if (!messageCenter) return null

  const { messages, unreadCount, isLoading, markRead, markAllRead } =
    messageCenter

  const handleMessageSelect = (message: MessageItem) => {
    setSelectedMessage(message)
    void markRead(message.id).catch(() => undefined)
  }

  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button
            variant="ghost"
            size="icon-lg"
            className="relative text-muted-foreground hover:text-foreground aria-expanded:bg-muted aria-expanded:text-foreground"
            aria-label={t("打开消息中心")}
          >
            <BellIcon className="size-4" />
            {unreadCount > 0 ? (
              <Badge
                variant="destructive"
                className="absolute -top-0.5 -right-0.5 min-w-4 justify-center rounded-full px-1 py-0 text-[10px] leading-4"
              >
                {unreadCount > 99 ? "99+" : unreadCount}
              </Badge>
            ) : null}
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent
          align="end"
          className="w-80 max-w-[calc(100vw-2rem)]"
        >
          <DropdownMenuLabel className="flex items-center justify-between">
            <span className="flex items-center gap-2">
              <MegaphoneIcon className="size-4" />
              {t("消息中心")}
            </span>
            <span className="text-xs font-normal text-muted-foreground">
              {unreadCount > 0
                ? t("{value} 条未读", { value: unreadCount })
                : t("已全部读")}
            </span>
          </DropdownMenuLabel>
          <DropdownMenuSeparator />
          {messages.length ? (
            <DropdownMenuGroup className="space-y-1 px-1">
              {messages.slice(0, 5).map((message) => (
                <MessagePreview
                  key={message.id}
                  message={message}
                  onSelect={() => handleMessageSelect(message)}
                />
              ))}
            </DropdownMenuGroup>
          ) : (
            <div className="px-3 py-8 text-center text-sm text-muted-foreground">
              {isLoading ? t("正在加载消息") : t("暂无消息")}
            </div>
          )}
          <DropdownMenuSeparator />
          <DropdownMenuGroup>
            <DropdownMenuItem onSelect={() => router.push("/app/messages")}>
              <MegaphoneIcon />
              {t("查看全部消息")}
            </DropdownMenuItem>
            <DropdownMenuItem
              disabled={unreadCount === 0}
              onSelect={() => void markAllRead().catch(() => undefined)}
            >
              <CheckCheckIcon />
              {t("全部标为已读")}
            </DropdownMenuItem>
          </DropdownMenuGroup>
        </DropdownMenuContent>
      </DropdownMenu>
      <MessageDetailsDialog
        message={selectedMessage}
        onOpenChange={(open) => {
          if (!open) setSelectedMessage(null)
        }}
      />
    </>
  )
}

export function MessagesPage() {
  const { t } = useLanguage()
  const { token, selectedWorkspaceId, mustChangePassword } = useSession()
  const [selectedMessage, setSelectedMessage] =
    React.useState<MessageItem | null>(null)
  const [pageMessages, setPageMessages] = React.useState<MessageItem[]>([])
  const [page, setPage] = React.useState(1)
  const [pageSize, setPageSize] = React.useState<SystemPageSize>(20)
  const [total, setTotal] = React.useState(0)
  const [isPageLoading, setIsPageLoading] = React.useState(true)
  const [pageError, setPageError] = React.useState<Error | null>(null)
  const requestId = React.useRef(0)
  const {
    unreadCount,
    isLoading,
    error,
    refresh,
    refreshVersion,
    markRead,
    markAllRead,
  } = useMessageCenter()

  const loadPage = React.useCallback(async () => {
    if (!token || mustChangePassword) {
      requestId.current += 1
      setPageMessages([])
      setTotal(0)
      setIsPageLoading(false)
      setPageError(null)
      return
    }
    const currentRequestId = requestId.current + 1
    requestId.current = currentRequestId
    setIsPageLoading(true)
    try {
      const result = await listMessages(token, selectedWorkspaceId, {
        limit: pageSize,
        offset: (page - 1) * pageSize,
      })
      if (currentRequestId !== requestId.current) return
      const lastPage = Math.max(1, Math.ceil(result.total / pageSize))
      if (page > lastPage) {
        setPage(lastPage)
        return
      }
      setPageMessages(result.items)
      setTotal(result.total)
      setPageError(null)
    } catch (cause) {
      if (currentRequestId === requestId.current) {
        setPageError(cause instanceof Error ? cause : new Error(String(cause)))
      }
    } finally {
      if (currentRequestId === requestId.current) setIsPageLoading(false)
    }
  }, [mustChangePassword, page, pageSize, selectedWorkspaceId, token])

  React.useEffect(() => {
    const timer = window.setTimeout(() => {
      void loadPage()
    }, 0)
    return () => window.clearTimeout(timer)
  }, [loadPage, refreshVersion])

  const handleMessageSelect = (message: MessageItem) => {
    setSelectedMessage(message)
    if (message.is_read) return
    const readAt = new Date().toISOString()
    setPageMessages((items) =>
      items.map((item) =>
        item.id === message.id
          ? { ...item, is_read: true, read_at: readAt }
          : item
      )
    )
    void markRead(message.id).catch(() => {
      void loadPage()
    })
  }

  const handleMarkAllRead = () => {
    const readAt = new Date().toISOString()
    setPageMessages((items) =>
      items.map((message) =>
        message.is_read
          ? message
          : { ...message, is_read: true, read_at: readAt }
      )
    )
    void markAllRead().catch(() => {
      void loadPage()
    })
  }

  const loading = isLoading || isPageLoading
  const loadError = error ?? pageError

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold">{t("消息中心")}</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            {t("查看全局和当前工作空间的公告。")}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button
            type="button"
            variant="outline"
            onClick={() => void refresh()}
            disabled={loading}
          >
            {t("刷新")}
          </Button>
          <Button
            type="button"
            variant="outline"
            onClick={handleMarkAllRead}
            disabled={unreadCount === 0 || loading}
          >
            <CheckCheckIcon data-icon="inline-start" />
            {t("全部标为已读")}
          </Button>
        </div>
      </div>

      {loadError ? (
        <div className="rounded-lg border border-destructive/40 bg-destructive/5 px-4 py-3 text-sm text-destructive">
          {t("消息加载失败，请稍后重试。")}
        </div>
      ) : null}

      {pageMessages.length ? (
        <div className="flex flex-col gap-2">
          {pageMessages.map((message) => (
            <article
              key={message.id}
              className={cn(
                "overflow-hidden rounded-lg border bg-card py-0 shadow-sm transition-[border-color,box-shadow] hover:border-foreground/20 hover:shadow-md",
                !message.is_read && "border-primary/40"
              )}
            >
              <button
                type="button"
                aria-haspopup="dialog"
                className="flex w-full items-center gap-3 px-5 py-4 text-left transition-colors outline-none hover:bg-muted/50 focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset"
                onClick={() => {
                  handleMessageSelect(message)
                }}
              >
                <SeverityIcon
                  severity={message.severity}
                  className={cn(
                    "size-4 shrink-0",
                    severityClass(message.severity)
                  )}
                />
                <span className="min-w-0 flex-1">
                  <span className="flex flex-wrap items-center gap-2">
                    <span className="truncate text-sm font-semibold sm:text-base">
                      {message.title}
                    </span>
                    {!message.is_read ? (
                      <Badge variant="secondary" className="rounded-full">
                        {t("未读")}
                      </Badge>
                    ) : null}
                    {message.pinned ? (
                      <Badge variant="outline" className="rounded-full">
                        {t("置顶")}
                      </Badge>
                    ) : null}
                  </span>
                </span>
              </button>
            </article>
          ))}
          <SystemPagination
            page={page}
            pageSize={pageSize}
            itemCount={pageMessages.length}
            total={total}
            hasNext={page * pageSize < total}
            onPageChange={setPage}
            onPageSizeChange={(nextPageSize) => {
              setPageSize(nextPageSize)
              setPage(1)
            }}
          />
        </div>
      ) : (
        <div className="rounded-lg border border-dashed px-6 py-16 text-center text-sm text-muted-foreground">
          {isPageLoading ? t("正在加载消息") : t("暂无消息")}
        </div>
      )}
      <MessageDetailsDialog
        message={selectedMessage}
        onOpenChange={(open) => {
          if (!open) setSelectedMessage(null)
        }}
      />
    </div>
  )
}
