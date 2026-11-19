"use client"

import * as React from "react"
import Link from "next/link"
import {
  ChevronDownIcon,
  LoaderCircleIcon,
  PlusIcon,
  Trash2Icon,
} from "lucide-react"
import { useLanguage } from "@/contexts/language-provider"
import { useSession } from "@/contexts/session-context"
import { useConfirmDialog } from "@/components/app/confirm-dialog"
import { OperationNotification } from "@/components/app/operation-notification"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
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
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import {
  getMemoryProfile,
  listMemoryProjects,
  updateMemoryPreferences,
  saveUserMemory,
  deleteUserMemory,
  type MemoryCategory,
  type MemoryDraft,
  type MemoryProfile,
  type MemoryProject,
  type UserMemory,
} from "@/lib/api/memories"
import { publicChatUrl } from "@/lib/api/public-chat-projects"
import { getErrorMessage } from "@/lib/errors"
import type { AppNotification } from "@/lib/notifications"
import { languageLocales, type TranslationKey } from "@/i18n"

const categories: Record<MemoryCategory, TranslationKey> = {
  preference: "沟通与工作偏好",
  background: "明确背景",
  goal: "长期目标",
  project: "项目记忆",
}
const emptyDraft: MemoryDraft = {
  category: "preference",
  key: "",
  content: "",
  project_id: "",
  expires_at: null,
}

function Choice({
  label,
  children,
  disabled,
}: {
  label: string
  children: React.ReactNode
  disabled?: boolean
}) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          type="button"
          variant="outline"
          disabled={disabled}
          className="w-full justify-between"
        >
          {label}
          <ChevronDownIcon />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent className="max-w-80">{children}</DropdownMenuContent>
    </DropdownMenu>
  )
}

export function UserMemoryPage() {
  const { token, selectedWorkspaceId } = useSession()
  return (
    <MemoryPageContent
      key={`${selectedWorkspaceId ?? ""}:${token ?? ""}`}
      workspaceId={selectedWorkspaceId}
    />
  )
}

function MemoryPageContent({ workspaceId }: { workspaceId: string | null }) {
  const { t, language } = useLanguage()
  const { token, isSessionRestored } = useSession()
  const [state, setState] = React.useState<{
    token: string | null
    workspaceId: string
    profile: MemoryProfile
    projects: MemoryProject[]
  } | null>(null)
  const profile =
    state?.token === token && state.workspaceId === workspaceId
      ? state.profile
      : null
  const projects =
    state?.token === token && state.workspaceId === workspaceId
      ? state.projects
      : []
  const [loadError, setLoadError] = React.useState<string | null>(null)
  const [attempt, retry] = React.useReducer((value) => value + 1, 0)
  const [busy, setBusy] = React.useState(false)
  const [notification, setNotification] =
    React.useState<AppNotification | null>(null)
  const [editor, setEditor] = React.useState<{
    id?: string
    draft: MemoryDraft
  } | null>(null)
  const [confirm, confirmDialog] = useConfirmDialog()

  React.useEffect(() => {
    if (!token || !workspaceId) return
    const controller = new AbortController()
    Promise.all([
      getMemoryProfile(workspaceId, token, controller.signal),
      listMemoryProjects(workspaceId, token, controller.signal),
    ])
      .then(([profile, { items }]) => {
        if (!controller.signal.aborted) {
          setState({ token, workspaceId, profile, projects: items })
          setLoadError(null)
        }
      })
      .catch((error) => {
        if (!controller.signal.aborted) setLoadError(getErrorMessage(error, t))
      })
    return () => controller.abort()
  }, [workspaceId, token, attempt, t])

  async function mutate(action: () => Promise<MemoryProfile | void>) {
    if (!token || busy) return false
    setBusy(true)
    try {
      const updated = await action()
      const next = updated ?? (await getMemoryProfile(workspaceId!, token))
      setState((current) =>
        current?.token === token && current.workspaceId === workspaceId
          ? { ...current, profile: next }
          : current
      )
      setNotification({
        id: Date.now(),
        kind: "success",
        message: t("记忆设置已更新"),
      })
      return true
    } catch (error) {
      setNotification({
        id: Date.now(),
        kind: "error",
        message: getErrorMessage(error, t),
      })
      return false
    } finally {
      setBusy(false)
    }
  }

  async function remove(item?: UserMemory) {
    if (!token || busy) return
    const accepted = await confirm({
      title: item ? t("删除记忆") : t("清空全部记忆"),
      description: t("删除后将不再用于后续回答和推荐，历史对话仍会保留。"),
      destructive: true,
    })
    if (accepted)
      await mutate(() => deleteUserMemory(workspaceId!, token, item?.id))
  }

  async function save(event: React.FormEvent) {
    event.preventDefault()
    if (!token || !editor || busy) return
    if (
      await mutate(() =>
        saveUserMemory(workspaceId!, token, editor.draft, editor.id)
      )
    )
      setEditor(null)
  }

  function change(patch: Partial<MemoryDraft>) {
    setEditor((current) =>
      current ? { ...current, draft: { ...current.draft, ...patch } } : current
    )
  }

  return (
    <main className="mx-auto flex min-h-dvh max-w-3xl flex-col gap-6 px-4 py-6 sm:px-6">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-lg font-semibold">{t("记忆与个性化")}</h1>
        <Button
          variant="outline"
          disabled={!profile || busy}
          onClick={() => retry()}
        >
          {t("刷新")}
        </Button>
      </header>
      <p className="text-sm text-muted-foreground">
        {t(
          "记忆在当前工作空间的 Agent 之间共享，画像由下方条目汇总。当前要求优先于历史偏好。"
        )}
      </p>
      {!isSessionRestored || (token && !profile && !loadError) ? (
        <p role="status" className="flex items-center gap-2 text-sm">
          <LoaderCircleIcon className="size-4 animate-spin" />
          {t("正在加载")}
        </p>
      ) : !token ? (
        <Link href="/login" className="text-sm underline">
          {t("请先登录")}
        </Link>
      ) : !workspaceId ? (
        <p role="status" className="text-sm text-muted-foreground">
          {t("当前没有可用工作空间")}
        </p>
      ) : loadError ? (
        <div role="alert" className="text-sm text-destructive">
          {loadError}
          <Button variant="ghost" onClick={() => retry()}>
            {t("重试")}
          </Button>
        </div>
      ) : null}
      {profile && (
        <>
          <section
            className="space-y-4 rounded-xl border p-4"
            aria-label={t("记忆设置")}
          >
            <label className="flex items-center justify-between gap-4 text-sm">
              <span>
                {t("使用长期记忆")}
                <span className="mt-1 block text-xs text-muted-foreground">
                  {t("用于后续回答和相关问题推荐，关闭后暂停读取和更新。")}
                </span>
              </span>
              <input
                type="checkbox"
                className="size-4 shrink-0 accent-primary"
                checked={profile.enabled}
                disabled={busy}
                onChange={(event) =>
                  void mutate(() =>
                    updateMemoryPreferences(workspaceId!, token!, {
                      enabled: event.target.checked,
                      automatic: profile.automatic,
                    })
                  )
                }
              />
            </label>
            <label className="flex items-center justify-between gap-4 text-sm">
              <span>
                {t("自动记忆")}
                <span className="mt-1 block text-xs text-muted-foreground">
                  {t(
                    "开启后在后台提取明确、稳定的信息；关闭时仍可手动添加或明确要求记住。"
                  )}
                </span>
              </span>
              <input
                type="checkbox"
                className="size-4 shrink-0 accent-primary"
                checked={profile.automatic}
                disabled={busy || !profile.enabled}
                onChange={(event) =>
                  void mutate(() =>
                    updateMemoryPreferences(workspaceId!, token!, {
                      enabled: profile.enabled,
                      automatic: event.target.checked,
                    })
                  )
                }
              />
            </label>
          </section>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h2 className="text-sm font-medium">{t("我的记忆画像")}</h2>
            <div className="flex gap-2">
              <Button
                variant="ghost"
                disabled={busy || !profile.items.length}
                onClick={() => void remove()}
              >
                <Trash2Icon />
                {t("清空全部记忆")}
              </Button>
              <Button
                disabled={busy}
                onClick={() => setEditor({ draft: { ...emptyDraft } })}
              >
                <PlusIcon />
                {t("添加记忆")}
              </Button>
            </div>
          </div>
          {!profile.items.length && (
            <p className="py-8 text-center text-sm text-muted-foreground">
              {t("暂无长期记忆，可以手动添加，或在对话中明确要求记住。")}
            </p>
          )}
          {(Object.keys(categories) as MemoryCategory[]).map((category) => {
            const items = profile.items.filter(
              (item) => item.category === category
            )
            if (!items.length) return null
            return (
              <section key={category} className="space-y-2">
                <h3 className="text-xs font-medium text-muted-foreground">
                  {t(categories[category])}
                </h3>
                <div className="divide-y rounded-xl border">
                  {items.map((item) => (
                    <article key={item.id} className="min-w-0 space-y-2 p-4">
                      <div className="flex items-start justify-between gap-3">
                        <div className="min-w-0">
                          <p className="text-sm font-medium break-words">
                            {item.key}
                          </p>
                          <p className="mt-1 text-sm break-words whitespace-pre-wrap">
                            {item.content}
                          </p>
                        </div>
                        <div className="flex shrink-0 gap-1">
                          <Button
                            variant="ghost"
                            size="sm"
                            disabled={busy}
                            aria-label={t("编辑记忆：{key}", { key: item.key })}
                            onClick={() =>
                              setEditor({
                                id: item.id,
                                draft: {
                                  category: item.category,
                                  key: item.key,
                                  content: item.content,
                                  project_id: item.project_id,
                                  expires_at: item.expires_at,
                                },
                              })
                            }
                          >
                            {t("编辑")}
                          </Button>
                          <Button
                            variant="ghost"
                            size="icon-sm"
                            disabled={busy}
                            aria-label={t("删除记忆：{key}", { key: item.key })}
                            onClick={() => void remove(item)}
                          >
                            <Trash2Icon />
                          </Button>
                        </div>
                      </div>
                      <p className="text-xs text-muted-foreground">
                        {item.project_id
                          ? (projects.find(
                              (project) => project.id === item.project_id
                            )?.name ?? t("项目记忆"))
                          : t("个人记忆")}{" "}
                        ·{" "}
                        {t(
                          item.origin === "manual"
                            ? "手动添加"
                            : item.origin === "explicit"
                              ? "明确要求记住"
                              : "自动提取"
                        )}
                        {item.expires_at
                          ? ` · ${new Date(item.expires_at).toLocaleDateString(languageLocales[language])} ${t(new Date(item.expires_at).getTime() <= Date.now() ? "已过期" : "到期")}`
                          : ""}
                      </p>
                      {item.source_quote && (
                        <details className="text-xs text-muted-foreground">
                          <summary className="cursor-pointer">
                            {t("查看记忆来源")}
                          </summary>
                          <p className="mt-2 break-words whitespace-pre-wrap">
                            {item.source_quote}
                          </p>
                          {item.source_conversation_id && item.source_agent_id && (
                            <Link
                              className="mt-2 inline-block underline"
                              href={publicChatUrl(
                                item.source_agent_id,
                                item.source_conversation_id,
                                item.project_id || null
                              )}
                            >
                              {t("打开来源对话")}
                            </Link>
                          )}
                        </details>
                      )}
                    </article>
                  ))}
                </div>
              </section>
            )
          })}
        </>
      )}
      <Dialog
        open={editor !== null}
        onOpenChange={(open) => {
          if (!open && !busy) setEditor(null)
        }}
      >
        <DialogContent className="max-h-[90dvh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>
              {editor?.id ? t("编辑记忆") : t("添加记忆")}
            </DialogTitle>
            <DialogDescription>
              {t("只记录希望在后续对话中复用的信息，请勿填写密码或密钥。")}
            </DialogDescription>
          </DialogHeader>
          {editor && (
            <form className="space-y-4" onSubmit={save}>
              <label className="block space-y-1 text-sm">
                <span>{t("记忆主题")}</span>
                <Input
                  value={editor.draft.key}
                  maxLength={80}
                  required
                  disabled={busy}
                  onChange={(event) => change({ key: event.target.value })}
                />
              </label>
              <label className="block space-y-1 text-sm">
                <span>{t("记忆内容")}</span>
                <textarea
                  className="min-h-28 w-full rounded-lg border bg-transparent p-3 text-sm focus-visible:ring-2 focus-visible:ring-ring"
                  value={editor.draft.content}
                  maxLength={600}
                  required
                  disabled={busy}
                  onChange={(event) => change({ content: event.target.value })}
                />
              </label>
              <div className="space-y-1 text-sm">
                <span>{t("记忆分类")}</span>
                <Choice
                  label={t(categories[editor.draft.category])}
                  disabled={busy}
                >
                  {(Object.keys(categories) as MemoryCategory[]).map(
                    (category) => (
                      <DropdownMenuItem
                        key={category}
                        disabled={category === "project" && !projects.length}
                        onSelect={() =>
                          change({
                            category,
                            ...(category === "project" &&
                            !editor.draft.project_id
                              ? { project_id: projects[0]?.id ?? "" }
                              : {}),
                          })
                        }
                      >
                        {t(categories[category])}
                      </DropdownMenuItem>
                    )
                  )}
                </Choice>
              </div>
              <div className="space-y-1 text-sm">
                <span>{t("适用范围")}</span>
                <Choice
                  label={
                    editor.draft.project_id
                      ? (projects.find(
                          (project) => project.id === editor.draft.project_id
                        )?.name ?? t("项目记忆"))
                      : t("个人记忆")
                  }
                  disabled={busy}
                >
                  <DropdownMenuItem
                    disabled={editor.draft.category === "project"}
                    onSelect={() => change({ project_id: "" })}
                  >
                    {t("个人记忆")}
                  </DropdownMenuItem>
                  {projects.map((project) => (
                    <DropdownMenuItem
                      key={project.id}
                      onSelect={() => change({ project_id: project.id })}
                    >
                      {project.name}
                    </DropdownMenuItem>
                  ))}
                </Choice>
              </div>
              <div className="space-y-1 text-sm">
                <span>{t("有效期")}</span>
                <Choice
                  label={
                    editor.draft.expires_at
                      ? new Date(editor.draft.expires_at).toLocaleDateString(
                          languageLocales[language]
                        )
                      : t("长期保留")
                  }
                  disabled={busy}
                >
                  <DropdownMenuItem
                    onSelect={() => change({ expires_at: null })}
                  >
                    {t("长期保留")}
                  </DropdownMenuItem>
                  {[30, 90].map((days) => (
                    <DropdownMenuItem
                      key={days}
                      onSelect={() =>
                        change({
                          expires_at: new Date(
                            Date.now() + days * 86400000
                          ).toISOString(),
                        })
                      }
                    >
                      {t("{days} 天", { days })}
                    </DropdownMenuItem>
                  ))}
                </Choice>
              </div>
              <DialogFooter>
                <Button
                  type="button"
                  variant="outline"
                  disabled={busy}
                  onClick={() => setEditor(null)}
                >
                  {t("取消")}
                </Button>
                <Button
                  type="submit"
                  disabled={
                    busy ||
                    !editor.draft.key.trim() ||
                    !editor.draft.content.trim()
                  }
                >
                  {busy && <LoaderCircleIcon className="animate-spin" />}
                  {t("保存")}
                </Button>
              </DialogFooter>
            </form>
          )}
        </DialogContent>
      </Dialog>
      {confirmDialog}
      <OperationNotification
        notification={notification}
        onDismiss={() => setNotification(null)}
      />
    </main>
  )
}
