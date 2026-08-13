"use client"

import * as React from "react"
import ModelIcon from "@lobehub/icons/es/features/ModelIcon"
import dynamic from "next/dynamic"
import { useParams, useRouter } from "next/navigation"
import {
  BotIcon,
  LoaderCircleIcon,
  PencilIcon,
  PlusIcon,
  SearchIcon,
  ShieldCheckIcon,
  SparklesIcon,
  Trash2Icon,
  WorkflowIcon,
} from "lucide-react"

import {
  PermissionBadge,
  StatusBadge,
} from "@/components/knowledge/status-badges"
import { TopLoadingBar } from "@/components/app/top-progress"
import { AgentConfigFields } from "@/components/agents/agent-config-fields"
import { AgentDetailWorkspace } from "@/components/agents/agent-detail-workspace"
import { AgentPermissionsDialog } from "@/components/agents/agent-permissions-dialog"
import { Badge } from "@/components/ui/badge"
import { IconButton } from "@/components/ui/icon-button"
import { CardMoreMenu } from "@/components/ui/card-more-menu"
import { DropdownMenuItem } from "@/components/ui/dropdown-menu"
import { Input } from "@/components/ui/input"
import { Button } from "@/components/ui/button"
import { Spec } from "@/components/ui/spec"
import { isEventFromDropdownMenu } from "@/lib/dom"
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
  compareLiveStreamIds,
  createAgent,
  deleteAgent,
  grantAgentPermission,
  getAgent,
  listAgentPermissions,
  listAgentRunToolCalls,
  listAgentRuns,
  listAgents,
  observeAgentRun,
  resolveAgentToolCall,
  revokeAgentPermission,
  streamAgentRun,
  uploadAgentFiles,
  updateAgent,
  type Agent,
  type AgentInteractionConfig,
  type AgentMcpToolRef,
  type AgentPermission,
  type AppType,
  type AgentRun,
  type AgentRunStreamEvent,
  type AgentToolCall,
} from "@/lib/api/agents"
import { speakBrowserText } from "@/lib/browser-tts"
import { listKnowledgeBases, type KnowledgeBase } from "@/lib/api/knowledge"
import { listRegisteredModels, type RegisteredModel } from "@/lib/api/llm"
import { listMcpServers, type McpServer } from "@/lib/api/mcp"
import { listWorkspaceMembers, type WorkspaceMember } from "@/lib/api/system"
import { CARD_BATCH_SIZE, useInfiniteScroll } from "@/lib/use-infinite-scroll"
import { getErrorMessage } from "@/lib/errors"
import { getMembershipRole } from "@/lib/display"
import { appViewPath, type AgentDetailView } from "@/lib/agent-views"
import { normalizeInteractionConfigForAppType } from "@/lib/interaction-config"

const WorkflowDetailWorkspace = dynamic(
  () =>
    import("@/components/workflows/workflow-detail-workspace").then(
      (module) => module.WorkflowDetailWorkspace
    ),
  { ssr: false }
)

export type AgentFormState = {
  id: string | null
  appType: AppType
  name: string
  description: string
  interactionConfig: AgentInteractionConfig
  modelId: string
  instructions: string
  knowledgeQueryMode: Agent["knowledge_query_mode"]
  knowledgeBaseIds: string[]
  mcpTools: AgentMcpToolRef[]
  status: Agent["status"]
}

const EMPTY_FORM: AgentFormState = {
  id: null,
  appType: "agent",
  name: "",
  description: "",
  interactionConfig: {
    prologue: "",
    tts_type: "BROWSER",
    file_upload: false,
    file_upload_setting: {
      max_files: 3,
      file_limit: 10,
      file_upload_type: ["document", "image"],
    },
    user_input_title: "",
  },
  modelId: "",
  instructions: "",
  knowledgeQueryMode: "required",
  knowledgeBaseIds: [],
  mcpTools: [],
  status: "active",
}

function formFromAgent(agent: Agent): AgentFormState {
  return {
    id: agent.id,
    appType: agent.app_type,
    name: agent.name,
    description: agent.description,
    interactionConfig: structuredClone(agent.interaction_config),
    modelId: agent.model_id,
    instructions: agent.instructions,
    knowledgeQueryMode: agent.knowledge_query_mode,
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

export function isCurrentAgentConversation(
  currentConversationId: string | null,
  expectedConversationId: string | null
) {
  return currentConversationId === expectedConversationId
}

export function mergeInitialAgentRun(pendingRun: AgentRun, liveRun: AgentRun) {
  const keepLiveAnswer = ["queued", "running", "awaiting_approval"].includes(
    liveRun.status
  )
  return {
    ...liveRun,
    events: liveRun.events.length > 0 ? liveRun.events : pendingRun.events,
    result:
      keepLiveAnswer && !liveRun.result ? pendingRun.result : liveRun.result,
    live_stream_epoch: keepLiveAnswer
      ? pendingRun.live_stream_epoch
      : undefined,
    live_stream_cursor: keepLiveAnswer
      ? pendingRun.live_stream_cursor
      : undefined,
  }
}

export function mergeAgentRunSnapshot(
  runs: AgentRun[],
  snapshot: AgentRun,
  placeholderId?: string
): AgentRun[] {
  const replaced = runs.map((run) => {
    if (placeholderId && run.id === placeholderId) {
      return mergeInitialAgentRun(run, snapshot)
    }
    return run.id === snapshot.id ? mergeInitialAgentRun(run, snapshot) : run
  })
  return replaced.some((run) => run.id === snapshot.id)
    ? replaced
    : [snapshot, ...replaced]
}

export function mergeAgentRunStreamEvent(
  runs: AgentRun[],
  runId: string,
  streamEvent: AgentRunStreamEvent,
  placeholderId?: string
): AgentRun[] {
  if (streamEvent.type === "run") {
    return mergeAgentRunSnapshot(runs, streamEvent.run, placeholderId)
  }
  if (streamEvent.type === "process") {
    return runs.map((run) => {
      if (run.id !== runId) return run
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
  }
  if (streamEvent.type === "reasoning_delta") {
    return runs.map((run) =>
      run.id === runId
        ? (() => {
            const sameStream =
              !streamEvent.stream_epoch ||
              streamEvent.stream_epoch === run.live_stream_epoch
            if (
              sameStream &&
              streamEvent.live_sequence &&
              run.live_stream_cursor &&
              compareLiveStreamIds(
                streamEvent.live_sequence,
                run.live_stream_cursor
              ) <= 0
            ) {
              return run
            }
            return {
              ...run,
              result: sameStream ? run.result : "",
              live_stream_epoch:
                streamEvent.stream_epoch ?? run.live_stream_epoch,
              live_stream_cursor:
                streamEvent.live_sequence ?? run.live_stream_cursor,
              events: run.events.map((event) =>
                event.type === "thought" && event.turn === streamEvent.turn
                  ? {
                      ...event,
                      reasoning: sameStream
                          ? (event.reasoning ?? "") + streamEvent.delta
                          : streamEvent.delta,
                    }
                  : event
              ),
            }
          })()
        : run
    )
  }
  if (streamEvent.type === "answer_delta") {
    return runs.map((run) =>
      run.id === runId
        ? (() => {
            const sameStream =
              !streamEvent.stream_epoch ||
              streamEvent.stream_epoch === run.live_stream_epoch
            if (
              sameStream &&
              streamEvent.live_sequence &&
              run.live_stream_cursor &&
              compareLiveStreamIds(
                streamEvent.live_sequence,
                run.live_stream_cursor
              ) <= 0
            ) {
              return run
            }
            return {
              ...run,
              result: sameStream
                ? run.result + streamEvent.delta
                : streamEvent.delta,
              live_stream_epoch:
                streamEvent.stream_epoch ?? run.live_stream_epoch,
              live_stream_cursor:
                streamEvent.live_sequence ?? run.live_stream_cursor,
            }
          })()
        : run
    )
  }
  if (streamEvent.type === "approval_required") {
    return runs.map((run) =>
      run.id === runId
        ? {
            ...run,
            status: "awaiting_approval" as const,
            last_error: streamEvent.reason,
          }
        : run
    )
  }
  if (streamEvent.type === "approval_resolved") {
    return runs.map((run) =>
      run.id === runId
        ? { ...run, status: "queued" as const, last_error: null }
        : run
    )
  }
  return runs.map((run) =>
    run.id === streamEvent.run.id ? streamEvent.run : run
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
    form.description.trim() !== agent.description ||
    JSON.stringify(form.interactionConfig) !==
      JSON.stringify(agent.interaction_config) ||
    form.modelId !== agent.model_id ||
    form.instructions.trim() !== agent.instructions ||
    form.knowledgeQueryMode !== agent.knowledge_query_mode ||
    form.status !== agent.status ||
    !sameValues(form.knowledgeBaseIds, agent.knowledge_base_ids) ||
    !sameValues(formTools, agentTools)
  )
}

type AgentsPageProps = {
  initialConversationId?: string | null
  initialView?: AgentDetailView
  workflowCanvasMode?: boolean
}

export function AgentsPage({
  initialConversationId = null,
  initialView = "overview",
  workflowCanvasMode = false,
}: AgentsPageProps) {
  const router = useRouter()
  const params = useParams<{ id?: string }>()
  const selectedAgentId = params.id ?? null
  const { language, t } = useLanguage()
  const { token, me, selectedWorkspaceId, notify } = useSession()
  const [agents, setAgents] = React.useState<Agent[]>([])
  const [models, setModels] = React.useState<RegisteredModel[]>([])
  const [knowledgeBases, setKnowledgeBases] = React.useState<KnowledgeBase[]>(
    []
  )
  const [mcpServers, setMcpServers] = React.useState<McpServer[]>([])
  const [runs, setRuns] = React.useState<AgentRun[]>([])
  const [toolCallsByRun, setToolCallsByRun] = React.useState<
    Record<string, AgentToolCall[]>
  >({})
  const [resolvingCallId, setResolvingCallId] = React.useState<string | null>(
    null
  )
  const [question, setQuestion] = React.useState("")
  const [agentFiles, setAgentFiles] = React.useState<File[]>([])
  const [pendingQuestion, setPendingQuestion] = React.useState<string | null>(
    null
  )
  const [askAbortController, setAskAbortController] =
    React.useState<AbortController | null>(null)
  const [form, setForm] = React.useState<AgentFormState>(EMPTY_FORM)
  const [isLoading, setIsLoading] = React.useState(true)
  const [isRunsLoading, setIsRunsLoading] = React.useState(false)
  const [isDialogOpen, setIsDialogOpen] = React.useState(false)
  const [isChooserOpen, setIsChooserOpen] = React.useState(false)
  const [isSaving, setIsSaving] = React.useState(false)
  const [isPublishing, setIsPublishing] = React.useState(false)
  const [isAsking, setIsAsking] = React.useState(false)
  const [agentSearch, setAgentSearch] = React.useState("")
  const [agentsHasMore, setAgentsHasMore] = React.useState(true)
  const [listedAgentsCount, setListedAgentsCount] = React.useState(0)
  const [isAgentsLoadingMore, setIsAgentsLoadingMore] = React.useState(false)
  const [permissionAgent, setPermissionAgent] = React.useState<Agent | null>(
    null
  )
  const [permissionMembers, setPermissionMembers] = React.useState<
    WorkspaceMember[]
  >([])
  const [agentPermissions, setAgentPermissions] = React.useState<
    AgentPermission[]
  >([])
  const [isPermissionsLoading, setIsPermissionsLoading] = React.useState(false)
  const [isPermissionsSaving, setIsPermissionsSaving] = React.useState(false)
  const permissionRequestRef = React.useRef(0)
  const agentsLoadingMoreRef = React.useRef(false)
  const activeConversationIdRef = React.useRef<string | null>(
    initialConversationId
  )
  const [hasLoadedWorkspaceData, setHasLoadedWorkspaceData] =
    React.useState(false)
  const [isMissingAgentLoading, setIsMissingAgentLoading] =
    React.useState(false)
  const [activeView, setActiveView] =
    React.useState<AgentDetailView>(initialView)

  const selectedAgent =
    agents.find((agent) => agent.id === selectedAgentId) ?? null
  const isDirty = selectedAgent ? isAgentFormDirty(form, selectedAgent) : false
  const workspaceRole = getMembershipRole(me, selectedWorkspaceId)
  const canManagePublishing = workspaceRole === "admin"
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

  const loadRunToolCalls = React.useCallback(
    async (agentId: string, runId: string, conversationId: string) => {
      if (
        !token ||
        !selectedWorkspaceId ||
        !isCurrentAgentConversation(
          activeConversationIdRef.current,
          conversationId
        )
      ) {
        return
      }
      const calls = await listAgentRunToolCalls(
        token,
        selectedWorkspaceId,
        agentId,
        runId
      )
      if (
        !isCurrentAgentConversation(
          activeConversationIdRef.current,
          conversationId
        )
      ) {
        return
      }
      setToolCallsByRun((current) => ({ ...current, [runId]: calls }))
    },
    [selectedWorkspaceId, token]
  )

  const applyStreamEvent = React.useCallback(
    (
      conversationId: string,
      runId: string,
      streamEvent: AgentRunStreamEvent,
      placeholderId?: string
    ) => {
      if (
        !isCurrentAgentConversation(
          activeConversationIdRef.current,
          conversationId
        )
      ) {
        return
      }
      setRuns((current) =>
        mergeAgentRunStreamEvent(current, runId, streamEvent, placeholderId)
      )
      if (
        streamEvent.type === "approval_required" ||
        streamEvent.type === "approval_resolved"
      ) {
        if (selectedAgentId) {
          void loadRunToolCalls(selectedAgentId, runId, conversationId).catch(
            (error: unknown) => {
            if (
              isCurrentAgentConversation(
                activeConversationIdRef.current,
                conversationId
              )
            ) {
              reportError(error)
            }
            }
          )
        }
      }
    },
    [loadRunToolCalls, reportError, selectedAgentId]
  )

  const loadWorkspaceData = React.useCallback(async () => {
    permissionRequestRef.current += 1
    setPermissionAgent(null)
    setPermissionMembers([])
    setAgentPermissions([])
    setIsPermissionsLoading(false)
    setIsPermissionsSaving(false)
    if (!token || !selectedWorkspaceId) {
      setAgents([])
      setModels([])
      setKnowledgeBases([])
      setMcpServers([])
      setListedAgentsCount(0)
      setHasLoadedWorkspaceData(false)
      return
    }
    setIsLoading(true)
    setHasLoadedWorkspaceData(false)
    try {
      const [listedAgents, nextModels, nextKnowledgeBases, nextMcpServers] =
        await Promise.all([
          listAgents(token, selectedWorkspaceId, {
            limit: CARD_BATCH_SIZE,
            offset: 0,
          }),
          listRegisteredModels(token, selectedWorkspaceId),
          listKnowledgeBases(token, selectedWorkspaceId),
          listMcpServers(token, selectedWorkspaceId),
        ])
      setAgents(listedAgents)
      setListedAgentsCount(listedAgents.length)
      setAgentsHasMore(listedAgents.length === CARD_BATCH_SIZE)
      setModels(nextModels)
      setKnowledgeBases(nextKnowledgeBases)
      setMcpServers(nextMcpServers)
    } catch (error) {
      setAgents([])
      setModels([])
      setKnowledgeBases([])
      setMcpServers([])
      setListedAgentsCount(0)
      reportError(error)
    } finally {
      setIsLoading(false)
      setHasLoadedWorkspaceData(true)
    }
  }, [reportError, selectedWorkspaceId, token])

  const loadMoreAgents = React.useCallback(async () => {
    if (!token || !selectedWorkspaceId) {
      return
    }
    if (agentsLoadingMoreRef.current || !agentsHasMore) {
      return
    }
    agentsLoadingMoreRef.current = true
    setIsAgentsLoadingMore(true)
    try {
      const batch = await listAgents(token, selectedWorkspaceId, {
        limit: CARD_BATCH_SIZE,
        offset: listedAgentsCount,
      })
      setAgents((current) => {
        const existingIds = new Set(current.map((agent) => agent.id))
        return [
          ...current,
          ...batch.filter((agent) => !existingIds.has(agent.id)),
        ]
      })
      setListedAgentsCount((current) => current + batch.length)
      setAgentsHasMore(batch.length === CARD_BATCH_SIZE)
    } catch (error) {
      reportError(error)
    } finally {
      agentsLoadingMoreRef.current = false
      setIsAgentsLoadingMore(false)
    }
  }, [
    agentsHasMore,
    listedAgentsCount,
    reportError,
    selectedWorkspaceId,
    token,
  ])

  const agentsListEndRef = useInfiniteScroll(loadMoreAgents)

  React.useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void loadWorkspaceData()
  }, [loadWorkspaceData])

  React.useEffect(() => {
    activeConversationIdRef.current = initialConversationId
  }, [initialConversationId, selectedAgentId])

  React.useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setActiveView(initialView)
  }, [initialView, selectedAgentId])

  React.useEffect(() => {
    if (!selectedAgent || form.id === selectedAgent.id) return
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setForm(formFromAgent(selectedAgent))
  }, [form.id, selectedAgent])

  React.useEffect(
    () => () => askAbortController?.abort(),
    [askAbortController, selectedAgentId]
  )

  React.useEffect(() => {
    if (
      !token ||
      !selectedWorkspaceId ||
      !selectedAgentId ||
      !hasLoadedWorkspaceData
    ) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setIsMissingAgentLoading(false)
      return
    }
    if (agents.some((agent) => agent.id === selectedAgentId)) {
      setIsMissingAgentLoading(false)
      return
    }
    let current = true
    setIsMissingAgentLoading(true)
    getAgent(token, selectedWorkspaceId, selectedAgentId)
      .then((agent) => {
        if (!current) return
        setAgents((currentAgents) =>
          currentAgents.some((item) => item.id === agent.id)
            ? currentAgents
            : [agent, ...currentAgents]
        )
      })
      .catch((error: unknown) => {
        if (current) reportError(error)
      })
      .finally(() => {
        if (current) setIsMissingAgentLoading(false)
      })
    return () => {
      current = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    hasLoadedWorkspaceData,
    reportError,
    selectedAgentId,
    selectedWorkspaceId,
    token,
  ])

  React.useEffect(() => {
    if (!selectedAgent || !selectedAgentId) return
    if (workflowCanvasMode && selectedAgent.app_type !== "workflow") {
      router.replace(appViewPath(selectedAgentId, "agent", "overview"))
      return
    }
    if (
      !workflowCanvasMode &&
      selectedAgent.app_type === "workflow" &&
      activeView === "settings"
    ) {
      router.replace(appViewPath(selectedAgentId, "workflow", "settings"))
    }
  }, [
    activeView,
    router,
    selectedAgent,
    selectedAgentId,
    workflowCanvasMode,
  ])

  React.useEffect(() => {
    if (
      token &&
      selectedWorkspaceId &&
      selectedAgentId &&
      hasLoadedWorkspaceData &&
      !isLoading &&
      !isMissingAgentLoading &&
      !selectedAgent
    ) {
      router.replace("/app/apps")
    }
  }, [
    hasLoadedWorkspaceData,
    isLoading,
    isMissingAgentLoading,
    router,
    selectedAgent,
    selectedAgentId,
    selectedWorkspaceId,
    token,
  ])

  React.useEffect(() => {
    if (
      !token ||
      !selectedWorkspaceId ||
      !selectedAgentId ||
      !selectedAgent ||
      selectedAgent.app_type === "workflow"
    ) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setRuns([])
      setToolCallsByRun({})
      return
    }
    if (activeView !== "settings") {
      return
    }
    let isCurrent = true
    let expectedConversationId = activeConversationIdRef.current
    const observers: AbortController[] = []
    setIsRunsLoading(true)
    listAgentRuns(
      token,
      selectedWorkspaceId,
      selectedAgentId,
      initialConversationId
    )
      .then((nextRuns) => {
        if (
          !isCurrent ||
          !isCurrentAgentConversation(
            activeConversationIdRef.current,
            expectedConversationId
          )
        ) {
          return
        }
        const resolvedConversationId =
          initialConversationId ??
          nextRuns[0]?.conversation_id ??
          crypto.randomUUID()
        activeConversationIdRef.current = resolvedConversationId
        expectedConversationId = resolvedConversationId
        const visibleRuns = nextRuns.filter(
          (run) => run.conversation_id === resolvedConversationId
        )
        setRuns(visibleRuns)
        if (!initialConversationId) {
          router.replace(
            `/app/apps/${selectedAgentId}?view=settings&conversation_id=${encodeURIComponent(resolvedConversationId)}`
          )
        }
        for (const run of visibleRuns) {
          if (run.status === "awaiting_approval") {
            void loadRunToolCalls(
              selectedAgentId,
              run.id,
              resolvedConversationId
            ).catch((error: unknown) => {
              if (
                isCurrent &&
                isCurrentAgentConversation(
                  activeConversationIdRef.current,
                  resolvedConversationId
                )
              ) {
                reportError(error)
              }
            })
          }
          if (
            !["queued", "running", "awaiting_approval"].includes(run.status)
          ) {
            continue
          }
          const controller = new AbortController()
          observers.push(controller)
          void observeAgentRun(
            token,
            selectedWorkspaceId,
            selectedAgentId,
            run.id,
            (streamEvent) =>
              applyStreamEvent(resolvedConversationId, run.id, streamEvent),
            controller.signal
          ).catch((error: unknown) => {
            if (
              !controller.signal.aborted &&
              isCurrentAgentConversation(
                activeConversationIdRef.current,
                resolvedConversationId
              )
            ) {
              reportError(error)
            }
          })
        }
      })
      .catch((error: unknown) => {
        if (
          isCurrent &&
          isCurrentAgentConversation(
            activeConversationIdRef.current,
            expectedConversationId
          )
        ) {
          setRuns([])
          reportError(error)
        }
      })
      .finally(() => {
        if (
          isCurrent &&
          isCurrentAgentConversation(
            activeConversationIdRef.current,
            expectedConversationId
          )
        ) {
          setIsRunsLoading(false)
        }
      })
    return () => {
      isCurrent = false
      observers.forEach((controller) => controller.abort())
    }
  }, [
    applyStreamEvent,
    loadRunToolCalls,
    reportError,
    router,
    initialConversationId,
    selectedAgentId,
    selectedAgent,
    selectedWorkspaceId,
    token,
    activeView,
  ])

  if (!token || !me) return null

  function modelLine(modelId: string) {
    const model = models.find((item) => item.id === modelId)
    if (!model) {
      return t("未连接")
    }
    return (
      <span className="flex min-w-0 items-center gap-1.5">
        <ModelIcon
          model={model.model_name}
          size={14}
          type="color"
          className="shrink-0"
        />
        <span className="truncate">{model.name}</span>
      </span>
    )
  }

  function openCreateDialog() {
    setForm({ ...EMPTY_FORM, modelId: activeModels[0]?.id ?? "" })
    setIsChooserOpen(true)
  }

  function chooseAppType(appType: AppType) {
    setForm((current) => ({
      ...current,
      appType,
      interactionConfig: normalizeInteractionConfigForAppType(
        current.interactionConfig,
        appType
      ),
    }))
    setIsChooserOpen(false)
    setIsDialogOpen(true)
  }

  function openAgent(agent: Agent) {
    setForm(formFromAgent(agent))
    router.push(`/app/apps/${agent.id}`)
  }

  async function handleSaveAgent(event?: React.FormEvent<HTMLFormElement>) {
    event?.preventDefault()
    if (!token || !selectedWorkspaceId || !form.name.trim() || !form.modelId)
      return
    setIsSaving(true)
    try {
      const interactionConfig = normalizeInteractionConfigForAppType(
        form.interactionConfig,
        form.appType
      )
      const payload = {
        name: form.name.trim(),
        app_type: form.appType,
        description: form.description.trim(),
        interaction_config: interactionConfig,
        model_id: form.modelId,
        instructions: form.instructions,
        knowledge_query_mode: form.knowledgeQueryMode,
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
        notify(
          "success",
          t(updated.app_type === "workflow" ? "工作流已更新" : "Agent 已更新")
        )
      } else {
        const created = await createAgent(token, selectedWorkspaceId, payload)
        setAgents((current) => [created, ...current])
        setForm(formFromAgent(created))
        router.push(`/app/apps/${created.id}`)
        notify(
          "success",
          t(created.app_type === "workflow" ? "工作流已创建" : "Agent 已创建")
        )
      }
      setIsDialogOpen(false)
    } catch (error) {
      reportError(error)
    } finally {
      setIsSaving(false)
    }
  }

  async function handlePublishAgent() {
    if (
      !token ||
      !selectedWorkspaceId ||
      !selectedAgent ||
      !canManagePublishing ||
      isDirty ||
      isPublishing
    ) {
      return
    }
    setIsPublishing(true)
    try {
      const publishing =
        !selectedAgent.published || selectedAgent.has_unpublished_changes
      const updated = await updateAgent(
        token,
        selectedWorkspaceId,
        selectedAgent.id,
        { published: publishing }
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
    } finally {
      setIsPublishing(false)
    }
  }

  function handleViewChange(view: AgentDetailView) {
    if (!selectedAgentId || !selectedAgent) return
    const path = appViewPath(
      selectedAgentId,
      selectedAgent.app_type,
      view,
      activeConversationIdRef.current
    )
    if (
      selectedAgent.app_type === "workflow" &&
      view === "settings" &&
      !workflowCanvasMode
    ) {
      router.push(path)
      return
    }
    setActiveView(view)
    router.replace(path)
  }

  async function handleDeleteAgent(agent: Agent) {
    if (
      !token ||
      !selectedWorkspaceId ||
      !window.confirm(
        t(
          agent.app_type === "workflow"
            ? "确定删除工作流“{name}”吗？"
            : "确定删除 Agent“{name}”吗？",
          { name: agent.name }
        )
      )
    ) {
      return
    }
    try {
      await deleteAgent(token, selectedWorkspaceId, agent.id)
      setAgents((current) => current.filter((item) => item.id !== agent.id))
      if (selectedAgentId === agent.id) router.push("/app/apps")
      notify(
        "success",
        t(agent.app_type === "workflow" ? "工作流已删除" : "Agent 已删除")
      )
    } catch (error) {
      reportError(error)
    }
  }

  function closeAgentPermissions() {
    permissionRequestRef.current += 1
    setPermissionAgent(null)
    setPermissionMembers([])
    setAgentPermissions([])
    setIsPermissionsLoading(false)
    setIsPermissionsSaving(false)
  }

  async function handleOpenAgentPermissions(agent: Agent) {
    if (!token || !selectedWorkspaceId || !agent.can_edit) return
    const requestId = permissionRequestRef.current + 1
    permissionRequestRef.current = requestId
    setPermissionAgent(agent)
    setPermissionMembers([])
    setAgentPermissions([])
    setIsPermissionsLoading(true)
    setIsPermissionsSaving(false)
    try {
      const [members, permissions] = await Promise.all([
        listWorkspaceMembers(token, selectedWorkspaceId),
        listAgentPermissions(token, selectedWorkspaceId, agent.id),
      ])
      if (permissionRequestRef.current !== requestId) return
      setPermissionMembers(members)
      setAgentPermissions(permissions)
    } catch (error) {
      if (permissionRequestRef.current !== requestId) return
      closeAgentPermissions()
      reportError(error)
    } finally {
      if (permissionRequestRef.current === requestId) {
        setIsPermissionsLoading(false)
      }
    }
  }

  async function handleGrantAgentPermission(userId: string) {
    if (!token || !selectedWorkspaceId || !permissionAgent) return
    const agentId = permissionAgent.id
    const requestId = permissionRequestRef.current
    setIsPermissionsSaving(true)
    try {
      const permission = await grantAgentPermission(
        token,
        selectedWorkspaceId,
        agentId,
        userId
      )
      if (permissionRequestRef.current !== requestId) return
      setAgentPermissions((current) => [
        ...current.filter((item) => item.user.id !== permission.user.id),
        permission,
      ])
      notify("success", t("授权已保存"))
    } catch (error) {
      if (permissionRequestRef.current === requestId) reportError(error)
    } finally {
      if (permissionRequestRef.current === requestId) {
        setIsPermissionsSaving(false)
      }
    }
  }

  async function handleRevokeAgentPermission(userId: string) {
    if (!token || !selectedWorkspaceId || !permissionAgent) return
    const agentId = permissionAgent.id
    const requestId = permissionRequestRef.current
    setIsPermissionsSaving(true)
    try {
      await revokeAgentPermission(
        token,
        selectedWorkspaceId,
        agentId,
        userId
      )
      if (permissionRequestRef.current !== requestId) return
      setAgentPermissions((current) =>
        current.filter((item) => item.user.id !== userId)
      )
      notify("success", t("授权已撤销"))
    } catch (error) {
      if (permissionRequestRef.current === requestId) reportError(error)
    } finally {
      if (permissionRequestRef.current === requestId) {
        setIsPermissionsSaving(false)
      }
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
      isRunsLoading ||
      isAsking ||
      selectedAgent.status !== "active"
    ) {
      return
    }
    const conversationId =
      activeConversationIdRef.current ??
      initialConversationId ??
      crypto.randomUUID()
    activeConversationIdRef.current = conversationId
    if (!initialConversationId) {
      router.replace(
        `/app/apps/${selectedAgent.id}?view=settings&conversation_id=${encodeURIComponent(conversationId)}`
      )
    }
    setQuestion("")
    setPendingQuestion(nextQuestion)
    setIsAsking(true)
    const askAbortController = new AbortController()
    setAskAbortController(askAbortController)
    const placeholderRun: AgentRun = {
      id: `pending-${Date.now()}`,
      workspace_id: selectedWorkspaceId,
      agent_id: selectedAgent.id,
      requested_by_user_id: me?.user.id ?? "",
      conversation_id: conversationId,
      goal: nextQuestion,
      model_id: selectedAgent.model_id,
      model_name:
        models.find((m) => m.id === selectedAgent.model_id)?.name ?? "",
      knowledge_query_mode: selectedAgent.knowledge_query_mode,
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
          duration_ms: 0,
          reasoning: "",
        },
      ],
      result: "",
      model_usage: {},
      last_error: null,
      planned_at: null,
      started_at: new Date().toISOString(),
      finished_at: null,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
      trace_id: "",
    }
    setRuns((current) => [placeholderRun, ...current])
    let liveRunId: string | null = null
    try {
      const uploaded = agentFiles.length
        ? await uploadAgentFiles(
            token,
            selectedWorkspaceId,
            selectedAgent.id,
            agentFiles
          )
        : []
      await streamAgentRun(
        token,
        selectedWorkspaceId,
        selectedAgent.id,
        nextQuestion,
        (streamEvent) => {
          if (
            !isCurrentAgentConversation(
              activeConversationIdRef.current,
              conversationId
            )
          ) {
            return
          }
          if (streamEvent.type === "run") {
            liveRunId = streamEvent.run.id
            setPendingQuestion(null)
          }
          const eventRunId =
            streamEvent.type === "run" ||
            streamEvent.type === "complete" ||
            streamEvent.type === "error"
              ? streamEvent.run.id
              : liveRunId
          if (eventRunId) {
            applyStreamEvent(
              conversationId,
              eventRunId,
              streamEvent,
              placeholderRun.id
            )
          }
          if (streamEvent.type === "error") {
            notify("error", t("Agent 回答失败"))
          }
          if (
            streamEvent.type === "complete" &&
            streamEvent.run.status === "succeeded" &&
            selectedAgent.interaction_config.tts_type === "BROWSER"
          ) {
            speakBrowserText(streamEvent.run.result, language)
          }
        },
        askAbortController.signal,
        conversationId,
        uploaded.map((item) => item.id)
      )
      setAgentFiles([])
    } catch (error) {
      const userCancelled = askAbortController.signal.aborted
      const isCurrentConversation = isCurrentAgentConversation(
        activeConversationIdRef.current,
        conversationId
      )
      if (!liveRunId && isCurrentConversation) {
        setQuestion(nextQuestion)
        setRuns((current) =>
          current.filter((run) => run.id !== placeholderRun.id)
        )
      }
      if (userCancelled || !isCurrentConversation) return
      reportError(error)
    } finally {
      if (
        isCurrentAgentConversation(
          activeConversationIdRef.current,
          conversationId
        )
      ) {
        setPendingQuestion(null)
        setIsAsking(false)
        setAskAbortController(null)
      }
    }
  }

  function handleCancelAsk() {
    askAbortController?.abort()
  }

  function handleNewConversation() {
    if (!selectedAgentId) return
    const conversationId = crypto.randomUUID()
    activeConversationIdRef.current = conversationId
    askAbortController?.abort()
    setRuns([])
    setToolCallsByRun({})
    setQuestion("")
    setAgentFiles([])
    setPendingQuestion(null)
    setAskAbortController(null)
    setIsAsking(false)
    setIsRunsLoading(false)
    setResolvingCallId(null)
    router.push(
      `/app/apps/${selectedAgentId}?view=settings&conversation_id=${encodeURIComponent(conversationId)}`
    )
  }

  async function handleToolCallDecision(
    runId: string,
    callId: string,
    decision: "approve" | "reject"
  ) {
    if (!token || !selectedWorkspaceId || !selectedAgent) return
    const conversationId = activeConversationIdRef.current
    if (!conversationId) return
    setResolvingCallId(`${runId}:${callId}`)
    try {
      const run = await resolveAgentToolCall(
        token,
        selectedWorkspaceId,
        selectedAgent.id,
        runId,
        callId,
        decision
      )
      if (
        !isCurrentAgentConversation(
          activeConversationIdRef.current,
          conversationId
        )
      ) {
        return
      }
      setRuns((current) => mergeAgentRunSnapshot(current, run))
      if (
        run.status === "succeeded" &&
        selectedAgent.interaction_config.tts_type === "BROWSER"
      ) {
        speakBrowserText(run.result, language)
      }
      await loadRunToolCalls(selectedAgent.id, runId, conversationId)
      if (
        !isCurrentAgentConversation(
          activeConversationIdRef.current,
          conversationId
        )
      ) {
        return
      }
      notify(
        "success",
        t(decision === "approve" ? "工具调用已批准" : "工具调用已拒绝")
      )
    } catch (error) {
      if (
        isCurrentAgentConversation(
          activeConversationIdRef.current,
          conversationId
        )
      ) {
        reportError(error)
      }
    } finally {
      if (
        isCurrentAgentConversation(
          activeConversationIdRef.current,
          conversationId
        )
      ) {
        setResolvingCallId(null)
      }
    }
  }

  if (selectedAgent && selectedWorkspaceId) {
    return (
      <>
        {selectedAgent.app_type === "workflow" ? (
          <WorkflowDetailWorkspace
            key={selectedAgent.id}
            agent={selectedAgent}
            form={form}
            setForm={setForm}
            models={models}
            knowledgeBases={knowledgeBases}
            mcpServers={mcpServers}
            token={token}
            workspaceId={selectedWorkspaceId}
            canManagePublishing={canManagePublishing}
            isAppDirty={isDirty}
            isSavingApp={isSaving}
            activeView={workflowCanvasMode ? "settings" : activeView}
            standalone={workflowCanvasMode}
            onBack={() =>
              workflowCanvasMode
                ? router.replace(
                    appViewPath(selectedAgent.id, "workflow", "overview")
                  )
                : router.push("/app/apps")
            }
            onDelete={() => void handleDeleteAgent(selectedAgent)}
            onManagePermissions={() =>
              void handleOpenAgentPermissions(selectedAgent)
            }
            onSaveApp={handleSaveAgent}
            onViewChange={handleViewChange}
            notify={notify}
            t={t}
          />
        ) : (
          <AgentDetailWorkspace
          agent={selectedAgent}
          form={form}
          setForm={setForm}
          models={models}
          knowledgeBases={knowledgeBases}
          mcpServers={mcpServers}
          runs={runs}
          toolCallsByRun={toolCallsByRun}
          resolvingCallId={resolvingCallId}
          question={question}
          setQuestion={setQuestion}
          files={agentFiles}
          setFiles={setAgentFiles}
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
          onManagePermissions={() =>
            void handleOpenAgentPermissions(selectedAgent)
          }
          onSave={handleSaveAgent}
          onPublish={() => void handlePublishAgent()}
          isPublishing={isPublishing}
          activeView={activeView}
          onViewChange={handleViewChange}
          token={token}
          workspaceId={selectedWorkspaceId}
          canManagePublishing={canManagePublishing}
          notify={notify}
          onAsk={handleAsk}
          onCancelAsk={handleCancelAsk}
          onNewConversation={handleNewConversation}
          onToolCallDecision={(runId, callId, decision) =>
            void handleToolCallDecision(runId, callId, decision)
          }
          t={t}
          />
        )}
        <AgentPermissionsDialog
          agent={permissionAgent}
          members={permissionMembers}
          permissions={agentPermissions}
          isLoading={isPermissionsLoading}
          isSaving={isPermissionsSaving}
          onClose={closeAgentPermissions}
          onGrant={handleGrantAgentPermission}
          onRevoke={handleRevokeAgentPermission}
        />
      </>
    )
  }

  return (
    <>
      {isLoading ? <TopLoadingBar progress={35} /> : null}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <h1 className="text-2xl font-semibold">{t("应用")}</h1>
          <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
            {t("编排业务流程、知识库和模型能力，构建可运行的 AI 应用。")}
          </p>
        </div>
        <Button
          type="button"
          onClick={openCreateDialog}
          disabled={activeModels.length === 0}
        >
          <PlusIcon data-icon="inline-start" />
          {t("新建应用")}
        </Button>
      </div>

      <div className="rounded-lg border bg-background p-3 shadow-sm">
        <div className="relative min-w-0 sm:w-[320px]">
          <SearchIcon className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={agentSearch}
            onChange={(event) => setAgentSearch(event.target.value)}
            placeholder={t("搜索{label}...", { label: t("应用") })}
            className="pl-9"
          />
        </div>
      </div>

      {isLoading && agents.length === 0 ? null : agents.length === 0 ? (
        <div className="mx-auto flex min-h-[320px] max-w-xl flex-col items-center justify-center gap-4 p-6 text-center">
          <span className="flex size-14 items-center justify-center rounded-lg bg-muted">
            <BotIcon className="size-5 text-muted-foreground" />
          </span>
          <div className="flex flex-col gap-2">
            <p className="text-base font-semibold">{t("还没有应用")}</p>
            <p className="text-sm leading-6 text-muted-foreground">
              {activeModels.length === 0
                ? t("先接入一个已启用的大语言模型，再创建 Agent。")
                : t("创建应用后，可以编排对话、检索和工具调用流程。")}
            </p>
          </div>
          {activeModels.length > 0 ? (
            <Button type="button" onClick={openCreateDialog}>
              <PlusIcon data-icon="inline-start" />
              {t("新建应用")}
            </Button>
          ) : null}
        </div>
      ) : filteredAgents.length === 0 ? (
        <div className="rounded-lg border bg-background p-8 text-center text-sm text-muted-foreground shadow-sm">
          {t("没有匹配的 Agent")}
        </div>
      ) : (
        <>
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">
            {filteredAgents.map((agent) => (
            <div
              key={agent.id}
              role="button"
              tabIndex={0}
              className="flex min-h-40 cursor-pointer flex-col rounded-md border p-3 transition-colors outline-none hover:bg-muted/40 focus-visible:ring-2 focus-visible:ring-ring"
              onClick={(event) => {
                if (isEventFromDropdownMenu(event)) return
                openAgent(agent)
              }}
              onKeyDown={(event) => {
                if (event.target !== event.currentTarget) return
                if (event.key === "Enter" || event.key === " ") {
                  event.preventDefault()
                  openAgent(agent)
                }
              }}
            >
              <div className="flex items-start justify-between gap-3">
                <div className="flex min-w-0 gap-3">
                  <span className="flex size-9 shrink-0 items-center justify-center rounded-md bg-violet-500/10 text-violet-700 dark:text-violet-400">
                    {agent.app_type === "workflow" ? (
                      <WorkflowIcon className="size-5" />
                    ) : (
                      <SparklesIcon className="size-5" />
                    )}
                  </span>
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <h2 className="truncate text-sm font-semibold">
                        {agent.name}
                      </h2>
                      <Badge variant="secondary">
                        {agent.app_type === "workflow"
                          ? t("工作流")
                          : t("Agent")}
                      </Badge>
                      <StatusBadge status={agent.status} />
                      <PermissionBadge
                        permission={agent.can_edit ? "edit" : "view"}
                      />
                    </div>
                    <p className="mt-1 flex items-center gap-1.5 truncate text-sm text-muted-foreground">
                      {modelLine(agent.model_id)}
                    </p>
                  </div>
                </div>
                {agent.can_edit ? (
                  <IconButton
                    label={t("编辑应用")}
                    onClick={(event) => {
                      event.stopPropagation()
                      openAgent(agent)
                    }}
                  >
                    <PencilIcon className="size-4" />
                  </IconButton>
                ) : null}
              </div>
              <div className="mt-auto flex items-end justify-between gap-2 pt-4">
                <dl className="grid grid-cols-2 gap-3 text-sm">
                  <Spec
                    label={t("知识库")}
                    value={String(agent.knowledge_base_ids.length)}
                  />
                  <Spec
                    label={t("MCP 工具")}
                    value={String(agent.mcp_tools.length)}
                  />
                </dl>
                {agent.can_edit ? (
                  <CardMoreMenu label={t("更多")}>
                    <DropdownMenuItem
                      onSelect={() => void handleOpenAgentPermissions(agent)}
                    >
                      <ShieldCheckIcon />
                      {t("资源授权")}
                    </DropdownMenuItem>
                    <DropdownMenuItem
                      variant="destructive"
                      onSelect={() => void handleDeleteAgent(agent)}
                    >
                      <Trash2Icon />
                      {t("删除")}
                    </DropdownMenuItem>
                  </CardMoreMenu>
                ) : null}
              </div>
            </div>
          ))}
        </div>
        <div
          ref={agentsListEndRef}
          className="flex min-h-12 items-center justify-center gap-2 py-3 text-sm text-muted-foreground"
        >
          {isAgentsLoadingMore ? (
            <>
              <LoaderCircleIcon className="size-4 animate-spin" />
              {t("正在加载")}
            </>
          ) : agents.length > 0 && !agentsHasMore ? (
            t("已加载全部")
          ) : null}
          </div>
        </>
      )}

      {renderTypeChooserDialog()}
      {renderAgentDialog()}
      <AgentPermissionsDialog
        agent={permissionAgent}
        members={permissionMembers}
        permissions={agentPermissions}
        isLoading={isPermissionsLoading}
        isSaving={isPermissionsSaving}
        onClose={closeAgentPermissions}
        onGrant={handleGrantAgentPermission}
        onRevoke={handleRevokeAgentPermission}
      />
    </>
  )

  function renderTypeChooserDialog() {
    return (
      <Dialog open={isChooserOpen} onOpenChange={setIsChooserOpen}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle>{t("选择要创建的应用类型")}</DialogTitle>
            <DialogDescription>
              {t("根据使用方式选择应用类型，创建后不可更改。")}
            </DialogDescription>
          </DialogHeader>
          <div className="grid gap-3 sm:grid-cols-2">
            <button
              type="button"
              className="group flex flex-col gap-2 rounded-md border p-4 text-left transition-colors outline-none hover:bg-muted/40 focus-visible:ring-2 focus-visible:ring-ring"
              onClick={() => chooseAppType("agent")}
            >
              <span className="flex size-9 items-center justify-center rounded-md bg-violet-500/10 text-violet-700 dark:text-violet-400">
                <BotIcon className="size-5" />
              </span>
              <span className="text-sm font-semibold">{t("Agent")}</span>
              <span className="text-sm leading-5 text-muted-foreground">
                {t("智能对话助手，自动规划并使用模型、知识和工具。")}
              </span>
            </button>
            <button
              type="button"
              className="group flex flex-col gap-2 rounded-md border p-4 text-left transition-colors outline-none hover:bg-muted/40 focus-visible:ring-2 focus-visible:ring-ring"
              onClick={() => chooseAppType("workflow")}
            >
              <span className="flex size-9 items-center justify-center rounded-md bg-violet-500/10 text-violet-700 dark:text-violet-400">
                <WorkflowIcon className="size-5" />
              </span>
              <span className="text-sm font-semibold">{t("工作流")}</span>
              <span className="text-sm leading-5 text-muted-foreground">
                {t("按预设步骤编排固定流程，适合确定性的处理任务。")}
              </span>
            </button>
          </div>
        </DialogContent>
      </Dialog>
    )
  }

  function renderAgentDialog() {
    return (
      <Dialog open={isDialogOpen} onOpenChange={setIsDialogOpen}>
        <DialogContent className="max-h-[calc(100svh-2rem)] max-w-xl overflow-y-auto">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              {form.id ? t("编辑应用") : t("新建应用")}
              <Badge variant="secondary">
                {form.appType === "workflow" ? t("工作流") : t("Agent")}
              </Badge>
            </DialogTitle>
            <DialogDescription>
              {t(
                !form.id
                  ? "填写应用名称、描述和模型。"
                  : form.appType === "workflow"
                  ? "设置工作流默认模型和可使用的资源，创建后进入画布编排。"
                  : "只需选择 Agent 可以使用的模型、知识和工具。"
              )}
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
                {form.id ? t("保存") : t("新建应用")}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    )
  }
}
