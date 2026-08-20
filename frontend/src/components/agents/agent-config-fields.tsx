"use client"

import * as React from "react"
import ModelIcon from "@lobehub/icons/es/features/ModelIcon"
import {
  BotIcon,
  CheckIcon,
  ChevronDownIcon,
  ChevronRightIcon,
  DatabaseIcon,
  PlusIcon,
  SearchIcon,
  SlidersHorizontalIcon,
  WorkflowIcon,
  WrenchIcon,
} from "lucide-react"

import { ToolPicker } from "@/components/tools/tool-picker"
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
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { Field, FieldGroup, FieldLabel } from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import type { TFunction } from "@/i18n"
import type { KnowledgeBase } from "@/lib/api/knowledge"
import type { RegisteredModel } from "@/lib/api/llm"
import type { ToolSummary } from "@/lib/api/tools"
import { toolDisplayName } from "@/lib/tool-display"

import type { AgentFormState } from "./agents-page"

type AgentConfigFieldsProps = {
  form: AgentFormState
  setForm: React.Dispatch<React.SetStateAction<AgentFormState>>
  models: RegisteredModel[]
  knowledgeBases: KnowledgeBase[]
  tools: ToolSummary[]
  token: string
  workspaceId: string
  hasLegacyToolBindings?: boolean
  readOnly: boolean
  t: TFunction
}

export function AgentConfigFields({
  form,
  setForm,
  models,
  knowledgeBases,
  tools,
  token,
  workspaceId,
  hasLegacyToolBindings = false,
  readOnly,
  t,
}: AgentConfigFieldsProps) {
  const [resourcePicker, setResourcePicker] = React.useState<
    "knowledge" | null
  >(null)
  const [isKnowledgeOpen, setIsKnowledgeOpen] = React.useState(false)
  const [isToolsOpen, setIsToolsOpen] = React.useState(false)
  const [isToolPickerOpen, setIsToolPickerOpen] = React.useState(false)
  const [knowledgeSearch, setKnowledgeSearch] = React.useState("")

  const configurableModels = models.filter(
    (model) =>
      model.model_type === "LLM" &&
      (model.status === "active" || model.id === form.modelId)
  )
  const activeKnowledgeBases = knowledgeBases.filter(
    (knowledgeBase) => knowledgeBase.status === "active"
  )
  const filteredKnowledgeBases = React.useMemo(() => {
    const query = knowledgeSearch.trim().toLowerCase()
    if (!query) return activeKnowledgeBases
    return activeKnowledgeBases.filter((knowledgeBase) =>
      `${knowledgeBase.name} ${knowledgeBase.description}`
        .toLowerCase()
        .includes(query)
    )
  }, [activeKnowledgeBases, knowledgeSearch])
  const selectedModel = configurableModels.find(
    (model) => model.id === form.modelId
  )
  const selectedKnowledgeBaseNames = form.knowledgeBaseIds
    .map((id) => knowledgeBases.find((item) => item.id === id)?.name)
    .filter((name): name is string => Boolean(name))
  const selectedToolNames = form.tools.map((reference) => {
    const tool = tools.find((item) => item.id === reference.tool_id)
    return tool ? toolDisplayName(tool, t) : reference.tool_id
  })

  function toggleKnowledgeBase(id: string) {
    setForm((current) => {
      const selected = current.knowledgeBaseIds.includes(id)
      if (!selected && current.knowledgeBaseIds.length >= 4) return current
      return {
        ...current,
        knowledgeBaseIds: selected
          ? current.knowledgeBaseIds.filter((item) => item !== id)
          : [...current.knowledgeBaseIds, id],
      }
    })
  }

  return (
    <>
      <FieldGroup className="gap-3">
        <section className="rounded-xl border bg-background p-4 shadow-xs">
          <div className="mb-4 flex items-center gap-3">
            <span className="flex size-9 items-center justify-center rounded-lg bg-foreground text-background">
              {form.appType === "workflow" ? (
                <WorkflowIcon className="size-4" />
              ) : (
                <BotIcon className="size-4" />
              )}
            </span>
            <div>
              <h3 className="text-sm font-semibold">{t("基本信息")}</h3>
              <p className="text-xs text-muted-foreground">
                {t(
                  !form.id
                    ? "填写应用名称、描述和模型。"
                    : form.appType === "workflow"
                      ? "配置工作流的默认模型。"
                      : "配置 Agent 使用的模型、知识库和工具。"
                )}
              </p>
            </div>
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field>
              <FieldLabel htmlFor="agent-name">
                {t(form.appType === "workflow" ? "工作流名称" : "Agent 名称")}
              </FieldLabel>
              <Input
                id="agent-name"
                value={form.name}
                onChange={(event) =>
                  setForm((current) => ({
                    ...current,
                    name: event.target.value,
                  }))
                }
                maxLength={120}
                disabled={readOnly}
                required
              />
            </Field>

            <Field>
              <FieldLabel htmlFor="agent-model">{t("选择模型")}</FieldLabel>
              <DropdownMenu modal={false}>
                <DropdownMenuTrigger asChild>
                  <Button
                    id="agent-model"
                    type="button"
                    variant="outline"
                    className="h-9 w-full justify-between px-3 font-normal"
                    disabled={readOnly}
                  >
                    <span className="flex min-w-0 flex-1 items-center gap-2 truncate text-left">
                      {selectedModel ? (
                        <ModelIcon
                          model={selectedModel.model_name}
                          size={16}
                          type="color"
                          className="shrink-0"
                        />
                      ) : null}
                      <span className="min-w-0 truncate">
                        {selectedModel?.name ?? t("选择模型")}
                      </span>
                    </span>
                    <ChevronDownIcon data-icon="inline-end" />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent
                  align="start"
                  className="max-h-72 w-(--radix-dropdown-menu-trigger-width) min-w-0 overflow-y-auto"
                >
                  <DropdownMenuGroup>
                    {configurableModels.map((model) => (
                      <DropdownMenuItem
                        key={model.id}
                        className="justify-between"
                        onSelect={() =>
                          setForm((current) => ({
                            ...current,
                            modelId: model.id,
                          }))
                        }
                      >
                        <span className="flex min-w-0 items-center gap-2 truncate">
                          <ModelIcon
                            model={model.model_name}
                            size={16}
                            type="color"
                            className="shrink-0"
                          />
                          <span className="min-w-0 truncate">{model.name}</span>
                        </span>
                        {model.id === form.modelId ? (
                          <CheckIcon className="text-primary" />
                        ) : null}
                      </DropdownMenuItem>
                    ))}
                  </DropdownMenuGroup>
                </DropdownMenuContent>
              </DropdownMenu>
            </Field>

            <Field className="sm:col-span-2">
              <FieldLabel htmlFor="agent-description">{t("描述")}</FieldLabel>
              <textarea
                id="agent-description"
                value={form.description}
                onChange={(event) =>
                  setForm((current) => ({
                    ...current,
                    description: event.target.value,
                  }))
                }
                className="min-h-20 w-full resize-y rounded-lg border border-input bg-muted/20 px-3 py-2 text-sm leading-6 shadow-xs transition-[color,box-shadow] outline-none placeholder:text-muted-foreground focus-visible:border-ring focus-visible:bg-background focus-visible:ring-3 focus-visible:ring-ring/50 disabled:pointer-events-none disabled:cursor-not-allowed disabled:opacity-50 dark:bg-input/20"
                placeholder={t(
                  form.appType === "workflow"
                    ? "说明工作流的用途和适用场景。"
                    : "说明 Agent 的用途和适用场景。"
                )}
                maxLength={500}
                rows={3}
                disabled={readOnly}
              />
            </Field>
          </div>
        </section>

        {form.id && form.appType === "agent" ? (
          <section className="rounded-xl border bg-background p-4 shadow-xs">
            <div className="mb-3 flex items-center gap-2">
              <SlidersHorizontalIcon className="size-4 text-muted-foreground" />
              <FieldLabel htmlFor="agent-instructions">
                {t("系统提示词")}
              </FieldLabel>
            </div>
            <textarea
              id="agent-instructions"
              value={form.instructions}
              onChange={(event) =>
                setForm((current) => ({
                  ...current,
                  instructions: event.target.value,
                }))
              }
              className="min-h-44 w-full resize-y rounded-lg border border-input bg-muted/20 px-3 py-3 text-sm leading-6 shadow-xs transition-[color,box-shadow] outline-none placeholder:text-muted-foreground focus-visible:border-ring focus-visible:bg-background focus-visible:ring-3 focus-visible:ring-ring/50 disabled:pointer-events-none disabled:cursor-not-allowed disabled:opacity-50 dark:bg-input/20"
              placeholder={t("描述 Agent 的角色、回答方式和约束。")}
              maxLength={8000}
              rows={7}
              disabled={readOnly}
            />
          </section>
        ) : null}

        {form.id && form.appType === "agent" ? (
          <section className="rounded-xl border bg-background shadow-xs">
            <div className="flex items-center gap-2 px-4 py-3">
              <button
                type="button"
                className="flex min-w-0 flex-1 items-center gap-3 rounded-md text-left outline-none focus-visible:ring-2 focus-visible:ring-ring"
                aria-expanded={isKnowledgeOpen}
                onClick={() => setIsKnowledgeOpen((current) => !current)}
              >
                <span className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-emerald-500/10 text-emerald-700 dark:text-emerald-400">
                  <DatabaseIcon className="size-4" />
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block text-sm font-medium">
                    {t("关联知识库")}
                  </span>
                  <span className="block text-xs text-muted-foreground">
                    {t("{value} 个知识库", {
                      value: form.knowledgeBaseIds.length,
                    })}
                  </span>
                </span>
                <ChevronRightIcon
                  className={`size-4 text-muted-foreground transition-transform ${isKnowledgeOpen ? "rotate-90" : ""}`}
                />
              </button>
              <Button
                type="button"
                variant="outline"
                size="icon-sm"
                aria-label={t("关联知识库")}
                title={t("关联知识库")}
                disabled={readOnly}
                onClick={() => {
                  setKnowledgeSearch("")
                  setResourcePicker("knowledge")
                }}
              >
                <PlusIcon />
              </Button>
            </div>
            {isKnowledgeOpen ? (
              <div className="grid gap-3 border-t px-4 py-3">
                {form.appType === "agent" ? (
                  <fieldset
                    disabled={readOnly || form.knowledgeBaseIds.length === 0}
                  >
                    <legend className="mb-2 text-xs font-medium text-muted-foreground">
                      {t("知识检索策略")}
                    </legend>
                    <div className="grid grid-cols-2 rounded-lg bg-muted p-1">
                      {(["required", "agentic"] as const).map((mode) => (
                        <button
                          key={mode}
                          type="button"
                          className={`min-h-9 rounded-md px-3 py-1.5 text-xs font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${
                            form.knowledgeQueryMode === mode
                              ? "bg-background text-foreground shadow-xs"
                              : "text-muted-foreground hover:text-foreground"
                          }`}
                          aria-pressed={form.knowledgeQueryMode === mode}
                          onClick={() =>
                            setForm((current) => ({
                              ...current,
                              knowledgeQueryMode: mode,
                            }))
                          }
                        >
                          {t(
                            mode === "required"
                              ? "每次先检索（推荐）"
                              : "Agent 按需检索"
                          )}
                        </button>
                      ))}
                    </div>
                  </fieldset>
                ) : null}
                {selectedKnowledgeBaseNames.length > 0 ? (
                  <div className="flex flex-wrap gap-1.5">
                    {selectedKnowledgeBaseNames.map((name) => (
                      <Badge
                        key={name}
                        variant="secondary"
                        className="font-normal"
                      >
                        {name}
                      </Badge>
                    ))}
                  </div>
                ) : (
                  <p className="text-sm text-muted-foreground">
                    {t("关联的知识库展示在这里")}
                  </p>
                )}
              </div>
            ) : null}
          </section>
        ) : null}

        {form.id && form.appType === "agent" ? (
          <section className="rounded-xl border bg-background shadow-xs">
            <div className="flex items-center gap-2 px-4 py-3">
              <button
                type="button"
                className="flex min-w-0 flex-1 items-center gap-3 rounded-md text-left outline-none focus-visible:ring-2 focus-visible:ring-ring"
                aria-expanded={isToolsOpen}
                onClick={() => setIsToolsOpen((current) => !current)}
              >
                <span className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-sky-500/10 text-sky-700 dark:text-sky-400">
                  <WrenchIcon className="size-4" />
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block text-sm font-medium">{t("工具")}</span>
                  <span className="block text-xs text-muted-foreground">
                    {t("{value} 个工具", { value: form.tools.length })}
                  </span>
                </span>
                <ChevronRightIcon
                  className={`size-4 text-muted-foreground transition-transform ${isToolsOpen ? "rotate-90" : ""}`}
                />
              </button>
              <Button
                type="button"
                variant="outline"
                size="icon-sm"
                aria-label={t("工具")}
                title={t("工具")}
                disabled={readOnly}
                onClick={() => setIsToolPickerOpen(true)}
              >
                <PlusIcon />
              </Button>
            </div>
            {isToolsOpen ? (
              <div className="border-t px-4 py-3">
                {hasLegacyToolBindings && form.tools.length === 0 ? (
                  <p className="mb-3 rounded-lg border border-amber-500/30 bg-amber-500/10 p-2.5 text-xs leading-5 text-amber-800 dark:text-amber-300">
                    {t(
                      "此 Agent 仍绑定旧版 MCP 工具；旧绑定不会继续写入，请重新选择需要保留的工具。"
                    )}
                  </p>
                ) : null}
                {selectedToolNames.length > 0 ? (
                  <div className="flex flex-wrap gap-1.5">
                    {selectedToolNames.map((name, index) => (
                      <Badge
                        key={`${form.tools[index]?.tool_id}:${form.tools[index]?.version_id}`}
                        variant="secondary"
                        className="font-normal"
                      >
                        {name}
                      </Badge>
                    ))}
                  </div>
                ) : (
                  <p className="text-sm text-muted-foreground">
                    {t("选择的工具展示在这里")}
                  </p>
                )}
              </div>
            ) : null}
          </section>
        ) : null}

        {form.id ? (
          <section className="rounded-xl border bg-background p-4 shadow-xs">
            <Field>
              <div className="flex items-center gap-2">
                <span className="flex size-8 items-center justify-center rounded-lg bg-muted">
                  <SlidersHorizontalIcon className="size-4 text-muted-foreground" />
                </span>
                <FieldLabel htmlFor="agent-status">{t("状态")}</FieldLabel>
              </div>
              <DropdownMenu modal={false}>
                <DropdownMenuTrigger asChild>
                  <Button
                    id="agent-status"
                    type="button"
                    variant="outline"
                    className="h-9 w-full justify-between px-3 font-normal"
                    disabled={readOnly}
                  >
                    <span>
                      {t(form.status === "active" ? "已启用" : "已停用")}
                    </span>
                    <ChevronDownIcon data-icon="inline-end" />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent
                  align="start"
                  className="w-(--radix-dropdown-menu-trigger-width)"
                >
                  <DropdownMenuGroup>
                    {(["active", "disabled"] as const).map((status) => (
                      <DropdownMenuItem
                        key={status}
                        className="justify-between"
                        onSelect={() =>
                          setForm((current) => ({ ...current, status }))
                        }
                      >
                        <span>
                          {t(status === "active" ? "已启用" : "已停用")}
                        </span>
                        {form.status === status ? (
                          <CheckIcon className="text-primary" />
                        ) : null}
                      </DropdownMenuItem>
                    ))}
                  </DropdownMenuGroup>
                </DropdownMenuContent>
              </DropdownMenu>
            </Field>
          </section>
        ) : null}
      </FieldGroup>

      <Dialog
        open={form.appType === "agent" && resourcePicker === "knowledge"}
        onOpenChange={(open) => {
          setResourcePicker(open ? "knowledge" : null)
          if (!open) setKnowledgeSearch("")
        }}
      >
        <DialogContent className="max-h-[calc(100svh-2rem)] max-w-xl gap-0 overflow-hidden p-0">
          <DialogHeader className="border-b bg-muted/25 px-5 py-5 sm:px-6">
            <div className="flex items-start gap-3">
              <span className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-emerald-500/10 text-emerald-700 dark:text-emerald-400">
                <DatabaseIcon className="size-5" />
              </span>
              <div className="min-w-0 pt-0.5">
                <DialogTitle>{t("关联知识库")}</DialogTitle>
                <DialogDescription className="mt-1.5 leading-5">
                  {t("按需选择知识库，最多 {value} 个。", { value: 4 })}
                </DialogDescription>
              </div>
            </div>
          </DialogHeader>
          <div className="border-b px-3 py-3 sm:px-4">
            <div className="relative">
              <SearchIcon className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                value={knowledgeSearch}
                onChange={(event) => setKnowledgeSearch(event.target.value)}
                className="bg-muted/20 pl-9"
                placeholder={t("搜索{label}...", { label: t("知识库") })}
                autoFocus
              />
            </div>
          </div>
          <div className="max-h-[46svh] min-h-48 overflow-y-auto p-3 sm:p-4">
            {activeKnowledgeBases.length === 0 ? (
              <div className="flex min-h-40 flex-col items-center justify-center gap-3 rounded-xl border border-dashed bg-muted/20 p-6 text-center">
                <span className="flex size-10 items-center justify-center rounded-xl bg-muted">
                  <DatabaseIcon className="size-4 text-muted-foreground" />
                </span>
                <p className="text-sm text-muted-foreground">
                  {t("暂无可用知识库")}
                </p>
              </div>
            ) : filteredKnowledgeBases.length === 0 ? (
              <div className="flex min-h-40 items-center justify-center rounded-xl border border-dashed bg-muted/20 p-6 text-center">
                <p className="text-sm text-muted-foreground">
                  {t("没有匹配的知识库")}
                </p>
              </div>
            ) : (
              <fieldset className="space-y-2" disabled={readOnly}>
                {filteredKnowledgeBases.map((knowledgeBase) => {
                  const checked = form.knowledgeBaseIds.includes(
                    knowledgeBase.id
                  )
                  const disabled = !checked && form.knowledgeBaseIds.length >= 4
                  return (
                    <label
                      key={knowledgeBase.id}
                      className={`group flex items-center gap-3 rounded-xl border p-3.5 transition-[border-color,background-color,box-shadow] ${
                        checked
                          ? "border-foreground/20 bg-muted/70 shadow-xs"
                          : "border-border/70 hover:border-foreground/20 hover:bg-muted/35"
                      } ${disabled ? "cursor-not-allowed opacity-50" : "cursor-pointer"}`}
                    >
                      <input
                        type="checkbox"
                        className="sr-only"
                        checked={checked}
                        disabled={disabled}
                        onChange={() => toggleKnowledgeBase(knowledgeBase.id)}
                      />
                      <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-emerald-500/10 text-emerald-700 dark:text-emerald-400">
                        <DatabaseIcon className="size-4" />
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-sm font-medium">
                          {knowledgeBase.name}
                        </span>
                        {knowledgeBase.description ? (
                          <span className="mt-0.5 line-clamp-2 block text-xs leading-5 text-muted-foreground">
                            {knowledgeBase.description}
                          </span>
                        ) : null}
                      </span>
                      <span
                        className={`flex size-6 shrink-0 items-center justify-center rounded-full border transition-colors ${
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
              </fieldset>
            )}
          </div>
          <DialogFooter className="flex-col border-t bg-muted/20 px-5 py-4 sm:flex-row sm:items-center sm:justify-between sm:px-6">
            <p className="text-xs text-muted-foreground">
              {t("{value} 个知识库", {
                value: form.knowledgeBaseIds.length,
              })}
            </p>
            <Button
              type="button"
              className="w-full sm:w-auto sm:min-w-20"
              onClick={() => setResourcePicker(null)}
            >
              {t("完成")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {isToolPickerOpen ? (
        <ToolPicker
          open={form.appType === "agent"}
          onOpenChange={setIsToolPickerOpen}
          token={token}
          workspaceId={workspaceId}
          value={form.tools}
          onChange={(nextTools) =>
            setForm((current) => ({
              ...current,
              tools: nextTools,
            }))
          }
        />
      ) : null}
    </>
  )
}
