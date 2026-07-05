import * as React from "react"
import {
  ArchiveIcon,
  ArrowLeftIcon,
  ArrowUpDownIcon,
  ChevronDownIcon,
  FileTextIcon,
  FilterIcon,
  HelpCircleIcon,
  LoaderCircleIcon,
  MoreHorizontalIcon,
  PencilIcon,
  PlusIcon,
  RotateCcwIcon,
  SearchIcon,
  SettingsIcon,
  SlidersHorizontalIcon,
  TagIcon,
  TargetIcon,
  Trash2Icon,
  UploadIcon,
  UsersIcon,
} from "lucide-react"
import { useLanguage } from "@/components/language-provider"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import {
  createKnowledgeBase,
  deleteKnowledgeBase,
  listKnowledgeBasePermissions,
  listKnowledgeBases,
  listWorkspaceMembers,
  revokeKnowledgeBasePermission,
  type KnowledgeBase,
  type MeResponse,
  type ResourcePermission,
  type WorkspaceMember,
  updateKnowledgeBase,
  upsertKnowledgeBasePermission,
} from "@/lib/api"
import { type FeaturePageConfig } from "@/lib/pages"
import { languageLocales } from "@/lib/i18n"
import { cn } from "@/lib/utils"
import { formatDateTime, getMembershipRole } from "@/app/display"
import { getErrorMessage } from "@/app/errors"
import type { AppNotification } from "@/app/notifications"
import { KnowledgeBaseDialogs } from "@/features/knowledge/knowledge-base-dialogs"
import {
  PermissionBadge,
  StatusBadge,
} from "@/features/knowledge/status-badges"
import type {
  KnowledgeBaseDetailTab,
  KnowledgeBaseEditForm,
  KnowledgeBaseForm,
  KnowledgeBasePermissionForm,
} from "@/features/knowledge/types"

export function KnowledgeBasePage({
  page,
  token,
  me,
  selectedWorkspaceId,
  onNotify,
}: {
  page: FeaturePageConfig
  token: string
  me: MeResponse
  selectedWorkspaceId: string | null
  onNotify: (kind: AppNotification["kind"], message: string) => void
}) {
  const { language, t } = useLanguage()
  const locale = languageLocales[language]
  const [knowledgeBases, setKnowledgeBases] = React.useState<KnowledgeBase[]>(
    []
  )
  const [workspaceMembers, setWorkspaceMembers] = React.useState<
    WorkspaceMember[]
  >([])
  const [permissions, setPermissions] = React.useState<ResourcePermission[]>([])
  const [selectedKnowledgeBaseId, setSelectedKnowledgeBaseId] = React.useState<
    string | null
  >(null)
  const [activeDetailTab, setActiveDetailTab] =
    React.useState<KnowledgeBaseDetailTab>("documents")
  const [form, setForm] = React.useState<KnowledgeBaseForm>({
    name: "",
    description: "",
  })
  const [editForm, setEditForm] = React.useState<KnowledgeBaseEditForm | null>(
    null
  )
  const [permissionForm, setPermissionForm] =
    React.useState<KnowledgeBasePermissionForm | null>(null)
  const [error, setError] = React.useState<string | null>(null)
  const [isLoading, setIsLoading] = React.useState(false)
  const [isSaving, setIsSaving] = React.useState(false)
  const [isDialogOpen, setIsDialogOpen] = React.useState(false)

  const workspaceRole = getMembershipRole(me, selectedWorkspaceId)
  const Icon = page.icon
  const selectedKnowledgeBase =
    knowledgeBases.find((item) => item.id === selectedKnowledgeBaseId) ?? null

  const reportError = React.useCallback(
    (error: unknown) => {
      const message = getErrorMessage(error, t)
      setError(message)
      onNotify("error", message)
      return message
    },
    [onNotify, t]
  )

  const loadKnowledgeBases = React.useCallback(async () => {
    if (!selectedWorkspaceId) {
      setKnowledgeBases([])
      setSelectedKnowledgeBaseId(null)
      return
    }

    setError(null)
    setIsLoading(true)
    try {
      setKnowledgeBases(await listKnowledgeBases(token, selectedWorkspaceId))
    } catch (error) {
      setKnowledgeBases([])
      reportError(error)
    } finally {
      setIsLoading(false)
    }
  }, [reportError, selectedWorkspaceId, token])

  React.useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void loadKnowledgeBases()
  }, [loadKnowledgeBases])

  function canManagePermissions(knowledgeBase: KnowledgeBase) {
    return (
      workspaceRole === "admin" ||
      knowledgeBase.created_by_user_id === me.user.id
    )
  }

  function resetForm() {
    setForm({ name: "", description: "" })
    setError(null)
  }

  function updateKnowledgeBaseInList(knowledgeBase: KnowledgeBase) {
    setKnowledgeBases((current) =>
      current.map((item) =>
        item.id === knowledgeBase.id ? knowledgeBase : item
      )
    )
  }

  function openKnowledgeBase(knowledgeBase: KnowledgeBase) {
    setActiveDetailTab("documents")
    setSelectedKnowledgeBaseId(knowledgeBase.id)
  }

  async function handleCreate(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!selectedWorkspaceId) {
      return
    }

    setIsSaving(true)
    setError(null)
    try {
      const knowledgeBase = await createKnowledgeBase(
        token,
        selectedWorkspaceId,
        form
      )
      setKnowledgeBases((current) => [...current, knowledgeBase])
      resetForm()
      setIsDialogOpen(false)
      onNotify("success", "知识库已新建")
    } catch (error) {
      reportError(error)
    } finally {
      setIsSaving(false)
    }
  }

  async function handleUpdate(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!selectedWorkspaceId || !editForm) {
      return
    }

    setIsSaving(true)
    setError(null)
    try {
      updateKnowledgeBaseInList(
        await updateKnowledgeBase(token, selectedWorkspaceId, editForm.id, {
          name: editForm.name,
          description: editForm.description,
        })
      )
      setEditForm(null)
      onNotify("success", "知识库已更新")
    } catch (error) {
      reportError(error)
    } finally {
      setIsSaving(false)
    }
  }

  async function handleToggleStatus(knowledgeBase: KnowledgeBase) {
    if (!selectedWorkspaceId) {
      return
    }

    const nextStatus = knowledgeBase.status === "active" ? "archived" : "active"
    setError(null)
    try {
      updateKnowledgeBaseInList(
        await updateKnowledgeBase(
          token,
          selectedWorkspaceId,
          knowledgeBase.id,
          {
            status: nextStatus,
          }
        )
      )
      onNotify(
        "success",
        nextStatus === "active" ? "知识库已恢复" : "知识库已归档"
      )
    } catch (error) {
      reportError(error)
    }
  }

  async function handleDelete(knowledgeBase: KnowledgeBase) {
    if (!selectedWorkspaceId) {
      return
    }

    if (
      !window.confirm(
        t("永久删除 {name}？此操作不可恢复。", { name: knowledgeBase.name })
      )
    ) {
      return
    }

    setError(null)
    try {
      await deleteKnowledgeBase(token, selectedWorkspaceId, knowledgeBase.id)
      setKnowledgeBases((current) =>
        current.filter((item) => item.id !== knowledgeBase.id)
      )
      if (selectedKnowledgeBaseId === knowledgeBase.id) {
        setSelectedKnowledgeBaseId(null)
      }
      onNotify("success", "知识库已删除")
    } catch (error) {
      reportError(error)
    }
  }

  async function handleOpenPermissions(knowledgeBase: KnowledgeBase) {
    if (!selectedWorkspaceId) {
      return
    }

    setError(null)
    try {
      const [members, grants] = await Promise.all([
        listWorkspaceMembers(token, selectedWorkspaceId),
        listKnowledgeBasePermissions(
          token,
          selectedWorkspaceId,
          knowledgeBase.id
        ),
      ])
      const firstTarget = members.find(
        (member) => member.user.id !== me.user.id
      )
      setWorkspaceMembers(members)
      setPermissions(grants)
      setPermissionForm({
        knowledgeBase,
        userId: firstTarget?.user.id ?? "",
        permission: "view",
      })
    } catch (error) {
      reportError(error)
    }
  }

  async function handleGrantPermission(
    event: React.FormEvent<HTMLFormElement>
  ) {
    event.preventDefault()
    if (!selectedWorkspaceId || !permissionForm || !permissionForm.userId) {
      return
    }

    const currentPermissionForm = permissionForm
    setIsSaving(true)
    setError(null)
    try {
      const grant = await upsertKnowledgeBasePermission(
        token,
        selectedWorkspaceId,
        currentPermissionForm.knowledgeBase.id,
        currentPermissionForm.userId,
        currentPermissionForm.permission
      )
      setPermissions((current) => [
        ...current.filter((item) => item.user.id !== grant.user.id),
        grant,
      ])
      onNotify("success", "授权已保存")
    } catch (error) {
      reportError(error)
    } finally {
      setIsSaving(false)
    }
  }

  async function handleRevokePermission(userId: string) {
    if (!selectedWorkspaceId || !permissionForm) {
      return
    }

    setError(null)
    try {
      await revokeKnowledgeBasePermission(
        token,
        selectedWorkspaceId,
        permissionForm.knowledgeBase.id,
        userId
      )
      setPermissions((current) =>
        current.filter((item) => item.user.id !== userId)
      )
      onNotify("success", "授权已撤销")
    } catch (error) {
      reportError(error)
    }
  }

  const shareTargets = workspaceMembers.filter(
    (member) => member.user.id !== me.user.id
  )
  const detailTabs: Array<{
    key: KnowledgeBaseDetailTab
    label: string
    icon: React.ElementType
  }> = [
    { key: "documents", label: "文档", icon: FileTextIcon },
    { key: "questions", label: "问题", icon: HelpCircleIcon },
    { key: "hit-test", label: "命中测试", icon: TargetIcon },
    { key: "settings", label: "设置", icon: SettingsIcon },
  ]

  if (selectedKnowledgeBase) {
    return (
      <>
        {error ? <p className="text-sm text-destructive">{error}</p> : null}

        <div className="-mx-4 grid min-h-[calc(100svh-6.5rem)] grid-cols-1 overflow-hidden border-y bg-background sm:-mx-6 lg:-mx-8 lg:grid-cols-[220px_minmax(0,1fr)]">
          <aside className="border-b bg-muted/30 p-3 lg:border-r lg:border-b-0 lg:p-4">
            <div className="mb-6 flex items-center gap-2">
              <Button
                type="button"
                variant="ghost"
                size="icon-sm"
                aria-label="返回"
                onClick={() => setSelectedKnowledgeBaseId(null)}
              >
                <ArrowLeftIcon />
              </Button>
              <span className="flex size-8 items-center justify-center rounded-lg bg-primary text-primary-foreground">
                <FileTextIcon className="size-4" />
              </span>
              <span className="min-w-0 truncate text-sm font-semibold">
                {selectedKnowledgeBase.name}
              </span>
            </div>
            <nav className="flex gap-2 overflow-x-auto lg:flex-col lg:overflow-visible">
              {detailTabs.map((tab) => {
                const TabIcon = tab.icon
                const isActive = activeDetailTab === tab.key

                return (
                  <button
                    key={tab.key}
                    type="button"
                    className={cn(
                      "flex h-10 shrink-0 items-center gap-2 rounded-md px-3 text-sm font-medium text-muted-foreground transition-colors outline-none hover:bg-muted hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring lg:w-full",
                      isActive && "bg-primary/10 text-primary"
                    )}
                    onClick={() => setActiveDetailTab(tab.key)}
                  >
                    <TabIcon className="size-4" />
                    {tab.label}
                  </button>
                )
              })}
            </nav>
          </aside>

          <div className="min-w-0 overflow-hidden">
            {activeDetailTab === "documents" ? (
              <div className="min-w-0">
                <div className="flex flex-col gap-3 border-b px-4 py-4 lg:px-5 xl:flex-row xl:items-center xl:justify-between">
                  <h1 className="text-xl font-semibold">文档</h1>
                  <div className="flex flex-wrap gap-2">
                    <Button type="button" disabled>
                      <UploadIcon data-icon="inline-start" />
                      上传文档
                    </Button>
                    <Button type="button" variant="outline" disabled>
                      向量化
                    </Button>
                    <Button type="button" variant="outline" disabled>
                      生成问题
                    </Button>
                    <Button type="button" variant="outline" disabled>
                      <SlidersHorizontalIcon data-icon="inline-start" />
                      设置
                    </Button>
                    <Button
                      type="button"
                      variant="outline"
                      size="icon"
                      disabled
                      aria-label="更多"
                    >
                      <MoreHorizontalIcon />
                    </Button>
                  </div>
                </div>
                <div className="flex flex-col gap-2 border-b bg-muted/20 px-4 py-3 lg:px-5 xl:flex-row xl:items-center xl:justify-between">
                  <button
                    type="button"
                    className="flex h-9 items-center gap-1 self-start text-sm text-primary disabled:text-muted-foreground"
                    disabled
                  >
                    <PlusIcon className="size-4" />
                    快速创建空白文档
                  </button>
                  <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
                    <Button
                      type="button"
                      variant="outline"
                      className="justify-between sm:w-28"
                      disabled
                    >
                      名称
                      <ChevronDownIcon data-icon="inline-end" />
                    </Button>
                    <div className="relative sm:w-72">
                      <SearchIcon className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" />
                      <Input
                        className="pl-9"
                        placeholder="按名称搜索"
                        disabled
                      />
                    </div>
                    <Button type="button" variant="outline" disabled>
                      <TagIcon data-icon="inline-start" />
                      标签管理
                    </Button>
                  </div>
                </div>

                <div className="p-4 lg:p-5">
                  <div className="overflow-x-auto rounded-lg border bg-background">
                    <div className="min-w-[1424px]">
                      <div className="grid grid-cols-[44px_minmax(220px,1.5fr)_120px_100px_100px_120px_150px_150px_150px_150px_120px] border-b bg-muted/30 px-3 py-3 text-sm font-medium text-muted-foreground">
                        <span />
                        <span>文件名称</span>
                        <span>文件状态</span>
                        <span className="flex items-center gap-1">
                          字符数
                          <ArrowUpDownIcon className="size-3.5" />
                        </span>
                        <span className="flex items-center gap-1">
                          分段
                          <ArrowUpDownIcon className="size-3.5" />
                        </span>
                        <span className="flex items-center gap-1">
                          启用状态
                          <FilterIcon className="size-3.5" />
                        </span>
                        <span className="flex items-center gap-1">
                          标签
                          <FilterIcon className="size-3.5" />
                        </span>
                        <span className="flex items-center gap-1">
                          命中处理方式
                          <FilterIcon className="size-3.5" />
                        </span>
                        <span className="flex items-center gap-1">
                          创建时间
                          <ArrowUpDownIcon className="size-3.5" />
                        </span>
                        <span className="flex items-center gap-1">
                          更新时间
                          <ArrowUpDownIcon className="size-3.5" />
                        </span>
                        <span>操作</span>
                      </div>
                      <div className="flex min-h-56 items-center justify-center px-3 py-10 text-sm text-muted-foreground">
                        暂无文档
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            ) : null}

            {activeDetailTab === "questions" ? (
              <div className="p-4 lg:p-5">
                <h1 className="text-xl font-semibold">问题</h1>
                <div className="mt-4 rounded-lg border p-8 text-sm text-muted-foreground">
                  暂无问题
                </div>
              </div>
            ) : null}

            {activeDetailTab === "hit-test" ? (
              <div className="p-4 lg:p-5">
                <h1 className="text-xl font-semibold">命中测试</h1>
                <div className="mt-4 rounded-lg border p-8 text-sm text-muted-foreground">
                  暂无测试结果
                </div>
              </div>
            ) : null}

            {activeDetailTab === "settings" ? (
              <div className="max-w-3xl p-4 lg:p-5">
                <h1 className="text-xl font-semibold">设置</h1>
                <div className="mt-4 rounded-lg border p-4">
                  <div className="flex flex-wrap gap-2">
                    <PermissionBadge
                      permission={selectedKnowledgeBase.permission}
                    />
                    <StatusBadge status={selectedKnowledgeBase.status} />
                  </div>
                  <p className="mt-5 text-sm font-medium">描述</p>
                  <p className="mt-2 text-sm leading-6 whitespace-pre-wrap text-muted-foreground">
                    {selectedKnowledgeBase.description || "-"}
                  </p>
                  <div className="mt-5 flex flex-wrap gap-2">
                    {selectedKnowledgeBase.permission === "edit" ? (
                      <Button
                        type="button"
                        variant="outline"
                        onClick={() =>
                          setEditForm({
                            id: selectedKnowledgeBase.id,
                            name: selectedKnowledgeBase.name,
                            description: selectedKnowledgeBase.description,
                          })
                        }
                      >
                        <PencilIcon data-icon="inline-start" />
                        编辑
                      </Button>
                    ) : null}
                    {canManagePermissions(selectedKnowledgeBase) ? (
                      <Button
                        type="button"
                        variant="outline"
                        onClick={() =>
                          void handleOpenPermissions(selectedKnowledgeBase)
                        }
                      >
                        <UsersIcon data-icon="inline-start" />
                        授权
                      </Button>
                    ) : null}
                  </div>
                </div>
              </div>
            ) : null}
          </div>
        </div>

        <KnowledgeBaseDialogs
          page={page}
          form={form}
          setForm={setForm}
          editForm={editForm}
          setEditForm={setEditForm}
          permissionForm={permissionForm}
          setPermissionForm={setPermissionForm}
          shareTargets={shareTargets}
          permissions={permissions}
          isDialogOpen={isDialogOpen}
          setIsDialogOpen={setIsDialogOpen}
          isSaving={isSaving}
          handleCreate={handleCreate}
          handleUpdate={handleUpdate}
          handleGrantPermission={handleGrantPermission}
          handleRevokePermission={handleRevokePermission}
        />
      </>
    )
  }

  return (
    <>
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <h1 className="truncate text-2xl font-semibold">{page.label}</h1>
          <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
            {page.description}
          </p>
        </div>
        <Button
          type="button"
          className="shrink-0"
          disabled={!selectedWorkspaceId}
          onClick={() => setIsDialogOpen(true)}
        >
          <PlusIcon data-icon="inline-start" />
          {page.actionLabel}
        </Button>
      </div>

      {error ? <p className="text-sm text-destructive">{error}</p> : null}

      {!selectedWorkspaceId ? (
        <div className="rounded-lg border bg-background p-6 shadow-sm">
          <div className="mx-auto flex min-h-[240px] max-w-xl flex-col items-center justify-center gap-3 text-center">
            <span className="flex size-14 items-center justify-center rounded-lg bg-muted">
              <Icon className="size-5 text-muted-foreground" />
            </span>
            <p className="text-base font-semibold">{t("先选择工作空间")}</p>
          </div>
        </div>
      ) : (
        <>
          {isLoading ? (
            <div className="flex min-h-[220px] items-center justify-center rounded-lg border bg-background shadow-sm">
              <LoaderCircleIcon className="animate-spin text-muted-foreground" />
            </div>
          ) : knowledgeBases.length ? (
            <div className="flex flex-wrap gap-3">
              {knowledgeBases.map((knowledgeBase) => (
                <div
                  key={knowledgeBase.id}
                  role="button"
                  tabIndex={0}
                  className="flex min-h-44 w-full min-w-0 cursor-pointer flex-col justify-between rounded-lg border bg-background p-3 shadow-sm transition-colors outline-none hover:bg-muted/40 focus-visible:ring-2 focus-visible:ring-ring sm:w-[19rem]"
                  onClick={() => openKnowledgeBase(knowledgeBase)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" || event.key === " ") {
                      event.preventDefault()
                      openKnowledgeBase(knowledgeBase)
                    }
                  }}
                >
                  <div className="min-w-0 space-y-2">
                    <div className="min-w-0">
                      <p className="truncate text-sm font-semibold">
                        {knowledgeBase.name}
                      </p>
                      <p className="mt-0.5 text-xs text-muted-foreground">
                        {formatDateTime(knowledgeBase.updated_at, locale)}
                      </p>
                    </div>
                    <p className="line-clamp-3 text-xs leading-5 text-muted-foreground">
                      {knowledgeBase.description || "-"}
                    </p>
                  </div>
                  <div className="mt-3 flex items-center justify-between gap-2">
                    <div className="flex min-w-0 flex-wrap gap-1.5">
                      <PermissionBadge permission={knowledgeBase.permission} />
                      <StatusBadge status={knowledgeBase.status} />
                    </div>
                    <div className="flex shrink-0 justify-end gap-1">
                      {knowledgeBase.permission === "edit" ? (
                        <>
                          <Button
                            type="button"
                            variant="ghost"
                            size="icon-sm"
                            title="编辑知识库"
                            aria-label="编辑知识库"
                            onClick={(event) => {
                              event.stopPropagation()
                              setEditForm({
                                id: knowledgeBase.id,
                                name: knowledgeBase.name,
                                description: knowledgeBase.description,
                              })
                            }}
                          >
                            <PencilIcon />
                          </Button>
                          <Button
                            type="button"
                            variant="ghost"
                            size="icon-sm"
                            title={
                              knowledgeBase.status === "active"
                                ? "归档知识库"
                                : "恢复知识库"
                            }
                            aria-label={
                              knowledgeBase.status === "active"
                                ? "归档知识库"
                                : "恢复知识库"
                            }
                            onClick={(event) => {
                              event.stopPropagation()
                              void handleToggleStatus(knowledgeBase)
                            }}
                          >
                            {knowledgeBase.status === "active" ? (
                              <ArchiveIcon />
                            ) : (
                              <RotateCcwIcon />
                            )}
                          </Button>
                        </>
                      ) : null}
                      {canManagePermissions(knowledgeBase) ? (
                        <>
                          <Button
                            type="button"
                            variant="ghost"
                            size="icon-sm"
                            title="资源授权"
                            aria-label="资源授权"
                            onClick={(event) => {
                              event.stopPropagation()
                              void handleOpenPermissions(knowledgeBase)
                            }}
                          >
                            <UsersIcon />
                          </Button>
                          <Button
                            type="button"
                            variant="ghost"
                            size="icon-sm"
                            title="永久删除知识库"
                            aria-label="永久删除知识库"
                            onClick={(event) => {
                              event.stopPropagation()
                              void handleDelete(knowledgeBase)
                            }}
                          >
                            <Trash2Icon />
                          </Button>
                        </>
                      ) : null}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="mx-auto flex min-h-[320px] max-w-xl flex-col items-center justify-center gap-4 p-6 text-center">
              <span className="flex size-14 items-center justify-center rounded-lg bg-muted">
                <Icon className="size-5 text-muted-foreground" />
              </span>
              <div className="flex flex-col gap-2">
                <p className="text-base font-semibold">{page.emptyTitle}</p>
                <p className="text-sm leading-6 text-muted-foreground">
                  {page.emptyDescription}
                </p>
              </div>
              <Button type="button" onClick={() => setIsDialogOpen(true)}>
                <PlusIcon data-icon="inline-start" />
                {page.actionLabel}
              </Button>
            </div>
          )}
        </>
      )}

      <KnowledgeBaseDialogs
        page={page}
        form={form}
        setForm={setForm}
        editForm={editForm}
        setEditForm={setEditForm}
        permissionForm={permissionForm}
        setPermissionForm={setPermissionForm}
        shareTargets={shareTargets}
        permissions={permissions}
        isDialogOpen={isDialogOpen}
        setIsDialogOpen={setIsDialogOpen}
        isSaving={isSaving}
        handleCreate={handleCreate}
        handleUpdate={handleUpdate}
        handleGrantPermission={handleGrantPermission}
        handleRevokePermission={handleRevokePermission}
      />
    </>
  )
}
