"use client"

import * as React from "react"
import {
  LoaderCircleIcon,
  NetworkIcon,
  RefreshCwIcon,
  SearchIcon,
  WrenchIcon,
  XIcon,
} from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { BuiltinToolIcon } from "@/components/tools/builtin-tool-icon"
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
import {
  listAllTools,
  type ToolKind,
  type ToolRef,
  type ToolSummary,
} from "@/lib/api/tools"
import { getErrorMessage } from "@/lib/errors"
import { toolDisplayDescription } from "@/lib/tool-display"
import {
  groupTools,
  selectToolGroup,
  toolBindingGroups,
  toolGroupName,
  type ToolGroup,
} from "@/lib/tool-groups"
import { isRegularTool } from "@/lib/tool-visibility"

type ToolPickerProps = {
  open: boolean
  onOpenChange: (open: boolean) => void
  token: string
  workspaceId: string
  value: ToolRef[]
  onChange: (value: ToolRef[]) => void
}

const toolKinds = ["builtin", "mcp"] as const satisfies readonly ToolKind[]
type ToolCategory = "all" | (typeof toolKinds)[number]

const toolCategoryLabels = {
  all: "全部工具",
  builtin: "内置工具",
  mcp: "MCP 工具",
} as const

/**
 * Provides a dialog for selecting, removing, and upgrading workspace tools.
 *
 * @param open - Whether the tool picker dialog is open
 * @param onOpenChange - Callback invoked when the dialog visibility changes
 * @param token - Authentication token used to load tools
 * @param workspaceId - Workspace whose tools are loaded
 * @param value - Currently selected tool references
 * @param onChange - Callback invoked with the updated tool references
 */
export function ToolPicker({
  open,
  onOpenChange,
  token,
  workspaceId,
  value,
  onChange,
}: ToolPickerProps) {
  const { t } = useLanguage()
  const [tools, setTools] = React.useState<ToolSummary[]>([])
  const [search, setSearch] = React.useState("")
  const [category, setCategory] = React.useState<ToolCategory>("all")
  const [isLoading, setIsLoading] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)
  const requestRef = React.useRef(0)
  const searchRef = React.useRef<HTMLInputElement>(null)
  const optionRefs = React.useRef<Array<HTMLInputElement | null>>([])
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
    setCategory("all")
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
      (tool.kind === "builtin" || tool.kind === "mcp") &&
      tool.can_use &&
      tool.current_version_id &&
      tool.status === "active" &&
      tool.availability === "available" &&
      tool.policy_mode !== "disabled" &&
      tool.function_name !== "inline_python" &&
      tool.function_name !== "create_artifact" &&
      isRegularTool(tool.function_name)
  )
  const catalogGroups = groupTools(usableTools)
  const matchingGroups = catalogGroups.filter(
    (group) =>
      !query ||
      `${toolGroupName(group, t)} ${group.tools[0]!.kind === "mcp" ? t("MCP 工具") : toolDisplayDescription(group.tools[0]!, t)}`
        .toLowerCase()
        .includes(query)
  )
  const groups = toolKinds
    .map((kind) => ({
      kind,
      entries: matchingGroups.filter(
        (group) =>
          group.tools[0]!.kind === kind &&
          (category === "all" || category === kind)
      ),
    }))
    .filter((group) => group.entries.length > 0)
  const visibleTools = groups.flatMap((group) => group.entries)
  const unavailableBindings = value.filter((reference) => {
    const tool = catalogById.get(reference.tool_id)
    return (
      (!tool || isRegularTool(tool.function_name)) &&
      (!tool ||
        !toolKinds.includes(tool.kind) ||
        !tool.can_use ||
        !tool.current_version_id ||
        tool.status !== "active" ||
        tool.availability !== "available" ||
        tool.policy_mode === "disabled")
    )
  })
  const unavailableGroups = toolBindingGroups(unavailableBindings, tools, t)
  const availableGroupIds = new Set(catalogGroups.map((group) => group.id))
  const visibleUnavailableBindings =
    category === "all"
      ? unavailableGroups.filter((group) => !availableGroupIds.has(group.id))
      : []
  const selectedGroups = new Map(
    toolBindingGroups(value, tools, t).map((group) => [group.id, group])
  )

  function toggle(group: ToolGroup) {
    const allSelected = group.tools.every((tool) => selected.has(tool.id))
    if (allSelected) {
      const ids = new Set(
        selectedGroups
          .get(group.id)
          ?.references.map((reference) => reference.tool_id)
      )
      onChange(value.filter((reference) => !ids.has(reference.tool_id)))
    } else {
      onChange(selectToolGroup(value, group.tools, true))
    }
  }

  function upgrade(group: ToolGroup) {
    const currentVersions = new Map(
      group.tools.map((tool) => [tool.id, tool.current_version_id])
    )
    onChange(
      value.map((item) => {
        const versionId = currentVersions.get(item.tool_id)
        return versionId
          ? { tool_id: item.tool_id, version_id: versionId }
          : item
      })
    )
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className="flex max-h-[calc(100svh-2rem)] w-[calc(100%-2rem)] max-w-xl flex-col gap-0 overflow-hidden p-0"
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
        <DialogHeader className="shrink-0 border-b bg-muted/25 px-5 py-5 sm:px-6">
          <div className="flex items-start gap-3">
            <span className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-sky-500/10 text-sky-700 dark:text-sky-400">
              <WrenchIcon className="size-5" />
            </span>
            <div className="min-w-0 pt-0.5">
              <DialogTitle>{t("选择工具")}</DialogTitle>
              <DialogDescription className="mt-1.5 leading-5">
                {t("选择有使用权限且已发布的工具。")}
              </DialogDescription>
            </div>
          </div>
        </DialogHeader>

        <div className="shrink-0 border-b px-3 py-3 sm:px-4">
          <div className="relative">
            <SearchIcon className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              ref={searchRef}
              role="searchbox"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              onKeyDown={(event) => {
                if (event.key !== "ArrowDown" || !visibleTools.length) return
                event.preventDefault()
                optionRefs.current[0]?.focus()
              }}
              className="bg-muted/20 pl-9"
              placeholder={t("按名称、描述或来源搜索工具")}
              disabled={Boolean(error)}
            />
          </div>
          {!isLoading && !error ? (
            <div
              role="group"
              aria-label={t("工具分类")}
              className="mt-3 flex gap-1 overflow-x-auto rounded-lg bg-muted/60 p-1"
            >
              {(["all", ...toolKinds] as const).map((kind) => (
                <button
                  key={kind}
                  type="button"
                  aria-label={t(toolCategoryLabels[kind])}
                  aria-pressed={category === kind}
                  onClick={() => setCategory(kind)}
                  className={`flex h-8 shrink-0 items-center gap-1.5 rounded-md px-2.5 text-xs font-medium whitespace-nowrap transition-colors outline-none focus-visible:ring-2 focus-visible:ring-ring ${
                    category === kind
                      ? "bg-background text-foreground shadow-xs"
                      : "text-muted-foreground hover:text-foreground"
                  }`}
                >
                  {t(toolCategoryLabels[kind])}
                  <span aria-hidden="true" className="text-[11px] opacity-65">
                    {kind === "all"
                      ? catalogGroups.length
                      : catalogGroups.filter(
                          (group) => group.tools[0]!.kind === kind
                        ).length}
                  </span>
                </button>
              ))}
            </div>
          ) : null}
        </div>

        <div className="max-h-[52svh] min-h-0 flex-1 overflow-y-auto p-3 sm:p-4">
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
              {visibleUnavailableBindings.length ? (
                <h3 className="px-1 text-xs font-medium text-muted-foreground">
                  {t("已选但不可用")}
                </h3>
              ) : null}
              {visibleUnavailableBindings.map((group) => {
                const tool = catalogById.get(group.references[0]!.tool_id)
                return (
                  <div
                    key={group.id}
                    className="flex items-center gap-3 rounded-xl border border-dashed bg-muted/20 p-3.5 opacity-80"
                  >
                    <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-muted text-muted-foreground">
                      <BuiltinToolIcon
                        functionName={tool?.function_name}
                        className="size-4"
                      />
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm font-medium">
                        {group.name}
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
                        name: group.name,
                      })}
                      title={t("移除工具 {name}", {
                        name: group.name,
                      })}
                      onClick={() => {
                        const ids = new Set(
                          group.references.map((reference) => reference.tool_id)
                        )
                        onChange(
                          value.filter(
                            (reference) => !ids.has(reference.tool_id)
                          )
                        )
                      }}
                    >
                      <XIcon />
                    </Button>
                  </div>
                )
              })}

              {groups.map((group) => (
                <section
                  key={group.kind}
                  aria-label={t(toolCategoryLabels[group.kind])}
                  className="space-y-2"
                >
                  <h3 className="flex items-center gap-2 px-1 pt-2 text-xs font-medium text-muted-foreground">
                    {t(toolCategoryLabels[group.kind])}
                    <span className="tabular-nums">{group.entries.length}</span>
                  </h3>
                  {group.entries.map((entry) => {
                    const tool = entry.tools[0]!
                    const name = toolGroupName(entry, t)
                    const index = visibleTools.indexOf(entry)
                    const checked = entry.tools.every((item) =>
                      selected.has(item.id)
                    )
                    const partiallySelected =
                      !checked && selectedGroups.has(entry.id)
                    const hasUnavailableBindings = unavailableGroups.some(
                      (group) => group.id === entry.id
                    )
                    const hasNewVersion = entry.tools.some((item) => {
                      const reference = selected.get(item.id)
                      return (
                        reference &&
                        reference.version_id !== item.current_version_id
                      )
                    })
                    return (
                      <div
                        key={entry.id}
                        className={`group flex items-start gap-3 rounded-xl border p-3.5 transition-[border-color,background-color,box-shadow] focus-within:ring-2 focus-within:ring-ring ${
                          checked
                            ? "border-foreground/20 bg-muted/70 shadow-xs"
                            : "border-border/70 hover:border-foreground/20 hover:bg-muted/35"
                        } cursor-pointer`}
                        onClick={(event) => {
                          if (
                            event.target instanceof Element &&
                            event.target.closest("button, input")
                          ) {
                            return
                          }
                          toggle(entry)
                        }}
                      >
                        <input
                          ref={(element) => {
                            optionRefs.current[index] = element
                            if (element)
                              element.indeterminate = partiallySelected
                          }}
                          type="checkbox"
                          className="mt-1 size-5 shrink-0 accent-foreground"
                          aria-label={name}
                          aria-checked={partiallySelected ? "mixed" : checked}
                          checked={checked}
                          onChange={() => toggle(entry)}
                          onKeyDown={(event) => {
                            if (event.key === "Enter") {
                              event.preventDefault()
                              toggle(entry)
                              return
                            }
                            if (
                              !["ArrowDown", "ArrowUp", "Home", "End"].includes(
                                event.key
                              )
                            ) {
                              return
                            }
                            event.preventDefault()
                            const nextIndex =
                              event.key === "Home"
                                ? 0
                                : event.key === "End"
                                  ? visibleTools.length - 1
                                  : event.key === "ArrowDown"
                                    ? (index + 1) % visibleTools.length
                                    : (index - 1 + visibleTools.length) %
                                      visibleTools.length
                            optionRefs.current[nextIndex]?.focus()
                          }}
                        />
                        <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-sky-500/10 text-sky-700 dark:text-sky-400">
                          <BuiltinToolIcon
                            functionName={tool.function_name}
                            fallback={
                              tool.kind === "mcp" ? NetworkIcon : undefined
                            }
                            className="size-4"
                          />
                        </span>
                        <span className="min-w-0 flex-1">
                          <span className="flex flex-wrap items-center gap-1.5">
                            <span className="truncate text-sm font-medium">
                              {name}
                            </span>
                            {tool.kind !== "builtin" ? (
                              <Badge variant="outline" className="text-[10px]">
                                {t("MCP 工具")}
                              </Badge>
                            ) : null}
                            {hasNewVersion ? (
                              <Badge
                                variant="secondary"
                                className="text-[10px]"
                              >
                                {t("已固定旧版本")}
                              </Badge>
                            ) : null}
                          </span>
                          {hasUnavailableBindings ? (
                            <span className="mt-1 block text-xs text-muted-foreground">
                              {t("工具已不可用或授权已撤销")}
                            </span>
                          ) : null}
                          {tool.kind === "builtin" &&
                          toolDisplayDescription(tool, t) ? (
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
                                event.stopPropagation()
                                upgrade(entry)
                              }}
                            >
                              {t("升级到当前版本")}
                            </Button>
                          ) : null}
                        </span>
                      </div>
                    )
                  })}
                </section>
              ))}

              {!visibleUnavailableBindings.length && !visibleTools.length ? (
                <div className="flex min-h-48 items-center justify-center rounded-xl border border-dashed bg-muted/20 p-6 text-sm text-muted-foreground">
                  {query ? t("没有匹配的工具") : t("暂无可用工具")}
                </div>
              ) : null}
            </div>
          )}
        </div>

        <DialogFooter className="shrink-0 flex-col border-t bg-muted/20 px-5 py-4 sm:flex-row sm:items-center sm:justify-between sm:px-6">
          <p className="text-xs text-muted-foreground">
            {t("已选择 {value} 个工具", {
              value: toolBindingGroups(
                value.filter((reference) => {
                  const tool = catalogById.get(reference.tool_id)
                  return !tool || isRegularTool(tool.function_name)
                }),
                tools,
                t
              ).length,
            })}
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
