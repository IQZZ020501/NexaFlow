"use client"

import * as React from "react"
import {
  DownloadIcon,
  EyeIcon,
  FolderIcon,
  LoaderCircleIcon,
  PlusIcon,
  Trash2Icon,
  XIcon,
} from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { IconButton } from "@/components/ui/icon-button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { AgentFilePicker } from "@/components/agents/agent-file-picker"
import { AgentArtifactPreviewContext } from "@/components/agents/artifacts/agent-artifact-preview-context"
import { ArtifactDownloadLink } from "@/components/knowledge/markdown-content"
import { useLanguage } from "@/contexts/language-provider"
import { getErrorMessage } from "@/lib/errors"
import type { PreviewArtifact, PreviewFormat } from "@/lib/agent-artifacts"
import {
  chatProjectFileUrl,
  createChatProject,
  deleteChatProjectFile,
  listChatProjectFiles,
  listChatProjects,
  uploadChatProjectFiles,
  type ChatProject,
  type ChatProjectFile,
} from "@/lib/api/public-chat-projects"

export function usePublicChatProjects(
  agentId: string,
  token: string | null,
  ready: boolean
) {
  const [state, setState] = React.useState({
    agentId,
    token,
    projects: [] as ChatProject[],
    error: false,
    loaded: false,
  })
  const sameScope = state.agentId === agentId && state.token === token
  const setProjects = React.useCallback(
    (update: React.SetStateAction<ChatProject[]>) => {
      setState((current) => {
        const projects =
          current.agentId === agentId && current.token === token
            ? current.projects
            : []
        return {
          agentId,
          token,
          projects: typeof update === "function" ? update(projects) : update,
          error: false,
          loaded: true,
        }
      })
    },
    [agentId, token]
  )
  const [attempt, retry] = React.useReducer((value) => value + 1, 0)
  React.useEffect(() => {
    if (!token || !ready) return
    const controller = new AbortController()
    listChatProjects(agentId, token, controller.signal)
      .then((result) => {
        if (!Array.isArray(result.items))
          throw new Error("Invalid project list")
        if (!controller.signal.aborted) {
          setState({
            agentId,
            token,
            projects: result.items,
            loaded: true,
            error: false,
          })
        }
      })
      .catch(() => {
        if (!controller.signal.aborted)
          setState({ agentId, token, projects: [], loaded: false, error: true })
      })
    return () => controller.abort()
  }, [agentId, token, ready, attempt])
  return {
    projects: sameScope && ready && token ? state.projects : [],
    setProjects,
    error: sameScope && state.error,
    loaded: sameScope && state.loaded,
    retry,
  }
}

export function CreateChatProjectDialog({
  open,
  onOpenChange,
  agentId,
  token,
  onCreated,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  agentId: string
  token: string
  onCreated: (project: ChatProject) => void
}) {
  const { t } = useLanguage()
  const [name, setName] = React.useState("")
  const [busy, setBusy] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)
  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!busy) onOpenChange(next)
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("新建项目")}</DialogTitle>
          <DialogDescription>
            {t("将相关对话和资料放在一起，仅你自己可见。")}
          </DialogDescription>
        </DialogHeader>
        <form
          className="space-y-4"
          onSubmit={async (event) => {
            event.preventDefault()
            if (!name.trim() || busy) return
            setBusy(true)
            setError(null)
            try {
              const project = await createChatProject(
                agentId,
                token,
                name.trim()
              )
              onCreated(project)
              onOpenChange(false)
              setName("")
            } catch (error) {
              setError(getErrorMessage(error, t))
            } finally {
              setBusy(false)
            }
          }}
        >
          <label className="grid gap-2 text-sm">
            {t("项目名称")}
            <Input
              value={name}
              maxLength={120}
              required
              onChange={(event) => setName(event.target.value)}
            />
          </label>
          {error ? (
            <p role="alert" className="text-sm text-destructive">
              {error}
            </p>
          ) : null}
          <div className="flex justify-end">
            <Button disabled={busy || !name.trim()} type="submit">
              {busy ? (
                <LoaderCircleIcon className="animate-spin" />
              ) : (
                <PlusIcon />
              )}
              {t("创建项目")}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  )
}

function filePreview(
  agentId: string,
  projectId: string,
  file: ChatProjectFile
): PreviewArtifact | null {
  const extension = file.path.split(".").pop()?.toLowerCase()
  const format = extension === "htm" ? "html" : extension
  if (!format || !["html", "pdf", "docx", "xlsx", "pptx"].includes(format))
    return null
  return {
    filename: file.path.split("/").pop()!,
    relativePath: file.path,
    format: format as PreviewFormat,
    downloadUrl: chatProjectFileUrl(agentId, projectId, file.id),
  }
}

export function EditChatProjectDialog({
  project,
  agentId,
  token,
  onClose,
  onSave,
  onReturnFocus,
  onPreview,
  onMessage,
}: {
  project: ChatProject
  agentId: string
  token: string
  onClose: () => void
  onSave: (project: ChatProject) => Promise<void>
  onReturnFocus: () => void
  onPreview: (artifact: PreviewArtifact, opener: HTMLButtonElement) => void
  onMessage: (kind: "success" | "error", message: string) => void
}) {
  const { t } = useLanguage()
  const preview = React.useContext(AgentArtifactPreviewContext)
  const formId = React.useId()
  const openingPreview = React.useRef(false)
  const [name, setName] = React.useState(project.name)
  const [files, setFiles] = React.useState<ChatProjectFile[]>([])
  const [loading, setLoading] = React.useState(true)
  const [attempt, retry] = React.useReducer((value) => value + 1, 0)
  const [busy, setBusy] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)
  const updateSource = preview?.updateSource
  React.useEffect(() => {
    const controller = new AbortController()
    listChatProjectFiles(agentId, token, project.id, controller.signal)
      .then((result) => {
        if (!Array.isArray(result.items)) throw new Error(t("操作失败"))
        if (!controller.signal.aborted) setFiles(result.items)
      })
      .catch((error) => {
        if (!controller.signal.aborted) setError(getErrorMessage(error, t))
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false)
      })
    return () => controller.abort()
  }, [agentId, token, project.id, attempt, t])
  React.useEffect(() => {
    updateSource?.(
      `project:${project.id}`,
      files.map((file) => chatProjectFileUrl(agentId, project.id, file.id))
    )
    // Keep a selected project preview registered after this dialog closes.
  }, [agentId, project.id, files, updateSource])
  async function act(action: () => Promise<void>) {
    if (busy) return
    setBusy(true)
    setError(null)
    try {
      await action()
    } catch (error) {
      setError(getErrorMessage(error, t))
    } finally {
      setBusy(false)
    }
  }
  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open && !busy) onClose()
      }}
    >
      <DialogContent
        className="flex min-h-0 max-w-xl flex-col gap-0 overflow-hidden p-0"
        onCloseAutoFocus={(event) => {
          event.preventDefault()
          if (!openingPreview.current) onReturnFocus()
        }}
      >
        <DialogHeader className="flex-row items-center gap-3 px-5 py-4">
          <DialogTitle className="min-w-0 flex-1">{t("编辑项目")}</DialogTitle>
          <DialogDescription className="sr-only">
            {t("将相关对话和资料放在一起，仅你自己可见。")}
          </DialogDescription>
          <IconButton label={t("关闭")} onClick={onClose} disabled={busy}>
            <XIcon className="size-4" />
          </IconButton>
        </DialogHeader>
        <div className="min-h-0 flex-1 space-y-5 overflow-y-auto px-5 pb-5">
          {error ? (
            <div
              role="alert"
              className="flex items-center gap-2 text-sm text-destructive"
            >
              <span className="flex-1">{error}</span>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => {
                  setLoading(true)
                  setError(null)
                  retry()
                }}
              >
                {t("重试")}
              </Button>
            </div>
          ) : null}
          <form
            id={formId}
            onSubmit={(event) => {
              event.preventDefault()
              if (!name.trim() || project.archived) return
              void act(async () => {
                await onSave({ ...project, name: name.trim() })
                onClose()
              })
            }}
          >
            <label className="grid gap-2 text-sm">
              {t("项目名称")}
              <div className="relative">
                <FolderIcon className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" />
                <Input
                  autoFocus={!project.archived}
                  className="pl-9"
                  value={name}
                  required
                  maxLength={120}
                  disabled={busy || project.archived}
                  onChange={(event) => setName(event.target.value)}
                />
              </div>
            </label>
          </form>
          <section className="space-y-3" aria-label={t("项目资料")}>
            <div className="flex items-center justify-between gap-2">
              <h3 className="text-sm font-medium">{t("项目资料")}</h3>
              <AgentFilePicker
                label={t("上传资料")}
                disabled={busy || project.archived || loading}
                t={t}
                onFiles={(selected) =>
                  void act(async () => {
                    setFiles(
                      (
                        await uploadChatProjectFiles(
                          agentId,
                          token,
                          project.id,
                          selected
                        )
                      ).items
                    )
                    onMessage("success", t("项目资料已上传"))
                  })
                }
              />
            </div>
            <p className="text-xs leading-5 text-muted-foreground">
              {t(
                "项目内各段对话共用只读资料；每个文件最多 5 MiB，合计最多 64 个文件、64 MiB。"
              )}
            </p>
            {loading ? (
              <p role="status" className="text-sm text-muted-foreground">
                {t("正在加载")}
              </p>
            ) : !files.length ? (
              <p className="text-sm text-muted-foreground">
                {t("暂无项目资料")}
              </p>
            ) : (
              <div className="space-y-1">
                {files.map((file) => {
                  const artifact = filePreview(agentId, project.id, file)
                  return (
                    <div
                      key={file.id}
                      className="flex min-w-0 items-center gap-1 rounded-md border p-1"
                    >
                      {artifact ? (
                        <button
                          disabled={busy}
                          className="flex min-w-0 flex-1 items-center gap-2 rounded-sm px-2 py-2 text-left text-sm hover:bg-muted focus-visible:outline-2 focus-visible:outline-ring"
                          aria-label={t("预览文件：{filename}", {
                            filename: file.path,
                          })}
                          onClick={(event) => {
                            openingPreview.current = true
                            onPreview(artifact, event.currentTarget)
                          }}
                        >
                          <span className="truncate">{file.path}</span>
                          <EyeIcon className="size-3.5 shrink-0" />
                        </button>
                      ) : (
                        <span className="min-w-0 flex-1 truncate px-2 text-sm">
                          {file.path}
                        </span>
                      )}
                      <ArtifactDownloadLink
                        href={chatProjectFileUrl(agentId, project.id, file.id)}
                        filename={file.path.split("/").pop()}
                        className="inline-flex size-8 shrink-0 items-center justify-center rounded-sm text-muted-foreground no-underline hover:bg-muted"
                      >
                        <DownloadIcon className="size-4" />
                        <span className="sr-only">{t("下载原文")}</span>
                      </ArtifactDownloadLink>
                      <IconButton
                        label={t("移除项目资料：{filename}", {
                          filename: file.path,
                        })}
                        disabled={busy || project.archived}
                        onClick={() =>
                          void act(async () => {
                            await deleteChatProjectFile(
                              agentId,
                              token,
                              project.id,
                              file.id
                            )
                            setFiles((current) =>
                              current.filter((item) => item.id !== file.id)
                            )
                            onMessage("success", t("项目资料已移除"))
                          })
                        }
                      >
                        <Trash2Icon className="size-4" />
                      </IconButton>
                    </div>
                  )
                })}
              </div>
            )}
          </section>
        </div>
        <DialogFooter className="shrink-0 border-t px-5 py-4">
          <Button variant="ghost" disabled={busy} onClick={onClose}>
            {t("取消")}
          </Button>
          <Button
            type="submit"
            form={formId}
            disabled={
              busy ||
              project.archived ||
              !name.trim() ||
              name.trim() === project.name
            }
          >
            {busy ? <LoaderCircleIcon className="animate-spin" /> : null}
            {t("保存")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
