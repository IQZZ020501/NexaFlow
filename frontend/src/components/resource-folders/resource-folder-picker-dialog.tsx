"use client"

import * as React from "react"
import { FolderIcon, FolderOpenIcon, LoaderCircleIcon } from "lucide-react"

import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { useLanguage } from "@/contexts/language-provider"
import { getErrorMessage } from "@/lib/errors"
import type { ResourceFolder } from "@/lib/api/resource-folders"

type Props = {
  open: boolean
  folders: ResourceFolder[]
  currentFolderId: string | null
  onOpenChange: (open: boolean) => void
  onMove: (folderId: string | null) => Promise<void>
}

function flattenFolders(
  folders: ResourceFolder[],
  parentId: string | null,
  depth = 0
): Array<{ folder: ResourceFolder; depth: number }> {
  return folders
    .filter((folder) => folder.parent_id === parentId)
    .sort((left, right) => left.name.localeCompare(right.name))
    .flatMap((folder) => [
      { folder, depth },
      ...flattenFolders(folders, folder.id, depth + 1),
    ])
}

export function ResourceFolderPickerDialog({
  open,
  folders,
  currentFolderId,
  onOpenChange,
  onMove,
}: Props) {
  const { t } = useLanguage()
  const [busyFolderId, setBusyFolderId] = React.useState<
    string | null | undefined
  >()
  const [error, setError] = React.useState<string | null>(null)

  async function move(folderId: string | null) {
    if (folderId === currentFolderId) return
    setBusyFolderId(folderId)
    setError(null)
    try {
      await onMove(folderId)
      onOpenChange(false)
    } catch (nextError) {
      setError(getErrorMessage(nextError, t))
    } finally {
      setBusyFolderId(undefined)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("移动到文件夹")}</DialogTitle>
          <DialogDescription>{t("选择资源要归入的目录。")}</DialogDescription>
        </DialogHeader>
        <div className="max-h-80 space-y-1 overflow-y-auto">
          <Button
            type="button"
            variant={currentFolderId === null ? "secondary" : "ghost"}
            className="w-full justify-start"
            disabled={currentFolderId === null || busyFolderId !== undefined}
            onClick={() => void move(null)}
          >
            {busyFolderId === null ? (
              <LoaderCircleIcon className="animate-spin" />
            ) : currentFolderId === null ? (
              <FolderOpenIcon />
            ) : (
              <FolderIcon />
            )}
            {t("根目录")}
          </Button>
          {flattenFolders(folders, null).map(({ folder, depth }) => (
            <Button
              key={folder.id}
              type="button"
              variant={currentFolderId === folder.id ? "secondary" : "ghost"}
              className="w-full justify-start"
              style={{ paddingLeft: `${10 + depth * 16}px` }}
              disabled={
                currentFolderId === folder.id || busyFolderId !== undefined
              }
              onClick={() => void move(folder.id)}
            >
              {busyFolderId === folder.id ? (
                <LoaderCircleIcon className="animate-spin" />
              ) : currentFolderId === folder.id ? (
                <FolderOpenIcon />
              ) : (
                <FolderIcon />
              )}
              <span className="truncate">{folder.name}</span>
            </Button>
          ))}
        </div>
        {error ? <p className="text-sm text-destructive">{error}</p> : null}
      </DialogContent>
    </Dialog>
  )
}
