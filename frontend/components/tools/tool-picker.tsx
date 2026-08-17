"use client"

import * as React from "react"
import {
  CheckIcon,
  LoaderCircleIcon,
  RefreshCwIcon,
  SearchIcon,
  WrenchIcon,
  XIcon,
} from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { useLanguage } from "@/contexts/language-provider"
import { listAllTools, type ToolRef, type ToolSummary } from "@/lib/api/tools"
import { getErrorMessage } from "@/lib/errors"
import {
  toolDisplayDescription,
  toolDisplayName,
  toolSourceDisplayName,
} from "@/lib/tool-display"

type ToolPickerProps = {
  open: boolean
  onOpenChange: (open: boolean) => void
  token: string
  workspaceId: string
  value: ToolRef[]
  onChange: (value: ToolRef[]) => void
  maxItems?: number
}

function sameTool(left: ToolRef, right: ToolRef) {
  return left.tool_id === right.tool_id && left.version_id === right.version_id
}

export function ToolPicker({
  open,
  onOpenChange,
  token,
  workspaceId,
  value,
  onChange,
  maxItems = 12,
}: ToolPickerProps) {
  const { t } = useLanguage()
  const [tools, setTools] = React.useState<ToolSummary[]>([])
  const [search, setSearch] = React.useState("")
  const [isLoading, setIsLoading] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)
  const requestRef = React.useRef(0)
  const searchRef = React.useRef<HTMLInputElement>(null)
  const returnFocusRef = React.useRef<HTMLElement | null>(null)

  const load = React.useCallback(async () => {
    const requestId = ++requestRef.current
    setIsLoading(true)
    setError(null)
    try {
      const items = await listAllTools(token, workspaceId)
      if (requestId === requestRef.current) setTools(items)
    } catch (nextError) {
      if (requestId === requestRef.current) {
        setTools([])
        setError(getErrorMessage(nextError, t))
      }
    } finally {
      if (requestId === requestRef.current) setIsLoading(false)
    }
  }, [token, t, workspaceId])

  React.useEffect(() => {
    if (!open) return
    // A new picker session starts with the full catalog.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setSearch("")
    void load()
    return () => {
      requestRef.current += 1
    }
  }, [load, open])

  const selected = React.useMemo(
    () => new Map(value.map((reference) => [reference.tool_id, reference])),
    [value]
  )
  const catalogById = React.useMemo(
    () => new Map(tools.map((tool) => [tool.id, tool])),
    [tools]
  )
  const query = search.trim().toLowerCase()
  const usableTools = tools.filter(
    (tool) =>
      tool.can_use &&
      tool.current_version_id &&
      tool.status === "active" &&
      tool.availability === "available" &&
      tool.function_name !== "inline_python" &&
      (!query ||
        `${toolDisplayName(tool, t)} ${toolDisplayDescription(tool, t)} ${toolSourceDisplayName(tool.source, t)}`
          .toLowerCase()
          .includes(query))
  )
  const unavailableBindings = value.filter((reference) => {
    const tool = catalogById.get(reference.tool_id)
    return (
      !tool ||
      !tool.can_use ||
      !tool.current_version_id ||
      tool.status !== "active" ||
      tool.availability !== "available"
    )
  })

  function remove(reference: ToolRef) {
    onChange(value.filter((item) => !sameTool(item, reference)))
  }

  function toggle(tool: ToolSummary) {
    const current = selected.get(tool.id)
    if (current) {
      remove(current)
      return
    }
    if (!tool.current_version_id || value.length >= maxItems) return
    onChange([
      ...value,
      { tool_id: tool.id, version_id: tool.current_version_id },
    ])
  }

  function upgrade(tool: ToolSummary) {
    if (!tool.current_version_id) return
    onChange(
      value.map((item) =>
        item.tool_id === tool.id
          ? { tool_id: tool.id, version_id: tool.current_version_id as string }
          : item
      )
    )
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className="max-h-[calc(100svh-2rem)] w-[calc(100%-2rem)] max-w-xl gap-0 overflow-hidden p-0"
        onOpenAutoFocus={(event) => {
          event.preventDefault()
          returnFocusRef.current =
            document.activeElement instanceof HTMLElement
              ? document.activeElement
              : null
          searchRef.current?.focus()
        }}
        onCloseAutoFocus={(event) => {
          if (!returnFocusRef.current) return
          event.preventDefault()
          returnFocusRef.current.focus()
          returnFocusRef.current = null
        }}
      >
        <DialogHeader className="border-b bg-muted/25 px-5 py-5 sm:px-6">
          <div className="flex items-start gap-3">
            <span className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-sky-500/10 text-sky-700 dark:text-sky-400">
              <WrenchIcon className="size-5" />
            </span>
            <div className="min-w-0 pt-0.5">
              <DialogTitle>{t("选择工具")}</DialogTitle>
              <DialogDescription className="mt-1.5 leading-5">
                {t("选择有使用权限且已发布的工具，最多 {value} 个。", {
                  value: maxItems,
                })}
              </DialogDescription>
            </div>
          </div>
        </DialogHeader>

        <div className="border-b px-3 py-3 sm:px-4">
          <div className="relative">
            <SearchIcon className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              ref={searchRef}
              role="searchbox"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              className="bg-muted/20 pl-9"
              placeholder={t("按名称、描述或来源搜索工具")}
              disabled={Boolean(error)}
            />
          </div>
        </div>

        <div className="max-h-[52svh] min-h-56 overflow-y-auto p-3 sm:p-4">
          {isLoading ? (
            <div className="flex min-h-48 items-center justify-center gap-2 text-sm text-muted-foreground">
              <LoaderCircleIcon className="size-4 animate-spin" />
              {t("正在加载工具")}
            </div>
          ) : error ? (
            <div className="flex min-h-48 flex-col items-center justify-center gap-3 rounded-xl border border-dashed bg-muted/20 p-6 text-center">
              <p className="font-medium">{t("工具加载失败")}</p>
              <p className="max-w-sm text-xs text-muted-foreground">{error}</p>
              <Button
                type="button"
                variant="outline"
                onClick={() => void load()}
              >
                <RefreshCwIcon />
                {t("重试")}
              </Button>
            </div>
          ) : (
            <div className="space-y-2">
              {unavailableBindings.map((reference) => {
                const tool = catalogById.get(reference.tool_id)
                return (
                  <div
                    key={`${reference.tool_id}:${reference.version_id}`}
                    className="flex items-center gap-3 rounded-xl border border-dashed bg-muted/20 p-3.5 opacity-80"
                  >
                    <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-muted text-muted-foreground">
                      <WrenchIcon className="size-4" />
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm font-medium">
                        {tool ? toolDisplayName(tool, t) : reference.tool_id}
                      </span>
                      <span className="mt-0.5 block text-xs text-muted-foreground">
                        {t("工具已不可用或授权已撤销")}
                      </span>
                    </span>
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon-sm"
                      aria-label={t("移除工具 {name}", {
                        name: tool
                          ? toolDisplayName(tool, t)
                          : reference.tool_id,
                      })}
                      onClick={() => remove(reference)}
                    >
                      <XIcon />
                    </Button>
                  </div>
                )
              })}

              {usableTools.map((tool) => {
                const reference = selected.get(tool.id)
                const checked = Boolean(reference)
                const hasNewVersion = Boolean(
                  reference && reference.version_id !== tool.current_version_id
                )
                const disabled = !checked && value.length >= maxItems
                return (
                  <label
                    key={tool.id}
                    className={`group flex items-start gap-3 rounded-xl border p-3.5 transition-[border-color,background-color,box-shadow] ${
                      checked
                        ? "border-foreground/20 bg-muted/70 shadow-xs"
                        : "border-border/70 hover:border-foreground/20 hover:bg-muted/35"
                    } ${disabled ? "cursor-not-allowed opacity-50" : "cursor-pointer"}`}
                  >
                    <input
                      type="checkbox"
                      className="sr-only"
                      aria-label={toolDisplayName(tool, t)}
                      checked={checked}
                      disabled={disabled}
                      onChange={() => toggle(tool)}
                    />
                    <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-sky-500/10 text-sky-700 dark:text-sky-400">
                      <WrenchIcon className="size-4" />
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="flex flex-wrap items-center gap-1.5">
                        <span className="truncate text-sm font-medium">
                          {toolDisplayName(tool, t)}
                        </span>
                        <Badge variant="outline" className="text-[10px]">
                          {toolSourceDisplayName(tool.source, t)}
                        </Badge>
                        {hasNewVersion ? (
                          <Badge variant="secondary" className="text-[10px]">
                            {t("已固定旧版本")}
                          </Badge>
                        ) : null}
                      </span>
                      {toolDisplayDescription(tool, t) ? (
                        <span className="mt-0.5 line-clamp-2 block text-xs leading-5 text-muted-foreground">
                          {toolDisplayDescription(tool, t)}
                        </span>
                      ) : null}
                      {hasNewVersion ? (
                        <Button
                          type="button"
                          variant="link"
                          size="sm"
                          className="mt-1 h-auto p-0 text-xs"
                          onClick={(event) => {
                            event.preventDefault()
                            upgrade(tool)
                          }}
                        >
                          {t("升级到当前版本")}
                        </Button>
                      ) : null}
                    </span>
                    <span
                      className={`mt-1 flex size-6 shrink-0 items-center justify-center rounded-full border transition-colors ${
                        checked
                          ? "border-foreground bg-foreground text-background"
                          : "border-muted-foreground/30 text-transparent group-hover:border-muted-foreground/60"
                      }`}
                      aria-hidden="true"
                    >
                      <CheckIcon className="size-3.5" />
                    </span>
                  </label>
                )
              })}

              {!unavailableBindings.length && !usableTools.length ? (
                <div className="flex min-h-48 items-center justify-center rounded-xl border border-dashed bg-muted/20 p-6 text-sm text-muted-foreground">
                  {query ? t("没有匹配的工具") : t("暂无可用工具")}
                </div>
              ) : null}
            </div>
          )}
        </div>

        <DialogFooter className="flex-col border-t bg-muted/20 px-5 py-4 sm:flex-row sm:items-center sm:justify-between sm:px-6">
          <p className="text-xs text-muted-foreground">
            {t("已选择 {value} 个工具", { value: value.length })}
          </p>
          <Button
            type="button"
            className="w-full sm:w-auto sm:min-w-20"
            onClick={() => onOpenChange(false)}
          >
            {t("完成")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
