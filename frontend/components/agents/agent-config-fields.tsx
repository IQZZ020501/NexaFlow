"use client"

import * as React from "react"
import {
  BotIcon,
  CheckIcon,
  ChevronDownIcon,
  ChevronRightIcon,
  DatabaseIcon,
  PlusIcon,
  SlidersHorizontalIcon,
  WrenchIcon,
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
import type { Agent, AgentMcpToolRef } from "@/lib/api/agents"
import type { KnowledgeBase } from "@/lib/api/knowledge"
import type { RegisteredModel } from "@/lib/api/llm"
import type { McpServer } from "@/lib/api/mcp"

import type { AgentFormState } from "./agents-page"

type AgentConfigFieldsProps = {
  form: AgentFormState
  setForm: React.Dispatch<React.SetStateAction<AgentFormState>>
  models: RegisteredModel[]
  knowledgeBases: KnowledgeBase[]
  mcpServers: McpServer[]
  readOnly: boolean
  t: TFunction
}

function hasMcpTool(items: AgentMcpToolRef[], item: AgentMcpToolRef) {
  return items.some(
    (candidate) =>
      candidate.server_id === item.server_id &&
      candidate.tool_name === item.tool_name
  )
}

export function AgentConfigFields({
  form,
  setForm,
  models,
  knowledgeBases,
  mcpServers,
  readOnly,
  t,
}: AgentConfigFieldsProps) {
  const [resourcePicker, setResourcePicker] = React.useState<
    "knowledge" | "mcp" | null
  >(null)
  const [isKnowledgeOpen, setIsKnowledgeOpen] = React.useState(true)
  const [isMcpOpen, setIsMcpOpen] = React.useState(true)

  const configurableModels = models.filter(
    (model) =>
      model.model_type === "LLM" &&
      (model.status === "active" || model.id === form.modelId)
  )
  const activeKnowledgeBases = knowledgeBases.filter(
    (knowledgeBase) => knowledgeBase.status === "active"
  )
  const activeMcpServers = mcpServers.filter(
    (server) => server.status === "active"
  )
  const selectedModel = configurableModels.find(
    (model) => model.id === form.modelId
  )
  const selectedKnowledgeBaseNames = form.knowledgeBaseIds
    .map((id) => knowledgeBases.find((item) => item.id === id)?.name)
    .filter((name): name is string => Boolean(name))
  const selectedMcpToolNames = form.mcpTools.map((reference) => {
    const server = mcpServers.find((item) => item.id === reference.server_id)
    return server
      ? `${server.name} / ${reference.tool_name}`
      : reference.tool_name
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

  function toggleMcpTool(item: AgentMcpToolRef) {
    setForm((current) => {
      const selected = hasMcpTool(current.mcpTools, item)
      if (!selected && current.mcpTools.length >= 12) return current
      return {
        ...current,
        mcpTools: selected
          ? current.mcpTools.filter(
              (candidate) =>
                candidate.server_id !== item.server_id ||
                candidate.tool_name !== item.tool_name
            )
          : [...current.mcpTools, item],
      }
    })
  }

  return (
    <>
      <FieldGroup className="gap-3">
        <section className="rounded-xl border bg-background p-4 shadow-xs">
          <div className="mb-4 flex items-center gap-3">
            <span className="flex size-9 items-center justify-center rounded-lg bg-foreground text-background">
              <BotIcon className="size-4" />
            </span>
            <div>
              <h3 className="text-sm font-semibold">{t("基本信息")}</h3>
              <p className="text-xs text-muted-foreground">
                {t("配置 Agent 使用的模型、知识库和 MCP 工具。")}
              </p>
            </div>
          </div>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-1 xl:grid-cols-2">
            <Field>
              <FieldLabel htmlFor="agent-name">{t("Agent 名称")}</FieldLabel>
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
                    <span className="min-w-0 flex-1 truncate text-left">
                      {selectedModel?.name ?? t("选择模型")}
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
                        <span className="min-w-0 truncate">{model.name}</span>
                        {model.id === form.modelId ? (
                          <CheckIcon className="text-primary" />
                        ) : null}
                      </DropdownMenuItem>
                    ))}
                  </DropdownMenuGroup>
                </DropdownMenuContent>
              </DropdownMenu>
            </Field>
          </div>
        </section>

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
            className="min-h-44 w-full resize-y rounded-lg border border-input bg-muted/20 px-3 py-3 text-sm leading-6 shadow-xs outline-none transition-[color,box-shadow] placeholder:text-muted-foreground disabled:pointer-events-none disabled:cursor-not-allowed disabled:opacity-50 focus-visible:border-ring focus-visible:bg-background focus-visible:ring-3 focus-visible:ring-ring/50 dark:bg-input/20"
            placeholder={t("描述 Agent 的角色、回答方式和约束。")}
            maxLength={8000}
            rows={7}
            disabled={readOnly}
          />
        </section>

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
              onClick={() => setResourcePicker("knowledge")}
            >
              <PlusIcon />
            </Button>
          </div>
          {isKnowledgeOpen ? (
            <div className="border-t px-4 py-3">
              {selectedKnowledgeBaseNames.length > 0 ? (
                <div className="flex flex-wrap gap-1.5">
                  {selectedKnowledgeBaseNames.map((name) => (
                    <Badge key={name} variant="secondary" className="font-normal">
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

        <section className="rounded-xl border bg-background shadow-xs">
          <div className="flex items-center gap-2 px-4 py-3">
            <button
              type="button"
              className="flex min-w-0 flex-1 items-center gap-3 rounded-md text-left outline-none focus-visible:ring-2 focus-visible:ring-ring"
              aria-expanded={isMcpOpen}
              onClick={() => setIsMcpOpen((current) => !current)}
            >
              <span className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-sky-500/10 text-sky-700 dark:text-sky-400">
                <WrenchIcon className="size-4" />
              </span>
              <span className="min-w-0 flex-1">
                <span className="block text-sm font-medium">{t("MCP 工具")}</span>
                <span className="block text-xs text-muted-foreground">
                  {t("{value} 个 MCP 工具", { value: form.mcpTools.length })}
                </span>
              </span>
              <ChevronRightIcon
                className={`size-4 text-muted-foreground transition-transform ${isMcpOpen ? "rotate-90" : ""}`}
              />
            </button>
            <Button
              type="button"
              variant="outline"
              size="icon-sm"
              aria-label={t("MCP 工具")}
              title={t("MCP 工具")}
              disabled={readOnly}
              onClick={() => setResourcePicker("mcp")}
            >
              <PlusIcon />
            </Button>
          </div>
          {isMcpOpen ? (
            <div className="border-t px-4 py-3">
              {selectedMcpToolNames.length > 0 ? (
                <div className="flex flex-wrap gap-1.5">
                  {selectedMcpToolNames.map((name) => (
                    <Badge key={name} variant="secondary" className="font-normal">
                      {name}
                    </Badge>
                  ))}
                </div>
              ) : (
                <p className="text-sm text-muted-foreground">
                  {t("选择的 MCP 工具展示在这里")}
                </p>
              )}
            </div>
          ) : null}
        </section>

        {form.id ? (
          <section className="rounded-xl border bg-background p-4 shadow-xs">
            <Field>
              <div className="flex items-center gap-2">
                <span className="flex size-8 items-center justify-center rounded-lg bg-muted">
                  <SlidersHorizontalIcon className="size-4 text-muted-foreground" />
                </span>
                <FieldLabel htmlFor="agent-status">{t("状态")}</FieldLabel>
              </div>
              <select
                id="agent-status"
                value={form.status}
                onChange={(event) =>
                  setForm((current) => ({
                    ...current,
                    status: event.target.value as Agent["status"],
                  }))
                }
                className="h-9 w-full rounded-lg border border-input bg-background px-3 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 disabled:cursor-not-allowed disabled:opacity-50"
                disabled={readOnly}
              >
                <option value="active">{t("已启用")}</option>
                <option value="disabled">{t("已停用")}</option>
              </select>
            </Field>
          </section>
        ) : null}
      </FieldGroup>

      <Dialog
        open={resourcePicker === "knowledge"}
        onOpenChange={(open) => setResourcePicker(open ? "knowledge" : null)}
      >
        <DialogContent className="max-h-[calc(100svh-2rem)] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>{t("关联知识库")}</DialogTitle>
            <DialogDescription>
              {t("按需选择知识库，最多 {value} 个。", { value: 4 })}
            </DialogDescription>
          </DialogHeader>
          {activeKnowledgeBases.length === 0 ? (
            <p className="rounded-md border border-dashed p-4 text-sm text-muted-foreground">
              {t("暂无可用知识库")}
            </p>
          ) : (
            <fieldset
              className="max-h-[50svh] space-y-1 overflow-y-auto"
              disabled={readOnly}
            >
              {activeKnowledgeBases.map((knowledgeBase) => {
                const checked = form.knowledgeBaseIds.includes(knowledgeBase.id)
                return (
                  <label
                    key={knowledgeBase.id}
                    className="flex cursor-pointer items-center gap-3 rounded-md px-3 py-2.5 text-sm hover:bg-muted"
                  >
                    <input
                      type="checkbox"
                      checked={checked}
                      disabled={!checked && form.knowledgeBaseIds.length >= 4}
                      onChange={() => toggleKnowledgeBase(knowledgeBase.id)}
                    />
                    <span className="min-w-0 truncate">{knowledgeBase.name}</span>
                  </label>
                )
              })}
            </fieldset>
          )}
          <DialogFooter>
            <Button type="button" onClick={() => setResourcePicker(null)}>
              {t("完成")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog
        open={resourcePicker === "mcp"}
        onOpenChange={(open) => setResourcePicker(open ? "mcp" : null)}
      >
        <DialogContent className="max-h-[calc(100svh-2rem)] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>{t("MCP 工具")}</DialogTitle>
            <DialogDescription>
              {t("按需选择 MCP 工具，最多 {value} 个。", { value: 12 })}
            </DialogDescription>
          </DialogHeader>
          {activeMcpServers.every((server) => server.tools.length === 0) ? (
            <p className="rounded-md border border-dashed p-4 text-sm text-muted-foreground">
              {t("暂无可用 MCP 工具")}
            </p>
          ) : (
            <fieldset
              className="max-h-[50svh] space-y-3 overflow-y-auto"
              disabled={readOnly}
            >
              {activeMcpServers.map((server) =>
                server.tools.length > 0 ? (
                  <div key={server.id}>
                    <p className="mb-1 px-3 text-xs font-medium text-muted-foreground">
                      {server.name}
                    </p>
                    {server.tools.map((tool) => {
                      const reference = {
                        server_id: server.id,
                        tool_name: tool.name,
                      }
                      const checked = hasMcpTool(form.mcpTools, reference)
                      return (
                        <label
                          key={tool.name}
                          className="flex cursor-pointer items-start gap-3 rounded-md px-3 py-2.5 text-sm hover:bg-muted"
                        >
                          <input
                            type="checkbox"
                            className="mt-0.5"
                            checked={checked}
                            disabled={!checked && form.mcpTools.length >= 12}
                            onChange={() => toggleMcpTool(reference)}
                          />
                          <span className="min-w-0">
                            <span className="block truncate">{tool.name}</span>
                            {tool.description ? (
                              <span className="mt-0.5 line-clamp-2 block text-xs text-muted-foreground">
                                {tool.description}
                              </span>
                            ) : null}
                          </span>
                        </label>
                      )
                    })}
                  </div>
                ) : null
              )}
            </fieldset>
          )}
          <DialogFooter>
            <Button type="button" onClick={() => setResourcePicker(null)}>
              {t("完成")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}
