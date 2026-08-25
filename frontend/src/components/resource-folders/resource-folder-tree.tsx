"use client"

import * as React from "react"
import {
  ChevronDownIcon,
  ChevronRightIcon,
  FolderIcon,
  FolderOpenIcon,
  MoreHorizontalIcon,
  PencilIcon,
  PlusIcon,
  Trash2Icon,
} from "lucide-react"

import { useConfirmDialog } from "@/components/app/confirm-dialog"
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
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { Input } from "@/components/ui/input"
import { useLanguage } from "@/contexts/language-provider"
import { getErrorMessage } from "@/lib/errors"
import type { ResourceFolder } from "@/lib/api/resource-folders"
import { cn } from "@/lib/utils"

type FolderDialogState =
  | { mode: "create"; parentId: string | null; name: string }
  | { mode: "rename"; folderId: string; name: string }
  | null

type Props = {
  folders: ResourceFolder[]
  selectedFolderId: string | null
  canManage: boolean
  isLoading?: boolean
  onSelect: (folderId: string | null) => void
  onCreate: (name: string, parentId: string | null) => Promise<void>
  onRename: (folderId: string, name: string) => Promise<void>
  onDelete: (folderId: string) => Promise<string | null | undefined>
  onFolderDeleted?: (folderId: string, parentId: string | null) => void
}

function childFolders(folders: ResourceFolder[], parentId: string | null) {
  return folders
    .filter((folder) => folder.parent_id === parentId)
    .sort((left, right) => left.name.localeCompare(right.name))
}

export function ResourceFolderTree({
  folders,
  selectedFolderId,
  canManage,
  isLoading,
  onSelect,
  onCreate,
  onRename,
  onDelete,
  onFolderDeleted,
}: Props) {
  const { t } = useLanguage()
  const [dialog, setDialog] = React.useState<FolderDialogState>(null)
  const [isSaving, setIsSaving] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)
  const [collapsedFolderIds, setCollapsedFolderIds] = React.useState<
    Set<string>
  >(new Set())
  const [confirmAction, confirmDialog] = useConfirmDialog()

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!dialog || !dialog.name.trim()) return
    setIsSaving(true)
    setError(null)
    try {
      if (dialog.mode === "create") {
        await onCreate(dialog.name.trim(), dialog.parentId)
      } else {
        await onRename(dialog.folderId, dialog.name.trim())
      }
      setDialog(null)
    } catch (nextError) {
      setError(getErrorMessage(nextError, t))
    } finally {
      setIsSaving(false)
    }
  }

  async function remove(folder: ResourceFolder) {
    if (
      !(await confirmAction({
        description: t("删除文件夹“{name}”？其中的内容会移动到上一级。", {
          name: folder.name,
        }),
        confirmLabel: t("删除"),
        destructive: true,
      }))
    ) {
      return
    }
    try {
      const parentId = (await onDelete(folder.id)) ?? null
      onFolderDeleted?.(folder.id, parentId)
    } catch (nextError) {
      setError(getErrorMessage(nextError, t))
    }
  }

  function renderFolder(folder: ResourceFolder): React.ReactNode {
    const selected = selectedFolderId === folder.id
    const children = childFolders(folders, folder.id)
    const collapsed = collapsedFolderIds.has(folder.id)
    return (
      <div key={folder.id}>
        <div
          className={cn(
            "group flex items-center gap-1 rounded-md px-1",
            selected ? "bg-muted" : "hover:bg-muted/60"
          )}
        >
          {children.length ? (
            <button
              type="button"
              className="flex size-6 shrink-0 items-center justify-center rounded-sm text-muted-foreground hover:bg-background"
              aria-label={t(collapsed ? "展开" : "收起")}
              onClick={() =>
                setCollapsedFolderIds((current) => {
                  const next = new Set(current)
                  if (next.has(folder.id)) next.delete(folder.id)
                  else next.add(folder.id)
                  return next
                })
              }
            >
              {collapsed ? <ChevronRightIcon /> : <ChevronDownIcon />}
            </button>
          ) : (
            <span className="size-6 shrink-0" />
          )}
          <button
            type="button"
            className="flex h-8 min-w-0 flex-1 items-center gap-2 text-left text-sm"
            onClick={() => onSelect(folder.id)}
          >
            {selected ? (
              <FolderOpenIcon className="size-4 shrink-0 text-primary" />
            ) : (
              <FolderIcon className="size-4 shrink-0 text-muted-foreground" />
            )}
            <span className="truncate">{folder.name}</span>
          </button>
          {canManage ? (
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon-xs"
                  aria-label={t("管理文件夹 {name}", { name: folder.name })}
                >
                  <MoreHorizontalIcon />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="start">
                <DropdownMenuItem
                  onSelect={() =>
                    setDialog({ mode: "create", parentId: folder.id, name: "" })
                  }
                >
                  <PlusIcon />
                  {t("新建子文件夹")}
                </DropdownMenuItem>
                <DropdownMenuItem
                  onSelect={() =>
                    setDialog({
                      mode: "rename",
                      folderId: folder.id,
                      name: folder.name,
                    })
                  }
                >
                  <PencilIcon />
                  {t("重命名")}
                </DropdownMenuItem>
                <DropdownMenuItem
                  variant="destructive"
                  onSelect={() => void remove(folder)}
                >
                  <Trash2Icon />
                  {t("删除")}
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          ) : null}
        </div>
        {!collapsed && children.length ? (
          <div className="ml-4 border-l border-border/70 pl-2">
            {children.map((child) => renderFolder(child))}
          </div>
        ) : null}
      </div>
    )
  }

  return (
    <>
      <aside className="flex min-w-0 flex-col rounded-lg border bg-background p-2 shadow-sm lg:min-h-[calc(100svh-11rem)] lg:w-56 lg:shrink-0">
        <div className="mb-1 flex items-center justify-between gap-2 px-1">
          <p className="text-xs font-medium text-muted-foreground">
            {t("目录")}
          </p>
          {canManage ? (
            <Button
              type="button"
              variant="ghost"
              size="icon-xs"
              aria-label={t("新建子文件夹")}
              onClick={() =>
                setDialog({
                  mode: "create",
                  parentId: selectedFolderId,
                  name: "",
                })
              }
            >
              <PlusIcon />
            </Button>
          ) : null}
        </div>
        <button
          type="button"
          className={cn(
            "flex h-8 w-full items-center gap-2 rounded-md px-2 text-left text-sm",
            selectedFolderId === null ? "bg-muted" : "hover:bg-muted/60"
          )}
          onClick={() => onSelect(null)}
        >
          {selectedFolderId === null ? (
            <FolderOpenIcon className="size-4 text-primary" />
          ) : (
            <FolderIcon className="size-4 text-muted-foreground" />
          )}
          {t("根目录")}
        </button>
        <div className="mt-1 max-h-80 overflow-y-auto lg:max-h-none lg:min-h-0 lg:flex-1">
          {childFolders(folders, null).map((folder) => renderFolder(folder))}
          {isLoading ? (
            <p className="px-2 py-3 text-xs text-muted-foreground">
              {t("正在加载")}
            </p>
          ) : null}
        </div>
      </aside>

      <Dialog
        open={dialog !== null}
        onOpenChange={(open) => !open && setDialog(null)}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {t(dialog?.mode === "rename" ? "重命名文件夹" : "新建文件夹")}
            </DialogTitle>
            <DialogDescription>
              {t("文件夹仅用于资源归类，不会改变访问权限。")}
            </DialogDescription>
          </DialogHeader>
          <form className="space-y-4" onSubmit={submit}>
            <Input
              autoFocus
              value={dialog?.name ?? ""}
              maxLength={120}
              placeholder={t("文件夹名称")}
              onChange={(event) =>
                setDialog((current) =>
                  current ? { ...current, name: event.target.value } : current
                )
              }
            />
            {error ? <p className="text-sm text-destructive">{error}</p> : null}
            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                onClick={() => setDialog(null)}
              >
                {t("取消")}
              </Button>
              <Button type="submit" disabled={isSaving || !dialog?.name.trim()}>
                {t("保存")}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
      {confirmDialog}
    </>
  )
}
