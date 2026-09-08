"use client"

import * as React from "react"
import {
  ArchiveIcon,
  CheckIcon,
  ChevronDownIcon,
  MegaphoneIcon,
  PencilIcon,
  PlusIcon,
  SendIcon,
} from "lucide-react"
import { useRouter } from "next/navigation"

import { MarkdownContent } from "@/components/knowledge/markdown-content"
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
import { useLanguage } from "@/contexts/language-provider"
import { useSession } from "@/contexts/session-context"
import {
  archiveAnnouncement,
  createAnnouncement,
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

function statusVariant(status: Announcement["status"]) {
  if (status === "published") return "default" as const
  if (status === "archived") return "outline" as const
  return "secondary" as const
}

function AnnouncementSelector({
  label,
  value,
  options,
  onChange,
}: {
  label: string
  value: string
  options: Array<{ value: string; label: string }>
  onChange: (value: string) => void
}) {
  const selected =
    options.find((option) => option.value === value) ?? options[0]
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          type="button"
          variant="outline"
          className="min-w-44 justify-between"
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
  const [isLoading, setIsLoading] = React.useState(true)
  const [isSaving, setIsSaving] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)
  const [editingId, setEditingId] = React.useState<string | null>(null)
  const [selectedAnnouncement, setSelectedAnnouncement] =
    React.useState<Announcement | null>(null)
  const [title, setTitle] = React.useState("")
  const [body, setBody] = React.useState("")
  const [severity, setSeverity] = React.useState<AnnouncementSeverity>("info")
  const [pinned, setPinned] = React.useState(false)

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
        effectiveWorkspaceId
      )
      setItems(result.items)
    } catch (cause) {
      setError(getErrorMessage(cause, t))
    } finally {
      setIsLoading(false)
    }
  }, [
    effectiveWorkspaceId,
    isGlobalAdmin,
    isWorkspaceAdmin,
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
  }

  const startAdding = () => {
    resetForm()
    titleInputRef.current?.scrollIntoView({
      behavior: "smooth",
      block: "center",
    })
    window.requestAnimationFrame(() => titleInputRef.current?.focus())
  }

  const startEditing = (item: Announcement) => {
    setEditingId(item.id)
    setTitle(item.title)
    setBody(item.body)
    setSeverity(item.severity)
    setPinned(item.pinned)
    window.scrollTo({ top: 0, behavior: "smooth" })
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
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-semibold tracking-tight">
            <MegaphoneIcon className="size-6" />
            {t("公告管理")}
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            {t("管理全局和工作空间公告。")}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {isGlobalAdmin ? (
            <AnnouncementSelector
              label={t("切换公告范围")}
              value={scope}
              options={scopeOptions}
              onChange={(value) => {
                setRequestedScope(value as AnnouncementScope)
                resetForm()
              }}
            />
          ) : null}
          {scope === "workspace" ? (
            <AnnouncementSelector
              label={t("工作空间")}
              value={effectiveWorkspaceId ?? ""}
              options={workspaceOptions}
              onChange={(value) => {
                setWorkspaceId(value)
                resetForm()
              }}
            />
          ) : null}
        </div>
      </div>

      {error ? (
        <div className="rounded-lg border border-destructive/40 bg-destructive/5 px-4 py-3 text-sm text-destructive">
          {t("无法加载公告")}：{error}
        </div>
      ) : null}

      <Card>
        <CardHeader>
          <CardTitle>{editingId ? t("保存公告") : t("新建公告")}</CardTitle>
          <CardDescription>
            {t("草稿发布后会实时推送给可见范围内的用户。")}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form className="flex flex-col gap-5" onSubmit={handleSave}>
            <FieldGroup>
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
                <FieldLabel htmlFor="announcement-body">
                  {t("公告正文")}
                </FieldLabel>
                <textarea
                  id="announcement-body"
                  value={body}
                  onChange={(event) => setBody(event.target.value)}
                  placeholder={t("使用Markdown编写公告内容")}
                  className="min-h-36 w-full resize-y rounded-lg border border-input bg-transparent px-3 py-2 text-sm shadow-xs transition-[color,box-shadow] outline-none placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
                  required
                />
                <FieldDescription>
                  {t("使用Markdown编写公告内容")}
                </FieldDescription>
              </Field>
            </FieldGroup>
            <div className="flex flex-wrap items-end gap-4">
              <Field>
                <FieldLabel>{t("公告级别")}</FieldLabel>
                <AnnouncementSelector
                  label={t("公告级别")}
                  value={severity}
                  options={severityOptions}
                  onChange={(value) =>
                    setSeverity(value as AnnouncementSeverity)
                  }
                />
              </Field>
              <label className="flex h-9 items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={pinned}
                  onChange={(event) => setPinned(event.target.checked)}
                  className="size-4 accent-primary"
                />
                {t("是否置顶")}
              </label>
              <div className="ml-auto flex items-center gap-2">
                {editingId ? (
                  <Button type="button" variant="ghost" onClick={resetForm}>
                    {t("取消")}
                  </Button>
                ) : null}
                <Button
                  type="submit"
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
            </div>
          </form>
        </CardContent>
      </Card>

      <section className="flex w-full max-w-6xl flex-col gap-3">
        <div className="flex items-center justify-between gap-3">
          <h2 className="text-lg font-semibold">
            {scope === "global"
              ? t("全局公告")
              : selectedWorkspace
                ? displayWorkspaceName(selectedWorkspace, t)
                : t("工作空间公告")}
          </h2>
          <div className="flex items-center gap-2">
            <Button type="button" size="sm" onClick={startAdding}>
              <PlusIcon data-icon="inline-start" />
              {t("添加公告")}
            </Button>
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="h-9"
              onClick={() => void loadAnnouncements()}
              disabled={isLoading}
            >
              {t("刷新")}
            </Button>
          </div>
        </div>
        {isLoading ? (
          <div className="rounded-xl border border-dashed px-6 py-12 text-center text-sm text-muted-foreground">
            {t("正在加载公告")}
          </div>
        ) : items.length ? (
          <div className="flex flex-col gap-2">
            {items.map((item) => (
              <Card
                key={item.id}
                className={cn(
                  "border-border/70 py-0 shadow-sm transition-[border-color,box-shadow,opacity] hover:border-foreground/20 hover:shadow-md",
                  item.status === "archived" && "opacity-70"
                )}
              >
                <CardContent className="p-0">
                  <div className="flex items-center gap-4 px-5 py-4 sm:px-6">
                    <button
                      type="button"
                      aria-haspopup="dialog"
                      className="flex min-w-0 flex-1 items-center gap-3 text-left outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
                      onClick={() => setSelectedAnnouncement(item)}
                    >
                      <span
                        aria-hidden="true"
                        className={cn(
                          "size-2 shrink-0 rounded-full",
                          item.severity === "critical"
                            ? "bg-destructive"
                            : item.severity === "warning"
                              ? "bg-amber-500"
                              : "bg-sky-500"
                        )}
                      />
                      <span className="min-w-0 flex-1">
                        <span className="flex flex-wrap items-center gap-2">
                          <span className="truncate text-sm font-semibold sm:text-base">
                            {item.title}
                          </span>
                          <Badge
                            variant={statusVariant(item.status)}
                            className="rounded-full"
                          >
                            {t(
                              item.status === "draft"
                                ? "草稿"
                                : item.status === "published"
                                  ? "已发布"
                                  : "已归档"
                            )}
                          </Badge>
                          {item.pinned ? (
                            <Badge variant="outline" className="rounded-full">
                              {t("置顶")}
                            </Badge>
                          ) : null}
                        </span>
                        <span className="mt-1 block text-xs text-muted-foreground">
                          {new Intl.DateTimeFormat(language, {
                            dateStyle: "medium",
                            timeStyle: "short",
                          }).format(new Date(item.updated_at))}
                        </span>
                      </span>
                    </button>
                    <div className="flex shrink-0 items-center gap-1">
                      {item.status !== "archived" ? (
                        <Button
                          type="button"
                          variant="ghost"
                          size="sm"
                          onClick={() => startEditing(item)}
                          className="h-8 px-2"
                        >
                          <PencilIcon data-icon="inline-start" />
                          {t("编辑")}
                        </Button>
                      ) : null}
                      {item.status === "draft" ? (
                        <Button
                          type="button"
                          variant="outline"
                          size="sm"
                          onClick={() => void handleAction("publish", item)}
                          className="h-8 px-2.5"
                        >
                          <SendIcon data-icon="inline-start" />
                          {t("发布")}
                        </Button>
                      ) : null}
                      {item.status === "published" ? (
                        <Button
                          type="button"
                          variant="ghost"
                          size="sm"
                          onClick={() => void handleAction("archive", item)}
                          className="h-8 px-2"
                        >
                          <ArchiveIcon data-icon="inline-start" />
                          {t("归档")}
                        </Button>
                      ) : null}
                    </div>
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        ) : (
          <div className="rounded-xl border border-dashed px-6 py-12 text-center text-sm text-muted-foreground">
            {t("暂无公告")}
          </div>
        )}
      </section>
      <Dialog
        open={Boolean(selectedAnnouncement)}
        onOpenChange={(open) => {
          if (!open) setSelectedAnnouncement(null)
        }}
      >
        <DialogContent className="max-h-[min(80svh,48rem)] gap-0 overflow-hidden p-0 sm:max-w-2xl">
          {selectedAnnouncement ? (
            <>
              <DialogHeader className="border-b px-6 py-5">
                <DialogTitle className="pr-6 text-xl leading-snug">
                  {selectedAnnouncement.title}
                </DialogTitle>
                <DialogDescription className="mt-2 flex flex-wrap items-center gap-2">
                  <Badge variant={statusVariant(selectedAnnouncement.status)}>
                    {t(
                      selectedAnnouncement.status === "draft"
                        ? "草稿"
                        : selectedAnnouncement.status === "published"
                          ? "已发布"
                          : "已归档"
                    )}
                  </Badge>
                  <Badge variant="secondary">
                    {t(
                      selectedAnnouncement.severity === "info"
                        ? "信息"
                        : selectedAnnouncement.severity === "warning"
                          ? "警告"
                          : "严重"
                    )}
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
  )
}
