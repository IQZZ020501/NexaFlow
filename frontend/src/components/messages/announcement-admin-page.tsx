"use client"

import * as React from "react"
import {
  ArchiveIcon,
  CalendarClockIcon,
  CheckIcon,
  ChevronDownIcon,
  FileTextIcon,
  MegaphoneIcon,
  PencilIcon,
  PinIcon,
  PlusIcon,
  RefreshCwIcon,
  SendIcon,
  Trash2Icon,
} from "lucide-react"
import { useRouter } from "next/navigation"

import { MarkdownContent } from "@/components/knowledge/markdown-content"
import { useConfirmDialog } from "@/components/app/confirm-dialog"
import { AnnouncementExpirationField } from "@/components/messages/announcement-expiration-field"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
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
import {
  Field,
  FieldDescription,
  FieldGroup,
  FieldLabel,
} from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import {
  SystemPagination,
  type SystemPageSize,
} from "@/components/system/pagination-footer"
import { useLanguage } from "@/contexts/language-provider"
import { useSession } from "@/contexts/session-context"
import type { TFunction } from "@/i18n"
import {
  archiveAnnouncement,
  createAnnouncement,
  deleteAnnouncement,
  listAnnouncements,
  publishAnnouncement,
  updateAnnouncement,
  type Announcement,
  type AnnouncementScope,
  type AnnouncementSeverity,
} from "@/lib/api/announcements"
import { displayWorkspaceName } from "@/lib/display"
import { getErrorMessage } from "@/lib/errors"
import { cn } from "@/lib/utils"

const severities: AnnouncementSeverity[] = ["info", "warning", "critical"]

function toLocalDateTimeInput(value: string | null) {
  if (!value) return ""
  const date = new Date(value)
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60_000)
  return local.toISOString().slice(0, 16)
}

function statusVariant(status: Announcement["status"]) {
  if (status === "published") return "default" as const
  if (status === "archived") return "outline" as const
  return "secondary" as const
}

function statusLabel(status: Announcement["status"], t: TFunction) {
  return t(
    status === "draft" ? "草稿" : status === "published" ? "已发布" : "已归档"
  )
}

function severityLabel(severity: AnnouncementSeverity, t: TFunction) {
  return t(
    severity === "info" ? "信息" : severity === "warning" ? "警告" : "严重"
  )
}

const severityDotClass: Record<AnnouncementSeverity, string> = {
  info: "bg-emerald-500",
  warning: "bg-amber-400",
  critical: "bg-red-500",
}

function AnnouncementSelector({
  label,
  value,
  options,
  onChange,
  className,
}: {
  label: string
  value: string
  options: Array<{ value: string; label: string }>
  onChange: (value: string) => void
  className?: string
}) {
  const selected =
    options.find((option) => option.value === value) ?? options[0]
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          type="button"
          variant="outline"
          className={cn("min-w-44 justify-between", className)}
          aria-label={label}
        >
          <span className="truncate">{selected?.label ?? label}</span>
          <ChevronDownIcon className="size-4" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start">
        <DropdownMenuLabel>{label}</DropdownMenuLabel>
        <DropdownMenuSeparator />
        <DropdownMenuGroup>
          {options.map((option) => (
            <DropdownMenuItem
              key={option.value}
              onSelect={() => onChange(option.value)}
              className="justify-between"
            >
              {option.label}
              {option.value === value ? (
                <CheckIcon className="size-3.5" />
              ) : null}
            </DropdownMenuItem>
          ))}
        </DropdownMenuGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

export function AnnouncementAdminPage() {
  const { language, t } = useLanguage()
  const session = useSession()
  const router = useRouter()
  const [confirmAction, confirmDialog] = useConfirmDialog()
  const titleInputRef = React.useRef<HTMLInputElement>(null)
  const isGlobalAdmin = Boolean(session.me?.user.is_global_admin)
  const isWorkspaceAdmin = Boolean(
    session.me?.user.workspaces.some((workspace) => workspace.role === "admin")
  )
  const [requestedScope, setRequestedScope] =
    React.useState<AnnouncementScope>("global")
  const [workspaceId, setWorkspaceId] = React.useState<string | null>(
    session.selectedWorkspaceId
  )
  const [items, setItems] = React.useState<Announcement[]>([])
  const [page, setPage] = React.useState(1)
  const [pageSize, setPageSize] = React.useState<SystemPageSize>(20)
  const [total, setTotal] = React.useState(0)
  const [isLoading, setIsLoading] = React.useState(true)
  const [isSaving, setIsSaving] = React.useState(false)
  const [deletingId, setDeletingId] = React.useState<string | null>(null)
  const [error, setError] = React.useState<string | null>(null)
  const [editingId, setEditingId] = React.useState<string | null>(null)
  const [selectedAnnouncement, setSelectedAnnouncement] =
    React.useState<Announcement | null>(null)
  const [title, setTitle] = React.useState("")
  const [body, setBody] = React.useState("")
  const [severity, setSeverity] = React.useState<AnnouncementSeverity>("info")
  const [pinned, setPinned] = React.useState(false)
  const [expiresAt, setExpiresAt] = React.useState("")

  const scope: AnnouncementScope =
    requestedScope === "global" && isGlobalAdmin
      ? "global"
      : requestedScope === "workspace" && isWorkspaceAdmin
        ? "workspace"
        : isGlobalAdmin
          ? "global"
          : "workspace"
  const manageableWorkspaceIds = React.useMemo(
    () =>
      new Set(
        session.me?.user.workspaces
          .filter((workspace) => workspace.role === "admin")
          .map((workspace) => workspace.id) ?? []
      ),
    [session.me]
  )
  const availableWorkspaces = React.useMemo(
    () =>
      session.workspaceOptions.filter((workspace) =>
        manageableWorkspaceIds.has(workspace.id)
      ),
    [manageableWorkspaceIds, session.workspaceOptions]
  )
  const effectiveWorkspaceId = React.useMemo(() => {
    if (scope !== "workspace") return null
    const requestedWorkspaceId = workspaceId ?? session.selectedWorkspaceId
    return (
      availableWorkspaces.find(
        (workspace) => workspace.id === requestedWorkspaceId
      )?.id ??
      availableWorkspaces[0]?.id ??
      null
    )
  }, [availableWorkspaces, scope, session.selectedWorkspaceId, workspaceId])
  const selectedWorkspace = availableWorkspaces.find(
    (workspace) => workspace.id === effectiveWorkspaceId
  )

  const loadAnnouncements = React.useCallback(async () => {
    const canManageScope = scope === "global" ? isGlobalAdmin : isWorkspaceAdmin
    if (
      !session.token ||
      !canManageScope ||
      (scope === "workspace" && !effectiveWorkspaceId)
    ) {
      setItems([])
      setIsLoading(false)
      setError(null)
      return
    }
    setIsLoading(true)
    setError(null)
    try {
      const result = await listAnnouncements(
        session.token,
        scope,
        effectiveWorkspaceId,
        {
          limit: pageSize,
          offset: (page - 1) * pageSize,
        }
      )
      setItems(result.items)
      setTotal(result.total)
    } catch (cause) {
      setError(getErrorMessage(cause, t))
    } finally {
      setIsLoading(false)
    }
  }, [
    effectiveWorkspaceId,
    isGlobalAdmin,
    isWorkspaceAdmin,
    page,
    pageSize,
    scope,
    session.token,
    t,
  ])

  React.useEffect(() => {
    if (!session.me) return
    if (!isGlobalAdmin && !isWorkspaceAdmin) {
      router.replace("/app/apps")
      return
    }
    const timer = window.setTimeout(() => {
      void loadAnnouncements()
    }, 0)
    return () => window.clearTimeout(timer)
  }, [
    isGlobalAdmin,
    isWorkspaceAdmin,
    loadAnnouncements,
    router,
    session.me,
    scope,
    session.selectedWorkspaceId,
    workspaceId,
  ])

  const resetForm = () => {
    setEditingId(null)
    setTitle("")
    setBody("")
    setSeverity("info")
    setPinned(false)
    setExpiresAt("")
  }

  const startAdding = () => {
    resetForm()
    titleInputRef.current?.scrollIntoView({
      behavior: "smooth",
      block: "start",
    })
    window.requestAnimationFrame(() => titleInputRef.current?.focus())
  }

  const startEditing = (item: Announcement) => {
    setEditingId(item.id)
    setTitle(item.title)
    setBody(item.body)
    setSeverity(item.severity)
    setPinned(item.pinned)
    setExpiresAt(toLocalDateTimeInput(item.expires_at))
    titleInputRef.current?.scrollIntoView({
      behavior: "smooth",
      block: "start",
    })
    window.requestAnimationFrame(() => titleInputRef.current?.focus())
  }

  const handleSave = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!session.token) return
    if (scope === "workspace" && !effectiveWorkspaceId) {
      session.notify("error", t("请先选择工作空间"))
      return
    }
    if (!title.trim() || !body.trim()) return

    setIsSaving(true)
    try {
      const payload = {
        title: title.trim(),
        body: body.trim(),
        severity,
        pinned,
        expires_at: expiresAt ? new Date(expiresAt).toISOString() : null,
      }
      if (editingId) {
        await updateAnnouncement(
          session.token,
          scope,
          effectiveWorkspaceId,
          editingId,
          payload
        )
        session.notify("success", t("公告已更新"))
      } else {
        await createAnnouncement(
          session.token,
          scope,
          effectiveWorkspaceId,
          payload
        )
        session.notify("success", t("公告已创建"))
      }
      resetForm()
      await loadAnnouncements()
    } catch (cause) {
      session.notify("error", getErrorMessage(cause, t))
    } finally {
      setIsSaving(false)
    }
  }

  const handleAction = async (
    action: "publish" | "archive",
    item: Announcement
  ) => {
    if (!session.token) return
    try {
      if (action === "publish") {
        await publishAnnouncement(
          session.token,
          scope,
          effectiveWorkspaceId,
          item.id
        )
        session.notify("success", t("公告已发布"))
      } else {
        await archiveAnnouncement(
          session.token,
          scope,
          effectiveWorkspaceId,
          item.id
        )
        session.notify("success", t("公告已归档"))
      }
      await loadAnnouncements()
    } catch (cause) {
      session.notify("error", getErrorMessage(cause, t))
    }
  }

  const handleDelete = async (item: Announcement) => {
    if (!session.token || item.status !== "archived") return
    if (
      !(await confirmAction({
        description: t("确定删除公告“{title}”？此操作不可恢复。", {
          title: item.title,
        }),
        confirmLabel: t("删除"),
        destructive: true,
      }))
    ) {
      return
    }

    setDeletingId(item.id)
    try {
      await deleteAnnouncement(
        session.token,
        scope,
        effectiveWorkspaceId,
        item.id
      )
      if (selectedAnnouncement?.id === item.id) {
        setSelectedAnnouncement(null)
      }
      session.notify("success", t("公告已删除"))
      await loadAnnouncements()
    } catch (cause) {
      session.notify("error", getErrorMessage(cause, t))
    } finally {
      setDeletingId(null)
    }
  }

  if (!session.me || !session.token || (!isGlobalAdmin && !isWorkspaceAdmin)) {
    return null
  }

  const scopeOptions = [
    ...(isGlobalAdmin ? [{ value: "global", label: t("全局公告") }] : []),
    ...(isWorkspaceAdmin
      ? [{ value: "workspace", label: t("工作空间公告") }]
      : []),
  ]
  const workspaceOptions = availableWorkspaces.map((workspace) => ({
    value: workspace.id,
    label: displayWorkspaceName(workspace, t),
  }))
  const severityOptions = severities.map((value) => ({
    value,
    label: t(value === "info" ? "信息" : value === "warning" ? "警告" : "严重"),
  }))

  return (
    <>
      <div className="mx-auto flex w-full max-w-7xl flex-col gap-5">
        <header className="rounded-2xl border bg-card/80 p-4 shadow-sm sm:p-5 lg:p-6">
          <div className="flex flex-col gap-5 xl:flex-row xl:items-center xl:justify-between">
            <div className="flex min-w-0 items-start gap-3">
              <span className="flex size-11 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary ring-1 ring-primary/15">
                <MegaphoneIcon className="size-5" aria-hidden="true" />
              </span>
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <h1 className="text-2xl font-semibold tracking-tight">
                    {t("公告管理")}
                  </h1>
                  <Badge variant="secondary" className="rounded-full">
                    {scope === "global"
                      ? t("全局公告")
                      : selectedWorkspace
                        ? displayWorkspaceName(selectedWorkspace, t)
                        : t("工作空间公告")}
                  </Badge>
                </div>
                <p className="mt-1 max-w-2xl text-sm leading-6 text-muted-foreground">
                  {t("管理全局和工作空间公告。")}
                </p>
              </div>
            </div>
            <div
              className={cn(
                "grid w-full gap-3 xl:w-auto",
                isGlobalAdmin && scope === "workspace"
                  ? "sm:grid-cols-2 xl:min-w-[28rem]"
                  : "sm:max-w-64 xl:min-w-64"
              )}
            >
              {isGlobalAdmin ? (
                <div className="min-w-0 space-y-1.5">
                  <p className="text-xs font-medium text-muted-foreground">
                    {t("切换公告范围")}
                  </p>
                  <AnnouncementSelector
                    label={t("切换公告范围")}
                    value={scope}
                    options={scopeOptions}
                    className="w-full min-w-0"
                    onChange={(value) => {
                      setRequestedScope(value as AnnouncementScope)
                      setPage(1)
                      resetForm()
                    }}
                  />
                </div>
              ) : null}
              {scope === "workspace" ? (
                <div className="min-w-0 space-y-1.5">
                  <p className="text-xs font-medium text-muted-foreground">
                    {t("工作空间")}
                  </p>
                  <AnnouncementSelector
                    label={t("工作空间")}
                    value={effectiveWorkspaceId ?? ""}
                    options={workspaceOptions}
                    className="w-full min-w-0"
                    onChange={(value) => {
                      setWorkspaceId(value)
                      setPage(1)
                      resetForm()
                    }}
                  />
                </div>
              ) : null}
            </div>
          </div>
        </header>

        {error ? (
          <div className="rounded-xl border border-destructive/40 bg-destructive/5 px-4 py-3 text-sm text-destructive">
            {t("无法加载公告")}：{error}
          </div>
        ) : null}

        <div className="grid min-w-0 items-start gap-5 xl:grid-cols-[minmax(19rem,0.82fr)_minmax(0,1.18fr)]">
          <Card className="min-w-0 gap-0 overflow-hidden py-0 xl:sticky xl:top-4">
            <CardHeader className="border-b bg-muted/20 px-4 py-4 sm:px-5">
              <div className="flex items-center justify-between gap-3">
                <CardTitle className="text-base">
                  {editingId ? t("保存公告") : t("新建公告")}
                </CardTitle>
                {editingId ? (
                  <Badge variant="outline" className="rounded-full">
                    {t("编辑")}
                  </Badge>
                ) : null}
              </div>
              <CardDescription className="max-w-md leading-5">
                {t("草稿发布后会实时推送给可见范围内的用户。")}
              </CardDescription>
            </CardHeader>
            <CardContent className="p-4 sm:p-5">
              <form className="flex flex-col" onSubmit={handleSave}>
                <FieldGroup className="gap-4">
                  <Field>
                    <FieldLabel htmlFor="announcement-title">
                      {t("公告标题")}
                    </FieldLabel>
                    <Input
                      ref={titleInputRef}
                      id="announcement-title"
                      value={title}
                      onChange={(event) => setTitle(event.target.value)}
                      placeholder={t("请输入公告标题")}
                      required
                    />
                  </Field>
                  <Field>
                    <div className="flex items-center justify-between gap-3">
                      <FieldLabel htmlFor="announcement-body">
                        {t("公告正文")}
                      </FieldLabel>
                      <FileTextIcon
                        className="size-4 text-muted-foreground"
                        aria-hidden="true"
                      />
                    </div>
                    <textarea
                      id="announcement-body"
                      value={body}
                      onChange={(event) => setBody(event.target.value)}
                      placeholder={t("使用Markdown编写公告内容")}
                      className="max-h-72 min-h-44 w-full resize-y rounded-xl border border-input bg-background px-3 py-2.5 text-sm leading-6 shadow-xs transition-[color,box-shadow] outline-none placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
                      required
                    />
                    <FieldDescription className="leading-5">
                      {t("使用Markdown编写公告内容")}
                    </FieldDescription>
                  </Field>
                </FieldGroup>

                <div className="mt-5 rounded-xl border bg-muted/20 p-3">
                  <div className="mb-3 flex items-center gap-2 text-xs font-medium text-muted-foreground">
                    <span className="flex size-6 items-center justify-center rounded-md bg-background">
                      <CalendarClockIcon
                        className="size-3.5"
                        aria-hidden="true"
                      />
                    </span>
                    <span>{t("公告级别")}</span>
                    <span aria-hidden="true">·</span>
                    <span>{t("公告过期时间")}</span>
                  </div>
                  <div className="grid gap-4 sm:grid-cols-2">
                    <Field className="min-w-0">
                      <FieldLabel>{t("公告级别")}</FieldLabel>
                      <AnnouncementSelector
                        label={t("公告级别")}
                        value={severity}
                        options={severityOptions}
                        className="w-full min-w-0"
                        onChange={(value) =>
                          setSeverity(value as AnnouncementSeverity)
                        }
                      />
                    </Field>
                    <AnnouncementExpirationField
                      value={expiresAt}
                      onChange={setExpiresAt}
                    />
                  </div>
                  <label className="mt-4 flex min-h-9 items-center gap-2 rounded-lg border border-transparent px-2 text-sm transition-colors hover:border-border hover:bg-background">
                    <input
                      type="checkbox"
                      checked={pinned}
                      onChange={(event) => setPinned(event.target.checked)}
                      className="size-4 accent-primary"
                    />
                    <span className="flex items-center gap-1.5">
                      <PinIcon
                        className="size-3.5 text-muted-foreground"
                        aria-hidden="true"
                      />
                      {t("是否置顶")}
                    </span>
                  </label>
                </div>

                <div className="mt-5 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
                  {editingId ? (
                    <Button
                      type="button"
                      variant="ghost"
                      className="sm:min-w-20"
                      onClick={resetForm}
                    >
                      {t("取消")}
                    </Button>
                  ) : null}
                  <Button
                    type="submit"
                    className="sm:min-w-32"
                    disabled={isSaving || !title.trim() || !body.trim()}
                  >
                    {editingId ? (
                      <CheckIcon data-icon="inline-start" />
                    ) : (
                      <PlusIcon data-icon="inline-start" />
                    )}
                    {editingId ? t("保存公告") : t("创建草稿")}
                  </Button>
                </div>
              </form>
            </CardContent>
          </Card>

          <section
            className="flex min-w-0 flex-col gap-3"
            aria-labelledby="announcement-list-title"
          >
            <Card className="min-w-0 gap-0 overflow-hidden py-0">
              <CardHeader className="border-b bg-muted/20 px-4 py-4 sm:px-5">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div className="min-w-0">
                    <CardTitle
                      id="announcement-list-title"
                      className="truncate text-base"
                    >
                      {scope === "global"
                        ? t("全局公告")
                        : selectedWorkspace
                          ? displayWorkspaceName(selectedWorkspace, t)
                          : t("工作空间公告")}
                    </CardTitle>
                  </div>
                  <div className="flex w-full items-center gap-2 sm:w-auto">
                    <Button
                      type="button"
                      size="sm"
                      className="flex-1 sm:flex-none"
                      onClick={startAdding}
                    >
                      <PlusIcon data-icon="inline-start" />
                      {t("添加公告")}
                    </Button>
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      className="flex-1 sm:flex-none"
                      onClick={() => void loadAnnouncements()}
                      disabled={isLoading}
                    >
                      <RefreshCwIcon
                        className={cn(isLoading && "animate-spin")}
                        data-icon="inline-start"
                      />
                      {t("刷新")}
                    </Button>
                  </div>
                </div>
              </CardHeader>
              <CardContent className="p-3 sm:p-4">
                {isLoading ? (
                  <div className="rounded-xl border border-dashed px-6 py-12 text-center text-sm text-muted-foreground">
                    {t("正在加载公告")}
                  </div>
                ) : items.length ? (
                  <div className="flex flex-col gap-2.5" role="list">
                    {items.map((item) => (
                      <article
                        key={item.id}
                        role="listitem"
                        className={cn(
                          "rounded-lg border bg-background/70 px-3 py-2 transition-[border-color,box-shadow] hover:border-foreground/20 hover:shadow-sm",
                          item.status === "archived" && "bg-muted/20"
                        )}
                      >
                        <div className="flex min-h-9 items-center gap-2">
                          <span
                            className={cn(
                              "size-2.5 shrink-0 rounded-full",
                              severityDotClass[item.severity]
                            )}
                            role="img"
                            aria-label={severityLabel(item.severity, t)}
                            title={severityLabel(item.severity, t)}
                          />
                          <button
                            type="button"
                            aria-haspopup="dialog"
                            className="min-w-0 flex-1 truncate py-1 text-left text-sm font-medium outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 sm:text-[0.9375rem]"
                            onClick={() => setSelectedAnnouncement(item)}
                          >
                            <span className="block truncate">{item.title}</span>
                          </button>
                          <div className="flex shrink-0 items-center gap-0.5">
                            {item.status !== "archived" ? (
                              <Button
                                type="button"
                                variant="ghost"
                                size="icon-sm"
                                aria-label={t("编辑")}
                                title={t("编辑")}
                                onClick={() => startEditing(item)}
                              >
                                <PencilIcon />
                              </Button>
                            ) : null}
                            {item.status === "draft" ? (
                              <Button
                                type="button"
                                variant="outline"
                                size="icon-sm"
                                aria-label={t("发布")}
                                title={t("发布")}
                                onClick={() =>
                                  void handleAction("publish", item)
                                }
                              >
                                <SendIcon />
                              </Button>
                            ) : null}
                            {item.status === "published" ? (
                              <Button
                                type="button"
                                variant="ghost"
                                size="icon-sm"
                                aria-label={t("归档")}
                                title={t("归档")}
                                onClick={() =>
                                  void handleAction("archive", item)
                                }
                              >
                                <ArchiveIcon />
                              </Button>
                            ) : null}
                            {item.status === "archived" ? (
                              <Button
                                type="button"
                                variant="destructive"
                                size="icon-sm"
                                aria-label={t("删除公告：{value}", {
                                  value: item.title,
                                })}
                                title={t("删除公告")}
                                disabled={deletingId === item.id}
                                onClick={() => void handleDelete(item)}
                              >
                                <Trash2Icon
                                  className={cn(
                                    deletingId === item.id && "animate-pulse"
                                  )}
                                />
                              </Button>
                            ) : null}
                          </div>
                        </div>
                      </article>
                    ))}
                    <SystemPagination
                      page={page}
                      pageSize={pageSize}
                      itemCount={items.length}
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
                  <div className="rounded-xl border border-dashed px-6 py-12 text-center text-sm text-muted-foreground">
                    {t("暂无公告")}
                  </div>
                )}
              </CardContent>
            </Card>
          </section>
        </div>

        <Dialog
          open={Boolean(selectedAnnouncement)}
          onOpenChange={(open) => {
            if (!open) setSelectedAnnouncement(null)
          }}
        >
          <DialogContent className="max-h-[min(80svh,48rem)] gap-0 overflow-hidden p-0 sm:max-w-3xl">
            {selectedAnnouncement ? (
              <>
                <DialogHeader className="border-b px-6 py-5">
                  <DialogTitle className="pr-6 text-xl leading-snug">
                    {selectedAnnouncement.title}
                  </DialogTitle>
                  <DialogDescription className="mt-2 flex flex-wrap items-center gap-2">
                    <Badge variant={statusVariant(selectedAnnouncement.status)}>
                      {statusLabel(selectedAnnouncement.status, t)}
                    </Badge>
                    <Badge variant="secondary">
                      {severityLabel(selectedAnnouncement.severity, t)}
                    </Badge>
                    {selectedAnnouncement.pinned ? (
                      <Badge variant="outline">{t("置顶")}</Badge>
                    ) : null}
                    <span>
                      {new Intl.DateTimeFormat(language, {
                        dateStyle: "medium",
                        timeStyle: "short",
                      }).format(new Date(selectedAnnouncement.updated_at))}
                    </span>
                  </DialogDescription>
                </DialogHeader>
                <div className="min-h-0 overflow-y-auto px-6 py-5">
                  <MarkdownContent content={selectedAnnouncement.body} />
                </div>
                <DialogFooter className="border-t px-6 py-4">
                  <Button
                    type="button"
                    variant="outline"
                    onClick={() => setSelectedAnnouncement(null)}
                  >
                    {t("关闭")}
                  </Button>
                </DialogFooter>
              </>
            ) : null}
          </DialogContent>
        </Dialog>
      </div>
      {confirmDialog}
    </>
  )
}
