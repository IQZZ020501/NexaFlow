"use client"

import * as React from "react"
import Link from "next/link"
import { useRouter } from "next/navigation"
import { DownloadIcon, HistoryIcon, Trash2Icon } from "lucide-react"
import { useConfirmDialog } from "@/components/app/confirm-dialog"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { useLanguage } from "@/contexts/language-provider"
import { useSession } from "@/contexts/session-context"
import { ApiError } from "@/lib/api-client"
import { getErrorMessage } from "@/lib/errors"
import * as api from "@/lib/api/projects"

export function ProjectsPage({ projectId }: { projectId?: string }) {
  const { token, selectedWorkspaceId } = useSession()
  if (!token || !selectedWorkspaceId) return null
  return (
    <ProjectWorkspace
      key={`${selectedWorkspaceId}:${projectId ?? "list"}`}
      token={token}
      workspaceId={selectedWorkspaceId}
      projectId={projectId}
    />
  )
}

function ProjectWorkspace({
  token,
  workspaceId,
  projectId,
}: {
  token: string
  workspaceId: string
  projectId?: string
}) {
  const { t } = useLanguage()
  const router = useRouter()
  const [confirm, confirmDialog] = useConfirmDialog()
  const [projects, setProjects] = React.useState<api.AgentProject[]>([])
  const [project, setProject] = React.useState<api.AgentProject | null>(null)
  const [files, setFiles] = React.useState<api.ProjectFile[]>([])
  const [name, setName] = React.useState("")
  const [path, setPath] = React.useState("")
  const [role, setRole] = React.useState<api.ProjectFile["role"]>("source")
  const [upload, setUpload] = React.useState<File | null>(null)
  const [history, setHistory] = React.useState<{
    path: string
    items: api.ProjectFile[]
  } | null>(null)
  const [rename, setRename] = React.useState<{
    file: api.ProjectFile
    path: string
  } | null>(null)
  const [error, setError] = React.useState<string | null>(null)
  const [busy, setBusy] = React.useState(false)
  const [loading, setLoading] = React.useState(true)
  const [hasMore, setHasMore] = React.useState(false)
  const inputRef = React.useRef<HTMLInputElement>(null)
  const reload = React.useCallback(async () => {
    if (projectId) {
      const [item, versions] = await Promise.all([
        api.getProject(token, workspaceId, projectId),
        api.listProjectFiles(token, workspaceId, projectId),
      ])
      setProject(item)
      setName(item.name)
      setFiles(versions)
    } else {
      const items = await api.listProjects(token, workspaceId)
      setProjects(items)
      setHasMore(items.length === 100)
    }
  }, [token, workspaceId, projectId])
  React.useEffect(() => {
    let active = true
    async function load() {
      try {
        if (projectId) {
          const [item, versions] = await Promise.all([
            api.getProject(token, workspaceId, projectId),
            api.listProjectFiles(token, workspaceId, projectId),
          ])
          if (active) {
            setProject(item)
            setName(item.name)
            setFiles(versions)
          }
        } else {
          const items = await api.listProjects(token, workspaceId)
          if (active) {
            setProjects(items)
            setHasMore(items.length === 100)
          }
        }
      } catch (error) {
        if (active) setError(getErrorMessage(error, t))
      } finally {
        if (active) setLoading(false)
      }
    }
    void load()
    return () => {
      active = false
    }
  }, [token, workspaceId, projectId, t])
  async function act(action: () => Promise<unknown>) {
    setBusy(true)
    setError(null)
    try {
      await action()
    } catch (error) {
      setError(
        error instanceof ApiError && error.status === 409
          ? t("项目版本冲突，请刷新后重试；你的更改未覆盖其他版本。")
          : getErrorMessage(error, t)
      )
    } finally {
      setBusy(false)
    }
  }
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h1 className="text-2xl font-semibold break-words">
            {project?.name ?? t("项目文件")}
          </h1>
          <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
            {t(
              "私有项目保留源资料、脚本和文件版本，可在新的 Agent 对话中继续使用。"
            )}
          </p>
        </div>
        <Button asChild variant="outline">
          <Link href={projectId ? "/app/projects" : "/app/apps"}>
            {projectId ? t("全部项目") : t("应用")}
          </Link>
        </Button>
      </div>
      {error ? (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      ) : null}
      <div className="flex flex-wrap items-center gap-2">
        <Button
          variant="outline"
          disabled={busy || loading}
          onClick={() => void act(reload)}
        >
          {t("刷新")}
        </Button>
        {project ? (
          <Button
            variant="destructive"
            disabled={busy}
            onClick={async () => {
              if (
                await confirm({
                  description: t("删除项目及其全部文件版本？此操作无法撤销。"),
                  destructive: true,
                })
              )
                void act(async () => {
                  await api.deleteProject(token, workspaceId, project.id)
                  router.push("/app/projects")
                })
            }}
          >
            {t("删除项目")}
          </Button>
        ) : null}
      </div>
      {loading ? (
        <p aria-live="polite">{t("正在加载")}</p>
      ) : (
        <>
          <form
            className="flex flex-wrap items-center gap-2"
            onSubmit={(e) => {
              e.preventDefault()
              void act(async () => {
                if (project) {
                  setProject(
                    await api.renameProject(
                      token,
                      workspaceId,
                      project.id,
                      name
                    )
                  )
                } else {
                  const item = await api.createProject(token, workspaceId, name)
                  router.push(`/app/projects/${item.id}`)
                }
              })
            }}
          >
            <Input
              className="max-w-sm"
              aria-label={t("项目名称")}
              placeholder={t("项目名称")}
              value={name}
              maxLength={120}
              required
              onChange={(e) => setName(e.target.value)}
            />
            <Button disabled={busy || !name.trim()}>
              {project ? t("重命名") : t("新建项目")}
            </Button>
          </form>
          {!projectId ? (
            <>
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                {projects.map((item) => (
                  <Link
                    key={item.id}
                    href={`/app/projects/${item.id}`}
                    className="min-w-0 rounded-lg border bg-card p-4 hover:bg-muted"
                  >
                    <span className="block truncate font-medium">
                      {item.name}
                    </span>
                    <span className="text-xs text-muted-foreground">
                      {t("项目修订：{revision}", { revision: item.revision })}
                    </span>
                  </Link>
                ))}
              </div>
              {!projects.length ? (
                <p className="text-muted-foreground">{t("还没有项目")}</p>
              ) : null}
              {hasMore ? (
                <Button
                  disabled={busy}
                  onClick={() =>
                    void act(async () => {
                      const items = await api.listProjects(
                        token,
                        workspaceId,
                        projects.length
                      )
                      setProjects([...projects, ...items])
                      setHasMore(items.length === 100)
                    })
                  }
                >
                  {t("加载更多")}
                </Button>
              ) : null}
            </>
          ) : project ? (
            <>
              <p className="text-sm text-muted-foreground">
                {t(
                  "源资料只读；工作文件会在命令执行后保存。每个文件最多 5 MiB，项目最多 64 个文件和 64 MiB。"
                )}
              </p>
              <form
                className="grid gap-3 rounded-lg border p-4 sm:grid-cols-2"
                onSubmit={(e) => {
                  e.preventDefault()
                  if (!upload) return
                  void act(async () => {
                    const current = files.find((item) => item.path === path)
                    await api.uploadProjectFile(
                      token,
                      workspaceId,
                      projectId,
                      path,
                      role,
                      upload,
                      current?.id
                    )
                    setUpload(null)
                    setPath("")
                    if (inputRef.current) inputRef.current.value = ""
                    await reload()
                  })
                }}
              >
                <Input
                  ref={inputRef}
                  type="file"
                  aria-label={t("上传项目文件")}
                  required
                  disabled={busy}
                  onChange={(e) => {
                    const file = e.target.files?.[0] ?? null
                    setUpload(file)
                    if (file) setPath(file.name)
                  }}
                />
                <Input
                  aria-label={t("项目相对路径")}
                  placeholder={t("项目相对路径")}
                  value={path}
                  required
                  maxLength={512}
                  onChange={(e) => setPath(e.target.value)}
                />
                <select
                  aria-label={t("文件用途")}
                  className="h-9 rounded-md border bg-background px-2"
                  value={role}
                  onChange={(e) =>
                    setRole(e.target.value as api.ProjectFile["role"])
                  }
                >
                  <option value="source">{t("源资料（只读）")}</option>
                  <option value="work">{t("工作文件")}</option>
                </select>
                <Button disabled={busy || !upload || !path.trim()}>
                  {t("保存文件版本")}
                </Button>
              </form>
              <div className="divide-y rounded-lg border">
                {files.map((file) => (
                  <div
                    key={file.path}
                    className="flex min-w-0 flex-wrap items-center gap-3 p-3"
                  >
                    <div className="min-w-0 flex-1">
                      <span className="block text-sm font-medium break-all">
                        {file.path}
                      </span>
                      <span className="text-xs text-muted-foreground">
                        {file.deleted
                          ? t("已删除")
                          : file.role === "source"
                            ? t("源资料（只读）")
                            : t("工作文件")}{" "}
                        ·{" "}
                        {t("项目修订：{revision}", { revision: file.revision })}{" "}
                        · {file.size_bytes} B
                      </span>
                    </div>
                    {!file.deleted ? (
                      <Button
                        variant="ghost"
                        size="sm"
                        disabled={busy}
                        onClick={() =>
                          void act(() =>
                            api.downloadProjectVersion(
                              token,
                              workspaceId,
                              projectId,
                              file
                            )
                          )
                        }
                      >
                        <DownloadIcon />
                        {t("下载")}
                      </Button>
                    ) : null}
                    <Button
                      variant="ghost"
                      size="sm"
                      disabled={busy}
                      onClick={() =>
                        void act(async () =>
                          setHistory({
                            path: file.path,
                            items: await api.listProjectVersions(
                              token,
                              workspaceId,
                              projectId,
                              file.path
                            ),
                          })
                        )
                      }
                    >
                      <HistoryIcon />
                      {t("文件版本")}
                    </Button>
                    {!file.deleted ? (
                      <>
                        <Button
                          variant="ghost"
                          size="sm"
                          disabled={busy}
                          onClick={() => setRename({ file, path: file.path })}
                        >
                          {t("重命名")}
                        </Button>
                        <Button
                          variant="ghost"
                          size="sm"
                          disabled={busy}
                          onClick={async () => {
                            if (
                              await confirm({
                                description: t(
                                  "删除此文件？已有版本仍可在历史中下载。"
                                ),
                                destructive: true,
                              })
                            )
                              void act(async () => {
                                await api.deleteProjectFile(
                                  token,
                                  workspaceId,
                                  projectId,
                                  file
                                )
                                await reload()
                              })
                          }}
                        >
                          <Trash2Icon />
                          {t("删除")}
                        </Button>
                      </>
                    ) : null}
                  </div>
                ))}
              </div>
            </>
          ) : null}
        </>
      )}
      <Dialog
        open={history !== null}
        onOpenChange={(open) => {
          if (!open) setHistory(null)
        }}
      >
        <DialogContent className="max-h-[80dvh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>{t("文件版本")}</DialogTitle>
            <DialogDescription className="break-all">
              {history?.path}
            </DialogDescription>
          </DialogHeader>
          {history?.items.map((file) => (
            <div
              key={file.id}
              className="flex items-center justify-between gap-3 border-b py-2 text-sm"
            >
              <span>
                {t("项目修订：{revision}", { revision: file.revision })} ·{" "}
                {file.deleted ? t("已删除") : `${file.size_bytes} B`}
              </span>
              {!file.deleted && projectId ? (
                <Button
                  size="sm"
                  variant="outline"
                  disabled={busy}
                  onClick={() =>
                    void act(() =>
                      api.downloadProjectVersion(
                        token,
                        workspaceId,
                        projectId,
                        file
                      )
                    )
                  }
                >
                  {t("下载")}
                </Button>
              ) : null}
            </div>
          ))}
          {history &&
          history.items.length % 50 === 0 &&
          history.items.length > 0 &&
          projectId ? (
            <Button
              disabled={busy}
              onClick={() =>
                void act(async () => {
                  const items = await api.listProjectVersions(
                    token,
                    workspaceId,
                    projectId,
                    history.path,
                    history.items.length
                  )
                  setHistory({
                    ...history,
                    items: [...history.items, ...items],
                  })
                })
              }
            >
              {t("加载更多")}
            </Button>
          ) : null}
        </DialogContent>
      </Dialog>
      <Dialog
        open={rename !== null}
        onOpenChange={(open) => {
          if (!open) setRename(null)
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t("重命名")}</DialogTitle>
            <DialogDescription>
              {t("重命名会保存新版本，旧路径不会在新 Run 中恢复。")}
            </DialogDescription>
          </DialogHeader>
          <form
            className="space-y-3"
            onSubmit={(e) => {
              e.preventDefault()
              if (!rename || !projectId) return
              void act(async () => {
                await api.renameProjectFile(
                  token,
                  workspaceId,
                  projectId,
                  rename.file,
                  rename.path
                )
                setRename(null)
                await reload()
              })
            }}
          >
            <Input
              aria-label={t("项目相对路径")}
              value={rename?.path ?? ""}
              required
              maxLength={512}
              onChange={(e) =>
                setRename(
                  (current) => current && { ...current, path: e.target.value }
                )
              }
            />
            <Button disabled={busy}>{t("保存")}</Button>
          </form>
        </DialogContent>
      </Dialog>
      {confirmDialog}
    </div>
  )
}
