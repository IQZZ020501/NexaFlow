"use client"

import * as React from "react"
import {
  ArrowLeftIcon,
  BotIcon,
  BrainIcon,
  CircleCheckIcon,
  ChevronDownIcon,
  CircleXIcon,
  DatabaseIcon,
  LoaderCircleIcon,
  MessageSquareIcon,
  MoreHorizontalIcon,
  PanelLeftCloseIcon,
  PanelLeftOpenIcon,
  RocketIcon,
  SaveIcon,
  SendIcon,
  Trash2Icon,
  Undo2Icon,
  WrenchIcon,
} from "lucide-react"

import { MarkdownContent } from "@/components/knowledge/markdown-content"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import type { TFunction } from "@/i18n"
import type { Agent, AgentRun } from "@/lib/api/agents"
import type { KnowledgeBase } from "@/lib/api/knowledge"
import type { RegisteredModel } from "@/lib/api/llm"
import type { McpServer } from "@/lib/api/mcp"

import { AgentConfigFields } from "./agent-config-fields"
import type { AgentFormState } from "./agents-page"

type AgentDetailWorkspaceProps = {
  agent: Agent
  form: AgentFormState
  setForm: React.Dispatch<React.SetStateAction<AgentFormState>>
  models: RegisteredModel[]
  knowledgeBases: KnowledgeBase[]
  mcpServers: McpServer[]
  runs: AgentRun[]
  question: string
  setQuestion: React.Dispatch<React.SetStateAction<string>>
  pendingQuestion: string | null
  isDirty: boolean
  isSaving: boolean
  isAsking: boolean
  isRunsLoading: boolean
  onBack: () => void
  onDelete: () => void
  onSave: (event: React.FormEvent<HTMLFormElement>) => void
  onPublish: () => void
  onAsk: (event: React.FormEvent<HTMLFormElement>) => void
  t: TFunction
}


function processSummary(
  event: AgentRun["events"][number],
  run: AgentRun,
  t: TFunction
) {
  if (event.summary === "agent.analyzing") return t("正在分析问题")
  if (event.summary === "agent.reviewing_tool_results")
    return t("正在整理工具结果")
  if (event.summary === "agent.tools_selected") return t("已完成分析")
  if (event.summary === "agent.tool_running")
    return t("正在调用 {name}", { name: event.tool_name })
  if (event.summary === "agent.answer_ready")
    return t(run.status === "running" ? "正在生成回答" : "回答已生成")
  if (event.summary.startsWith("agent.knowledge_chunks_returned:")) {
    const count = Number(event.summary.split(":")[1])
    return t("已检索 {value} 个知识片段", { value: count })
  }
  const legacyKnowledgeMatch = event.summary.match(/^(\d+) knowledge chunks returned\.$/)
  if (legacyKnowledgeMatch) {
    return t("已检索 {value} 个知识片段", {
      value: Number(legacyKnowledgeMatch[1]),
    })
  }
  return event.summary
}

function ToolEventDetails({
  event,
  run,
  t,
}: {
  event: AgentRun["events"][number]
  run: AgentRun
  t: TFunction
}) {
  const [isOpen, setIsOpen] = React.useState(false)
  const label = event.tool_label || event.tool_name

  return (
    <div className="overflow-hidden rounded-lg border bg-background/70">
      <button
        type="button"
        className="flex w-full items-center gap-2 px-3 py-2 text-left hover:bg-muted/50"
        aria-expanded={isOpen}
        onClick={() => setIsOpen((current) => !current)}
      >
        <span className="flex size-7 shrink-0 items-center justify-center rounded-md bg-sky-500/10 text-sky-700 dark:text-sky-400">
          {event.tool_kind === "knowledge" ? (
            <DatabaseIcon className="size-3.5" />
          ) : (
            <WrenchIcon className="size-3.5" />
          )}
        </span>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-sm font-medium text-foreground">
            {label}
            {event.server_name ? (
              <span className="ml-1 font-normal text-muted-foreground">
                @ {event.server_name}
              </span>
            ) : null}
          </span>
          <span className="block truncate text-xs text-muted-foreground">
            {processSummary(event, run, t)}
          </span>
        </span>
        {event.status === "running" ? (
          <LoaderCircleIcon className="size-3.5 animate-spin text-sky-600" />
        ) : event.status === "succeeded" ? (
          <CircleCheckIcon className="size-3.5 text-emerald-600" />
        ) : (
          <CircleXIcon className="size-3.5 text-destructive" />
        )}
        <ChevronDownIcon
          className={`size-4 text-muted-foreground transition-transform ${isOpen ? "rotate-180" : ""}`}
        />
      </button>
      {isOpen ? (
        <div className="grid gap-3 border-t bg-muted/20 p-3 text-xs">
          <div>
            <p className="mb-1 font-medium text-muted-foreground">{t("调用输入")}</p>
            <pre className="max-h-44 overflow-auto whitespace-pre-wrap break-words rounded-md bg-background p-3 font-mono leading-5">
              {JSON.stringify(event.input, null, 2)}
            </pre>
          </div>
          {event.output !== null && event.output !== undefined ? (
            <div>
              <p className="mb-1 font-medium text-muted-foreground">{t("调用结果")}</p>
              {event.tool_kind === "knowledge" &&
              typeof event.output === "object" &&
              event.output &&
              "hits" in event.output &&
              Array.isArray(event.output.hits) ? (
                <div className="space-y-2">
                  {event.output.hits.map((hit, index) => {
                    const item = hit as Record<string, unknown>
                    return (
                      <article key={index} className="rounded-md border bg-background p-3">
                        <div className="flex flex-wrap items-center gap-2 font-medium">
                          <span>{String(item.document ?? t("未知文档"))}</span>
                          <span className="text-muted-foreground">{String(item.knowledge_base ?? "")}</span>
                        </div>
                        <p className="mt-2 whitespace-pre-wrap break-words leading-5 text-muted-foreground">
                          {String(item.content ?? "")}
                        </p>
                      </article>
                    )
                  })}
                </div>
              ) : (
                <pre className="max-h-64 overflow-auto whitespace-pre-wrap break-words rounded-md bg-background p-3 font-mono leading-5">
                  {typeof event.output === "string"
                    ? event.output
                    : JSON.stringify(event.output, null, 2)}
                </pre>
              )}
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  )
}

function processTimeline(run: AgentRun) {
  return run.events.map((event) => ({ event, count: 1 }))
}

function RunExchange({ run, t }: { run: AgentRun; t: TFunction }) {
  const timeline = processTimeline(run)
  const hasProcess = timeline.length > 0
  const [isProcessOpen, setIsProcessOpen] = React.useState(true)
  return (
    <article className="flex flex-col gap-5">
      <div className="ml-auto max-w-[88%] rounded-2xl rounded-br-md bg-foreground px-4 py-3 text-sm leading-6 text-background shadow-sm">
        {run.goal}
      </div>
      <div className="flex items-start gap-3">
        <span className="mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-lg bg-foreground text-background shadow-sm">
          <BotIcon className="size-4" />
        </span>
        <div className="min-w-0 flex-1 rounded-2xl rounded-tl-md border bg-background p-4 shadow-xs">
          {hasProcess ? (
            <details
              className="group mb-4 rounded-xl bg-muted/50 px-3 py-2.5 text-sm"
              open={isProcessOpen}
              onToggle={(event) => setIsProcessOpen(event.currentTarget.open)}
            >
              <summary className="flex cursor-pointer list-none items-center gap-2 font-medium text-muted-foreground outline-none [&::-webkit-details-marker]:hidden focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2">
                <BrainIcon className="size-4" />
                <span className="flex-1">{t("执行过程")}</span>
                <ChevronDownIcon className="size-4 transition-transform group-open:rotate-180" />
              </summary>
              <div className="mt-2 space-y-2 border-l pl-4">
                {timeline.map(({ event }, index) =>
                  event.type === "tool" ? (
                    <ToolEventDetails
                      key={event.call_id || `${event.turn}-${event.tool_name}-${index}`}
                      event={event}
                      run={run}
                      t={t}
                    />
                  ) : (
                    <div
                      key={`${event.type}-${event.turn}-${index}`}
                      className="relative flex items-start gap-2 px-1 text-xs leading-5 text-muted-foreground"
                    >
                      {event.status === "running" ? (
                        <LoaderCircleIcon className="mt-0.5 size-3.5 shrink-0 animate-spin" />
                      ) : event.status === "succeeded" ? (
                        <CircleCheckIcon className="mt-0.5 size-3.5 shrink-0 text-emerald-600" />
                      ) : (
                        <CircleXIcon className="mt-0.5 size-3.5 shrink-0 text-destructive" />
                      )}
                      <span>{processSummary(event, run, t)}</span>
                    </div>
                  )
                )}
              </div>
            </details>
          ) : null}

          {run.result ? (
            <MarkdownContent
              content={run.result.replace(/[ \t]*\[S\d+\]/g, "")}
              className="text-sm leading-6"
            />
          ) : run.status === "failed" ? (
            <p className="rounded-md border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
              {run.last_error ?? t("Agent 未返回结果")}
            </p>
          ) : (
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <span className="flex gap-1" aria-label={t("正在生成回答")}>
                <span className="size-1.5 animate-pulse rounded-full bg-current" />
                <span className="size-1.5 animate-pulse rounded-full bg-current [animation-delay:150ms]" />
                <span className="size-1.5 animate-pulse rounded-full bg-current [animation-delay:300ms]" />
              </span>
              {t("正在生成回答")}
            </div>
          )}
        </div>
      </div>
    </article>
  )
}

export function AgentDetailWorkspace({
  agent,
  form,
  setForm,
  models,
  knowledgeBases,
  mcpServers,
  runs,
  question,
  setQuestion,
  pendingQuestion,
  isDirty,
  isSaving,
  isAsking,
  isRunsLoading,
  onBack,
  onDelete,
  onSave,
  onPublish,
  onAsk,
  t,
}: AgentDetailWorkspaceProps) {
  const [activePanel, setActivePanel] = React.useState<"config" | "preview">(
    "config"
  )
  const [isConfigVisible, setIsConfigVisible] = React.useState(true)
  const previewScrollRef = React.useRef<HTMLDivElement>(null)

  React.useLayoutEffect(() => {
    const scrollContainer = previewScrollRef.current
    if (!scrollContainer) return

    scrollContainer.scrollTop = scrollContainer.scrollHeight
  }, [activePanel, isRunsLoading, pendingQuestion, runs])
  const selectedModel = models.find((model) => model.id === form.modelId)
  const visibleRuns = [...runs].reverse()

  return (
    <div className="-mx-4 -my-6 flex min-h-[calc(100svh-3.5rem)] flex-col overflow-hidden bg-background sm:-mx-6 lg:-mx-8 lg:h-[calc(100svh-3.5rem)] lg:min-h-0">
      <header className="z-10 flex min-h-16 shrink-0 flex-wrap items-center gap-3 border-b bg-background/95 px-4 py-3 backdrop-blur sm:px-6">
        <Button
          type="button"
          variant="ghost"
          size="icon"
          aria-label={t("返回 Agent 列表")}
          title={t("返回 Agent 列表")}
          onClick={onBack}
        >
          <ArrowLeftIcon />
        </Button>
        <span className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-foreground text-background shadow-sm">
          <BotIcon className="size-5" />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="max-w-52 truncate text-base font-semibold sm:max-w-none">
              {form.name || agent.name}
            </h1>
            <Badge
              variant="outline"
              className={
                agent.status === "active"
                  ? "border-emerald-600/20 bg-emerald-500/10 text-emerald-700 dark:text-emerald-400"
                  : "text-muted-foreground"
              }
            >
              <span
                className={`mr-1.5 size-1.5 rounded-full ${agent.status === "active" ? "bg-emerald-500" : "bg-muted-foreground"}`}
              />
              {t(agent.status === "active" ? "已启用" : "已停用")}
            </Badge>
            {agent.published ? (
              <Badge
                variant="outline"
                className="border-blue-600/20 bg-blue-500/10 text-blue-700 dark:text-blue-400"
              >
                <span className="mr-1.5 size-1.5 rounded-full bg-blue-500" />
                {t("已发布")}
              </Badge>
            ) : null}
            {isDirty ? <Badge variant="secondary">{t("未保存")}</Badge> : null}
          </div>
          <p className="mt-0.5 hidden truncate text-xs text-muted-foreground sm:block">
            {selectedModel?.name ?? t("未连接")} · {t("设置")}
          </p>
        </div>

        <Button
          type="button"
          variant="ghost"
          size="icon"
          className="hidden lg:inline-flex"
          aria-label={t(isConfigVisible ? "预览" : "设置")}
          title={t(isConfigVisible ? "预览" : "设置")}
          onClick={() => setIsConfigVisible((current) => !current)}
        >
          {isConfigVisible ? <PanelLeftCloseIcon /> : <PanelLeftOpenIcon />}
        </Button>
        {agent.can_edit ? (
          <>
            <Button
              type="button"
              variant="outline"
              disabled={isSaving}
              onClick={onPublish}
            >
              {agent.published ? (
                <Undo2Icon />
              ) : (
                <RocketIcon />
              )}
              <span className="hidden sm:inline">
                {t(agent.published ? "取消发布" : "发布")}
              </span>
            </Button>
            <Button
              type="submit"
              form="agent-settings-form"
              disabled={
                isSaving || !isDirty || !form.name.trim() || !form.modelId
              }
            >
              {isSaving ? (
                <LoaderCircleIcon className="animate-spin" />
              ) : (
                <SaveIcon />
              )}
              <span className="hidden sm:inline">{t("保存")}</span>
            </Button>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  aria-label={t("设置")}
                  title={t("设置")}
                >
                  <MoreHorizontalIcon />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem variant="destructive" onSelect={onDelete}>
                  <Trash2Icon />
                  {t("删除 Agent")}
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </>
        ) : null}
      </header>

      <nav className="grid shrink-0 grid-cols-2 border-b bg-background p-1 lg:hidden">
        <Button
          type="button"
          variant={activePanel === "config" ? "secondary" : "ghost"}
          onClick={() => setActivePanel("config")}
        >
          <DatabaseIcon />
          {t("基本信息")}
        </Button>
        <Button
          type="button"
          variant={activePanel === "preview" ? "secondary" : "ghost"}
          onClick={() => setActivePanel("preview")}
        >
          <MessageSquareIcon />
          {t("调试预览")}
        </Button>
      </nav>

      <main className="flex min-h-0 flex-1 bg-muted/20">
        <section
          className={`${activePanel === "config" ? "flex" : "hidden"} min-h-0 w-full flex-col border-r bg-muted/30 lg:flex ${isConfigVisible ? "lg:w-[46%] lg:max-w-[680px]" : "lg:hidden"}`}
        >
          <div className="flex items-center justify-between border-b bg-background/70 px-5 py-3">
            <div>
              <h2 className="text-sm font-semibold">{t("基本信息")}</h2>
              <p className="text-xs text-muted-foreground">
                {t("配置 Agent 使用的模型、知识库和 MCP 工具。")}
              </p>
            </div>
            <div className="hidden items-center gap-3 text-xs text-muted-foreground sm:flex">
              <span className="flex items-center gap-1.5">
                <DatabaseIcon className="size-3.5" />
                {form.knowledgeBaseIds.length}
              </span>
              <span className="flex items-center gap-1.5">
                <WrenchIcon className="size-3.5" />
                {form.mcpTools.length}
              </span>
            </div>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto p-4 sm:p-5">
            <form id="agent-settings-form" onSubmit={onSave}>
              <AgentConfigFields
                form={form}
                setForm={setForm}
                models={models}
                knowledgeBases={knowledgeBases}
                mcpServers={mcpServers}
                readOnly={!agent.can_edit}
                t={t}
              />
            </form>
          </div>
        </section>

        <section
          className={`${activePanel === "preview" ? "flex" : "hidden"} min-h-[680px] min-w-0 flex-1 flex-col bg-background lg:flex lg:min-h-0`}
        >
          <div className="flex items-center justify-between border-b px-5 py-3">
            <div>
              <h2 className="text-sm font-semibold">{t("调试预览")}</h2>
              <p className="text-xs text-muted-foreground">
                {t("保存配置后，在这里直接提问。")}
              </p>
            </div>
            <Badge variant="outline" className="font-normal text-muted-foreground">
              <span className="mr-1.5 size-1.5 rounded-full bg-emerald-500" />
              {t("预览")}
            </Badge>
          </div>

          <div
            ref={previewScrollRef}
            className="relative min-h-0 flex-1 overflow-y-auto bg-muted/20"
          >
            <div className="mx-auto flex min-h-full w-full max-w-3xl flex-col px-4 py-8 sm:px-8">
              {isRunsLoading ? (
                <div className="flex min-h-72 flex-1 items-center justify-center text-muted-foreground">
                  <LoaderCircleIcon className="mr-2 size-4 animate-spin" />
                  {t("正在加载")}
                </div>
              ) : visibleRuns.length === 0 && !pendingQuestion ? (
                <div className="flex min-h-72 flex-1 flex-col items-center justify-center text-center">
                  <span className="relative flex size-16 items-center justify-center rounded-2xl bg-foreground text-background shadow-lg">
                    <BotIcon className="size-7" />
                    <span className="absolute -right-1 -bottom-1 size-4 rounded-full border-2 border-muted bg-emerald-500" />
                  </span>
                  <p className="mt-5 text-base font-semibold">
                    {t("开始和 Agent 对话")}
                  </p>
                  <p className="mt-2 max-w-md text-sm leading-6 text-muted-foreground">
                    {t("直接提问，Agent 会按需使用已配置的知识库和 MCP 工具。")}
                  </p>
                </div>
              ) : (
                <div className="space-y-8">
                  {visibleRuns.map((run) => (
                    <RunExchange key={run.id} run={run} t={t} />
                  ))}
                </div>
              )}
            </div>
          </div>

          <div className="shrink-0 border-t bg-background p-3 sm:p-4">
            <form
              className="mx-auto max-w-3xl rounded-2xl border bg-background p-2 shadow-sm transition-shadow focus-within:shadow-md"
              onSubmit={onAsk}
            >
              <div className="flex items-end gap-2">
                <textarea
                  value={question}
                  onChange={(event) => setQuestion(event.target.value)}
                  onKeyDown={(event) => {
                    if (
                      event.key === "Enter" &&
                      !event.shiftKey &&
                      !event.nativeEvent.isComposing
                    ) {
                      event.preventDefault()
                      event.currentTarget.form?.requestSubmit()
                    }
                  }}
                  className="max-h-40 min-h-14 min-w-0 flex-1 resize-none bg-transparent px-3 py-2 text-sm leading-6 outline-none placeholder:text-muted-foreground disabled:cursor-not-allowed"
                  placeholder={
                    isDirty
                      ? t("请先保存配置后再调试")
                      : t("向 Agent 提问...")
                  }
                  aria-label={t("向 Agent 提问")}
                  disabled={isDirty || isAsking || agent.status !== "active"}
                  maxLength={4000}
                  rows={2}
                />
                <Button
                  type="submit"
                  size="icon-lg"
                  className="rounded-xl"
                  aria-label={t("发送问题")}
                  title={t("发送问题")}
                  disabled={
                    !question.trim() ||
                    isDirty ||
                    isAsking ||
                    agent.status !== "active"
                  }
                >
                  {isAsking ? (
                    <LoaderCircleIcon className="animate-spin" />
                  ) : (
                    <SendIcon />
                  )}
                </Button>
              </div>
            </form>
          </div>
        </section>
      </main>
    </div>
  )
}
