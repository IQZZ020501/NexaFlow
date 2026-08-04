"use client"

import * as React from "react"
import { useParams, useRouter } from "next/navigation"
import {
  BotIcon,
  LoaderCircleIcon,
  PencilIcon,
  PlusIcon,
  SearchIcon,
} from "lucide-react"

import {
  PermissionBadge,
  StatusBadge,
} from "@/components/knowledge/status-badges"
import { AgentConfigFields } from "@/components/agents/agent-config-fields"
import { AgentDetailWorkspace } from "@/components/agents/agent-detail-workspace"
import { IconButton } from "@/components/ui/icon-button"
import { Input } from "@/components/ui/input"
import { Button } from "@/components/ui/button"
import { Spec } from "@/components/ui/spec"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { useLanguage } from "@/contexts/language-provider"
import { useSession } from "@/contexts/session-context"
import {
  createAgent,
  deleteAgent,
  listAgentRuns,
  listAgents,
  streamAgentRun,
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


function sameValues(left: string[], right: string[]) {
  return (
    left.length === right.length && left.every((value) => right.includes(value))
  )
}

export function mergeInitialAgentRun(pendingRun: AgentRun, liveRun: AgentRun) {
  return {
    ...liveRun,
    events: liveRun.events.length > 0 ? liveRun.events : pendingRun.events,
  }
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
  const [hasLoadedWorkspaceData, setHasLoadedWorkspaceData] =
    React.useState(false)

  const selectedAgent =
    agents.find((agent) => agent.id === selectedAgentId) ?? null
  const isDirty = selectedAgent ? isAgentFormDirty(form, selectedAgent) : false
  const activeModels = models.filter(
    (model) => model.model_type === "LLM" && model.status === "active"
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

  async function handlePublishAgent() {
    if (!token || !selectedWorkspaceId || !selectedAgent) return
    try {
      const updated = await updateAgent(
        token,
        selectedWorkspaceId,
        selectedAgent.id,
        { published: !selectedAgent.published }
      )
      setAgents((current) =>
        current.map((agent) => (agent.id === updated.id ? updated : agent))
      )
      setForm(formFromAgent(updated))
      notify(
        "success",
        t(updated.published ? "Agent 已发布" : "Agent 已取消发布")
      )
    } catch (error) {
      reportError(error)
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
    const placeholderRun: AgentRun = {
      id: `pending-${Date.now()}`,
      workspace_id: selectedWorkspaceId,
      agent_id: selectedAgent.id,
      requested_by_user_id: me?.user.id ?? "",
      goal: nextQuestion,
      model_id: selectedAgent.model_id,
      model_name: models.find((m) => m.id === selectedAgent.model_id)?.name ?? "",
      status: "running",
      plan: [],
      events: [
        {
          type: "thought",
          turn: 1,
          tool_name: "",
          status: "running",
          summary: "agent.analyzing",
          call_id: "",
          tool_label: "",
          tool_kind: "unknown",
          server_name: "",
          input: {},
          output: null,
          reasoning: "",
        },
      ],
      result: "",
      last_error: null,
      planned_at: null,
      started_at: new Date().toISOString(),
      finished_at: null,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    }
    setRuns((current) => [placeholderRun, ...current])
    let liveRunId: string | null = null
    try {
      await streamAgentRun(
        token,
        selectedWorkspaceId,
        selectedAgent.id,
        nextQuestion,
        (streamEvent) => {
          if (streamEvent.type === "run") {
            liveRunId = streamEvent.run.id
            setPendingQuestion(null)
            setRuns((current) =>
              current.map((run) =>
                run.id === placeholderRun.id
                  ? mergeInitialAgentRun(run, streamEvent.run)
                  : run
              )
            )
            return
          }
          if (streamEvent.type === "process") {
            setRuns((current) =>
              current.map((run) => {
                if (run.id !== liveRunId) return run
                const eventIndex = run.events.findIndex((event) =>
                  streamEvent.event.call_id
                    ? event.call_id === streamEvent.event.call_id
                    : event.type === streamEvent.event.type &&
                      event.turn === streamEvent.event.turn &&
                      event.tool_name === streamEvent.event.tool_name
                )
                if (eventIndex === -1) {
                  return { ...run, events: [...run.events, streamEvent.event] }
                }
                return {
                  ...run,
                  events: run.events.map((event, index) =>
                    index === eventIndex ? streamEvent.event : event
                  ),
                }
              })
            )
            return
          }
          if (streamEvent.type === "reasoning_delta") {
            setRuns((current) =>
              current.map((run) =>
                run.id === liveRunId
                  ? {
                      ...run,
                      events: run.events.map((event) =>
                        event.type === "thought" &&
                        event.turn === streamEvent.turn
                          ? {
                              ...event,
                              reasoning:
                                (event.reasoning ?? "") + streamEvent.delta,
                            }
                          : event
                      ),
                    }
                  : run
              )
            )
            return
          }
          if (streamEvent.type === "answer_delta") {
            setRuns((current) =>
              current.map((run) =>
                run.id === liveRunId
                  ? { ...run, result: run.result + streamEvent.delta }
                  : run
              )
            )
            return
          }
          setRuns((current) =>
            current.map((run) =>
              run.id === streamEvent.run.id ? streamEvent.run : run
            )
          )
          if (streamEvent.type === "error") {
            notify("error", t("Agent 回答失败"))
          }
        },
        !selectedAgent.published
      )
    } catch (error) {
      setQuestion(nextQuestion)
      setRuns((current) =>
        current.filter(
          (run) =>
            run.id !== liveRunId && !run.id.startsWith("pending-")
        )
      )
      reportError(error)
    } finally {
      setPendingQuestion(null)
      setIsAsking(false)
    }
  }

  if (selectedAgent) {
    return (
      <AgentDetailWorkspace
        agent={selectedAgent}
        form={form}
        setForm={setForm}
        models={models}
        knowledgeBases={knowledgeBases}
        mcpServers={mcpServers}
        runs={runs}
        question={question}
        setQuestion={setQuestion}
        pendingQuestion={pendingQuestion}
        isDirty={isDirty}
        isSaving={isSaving}
        isAsking={isAsking}
        isRunsLoading={isRunsLoading}
        onBack={() => {
          if (!isDirty || window.confirm(t("放弃未保存的更改？"))) {
            router.push("/app/apps")
          }
        }}
        onDelete={() => void handleDeleteAgent(selectedAgent)}
        onSave={handleSaveAgent}
        onPublish={() => void handlePublishAgent()}
        onAsk={handleAsk}
        t={t}
      />
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
              <dl className="mt-4 grid grid-cols-2 gap-3 text-sm">
                <Spec
                  label={t("知识库")}
                  value={String(agent.knowledge_base_ids.length)}
                />
                <Spec
                  label={t("MCP 工具")}
                  value={String(agent.mcp_tools.length)}
                />
              </dl>
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
            <AgentConfigFields
              form={form}
              setForm={setForm}
              models={models}
              knowledgeBases={knowledgeBases}
              mcpServers={mcpServers}
              readOnly={false}
              t={t}
            />
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

}
