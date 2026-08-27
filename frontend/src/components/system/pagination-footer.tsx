"use client"

import { CheckIcon, ChevronDownIcon } from "lucide-react"

import { useLanguage } from "@/contexts/language-provider"
import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"

export const SYSTEM_PAGE_SIZES = [20, 50, 100] as const
export type SystemPageSize = (typeof SYSTEM_PAGE_SIZES)[number]

export function SystemPagination({
  page,
  pageSize,
  itemCount,
  total,
  hasNext,
  onPageChange,
  onPageSizeChange,
}: {
  page: number
  pageSize: SystemPageSize
  itemCount: number
  total?: number
  hasNext: boolean
  onPageChange: (page: number) => void
  onPageSizeChange: (pageSize: SystemPageSize) => void
}) {
  const { t } = useLanguage()
  const currentPage = Math.max(1, page)
  const hasPrevious = currentPage > 1
  const from = itemCount ? (currentPage - 1) * pageSize + 1 : 0
  const to = itemCount ? from + itemCount - 1 : 0
  const totalPages = total === undefined
    ? Math.max(currentPage, hasNext ? currentPage + 1 : currentPage)
    : Math.max(1, Math.ceil(total / pageSize))
  const pages = Array.from({ length: totalPages }, (_, index) => index + 1).filter(
    (candidate) =>
      candidate === 1 ||
      candidate === totalPages ||
      Math.abs(candidate - currentPage) <= 1
  )

  if (!itemCount && !hasPrevious && !hasNext) return null

  return (
    <div className="flex flex-wrap items-center justify-between gap-3 border-t px-1 pt-3 text-sm">
      <div className="flex items-center gap-2">
        <span className="text-muted-foreground">
          {total === undefined
            ? t("显示 {from}-{to}，共 {total} 条", {
                from,
                to,
                total: hasNext ? `${to}+` : to,
              })
            : t("共 {value} 条", { value: total })}
        </span>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button type="button" variant="outline" size="sm" className="h-7 gap-2">
              <span>{t("每页 {value} 条", { value: pageSize })}</span>
              <ChevronDownIcon className="size-3.5" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="start" className="w-36">
            {SYSTEM_PAGE_SIZES.map((option) => (
              <DropdownMenuItem
                key={option}
                className="justify-between"
                onSelect={() => onPageSizeChange(option)}
              >
                {t("每页 {value} 条", { value: option })}
                {pageSize === option ? <CheckIcon className="size-3.5 text-primary" /> : null}
              </DropdownMenuItem>
            ))}
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
      <div className="flex items-center gap-2">
        <Button type="button" variant="outline" size="sm" disabled={!hasPrevious} onClick={() => onPageChange(currentPage - 1)}>
          {t("上一页")}
        </Button>
        <div className="flex items-center gap-1">
          {pages.map((candidate, index) => (
            <div key={candidate} className="flex items-center gap-1">
              {index > 0 && candidate - pages[index - 1] > 1 ? (
                <span className="px-1 text-muted-foreground">…</span>
              ) : null}
              <Button
                type="button"
                variant={candidate === currentPage ? "default" : "outline"}
                size="icon"
                className="size-7"
                aria-current={candidate === currentPage ? "page" : undefined}
                onClick={() => onPageChange(candidate)}
              >
                {candidate}
              </Button>
            </div>
          ))}
        </div>
        <Button type="button" variant="outline" size="sm" disabled={!hasNext} onClick={() => onPageChange(currentPage + 1)}>
          {t("下一页")}
        </Button>
      </div>
    </div>
  )
}
