"use client"

import * as React from "react"
import { FolderInputIcon, ListChecksIcon } from "lucide-react"

import { Button } from "@/components/ui/button"
import { useLanguage } from "@/contexts/language-provider"

type Props = {
  resourceIds: string[]
  selectedIds: string[]
  isManaging: boolean
  onSelectedIdsChange: (ids: string[]) => void
  onManagingChange: (isManaging: boolean) => void
  onMove: () => void
}

export function ResourceBulkMoveBar({
  resourceIds,
  selectedIds,
  isManaging,
  onSelectedIdsChange,
  onManagingChange,
  onMove,
}: Props) {
  const { t } = useLanguage()
  const selectAllRef = React.useRef<HTMLInputElement>(null)
  const selectedCount = resourceIds.filter((id) =>
    selectedIds.includes(id)
  ).length
  const allSelected = resourceIds.length > 0 && selectedCount === resourceIds.length

  React.useEffect(() => {
    if (selectAllRef.current) {
      selectAllRef.current.indeterminate = selectedCount > 0 && !allSelected
    }
  }, [allSelected, selectedCount])

  if (!resourceIds.length) return null

  if (!isManaging) {
    return (
      <Button
        type="button"
        variant="outline"
        size="sm"
        onClick={() => onManagingChange(true)}
      >
        <ListChecksIcon />
        {t("批量管理")}
      </Button>
    )
  }

  return (
    <div className="flex flex-wrap items-center gap-3">
      <label className="flex cursor-pointer items-center gap-2 text-sm text-muted-foreground">
        <input
          ref={selectAllRef}
          type="checkbox"
          className="size-4 accent-primary"
          checked={allSelected}
          onChange={(event) =>
            onSelectedIdsChange(event.target.checked ? resourceIds : [])
          }
        />
        {t("全选")}
      </label>
      <span className="text-sm text-muted-foreground">
        {t("已选择 {count} 项", { count: selectedCount })}
      </span>
      <Button
        type="button"
        variant="outline"
        size="sm"
        disabled={!selectedCount}
        onClick={onMove}
      >
        <FolderInputIcon />
        {t("移动到文件夹")}
      </Button>
      <Button
        type="button"
        variant="ghost"
        size="sm"
        onClick={() => {
          onSelectedIdsChange([])
          onManagingChange(false)
        }}
      >
        {t("取消")}
      </Button>
    </div>
  )
}
