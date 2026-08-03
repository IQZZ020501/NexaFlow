"use client"

import * as React from "react"
import { useParams, useRouter } from "next/navigation"
import {
  ArrowLeftIcon,
  BotIcon,
  BrainIcon,
  CheckIcon,
  ChevronDownIcon,
  ChevronRightIcon,
  CircleCheckIcon,
  CircleXIcon,
  LoaderCircleIcon,
  PencilIcon,
  PlusIcon,
  SearchIcon,
  SendIcon,
  Trash2Icon,
} from "lucide-react"

import { MarkdownContent } from "@/components/knowledge/markdown-content"
import {
  PermissionBadge,
  StatusBadge,
} from "@/components/knowledge/status-badges"
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
import { IconButton } from "@/components/ui/icon-button"
import { useLanguage } from "@/contexts/language-provider"
import { useSession } from "@/contexts/session-context"
import type { TFunction } from "@/i18n"
import {
  askAgent,
  createAgent,
  deleteAgent,
  listAgentRuns,
  listAgents,
  updateAgent,
  type Agent,
  type AgentMcpToolRef,
  type AgentRun,
} from "@/lib/api/agents"
import { listKnowledgeBases, type KnowledgeBase } from "@/lib/api/knowledge"
import { listRegisteredModels, type RegisteredModel } from "@/lib/api/llm"
import { listMcpServers, type McpServer } from "@/lib/api/mcp"
import { getErrorMessage } from "@/lib/errors"

export type AgentFormState = {
  id: string | null
  name: string
  modelId: string
  instructions: string
  knowledgeBaseIds: string[]
  mcpTools: AgentMcpToolRef[]
  status: Agent["status"]
}

const EMPTY_FORM: AgentFormState = {
  id: null,
  name: "",
  modelId: "",
  instructions: "",
  knowledgeBaseIds: [],
  mcpTools: [],
  status: "active",
}

function formFromAgent(agent: Agent): AgentFormState {
  return {
    id: agent.id,
    name: agent.name,
    modelId: agent.model_id,
    instructions: agent.instructions,
    knowledgeBaseIds: [...agent.knowledge_base_ids],
    mcpTools: agent.mcp_tools.map((tool) => ({ ...tool })),
    status: agent.status,
  }
}

function hasMcpTool(items: AgentMcpToolRef[], item: AgentMcpToolRef) {
  return items.some(
    (candidate) =>
      candidate.server_id === item.server_id &&
      candidate.tool_name === item.tool_name
  )
}

function sameValues(left: string[], right: string[]) {
  return (
    left.length === right.length && left.every((value) => right.includes(value))
  )
}

export function isAgentFormDirty(form: AgentFormState, agent: Agent) {
  const formTools = form.mcpTools.map(
    (tool) => `${tool.server_id}:${tool.tool_name}`
  )
  const agentTools = agent.mcp_tools.map(
    (tool) => `${tool.server_id}:${tool.tool_name}`
  )
  return (
    form.name.trim() !== agent.name ||
    form.modelId !== agent.model_id ||
    form.instructions.trim() !== agent.instructions ||
    form.status !== agent.status ||
    !sameValues(form.knowledgeBaseIds, agent.knowledge_base_ids) ||
    !sameValues(formTools, agentTools)
  )
}

function RunExchange({ run, t }: { run: AgentRun; t: TFunction }) {
  const hasProcess = run.events.length > 0

  return (
    <article className="flex flex-col gap-5">
      <div className="ml-auto max-w-[85%] rounded-lg bg-primary px-4 py-3 text-sm leading-6 text-primary-foreground">
        {run.goal}
      </div>
      <div className="flex items-start gap-3">
        <span className="mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-md border bg-background">
          <BotIcon className="size-4" />
        </span>
        <div className="min-w-0 flex-1">
          {hasProcess ? (
            <details className="group mb-5 text-sm">
              <summary className="flex cursor-pointer list-none items-center gap-2 text-muted-foreground select-none hover:text-foreground [&::-webkit-details-marker]:hidden">
                <BrainIcon className="size-4" />
                <span>{t("思考过程")}</span>
                <ChevronDownIcon className="ml-auto size-4 transition-transform group-open:rotate-180" />
              </summary>
              <div className="mt-3 ml-2 space-y-3 border-l pl-5">
                {run.events.map((event, index) => (
                  <div
                    key={`${event.turn}-${event.tool_name}-${index}`}
                    className="relative text-xs leading-5 text-muted-foreground"
                  >
                    {event.status === "succeeded" ? (
                      <CircleCheckIcon className="absolute top-0.5 -left-[1.8rem] size-4 bg-background text-emerald-600" />
                    ) : (
                      <CircleXIcon className="absolute top-0.5 -left-[1.8rem] size-4 bg-background text-destructive" />
                    )}
                    <span className="sr-only">
                      {event.status === "succeeded"
                        ? t("调用成功")
                        : t("调用失败")}
                    </span>
                    {event.summary}
                  </div>
                ))}
              </div>
            </details>
          ) : null}

          {run.status === "succeeded" ? (
            <MarkdownContent
              content={run.result}
              className="text-sm leading-6"
            />
          ) : run.status === "failed" ? (
            <p className="rounded-md border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
              {run.last_error ?? t("Agent 未返回结果")}
            </p>
          ) : (
            <p className="text-sm text-muted-foreground">{t("正在处理问题")}</p>
          )}

          {run.citations.length > 0 ? (
            <section className="mt-5 border-t pt-4">
              <p className="text-xs font-medium text-muted-foreground">
                {t("来源")}
              </p>
              <div className="mt-2 grid gap-2 sm:grid-cols-2">
                {run.citations.map((citation) => (
                  <div
                    key={citation.source_id}
                    className="min-w-0 rounded-md bg-muted/50 px-3 py-2 text-xs"
                  >
                    <p className="truncate font-medium">
                      [{citation.source_id}] {citation.document_filename}
                    </p>
                    <p className="mt-1 line-clamp-2 leading-5 text-muted-foreground">
                      {citation.excerpt}
                    </p>
                  </div>
                ))}
              </div>
            </section>
          ) : null}
        </div>
      </div>
    </article>
  )
}

export function AgentsPage() {
  const router = useRouter()
  const params = useParams<{ id?: string }>()
  const selectedAgentId = params.id ?? null
  const { t } = useLanguage()
  const { token, me, selectedWorkspaceId, notify } = useSession()
  const [agents, setAgents] = React.useState<Agent[]>([])
  const [models, setModels] = React.useState<RegisteredModel[]>([])
  const [knowledgeBases, setKnowledgeBases] = React.useState<KnowledgeBase[]>(
    []
  )
  const [mcpServers, setMcpServers] = React.useState<McpServer[]>([])
  const [runs, setRuns] = React.useState<AgentRun[]>([])
  const [question, setQuestion] = React.useState("")
  const [pendingQuestion, setPendingQuestion] = React.useState<string | null>(
    null
  )
  const [form, setForm] = React.useState<AgentFormState>(EMPTY_FORM)
  const [isLoading, setIsLoading] = React.useState(false)
  const [isRunsLoading, setIsRunsLoading] = React.useState(false)
  const [isDialogOpen, setIsDialogOpen] = React.useState(false)
  const [isSaving, setIsSaving] = React.useState(false)
  const [isAsking, setIsAsking] = React.useState(false)
  const [agentSearch, setAgentSearch] = React.useState("")
  const [resourcePicker, setResourcePicker] = React.useState<
    "knowledge" | "mcp" | null
  >(null)
  const [isKnowledgeOpen, setIsKnowledgeOpen] = React.useState(true)
  const [isMcpOpen, setIsMcpOpen] = React.useState(false)
  const [hasLoadedWorkspaceData, setHasLoadedWorkspaceData] =
    React.useState(false)

  const selectedAgent =
    agents.find((agent) => agent.id === selectedAgentId) ?? null
  const isDirty = selectedAgent ? isAgentFormDirty(form, selectedAgent) : false
  const activeModels = models.filter(
    (model) => model.model_type === "LLM" && model.status === "active"
  )
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
  const filteredAgents = React.useMemo(() => {
    const search = agentSearch.trim().toLowerCase()
    if (!search) return agents

    return agents.filter((agent) => {
      const model = models.find((item) => item.id === agent.model_id)
      return [agent.name, agent.description, model?.name ?? ""].some((value) =>
        value.toLowerCase().includes(search)
      )
    })
  }, [agentSearch, agents, models])
  const visibleRuns = [...runs].reverse()

  const reportError = React.useCallback(
    (error: unknown) => notify("error", getErrorMessage(error, t)),
    [notify, t]
  )

  const loadWorkspaceData = React.useCallback(async () => {
    if (!token || !selectedWorkspaceId) {
      setAgents([])
      setModels([])
      setKnowledgeBases([])
      setMcpServers([])
      setHasLoadedWorkspaceData(false)
      return
    }
    setIsLoading(true)
    setHasLoadedWorkspaceData(false)
    try {
      const [nextAgents, nextModels, nextKnowledgeBases, nextMcpServers] =
        await Promise.all([
          listAgents(token, selectedWorkspaceId),
          listRegisteredModels(token, selectedWorkspaceId),
          listKnowledgeBases(token, selectedWorkspaceId),
          listMcpServers(token, selectedWorkspaceId),
        ])
      setAgents(nextAgents)
      setModels(nextModels)
      setKnowledgeBases(nextKnowledgeBases)
      setMcpServers(nextMcpServers)
    } catch (error) {
      setAgents([])
      setModels([])
      setKnowledgeBases([])
      setMcpServers([])
      reportError(error)
    } finally {
      setIsLoading(false)
      setHasLoadedWorkspaceData(true)
    }
  }, [reportError, selectedWorkspaceId, token])

  React.useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void loadWorkspaceData()
  }, [loadWorkspaceData])

  React.useEffect(() => {
    if (!selectedAgent || form.id === selectedAgent.id) return
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setForm(formFromAgent(selectedAgent))
  }, [form.id, selectedAgent])

  React.useEffect(() => {
    if (
      token &&
      selectedWorkspaceId &&
      selectedAgentId &&
      hasLoadedWorkspaceData &&
      !isLoading &&
      !selectedAgent
    ) {
      router.replace("/app/apps")
    }
  }, [
    hasLoadedWorkspaceData,
    isLoading,
    router,
    selectedAgent,
    selectedAgentId,
    selectedWorkspaceId,
    token,
  ])

  React.useEffect(() => {
    if (!token || !selectedWorkspaceId || !selectedAgentId) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setRuns([])
      return
    }
    let isCurrent = true
    setIsRunsLoading(true)
    listAgentRuns(token, selectedWorkspaceId, selectedAgentId)
      .then((nextRuns) => {
        if (isCurrent) setRuns(nextRuns)
      })
      .catch((error: unknown) => {
        if (isCurrent) {
          setRuns([])
          reportError(error)
        }
      })
      .finally(() => {
        if (isCurrent) setIsRunsLoading(false)
      })
    return () => {
      isCurrent = false
    }
  }, [reportError, selectedAgentId, selectedWorkspaceId, token])

  if (!token || !me) return null

  function modelName(modelId: string) {
    return models.find((model) => model.id === modelId)?.name ?? t("未连接")
  }

  function openCreateDialog() {
    setForm({ ...EMPTY_FORM, modelId: activeModels[0]?.id ?? "" })
    setIsDialogOpen(true)
  }

  function openAgent(agent: Agent) {
    setForm(formFromAgent(agent))
    router.push(`/app/apps/${agent.id}`)
  }

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

  async function handleSaveAgent(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!token || !selectedWorkspaceId || !form.name.trim() || !form.modelId)
      return
    setIsSaving(true)
    try {
      const payload = {
        name: form.name.trim(),
        model_id: form.modelId,
        instructions: form.instructions,
        knowledge_base_ids: form.knowledgeBaseIds,
        mcp_tools: form.mcpTools,
        status: form.status,
      }
      if (form.id) {
        const updated = await updateAgent(
          token,
          selectedWorkspaceId,
          form.id,
          payload
        )
        setAgents((current) =>
          current.map((agent) => (agent.id === updated.id ? updated : agent))
        )
        setForm(formFromAgent(updated))
        notify("success", t("Agent 已更新"))
      } else {
        const created = await createAgent(token, selectedWorkspaceId, payload)
        setAgents((current) => [created, ...current])
        setForm(formFromAgent(created))
        router.push(`/app/apps/${created.id}`)
        notify("success", t("Agent 已创建"))
      }
      setIsDialogOpen(false)
    } catch (error) {
      reportError(error)
    } finally {
      setIsSaving(false)
    }
  }

  async function handleDeleteAgent(agent: Agent) {
    if (
      !token ||
      !selectedWorkspaceId ||
      !window.confirm(t("确定删除 Agent“{name}”吗？", { name: agent.name }))
    ) {
      return
    }
    try {
      await deleteAgent(token, selectedWorkspaceId, agent.id)
      setAgents((current) => current.filter((item) => item.id !== agent.id))
      if (selectedAgentId === agent.id) router.push("/app/apps")
      notify("success", t("Agent 已删除"))
    } catch (error) {
      reportError(error)
    }
  }

  async function handleAsk(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const nextQuestion = question.trim()
    if (
      !token ||
      !selectedWorkspaceId ||
      !selectedAgent ||
      !nextQuestion ||
      isAsking ||
      selectedAgent.status !== "active"
    ) {
      return
    }
    setQuestion("")
    setPendingQuestion(nextQuestion)
    setIsAsking(true)
    try {
      const run = await askAgent(
        token,
        selectedWorkspaceId,
        selectedAgent.id,
        nextQuestion
      )
      setRuns((current) => [run, ...current])
      if (run.status === "failed") notify("error", t("Agent 回答失败"))
    } catch (error) {
      setQuestion(nextQuestion)
      reportError(error)
    } finally {
      setPendingQuestion(null)
      setIsAsking(false)
    }
  }

  if (selectedAgent) {
    return (
      <div className="flex min-h-[calc(100svh-8rem)] flex-col lg:h-[calc(100svh-8rem)] lg:min-h-0">
        <header className="flex flex-wrap items-center gap-3">
          <Button
            type="button"
            variant="ghost"
            size="icon"
            aria-label={t("返回 Agent 列表")}
            title={t("返回 Agent 列表")}
            onClick={() => {
              if (!isDirty || window.confirm(t("放弃未保存的更改？"))) {
                router.push("/app/apps")
              }
            }}
          >
            <ArrowLeftIcon />
          </Button>
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="truncate text-lg font-semibold">
                {selectedAgent.name}
              </h1>
              {isDirty ? <Badge variant="outline">{t("未保存")}</Badge> : null}
              {selectedAgent.status === "disabled" ? (
                <Badge variant="outline">{t("已停用")}</Badge>
              ) : null}
            </div>
            <p className="mt-0.5 text-xs text-muted-foreground">{t("设置")}</p>
          </div>
          {selectedAgent.can_edit ? (
            <>
              <Button
                type="submit"
                form="agent-settings-form"
                disabled={
                  isSaving || !isDirty || !form.name.trim() || !form.modelId
                }
              >
                {isSaving ? (
                  <LoaderCircleIcon className="animate-spin" />
                ) : null}
                {t("保存")}
              </Button>
              <Button
                type="button"
                variant="destructive"
                size="icon"
                aria-label={t("删除 Agent")}
                title={t("删除 Agent")}
                onClick={() => void handleDeleteAgent(selectedAgent)}
              >
                <Trash2Icon />
              </Button>
            </>
          ) : null}
        </header>

        <main className="mt-4 grid min-h-0 flex-1 overflow-hidden rounded-lg border bg-background lg:grid-cols-[minmax(320px,0.82fr)_minmax(420px,1.18fr)]">
          <section className="overflow-y-auto border-b p-5 lg:border-r lg:border-b-0">
            <div className="mb-5 border-l-2 border-primary pl-3">
              <h2 className="font-semibold">{t("基本信息")}</h2>
              <p className="mt-1 text-xs text-muted-foreground">
                {t("配置 Agent 使用的模型、知识库和 MCP 工具。")}
              </p>
            </div>
            <form id="agent-settings-form" onSubmit={handleSaveAgent}>
              {renderAgentFields(!selectedAgent.can_edit)}
            </form>
          </section>

          <section className="flex min-h-[620px] min-w-0 flex-col p-5 lg:min-h-0">
            <div className="mb-4 border-l-2 border-primary pl-3">
              <h2 className="font-semibold">{t("调试预览")}</h2>
              <p className="mt-1 text-xs text-muted-foreground">
                {t("保存配置后，在这里直接提问。")}
              </p>
            </div>
            <div className="flex min-h-0 flex-1 flex-col rounded-lg bg-muted/40 p-4">
              <div className="min-h-0 flex-1 space-y-8 overflow-y-auto rounded-md bg-background p-4">
                {isRunsLoading ? (
                  <div className="flex min-h-56 items-center justify-center text-muted-foreground">
                    <LoaderCircleIcon className="mr-2 size-4 animate-spin" />
                    {t("正在加载")}
                  </div>
                ) : visibleRuns.length === 0 && !pendingQuestion ? (
                  <div className="flex min-h-56 flex-col items-center justify-center text-center">
                    <span className="flex size-12 items-center justify-center rounded-lg bg-muted">
                      <BotIcon className="size-5 text-muted-foreground" />
                    </span>
                    <p className="mt-4 font-medium">{t("开始和 Agent 对话")}</p>
                    <p className="mt-1 max-w-md text-sm text-muted-foreground">
                      {t("直接提问，Agent 会按需使用已配置的知识库和 MCP 工具。")}
                    </p>
                  </div>
                ) : (
                  visibleRuns.map((run) => (
                    <RunExchange key={run.id} run={run} t={t} />
                  ))
                )}
                {pendingQuestion ? (
                  <article className="flex flex-col gap-5">
                    <div className="ml-auto max-w-[85%] rounded-lg bg-primary px-4 py-3 text-sm leading-6 text-primary-foreground">
                      {pendingQuestion}
                    </div>
                    <div className="flex items-start gap-3">
                      <span className="mt-0.5 flex size-8 items-center justify-center rounded-md border bg-background">
                        <BotIcon className="size-4" />
                      </span>
                      <div className="flex items-center gap-2 py-1.5 text-sm text-muted-foreground">
                        <BrainIcon className="size-4 animate-pulse" />
                        {t("正在思考")}
                      </div>
                    </div>
                  </article>
                ) : null}
              </div>

              <form
                className="mt-3 rounded-lg border bg-background p-2 shadow-sm"
                onSubmit={handleAsk}
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
                    className="max-h-40 min-h-16 min-w-0 flex-1 resize-none bg-transparent px-3 py-2 text-sm leading-6 outline-none placeholder:text-muted-foreground disabled:cursor-not-allowed"
                    placeholder={
                      isDirty
                        ? t("请先保存配置后再调试")
                        : t("向 Agent 提问...")
                    }
                    aria-label={t("向 Agent 提问")}
                    disabled={
                      isDirty || isAsking || selectedAgent.status !== "active"
                    }
                    maxLength={4000}
                    rows={2}
                  />
                  <Button
                    type="submit"
                    size="icon-lg"
                    aria-label={t("发送问题")}
                    title={t("发送问题")}
                    disabled={
                      !question.trim() ||
                      isDirty ||
                      isAsking ||
                      selectedAgent.status !== "active"
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

  return (
    <>
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <h1 className="text-2xl font-semibold">{t("智能 Agent")}</h1>
          <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
            {t("选择模型、知识库和 MCP 工具，创建可以直接对话的 Agent。")}
          </p>
        </div>
        <Button
          type="button"
          onClick={openCreateDialog}
          disabled={activeModels.length === 0}
        >
          <PlusIcon data-icon="inline-start" />
          {t("新建 Agent")}
        </Button>
      </div>

      <div className="rounded-lg border bg-background p-3 shadow-sm">
        <div className="relative min-w-0 sm:w-[320px]">
          <SearchIcon className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={agentSearch}
            onChange={(event) => setAgentSearch(event.target.value)}
            placeholder={t("搜索{label}...", { label: t("智能 Agent") })}
            className="pl-9"
          />
        </div>
      </div>

      {isLoading ? (
        <div className="flex min-h-[220px] items-center justify-center rounded-lg border bg-background shadow-sm">
          <LoaderCircleIcon className="mr-2 size-4 animate-spin" />
          {t("正在加载")}
        </div>
      ) : agents.length === 0 ? (
        <div className="mx-auto flex min-h-[320px] max-w-xl flex-col items-center justify-center gap-4 p-6 text-center">
          <span className="flex size-14 items-center justify-center rounded-lg bg-muted">
            <BotIcon className="size-5 text-muted-foreground" />
          </span>
          <div className="flex flex-col gap-2">
            <p className="text-base font-semibold">{t("还没有 Agent")}</p>
            <p className="text-sm leading-6 text-muted-foreground">
              {activeModels.length === 0
                ? t("先接入一个已启用的大语言模型，再创建 Agent。")
                : t("创建 Agent 后，就可以直接提问。")}
            </p>
          </div>
          {activeModels.length > 0 ? (
            <Button type="button" onClick={openCreateDialog}>
              <PlusIcon data-icon="inline-start" />
              {t("新建 Agent")}
            </Button>
          ) : null}
        </div>
      ) : filteredAgents.length === 0 ? (
        <div className="rounded-lg border bg-background p-8 text-center text-sm text-muted-foreground shadow-sm">
          {t("没有匹配的 Agent")}
        </div>
      ) : (
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">
          {filteredAgents.map((agent) => (
            <div
              key={agent.id}
              role="button"
              tabIndex={0}
              className="min-h-40 cursor-pointer rounded-md border p-3 outline-none transition-colors hover:bg-muted/40 focus-visible:ring-2 focus-visible:ring-ring"
              onClick={() => openAgent(agent)}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") {
                  event.preventDefault()
                  openAgent(agent)
                }
              }}
            >
              <div className="flex items-start justify-between gap-3">
                <div className="flex min-w-0 gap-3">
                  <span className="flex size-9 shrink-0 items-center justify-center rounded-md bg-muted">
                    <BotIcon className="size-5 text-muted-foreground" />
                  </span>
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <h2 className="truncate text-sm font-semibold">
                        {agent.name}
                      </h2>
                      <StatusBadge status={agent.status} />
                      <PermissionBadge
                        permission={agent.can_edit ? "edit" : "view"}
                      />
                    </div>
                    <p className="mt-1 truncate text-sm text-muted-foreground">
                      {modelName(agent.model_id)}
                    </p>
                  </div>
                </div>
                {agent.can_edit ? (
                  <IconButton
                    label={t("编辑 Agent")}
                    onClick={(event) => {
                      event.stopPropagation()
                      openAgent(agent)
                    }}
                  >
                    <PencilIcon className="size-4" />
                  </IconButton>
                ) : null}
              </div>
              <div className="mt-4 flex flex-wrap gap-x-4 gap-y-2 text-sm text-muted-foreground">
                <span>
                  {t("{value} 个知识库", {
                    value: agent.knowledge_base_ids.length,
                  })}
                </span>
                <span>
                  {t("{value} 个 MCP 工具", {
                    value: agent.mcp_tools.length,
                  })}
                </span>
              </div>
            </div>
          ))}
        </div>
      )}

      {renderAgentDialog()}
    </>
  )

  function renderAgentDialog() {
    return (
      <Dialog open={isDialogOpen} onOpenChange={setIsDialogOpen}>
        <DialogContent className="max-h-[calc(100svh-2rem)] max-w-xl overflow-y-auto">
          <DialogHeader>
            <DialogTitle>
              {form.id ? t("编辑 Agent") : t("新建 Agent")}
            </DialogTitle>
            <DialogDescription>
              {t("只需选择 Agent 可以使用的模型、知识和工具。")}
            </DialogDescription>
          </DialogHeader>
          <form onSubmit={handleSaveAgent}>
            {renderAgentFields(false)}
            <DialogFooter className="pt-5">
              <Button
                type="button"
                variant="outline"
                onClick={() => setIsDialogOpen(false)}
              >
                {t("取消")}
              </Button>
              <Button
                type="submit"
                disabled={isSaving || !form.name.trim() || !form.modelId}
              >
                {isSaving ? (
                  <LoaderCircleIcon className="animate-spin" />
                ) : null}
                {form.id ? t("保存") : t("新建 Agent")}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    )
  }

  function renderAgentFields(readOnly: boolean) {
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

    return (
      <FieldGroup>
        <Field>
          <FieldLabel htmlFor="agent-name">{t("Agent 名称")}</FieldLabel>
          <Input
            id="agent-name"
            value={form.name}
            onChange={(event) =>
              setForm((current) => ({ ...current, name: event.target.value }))
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

        <Field>
          <FieldLabel htmlFor="agent-instructions">
            {t("系统提示词")}
          </FieldLabel>
          <textarea
            id="agent-instructions"
            value={form.instructions}
            onChange={(event) =>
              setForm((current) => ({
                ...current,
                instructions: event.target.value,
              }))
            }
            className="min-h-36 w-full resize-y rounded-lg border border-input bg-transparent px-3 py-2 text-sm leading-6 shadow-xs outline-none transition-[color,box-shadow] placeholder:text-muted-foreground disabled:pointer-events-none disabled:cursor-not-allowed disabled:opacity-50 focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 dark:bg-input/30"
            placeholder={t("描述 Agent 的角色、回答方式和约束。")}
            maxLength={8000}
            rows={6}
            disabled={readOnly}
          />
        </Field>

        <section className="space-y-2 py-1">
          <div className="flex items-center gap-1">
            <button
              type="button"
              className="flex min-w-0 flex-1 items-center gap-2 rounded-md py-1 text-left text-sm font-medium outline-none focus-visible:ring-2 focus-visible:ring-ring"
              aria-expanded={isKnowledgeOpen}
              onClick={() => setIsKnowledgeOpen((current) => !current)}
            >
              <ChevronRightIcon
                className={`size-4 transition-transform ${isKnowledgeOpen ? "rotate-90" : ""}`}
              />
              <span>{t("关联知识库")}</span>
              {form.knowledgeBaseIds.length > 0 ? (
                <Badge variant="secondary">
                  {t("{value} 个", {
                    value: form.knowledgeBaseIds.length,
                  })}
                </Badge>
              ) : null}
            </button>
            <Button
              type="button"
              variant="ghost"
              size="icon-sm"
              aria-label={t("关联知识库")}
              title={t("关联知识库")}
              disabled={readOnly}
              onClick={() => setResourcePicker("knowledge")}
            >
              <PlusIcon className="size-5 text-primary" />
            </Button>
          </div>
          {isKnowledgeOpen ? (
            <p className="min-h-6 pl-6 text-sm leading-6 text-muted-foreground">
              {selectedKnowledgeBaseNames.length > 0
                ? selectedKnowledgeBaseNames.join(t("列表分隔符"))
                : t("关联的知识库展示在这里")}
            </p>
          ) : null}
        </section>

        <section className="space-y-2 py-1">
          <div className="flex items-center gap-1">
            <button
              type="button"
              className="flex min-w-0 flex-1 items-center gap-2 rounded-md py-1 text-left text-sm font-medium outline-none focus-visible:ring-2 focus-visible:ring-ring"
              aria-expanded={isMcpOpen}
              onClick={() => setIsMcpOpen((current) => !current)}
            >
              <ChevronRightIcon
                className={`size-4 transition-transform ${isMcpOpen ? "rotate-90" : ""}`}
              />
              <span>{t("MCP")}</span>
              {form.mcpTools.length > 0 ? (
                <Badge variant="secondary">
                  {t("{value} 个", { value: form.mcpTools.length })}
                </Badge>
              ) : null}
            </button>
            <Button
              type="button"
              variant="ghost"
              size="icon-sm"
              aria-label={t("MCP 工具")}
              title={t("MCP 工具")}
              disabled={readOnly}
              onClick={() => setResourcePicker("mcp")}
            >
              <PlusIcon className="size-5 text-primary" />
            </Button>
          </div>
          {isMcpOpen ? (
            <p className="min-h-6 pl-6 text-sm leading-6 text-muted-foreground">
              {selectedMcpToolNames.length > 0
                ? selectedMcpToolNames.join(t("列表分隔符"))
                : t("选择的 MCP 工具展示在这里")}
            </p>
          ) : null}
        </section>

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
                  const checked = form.knowledgeBaseIds.includes(
                    knowledgeBase.id
                  )
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
                      <span className="min-w-0 truncate">
                        {knowledgeBase.name}
                      </span>
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
                              <span className="block truncate">
                                {tool.name}
                              </span>
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

        {form.id ? (
          <Field>
            <FieldLabel htmlFor="agent-status">{t("状态")}</FieldLabel>
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
        ) : null}
      </FieldGroup>
    )
  }
}
