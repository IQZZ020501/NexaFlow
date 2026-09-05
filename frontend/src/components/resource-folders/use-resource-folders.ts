"use client"

import * as React from "react"

import { useLanguage } from "@/contexts/language-provider"
import { useSession } from "@/contexts/session-context"
import { getErrorMessage } from "@/lib/errors"
import {
  createResourceFolder,
  deleteResourceFolder,
  listResourceFolders,
  moveResourceToFolder,
  moveResourcesToFolder,
  updateResourceFolder,
  type FolderResourceType,
  type ResourceFolder,
} from "@/lib/api/resource-folders"

export function useResourceFolders(resourceType: FolderResourceType) {
  const { t } = useLanguage()
  const { token, selectedWorkspaceId, notify } = useSession()
  const [folders, setFolders] = React.useState<ResourceFolder[]>([])
  const [selectedFolderId, setSelectedFolderId] = React.useState<string | null>(
    null
  )
  const [isLoading, setIsLoading] = React.useState(false)

  const load = React.useCallback(async () => {
    if (!token || !selectedWorkspaceId) {
      setFolders([])
      setSelectedFolderId(null)
      return
    }
    setIsLoading(true)
    try {
      setFolders(
        await listResourceFolders(token, selectedWorkspaceId, resourceType)
      )
    } catch (error) {
      setFolders([])
      notify("error", getErrorMessage(error, t))
    } finally {
      setIsLoading(false)
    }
  }, [notify, resourceType, selectedWorkspaceId, t, token])

  React.useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setSelectedFolderId(null)
    void load()
  }, [load, selectedWorkspaceId])

  async function create(name: string, parentId: string | null) {
    if (!token || !selectedWorkspaceId) return
    const folder = await createResourceFolder(token, selectedWorkspaceId, {
      name,
      resource_type: resourceType,
      parent_id: parentId,
    })
    setFolders((current) => [...current, folder])
    notify("success", t("文件夹已创建"))
  }

  async function rename(folderId: string, name: string) {
    if (!token || !selectedWorkspaceId) return
    const folder = await updateResourceFolder(
      token,
      selectedWorkspaceId,
      folderId,
      { name }
    )
    setFolders((current) =>
      current.map((item) => (item.id === folder.id ? folder : item))
    )
    notify("success", t("文件夹已重命名"))
  }

  async function remove(folderId: string) {
    if (!token || !selectedWorkspaceId) return
    const folder = folders.find((item) => item.id === folderId)
    await deleteResourceFolder(token, selectedWorkspaceId, folderId)
    setFolders((current) =>
      current
        .filter((item) => item.id !== folderId)
        .map((item) =>
          item.parent_id === folderId
            ? { ...item, parent_id: folder?.parent_id ?? null }
            : item
        )
    )
    if (selectedFolderId === folderId) {
      setSelectedFolderId(folder?.parent_id ?? null)
    }
    notify("success", t("文件夹已删除"))
    return folder?.parent_id ?? null
  }

  async function move(resourceId: string, folderId: string | null) {
    if (!token || !selectedWorkspaceId) return
    await moveResourceToFolder(token, selectedWorkspaceId, {
      resource_type: resourceType,
      resource_id: resourceId,
      folder_id: folderId,
    })
    notify("success", t("已移动到文件夹"))
  }

  async function moveMany(resourceIds: string[], folderId: string | null) {
    if (!token || !selectedWorkspaceId || !resourceIds.length) return
    await moveResourcesToFolder(token, selectedWorkspaceId, {
      resource_type: resourceType,
      resource_ids: resourceIds,
      folder_id: folderId,
    })
    notify("success", t("已移动到文件夹"))
  }

  return {
    folders,
    selectedFolderId,
    setSelectedFolderId,
    isLoading,
    create,
    rename,
    remove,
    move,
    moveMany,
  }
}

export type ResourceFoldersState = ReturnType<typeof useResourceFolders>
