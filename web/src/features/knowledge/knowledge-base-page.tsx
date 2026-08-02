import * as React from "react"
import {
  AlertCircleIcon,
  ArchiveIcon,
  ArrowDownIcon,
  ArrowLeftIcon,
  ArrowUpDownIcon,
  ArrowUpIcon,
  CircleCheckIcon,
  DownloadIcon,
  FileTextIcon,
  FlaskConicalIcon,
  HelpCircleIcon,
  LoaderCircleIcon,
  MoreHorizontalIcon,
  PencilIcon,
  PlusIcon,
  RotateCcwIcon,
  SearchIcon,
  SettingsIcon,
  SlidersHorizontalIcon,
  TargetIcon,
  Trash2Icon,
  UploadIcon,
  UsersIcon,
} from "lucide-react"
import { useLanguage } from "@/components/language-provider"
import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { Input } from "@/components/ui/input"
import {
  createKnowledgeBase,
  deleteKnowledgeDocument,
  deleteKnowledgeBase,
  downloadKnowledgeDocument,
  indexKnowledgeDocument,
  listKnowledgeBasePermissions,
  listKnowledgeBases,
  listKnowledgeDocuments,
  listKnowledgeTasks,
  parseKnowledgeDocument,
  queryKnowledgeBase,
  rebuildKnowledgeIndex,
  retryKnowledgeTask,
  revokeKnowledgeBasePermission,
  setKnowledgeDocumentActive,
  testKnowledgeBaseModels,
  updateKnowledgeBase,
  upsertKnowledgeBasePermission,
} from "@/features/knowledge/api"
import type {
  KnowledgeBase,
  KnowledgeDocument,
  KnowledgeModelTestResult,
  KnowledgeQueryHit,
  KnowledgeTask,
  ResourcePermission,
} from "@/features/knowledge/types"
import type { MeResponse } from "@/features/auth/types"
import { listRegisteredModels } from "@/features/llm/api"
import type { RegisteredModel } from "@/features/llm/types"
import { listWorkspaceMembers } from "@/features/system/api"
import type { WorkspaceMember } from "@/features/system/types"
import { type FeaturePageConfig } from "@/lib/pages"
import { languageLocales } from "@/lib/i18n"
import { cn } from "@/lib/utils"
import { formatDateTime, getMembershipRole } from "@/app/display"
import { getErrorMessage } from "@/app/errors"
import type { AppNotification } from "@/app/notifications"
import { KnowledgeBaseDialogs } from "@/features/knowledge/knowledge-base-dialogs"
import { MarkdownContent } from "@/features/knowledge/markdown-content"
import { KnowledgeUploadFlow } from "@/features/knowledge/knowledge-upload-flow"
import {
  documentStatusDotClassName,
  documentStatusLabel,
  formatBytes,
  taskStatusDotClassName,
  taskStatusLabel,
  taskTypeLabel,
} from "@/features/knowledge/status-labels"
import {
  PermissionBadge,
  StatusBadge,
} from "@/features/knowledge/status-badges"
import type {
  KnowledgeBaseDetailTab,
  KnowledgeBaseEditForm,
  KnowledgeBaseForm,
  KnowledgeBasePermissionForm,
} from "@/features/knowledge/types"

type DocumentSortKey =
  | "name"
  | "size_bytes"
  | "chunk_count"
  | "created_at"
  | "updated_at"

const DOCUMENT_SORT_OPTIONS: Array<{
  key: DocumentSortKey
  label: string
}> = [
  { key: "name", label: "名称" },
  { key: "size_bytes", label: "大小" },
  { key: "chunk_count", label: "分段数" },
  { key: "created_at", label: "创建时间" },
  { key: "updated_at", label: "更新时间" },
]

const DOCUMENT_SORT_FIELDS: Record<DocumentSortKey, keyof KnowledgeDocument> = {
  name: "filename",
  size_bytes: "size_bytes",
  chunk_count: "chunk_count",
  created_at: "created_at",
  updated_at: "updated_at",
}

const PROCESSING_DOCUMENT_STATUSES: Record<string, true> = {
  parse_queued: true,
  parsing: true,
  index_queued: true,
  indexing: true,
}

function documentStatusText(
  document: KnowledgeDocument,
  tasks: KnowledgeTask[]
) {
  if (document.status === "indexing") {
    const indexTask = tasks.find(
      (task) =>
        task.document_id === document.id &&
        task.task_type === "index" &&
        task.total_items > 0
    )
    if (indexTask) {
      return `向量化中 ${indexTask.processed_items}/${indexTask.total_items}`
    }
  }

  return documentStatusLabel(document.status)
}

export function KnowledgeBasePage({
  page,
  token,
  me,
  selectedWorkspaceId,
  activeKnowledgeBaseId,
  onOpenKnowledgeBase,
  onCloseKnowledgeBase,
  onOpenDocument,
  onNotify,
}: {
  page: FeaturePageConfig
  token: string
  me: MeResponse
  selectedWorkspaceId: string | null
  activeKnowledgeBaseId: string | null
  onOpenKnowledgeBase: (knowledgeBaseId: string) => void
  onCloseKnowledgeBase: () => void
  onOpenDocument: (documentId: string) => void
  onNotify: (kind: AppNotification["kind"], message: string) => void
}) {
  const { language, t } = useLanguage()
  const locale = languageLocales[language]
  const [knowledgeBases, setKnowledgeBases] = React.useState<KnowledgeBase[]>(
    []
  )
  const [documents, setDocuments] = React.useState<KnowledgeDocument[]>([])
  const [knowledgeTasks, setKnowledgeTasks] = React.useState<KnowledgeTask[]>(
    []
  )
  const [queryText, setQueryText] = React.useState("")
  const [queryLimit, setQueryLimit] = React.useState(5)
  const [queryHits, setQueryHits] = React.useState<KnowledgeQueryHit[]>([])
  const [selectedDocumentIds, setSelectedDocumentIds] = React.useState<
    string[]
  >([])
  const [registeredModels, setRegisteredModels] = React.useState<
    RegisteredModel[]
  >([])
  const [knowledgeSearch, setKnowledgeSearch] = React.useState("")
  const [documentSearch, setDocumentSearch] = React.useState("")
  const [documentSortKey, setDocumentSortKey] =
    React.useState<DocumentSortKey>("created_at")
  const [documentSortDirection, setDocumentSortDirection] = React.useState<
    "asc" | "desc"
  >("desc")
  const [workspaceMembers, setWorkspaceMembers] = React.useState<
    WorkspaceMember[]
  >([])
  const [permissions, setPermissions] = React.useState<ResourcePermission[]>([])
  const [activeDetailTab, setActiveDetailTab] =
    React.useState<KnowledgeBaseDetailTab>("documents")
  const [form, setForm] = React.useState<KnowledgeBaseForm>({
    name: "",
    description: "",
    embedding_model_id: null,
    reranker_model_id: null,
  })
  const [editForm, setEditForm] = React.useState<KnowledgeBaseEditForm | null>(
    null
  )
  const [permissionForm, setPermissionForm] =
    React.useState<KnowledgeBasePermissionForm | null>(null)
  const [isLoading, setIsLoading] = React.useState(false)
  const [isDocumentLoading, setIsDocumentLoading] = React.useState(false)
  const [isKnowledgeTaskLoading, setIsKnowledgeTaskLoading] =
    React.useState(false)
  const [isSubmittingDocumentTask, setIsSubmittingDocumentTask] =
    React.useState(false)
  const [isRetryingTask, setIsRetryingTask] = React.useState(false)
  const [isQuerying, setIsQuerying] = React.useState(false)
  const [isTestingModels, setIsTestingModels] = React.useState(false)
  const [modelTestResult, setModelTestResult] =
    React.useState<KnowledgeModelTestResult | null>(null)
  const [modelTestError, setModelTestError] = React.useState<string | null>(
    null
  )
  const [isSaving, setIsSaving] = React.useState(false)
  const [isDialogOpen, setIsDialogOpen] = React.useState(false)
  const [isUploadFlowOpen, setIsUploadFlowOpen] = React.useState(false)
  const selectAllDocumentsRef = React.useRef<HTMLInputElement>(null)

  const workspaceRole = getMembershipRole(me, selectedWorkspaceId)
  const Icon = page.icon
  const selectedKnowledgeBaseId = activeKnowledgeBaseId
  const selectedKnowledgeBase =
    knowledgeBases.find((item) => item.id === selectedKnowledgeBaseId) ?? null
  const canEditDocuments = selectedKnowledgeBase?.permission === "edit"
  const selectedEmbeddingModel =
    registeredModels.find(
      (model) => model.id === selectedKnowledgeBase?.embedding_model_id
    ) ?? null
  const selectedRerankerModel =
    registeredModels.find(
      (model) => model.id === selectedKnowledgeBase?.reranker_model_id
    ) ?? null
  const filteredKnowledgeBases = React.useMemo(() => {
    const search = knowledgeSearch.trim().toLowerCase()

    if (!search) {
      return knowledgeBases
    }

    return knowledgeBases.filter((knowledgeBase) =>
      [knowledgeBase.name, knowledgeBase.description].some((value) =>
        value.toLowerCase().includes(search)
      )
    )
  }, [knowledgeBases, knowledgeSearch])
  const filteredDocuments = React.useMemo(() => {
    const search = documentSearch.trim().toLowerCase()
    const matched = search
      ? documents.filter((document) =>
          document.filename.toLowerCase().includes(search)
        )
      : documents
    const direction = documentSortDirection === "asc" ? 1 : -1
    const sortField = DOCUMENT_SORT_FIELDS[documentSortKey]
    return [...matched].sort((left, right) => {
      const leftValue = left[sortField]
      const rightValue = right[sortField]
      if (typeof leftValue === "string") {
        return leftValue.localeCompare(String(rightValue)) * direction
      }
      return (Number(leftValue) - Number(rightValue)) * direction
    })
  }, [documents, documentSearch, documentSortDirection, documentSortKey])

  function cycleDocumentSort(key: DocumentSortKey) {
    if (documentSortKey === key) {
      setDocumentSortDirection((current) =>
        current === "asc" ? "desc" : "asc"
      )
      return
    }
    setDocumentSortKey(key)
    setDocumentSortDirection(key === "name" ? "asc" : "desc")
  }
  const selectedDocuments = documents.filter((document) =>
    selectedDocumentIds.includes(document.id)
  )
  const selectedDocumentCount = selectedDocuments.length
  const isAllFilteredDocumentsSelected =
    filteredDocuments.length > 0 &&
    filteredDocuments.every((document) =>
      selectedDocumentIds.includes(document.id)
    )
  const isSomeFilteredDocumentSelected = filteredDocuments.some((document) =>
    selectedDocumentIds.includes(document.id)
  )

  React.useEffect(() => {
    if (selectAllDocumentsRef.current) {
      selectAllDocumentsRef.current.indeterminate =
        isSomeFilteredDocumentSelected && !isAllFilteredDocumentsSelected
    }
  }, [isAllFilteredDocumentsSelected, isSomeFilteredDocumentSelected])

  const reportError = React.useCallback(
    (error: unknown) => {
      const message = getErrorMessage(error, t)
      onNotify("error", message)
      return message
    },
    [onNotify, t]
  )

  const loadKnowledgeBases = React.useCallback(async () => {
    if (!selectedWorkspaceId) {
      setKnowledgeBases([])
      setRegisteredModels([])
      return
    }

    setIsLoading(true)
    try {
      const [knowledgeBases, models] = await Promise.all([
        listKnowledgeBases(token, selectedWorkspaceId),
        listRegisteredModels(token, selectedWorkspaceId),
      ])
      setKnowledgeBases(knowledgeBases)
      setRegisteredModels(models)
    } catch (error) {
      setKnowledgeBases([])
      setRegisteredModels([])
      reportError(error)
    } finally {
      setIsLoading(false)
    }
  }, [reportError, selectedWorkspaceId, token])

  const loadDocuments = React.useCallback(async (silent = false) => {
    if (!selectedWorkspaceId || !selectedKnowledgeBaseId) {
      setDocuments([])
      return
    }

    if (!silent) {
      setIsDocumentLoading(true)
    }
    try {
      setDocuments(
        await listKnowledgeDocuments(
          token,
          selectedWorkspaceId,
          selectedKnowledgeBaseId
        )
      )
    } catch (error) {
      if (!silent) {
        setDocuments([])
        reportError(error)
      }
    } finally {
      if (!silent) {
        setIsDocumentLoading(false)
      }
    }
  }, [reportError, selectedKnowledgeBaseId, selectedWorkspaceId, token])

  const loadKnowledgeTasks = React.useCallback(async (silent = false) => {
    if (!selectedWorkspaceId || !selectedKnowledgeBaseId) {
      setKnowledgeTasks([])
      return
    }

    if (!silent) {
      setIsKnowledgeTaskLoading(true)
    }
    try {
      setKnowledgeTasks(
        await listKnowledgeTasks(token, selectedWorkspaceId, selectedKnowledgeBaseId)
      )
    } catch (error) {
      if (!silent) {
        setKnowledgeTasks([])
        reportError(error)
      }
    } finally {
      if (!silent) {
        setIsKnowledgeTaskLoading(false)
      }
    }
  }, [reportError, selectedKnowledgeBaseId, selectedWorkspaceId, token])

  React.useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void loadKnowledgeBases()
  }, [loadKnowledgeBases])

  React.useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void loadDocuments()
  }, [loadDocuments])

  React.useEffect(() => {
    if (activeDetailTab !== "tasks") {
      return
    }

    // eslint-disable-next-line react-hooks/set-state-in-effect
    void loadKnowledgeTasks()
  }, [activeDetailTab, loadKnowledgeTasks])

  const hasProcessingDocuments = documents.some(
    (document) => PROCESSING_DOCUMENT_STATUSES[document.status]
  )

  React.useEffect(() => {
    if (!hasProcessingDocuments) {
      return
    }

    const timer = window.setInterval(() => {
      void loadDocuments(true)
      void loadKnowledgeTasks(true)
    }, 3000)
    return () => window.clearInterval(timer)
  }, [hasProcessingDocuments, loadDocuments, loadKnowledgeTasks])

  function toggleDocumentSelection(documentId: string, checked: boolean) {
    setSelectedDocumentIds((current) =>
      checked
        ? current.includes(documentId)
          ? current
          : [...current, documentId]
        : current.filter((id) => id !== documentId)
    )
  }

  function toggleAllFilteredDocuments(checked: boolean) {
    const filteredDocumentIds = filteredDocuments.map((document) => document.id)
    setSelectedDocumentIds((current) =>
      checked
        ? Array.from(new Set([...current, ...filteredDocumentIds]))
        : current.filter((id) => !filteredDocumentIds.includes(id))
    )
  }

  function canManagePermissions(knowledgeBase: KnowledgeBase) {
    return (
      workspaceRole === "admin" ||
      knowledgeBase.created_by_user_id === me.user.id
    )
  }

  function formatDistance(distance: number | null) {
    return distance === null ? "-" : distance.toFixed(4)
  }

  function registeredModelLabel(model: RegisteredModel | null) {
    return model ? `${model.name} / ${model.model_name}` : "未配置"
  }

  function resetForm() {
    setForm({
      name: "",
      description: "",
      embedding_model_id: null,
      reranker_model_id: null,
    })
  }

  function updateKnowledgeBaseInList(knowledgeBase: KnowledgeBase) {
    setKnowledgeBases((current) =>
      current.map((item) =>
        item.id === knowledgeBase.id ? knowledgeBase : item
      )
    )
  }

  function openKnowledgeBase(knowledgeBase: KnowledgeBase) {
    setActiveDetailTab("documents")
    setDocumentSearch("")
    setSelectedDocumentIds([])
    setKnowledgeTasks([])
    setQueryHits([])
    setQueryText("")
    setIsUploadFlowOpen(false)
    onOpenKnowledgeBase(knowledgeBase.id)
  }

  function closeKnowledgeBase() {
    setIsUploadFlowOpen(false)
    setKnowledgeTasks([])
    onCloseKnowledgeBase()
  }

  async function handleCreate(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!selectedWorkspaceId) {
      return
    }

    setIsSaving(true)
    try {
      const knowledgeBase = await createKnowledgeBase(
        token,
        selectedWorkspaceId,
        form
      )
      setKnowledgeBases((current) => [...current, knowledgeBase])
      resetForm()
      setIsDialogOpen(false)
      onNotify("success", "知识库已新建")
    } catch (error) {
      reportError(error)
    } finally {
      setIsSaving(false)
    }
  }

  async function handleUpdate(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!selectedWorkspaceId || !editForm) {
      return
    }

    setIsSaving(true)
    try {
      updateKnowledgeBaseInList(
        await updateKnowledgeBase(token, selectedWorkspaceId, editForm.id, {
          name: editForm.name,
          description: editForm.description,
          embedding_model_id: editForm.embedding_model_id,
          reranker_model_id: editForm.reranker_model_id,
        })
      )
      setEditForm(null)
      onNotify("success", "知识库已更新")
    } catch (error) {
      reportError(error)
    } finally {
      setIsSaving(false)
    }
  }

  async function handleToggleStatus(knowledgeBase: KnowledgeBase) {
    if (!selectedWorkspaceId) {
      return
    }

    const nextStatus = knowledgeBase.status === "active" ? "archived" : "active"
    try {
      updateKnowledgeBaseInList(
        await updateKnowledgeBase(
          token,
          selectedWorkspaceId,
          knowledgeBase.id,
          {
            status: nextStatus,
          }
        )
      )
      onNotify(
        "success",
        nextStatus === "active" ? "知识库已恢复" : "知识库已归档"
      )
    } catch (error) {
      reportError(error)
    }
  }

  async function handleTestKnowledgeModels() {
    if (!selectedWorkspaceId || !selectedKnowledgeBase) {
      return
    }

    setIsTestingModels(true)
    setModelTestError(null)
    try {
      const result = await testKnowledgeBaseModels(
        token,
        selectedWorkspaceId,
        selectedKnowledgeBase.id
      )
      setModelTestResult(result)
    } catch (error) {
      setModelTestResult(null)
      setModelTestError(getErrorMessage(error, t))
    } finally {
      setIsTestingModels(false)
    }
  }

  async function handleDelete(knowledgeBase: KnowledgeBase) {
    if (!selectedWorkspaceId) {
      return
    }

    if (
      !window.confirm(
        t("永久删除 {name}？此操作不可恢复。", { name: knowledgeBase.name })
      )
    ) {
      return
    }

    try {
      await deleteKnowledgeBase(token, selectedWorkspaceId, knowledgeBase.id)
      setKnowledgeBases((current) =>
        current.filter((item) => item.id !== knowledgeBase.id)
      )
      if (selectedKnowledgeBaseId === knowledgeBase.id) {
        closeKnowledgeBase()
      }
      onNotify("success", "知识库已删除")
    } catch (error) {
      reportError(error)
    }
  }

  async function handleParseDocument(document: KnowledgeDocument) {
    if (!selectedWorkspaceId || !selectedKnowledgeBase) {
      return
    }

    setIsSubmittingDocumentTask(true)
    try {
      await parseKnowledgeDocument(
        token,
        selectedWorkspaceId,
        selectedKnowledgeBase.id,
        document.id,
        {
          chunk_size: 1200,
          chunk_overlap: 150,
          cleaning_rules: [],
          auto_index: false,
        }
      )
      await loadDocuments()
      await loadKnowledgeTasks()
      onNotify("success", "已提交解析任务")
    } catch (error) {
      reportError(error)
    } finally {
      setIsSubmittingDocumentTask(false)
    }
  }

  async function handleIndexDocuments(targetDocuments: KnowledgeDocument[]) {
    if (!selectedWorkspaceId || !selectedKnowledgeBase || !targetDocuments.length) {
      return
    }

    setIsSubmittingDocumentTask(true)
    try {
      await Promise.all(
        targetDocuments.map((document) =>
          indexKnowledgeDocument(
            token,
            selectedWorkspaceId,
            selectedKnowledgeBase.id,
            document.id
          )
        )
      )
      await loadDocuments()
      await loadKnowledgeTasks()
      onNotify(
        "success",
        targetDocuments.length === 1
          ? "已提交向量化任务"
          : `已提交 ${targetDocuments.length} 个向量化任务`
      )
    } catch (error) {
      reportError(error)
    } finally {
      setIsSubmittingDocumentTask(false)
    }
  }

  async function handleDownloadDocument(document: KnowledgeDocument) {
    if (!selectedWorkspaceId || !selectedKnowledgeBase) {
      return
    }

    try {
      await downloadKnowledgeDocument(
        token,
        selectedWorkspaceId,
        selectedKnowledgeBase.id,
        document.id,
        document.filename
      )
    } catch (error) {
      reportError(error)
    }
  }

  async function handleToggleDocumentActive(document: KnowledgeDocument) {
    if (!selectedWorkspaceId || !selectedKnowledgeBase) {
      return
    }

    setIsSubmittingDocumentTask(true)
    try {
      const updated = await setKnowledgeDocumentActive(
        token,
        selectedWorkspaceId,
        selectedKnowledgeBase.id,
        document.id,
        !document.is_active
      )
      setDocuments((current) =>
        current.map((item) => (item.id === updated.id ? updated : item))
      )
      onNotify("success", updated.is_active ? "文档已启用" : "文档已停用")
    } catch (error) {
      reportError(error)
    } finally {
      setIsSubmittingDocumentTask(false)
    }
  }

  async function handleDeleteSelectedDocuments() {
    if (!selectedWorkspaceId || !selectedKnowledgeBase || !selectedDocuments.length) {
      return
    }

    if (
      !window.confirm(
        `永久删除选中的 ${selectedDocuments.length} 个文档？此操作不可恢复。`
      )
    ) {
      return
    }

    setIsSubmittingDocumentTask(true)
    try {
      await Promise.all(
        selectedDocuments.map((document) =>
          deleteKnowledgeDocument(
            token,
            selectedWorkspaceId,
            selectedKnowledgeBase.id,
            document.id
          )
        )
      )
      const deletedIds = new Set(selectedDocuments.map((document) => document.id))
      setDocuments((current) =>
        current.filter((item) => !deletedIds.has(item.id))
      )
      setSelectedDocumentIds([])
      await loadKnowledgeTasks()
      onNotify("success", `已删除 ${selectedDocuments.length} 个文档`)
    } catch (error) {
      reportError(error)
    } finally {
      setIsSubmittingDocumentTask(false)
    }
  }

  async function handleRebuildIndex() {
    if (!selectedWorkspaceId || !selectedKnowledgeBase) {
      return
    }

    setIsSubmittingDocumentTask(true)
    try {
      await rebuildKnowledgeIndex(
        token,
        selectedWorkspaceId,
        selectedKnowledgeBase.id
      )
      await loadKnowledgeTasks()
      onNotify("success", "已提交重建索引任务")
    } catch (error) {
      reportError(error)
    } finally {
      setIsSubmittingDocumentTask(false)
    }
  }

  async function handleRetryKnowledgeTask(task: KnowledgeTask) {
    if (!selectedWorkspaceId || !selectedKnowledgeBase) {
      return
    }

    setIsRetryingTask(true)
    try {
      await retryKnowledgeTask(
        token,
        selectedWorkspaceId,
        selectedKnowledgeBase.id,
        task.id
      )
      await Promise.all([
        loadDocuments(),
        loadKnowledgeTasks(),
      ])
      onNotify("success", "已重新提交任务")
    } catch (error) {
      reportError(error)
    } finally {
      setIsRetryingTask(false)
    }
  }

  async function handleQueryKnowledgeBase(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!selectedWorkspaceId || !selectedKnowledgeBase) {
      return
    }

    const query = queryText.trim()
    if (!query) {
      return
    }

    setIsQuerying(true)
    try {
      setQueryHits(
        await queryKnowledgeBase(token, selectedWorkspaceId, selectedKnowledgeBase.id, {
          query,
          limit: queryLimit,
        })
      )
    } catch (error) {
      setQueryHits([])
      reportError(error)
    } finally {
      setIsQuerying(false)
    }
  }

  async function handleDeleteDocument(document: KnowledgeDocument) {
    if (!selectedWorkspaceId || !selectedKnowledgeBase) {
      return
    }

    if (
      !window.confirm(
        t("永久删除 {name}？此操作不可恢复。", { name: document.filename })
      )
    ) {
      return
    }

    try {
      await deleteKnowledgeDocument(
        token,
        selectedWorkspaceId,
        selectedKnowledgeBase.id,
        document.id
      )
      setDocuments((current) =>
        current.filter((item) => item.id !== document.id)
      )
      setSelectedDocumentIds((current) =>
        current.filter((id) => id !== document.id)
      )
      await loadKnowledgeTasks()
      onNotify("success", "文档已删除")
    } catch (error) {
      reportError(error)
    }
  }

  async function handleOpenPermissions(knowledgeBase: KnowledgeBase) {
    if (!selectedWorkspaceId) {
      return
    }

    try {
      const [members, grants] = await Promise.all([
        listWorkspaceMembers(token, selectedWorkspaceId),
        listKnowledgeBasePermissions(
          token,
          selectedWorkspaceId,
          knowledgeBase.id
        ),
      ])
      const firstTarget = members.find(
        (member) => member.user.id !== me.user.id
      )
      setWorkspaceMembers(members)
      setPermissions(grants)
      setPermissionForm({
        knowledgeBase,
        userId: firstTarget?.user.id ?? "",
        permission: "view",
      })
    } catch (error) {
      reportError(error)
    }
  }

  async function handleGrantPermission(
    event: React.FormEvent<HTMLFormElement>
  ) {
    event.preventDefault()
    if (!selectedWorkspaceId || !permissionForm || !permissionForm.userId) {
      return
    }

    const currentPermissionForm = permissionForm
    setIsSaving(true)
    try {
      const grant = await upsertKnowledgeBasePermission(
        token,
        selectedWorkspaceId,
        currentPermissionForm.knowledgeBase.id,
        currentPermissionForm.userId,
        currentPermissionForm.permission
      )
      setPermissions((current) => [
        ...current.filter((item) => item.user.id !== grant.user.id),
        grant,
      ])
      onNotify("success", "授权已保存")
    } catch (error) {
      reportError(error)
    } finally {
      setIsSaving(false)
    }
  }

  async function handleRevokePermission(userId: string) {
    if (!selectedWorkspaceId || !permissionForm) {
      return
    }

    try {
      await revokeKnowledgeBasePermission(
        token,
        selectedWorkspaceId,
        permissionForm.knowledgeBase.id,
        userId
      )
      setPermissions((current) =>
        current.filter((item) => item.user.id !== userId)
      )
      onNotify("success", "授权已撤销")
    } catch (error) {
      reportError(error)
    }
  }

  const shareTargets = workspaceMembers.filter(
    (member) => member.user.id !== me.user.id
  )
  const detailTabs: Array<{
    key: KnowledgeBaseDetailTab
    label: string
    icon: React.ElementType
  }> = [
    { key: "documents", label: "文档", icon: FileTextIcon },
    { key: "tasks", label: "任务", icon: RotateCcwIcon },
    { key: "questions", label: "问题", icon: HelpCircleIcon },
    { key: "hit-test", label: "命中测试", icon: TargetIcon },
    { key: "settings", label: "设置", icon: SettingsIcon },
  ]

  if (selectedKnowledgeBase && isUploadFlowOpen && selectedWorkspaceId) {
    return (
      <KnowledgeUploadFlow
        token={token}
        workspaceId={selectedWorkspaceId}
        knowledgeBase={selectedKnowledgeBase}
        onBack={() => setIsUploadFlowOpen(false)}
        onDone={async () => {
          setIsUploadFlowOpen(false)
          setActiveDetailTab("documents")
          await Promise.all([loadDocuments(), loadKnowledgeTasks()])
        }}
        onNotify={onNotify}
      />
    )
  }

  if (selectedKnowledgeBase) {
    return (
      <>
        <div className="-mx-4 grid min-h-[calc(100svh-6.5rem)] grid-cols-1 overflow-hidden border-y bg-background sm:-mx-6 lg:-mx-8 lg:grid-cols-[220px_minmax(0,1fr)]">
          <aside className="border-b bg-muted/30 p-3 lg:border-r lg:border-b-0 lg:p-4">
            <div className="mb-6 flex items-center gap-2">
              <Button
                type="button"
                variant="ghost"
                size="icon-sm"
                aria-label="返回"
                onClick={closeKnowledgeBase}
              >
                <ArrowLeftIcon />
              </Button>
              <span className="flex size-8 items-center justify-center rounded-lg bg-primary text-primary-foreground">
                <FileTextIcon className="size-4" />
              </span>
              <span className="min-w-0 truncate text-sm font-semibold">
                {selectedKnowledgeBase.name}
              </span>
            </div>
            <nav className="flex gap-2 overflow-x-auto lg:flex-col lg:overflow-visible">
              {detailTabs.map((tab) => {
                const TabIcon = tab.icon
                const isActive = activeDetailTab === tab.key

                return (
                  <button
                    key={tab.key}
                    type="button"
                    className={cn(
                      "flex h-10 shrink-0 items-center gap-2 rounded-md px-3 text-sm font-medium text-muted-foreground transition-colors outline-none hover:bg-muted hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring lg:w-full",
                      isActive && "bg-primary/10 text-primary"
                    )}
                    onClick={() => setActiveDetailTab(tab.key)}
                  >
                    <TabIcon className="size-4" />
                    {tab.label}
                  </button>
                )
              })}
            </nav>
          </aside>

          <div className="min-w-0 overflow-hidden">
            {activeDetailTab === "documents" ? (
              <div className="min-w-0">
                <div className="flex flex-col gap-3 border-b px-4 py-4 lg:px-5 xl:flex-row xl:items-center xl:justify-between">
                  <div className="flex flex-wrap gap-2">
                    <Button
                      type="button"
                      disabled={!canEditDocuments}
                      onClick={() => setIsUploadFlowOpen(true)}
                    >
                      <UploadIcon data-icon="inline-start" />
                      上传文档
                    </Button>
                    <Button
                      type="button"
                      variant="outline"
                      disabled={
                        !canEditDocuments ||
                        selectedDocumentCount === 0 ||
                        isSubmittingDocumentTask
                      }
                      onClick={() => void handleIndexDocuments(selectedDocuments)}
                    >
                      {isSubmittingDocumentTask ? (
                        <LoaderCircleIcon
                          className="animate-spin"
                          data-icon="inline-start"
                        />
                      ) : null}
                      向量化
                      {selectedDocumentCount ? `(${selectedDocumentCount})` : ""}
                    </Button>
                    <Button
                      type="button"
                      variant="outline"
                      disabled={!canEditDocuments || isSubmittingDocumentTask}
                      onClick={() => void handleRebuildIndex()}
                    >
                      {isSubmittingDocumentTask ? (
                        <LoaderCircleIcon
                          className="animate-spin"
                          data-icon="inline-start"
                        />
                      ) : (
                        <RotateCcwIcon data-icon="inline-start" />
                      )}
                      重建索引
                    </Button>
                    <Button
                      type="button"
                      variant="outline"
                      disabled={
                        !canEditDocuments ||
                        selectedDocumentCount === 0 ||
                        isSubmittingDocumentTask
                      }
                      onClick={() => void handleDeleteSelectedDocuments()}
                    >
                      <Trash2Icon data-icon="inline-start" />
                      删除
                      {selectedDocumentCount ? `(${selectedDocumentCount})` : ""}
                    </Button>
                  </div>
                  <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
                    <DropdownMenu>
                      <DropdownMenuTrigger asChild>
                        <Button
                          type="button"
                          variant="outline"
                          className="h-9 justify-between sm:w-36"
                        >
                          <span className="truncate">
                            {DOCUMENT_SORT_OPTIONS.find(
                              (option) => option.key === documentSortKey
                            )?.label ?? "排序"}
                          </span>
                          {documentSortDirection === "asc" ? (
                            <ArrowUpIcon className="size-3.5" />
                          ) : (
                            <ArrowDownIcon className="size-3.5" />
                          )}
                        </Button>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent align="start" className="w-40">
                        {DOCUMENT_SORT_OPTIONS.map((option) => (
                          <DropdownMenuItem
                            key={option.key}
                            className="justify-between"
                            onSelect={() => cycleDocumentSort(option.key)}
                          >
                            {option.label}
                            {documentSortKey === option.key ? (
                              documentSortDirection === "asc" ? (
                                <ArrowUpIcon className="size-3.5 text-primary" />
                              ) : (
                                <ArrowDownIcon className="size-3.5 text-primary" />
                              )
                            ) : null}
                          </DropdownMenuItem>
                        ))}
                      </DropdownMenuContent>
                    </DropdownMenu>
                    <div className="relative sm:w-80">
                      <SearchIcon className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" />
                      <Input
                        value={documentSearch}
                        onChange={(event) =>
                          setDocumentSearch(event.target.value)
                        }
                        className="pl-9"
                        placeholder="按名称搜索"
                      />
                    </div>
                  </div>
                </div>

                <div className="px-4 py-4 lg:px-5">
                  <div className="overflow-x-auto rounded-lg border bg-background">
                    <div className="min-w-[1270px]">
                      <div className="grid grid-cols-[44px_240px_120px_100px_90px_110px_170px_170px_220px] items-center border-b px-3 py-4 text-sm font-medium text-muted-foreground">
                        <label className="flex items-center justify-center">
                          <input
                            ref={selectAllDocumentsRef}
                            type="checkbox"
                            className="size-4"
                            aria-label="选择所有文档"
                            checked={isAllFilteredDocumentsSelected}
                            disabled={!filteredDocuments.length}
                            onChange={(event) =>
                              toggleAllFilteredDocuments(event.target.checked)
                            }
                          />
                        </label>
                        <span>文件名称</span>
                        <span>文件状态</span>
                        <button
                          type="button"
                          className="flex items-center gap-1 outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring"
                          onClick={() => cycleDocumentSort("size_bytes")}
                        >
                          大小
                          {documentSortKey === "size_bytes" ? (
                            documentSortDirection === "asc" ? (
                              <ArrowUpIcon className="size-3.5" />
                            ) : (
                              <ArrowDownIcon className="size-3.5" />
                            )
                          ) : (
                            <ArrowUpDownIcon className="size-3.5" />
                          )}
                        </button>
                        <button
                          type="button"
                          className="flex items-center gap-1 outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring"
                          onClick={() => cycleDocumentSort("chunk_count")}
                        >
                          分段
                          {documentSortKey === "chunk_count" ? (
                            documentSortDirection === "asc" ? (
                              <ArrowUpIcon className="size-3.5" />
                            ) : (
                              <ArrowDownIcon className="size-3.5" />
                            )
                          ) : (
                            <ArrowUpDownIcon className="size-3.5" />
                          )}
                        </button>
                        <span>启用状态</span>
                        <button
                          type="button"
                          className="flex items-center gap-1 outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring"
                          onClick={() => cycleDocumentSort("created_at")}
                        >
                          创建时间
                          {documentSortKey === "created_at" ? (
                            documentSortDirection === "asc" ? (
                              <ArrowUpIcon className="size-3.5" />
                            ) : (
                              <ArrowDownIcon className="size-3.5" />
                            )
                          ) : (
                            <ArrowUpDownIcon className="size-3.5" />
                          )}
                        </button>
                        <button
                          type="button"
                          className="flex items-center gap-1 outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring"
                          onClick={() => cycleDocumentSort("updated_at")}
                        >
                          更新时间
                          {documentSortKey === "updated_at" ? (
                            documentSortDirection === "asc" ? (
                              <ArrowUpIcon className="size-3.5" />
                            ) : (
                              <ArrowDownIcon className="size-3.5" />
                            )
                          ) : (
                            <ArrowUpDownIcon className="size-3.5" />
                          )}
                        </button>
                        <span className="sticky right-0 flex h-full items-center border-l bg-background px-4">
                          操作
                        </span>
                      </div>
                      {isDocumentLoading ? (
                        <div className="flex min-h-56 items-center justify-center px-3 py-10 text-sm text-muted-foreground">
                          <LoaderCircleIcon className="animate-spin" />
                        </div>
                      ) : filteredDocuments.length ? (
                        filteredDocuments.map((document) => (
                          <div
                            key={document.id}
                            className="grid min-h-14 grid-cols-[44px_240px_120px_100px_90px_110px_170px_170px_220px] items-center border-b px-3 text-sm last:border-b-0 hover:bg-muted/40"
                          >
                            <label className="flex items-center justify-center">
                              <input
                                type="checkbox"
                                className="size-4"
                                aria-label={`选择 ${document.filename}`}
                                checked={selectedDocumentIds.includes(
                                  document.id
                                )}
                                onChange={(event) =>
                                  toggleDocumentSelection(
                                    document.id,
                                    event.target.checked
                                  )
                                }
                              />
                            </label>
                            <div className="min-w-0 pr-3">
                              <div className="flex min-w-0 items-center gap-2">
                                <FileTextIcon className="size-4 shrink-0 text-muted-foreground" />
                                <button
                                  type="button"
                                  className="min-w-0 truncate text-left font-medium outline-none hover:text-primary focus-visible:underline"
                                  title={document.filename}
                                  onClick={() => onOpenDocument(document.id)}
                                >
                                  {document.filename}
                                </button>
                              </div>
                              {document.last_error ? (
                                <p className="mt-1 truncate text-xs text-destructive">
                                  {document.last_error}
                                </p>
                              ) : null}
                            </div>
                            <span className="flex items-center gap-2">
                              {PROCESSING_DOCUMENT_STATUSES[document.status] ? (
                                <LoaderCircleIcon className="size-3.5 shrink-0 animate-spin text-primary" />
                              ) : (
                                <span
                                  className={cn(
                                    "size-2.5 shrink-0 rounded-full",
                                    documentStatusDotClassName(document.status)
                                  )}
                                />
                              )}
                              {documentStatusText(
                                document,
                                knowledgeTasks
                              )}
                            </span>
                            <span>{formatBytes(document.size_bytes)}</span>
                            <span>{document.chunk_count}</span>
                            <span className="flex items-center gap-2">
                              <button
                                type="button"
                                role="switch"
                                aria-checked={document.is_active}
                                aria-label={`${document.is_active ? "停用" : "启用"} ${document.filename}`}
                                disabled={!canEditDocuments || isSubmittingDocumentTask}
                                onClick={() =>
                                  void handleToggleDocumentActive(document)
                                }
                                className={cn(
                                  "relative h-5 w-9 rounded-full transition-colors outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50",
                                  document.is_active
                                    ? "bg-primary"
                                    : "bg-muted-foreground/40"
                                )}
                              >
                                <span
                                  className={cn(
                                    "block size-4 rounded-full bg-background shadow-sm transition-transform",
                                    document.is_active ? "translate-x-[18px]" : "translate-x-0.5"
                                  )}
                                />
                              </button>
                              <span>
                                {document.is_active ? "已启用" : "已停用"}
                              </span>
                            </span>
                            <span className="whitespace-nowrap">
                              {formatDateTime(document.created_at, locale)}
                            </span>
                            <span className="whitespace-nowrap">
                              {formatDateTime(document.updated_at, locale)}
                            </span>
                            <span className="sticky right-0 flex h-full items-center gap-2 border-l bg-background px-4">
                              <Button
                                type="button"
                                variant="ghost"
                                size="icon-sm"
                                disabled={
                                  !canEditDocuments ||
                                  isSubmittingDocumentTask
                                }
                                aria-label={`解析 ${document.filename}`}
                                onClick={() => void handleParseDocument(document)}
                              >
                                <RotateCcwIcon />
                              </Button>
                              <Button
                                type="button"
                                variant="ghost"
                                size="icon-sm"
                                disabled={
                                  !canEditDocuments ||
                                  isSubmittingDocumentTask
                                }
                                aria-label={`向量化 ${document.filename}`}
                                onClick={() =>
                                  void handleIndexDocuments([document])
                                }
                              >
                                <SlidersHorizontalIcon />
                              </Button>
                              <DropdownMenu>
                                <DropdownMenuTrigger asChild>
                                  <Button
                                    type="button"
                                    variant="ghost"
                                    size="icon-sm"
                                    disabled={
                                      !canEditDocuments ||
                                      isSubmittingDocumentTask
                                    }
                                    aria-label={`操作 ${document.filename}`}
                                  >
                                    <MoreHorizontalIcon />
                                  </Button>
                                </DropdownMenuTrigger>
                                <DropdownMenuContent align="end">
                                  <DropdownMenuItem
                                    onSelect={() =>
                                      void handleDownloadDocument(document)
                                    }
                                  >
                                    <DownloadIcon />
                                    下载原文
                                  </DropdownMenuItem>
                                  <DropdownMenuSeparator />
                                  <DropdownMenuItem
                                    onSelect={() => onOpenDocument(document.id)}
                                  >
                                    <FileTextIcon />
                                    预览切片
                                  </DropdownMenuItem>
                                  <DropdownMenuItem
                                    onSelect={() =>
                                      void handleParseDocument(document)
                                    }
                                  >
                                    <RotateCcwIcon />
                                    解析
                                  </DropdownMenuItem>
                                  <DropdownMenuItem
                                    onSelect={() =>
                                      void handleIndexDocuments([document])
                                    }
                                  >
                                    <SlidersHorizontalIcon />
                                    向量化
                                  </DropdownMenuItem>
                                  <DropdownMenuSeparator />
                                  <DropdownMenuItem
                                    variant="destructive"
                                    onSelect={() =>
                                      void handleDeleteDocument(document)
                                    }
                                  >
                                    <Trash2Icon />
                                    删除
                                  </DropdownMenuItem>
                                </DropdownMenuContent>
                              </DropdownMenu>
                            </span>
                          </div>
                        ))
                      ) : (
                        <div className="flex min-h-56 items-center justify-center px-3 py-10 text-sm text-muted-foreground">
                          {documents.length ? "没有匹配的文档" : "暂无文档"}
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              </div>
            ) : null}

            {activeDetailTab === "tasks" ? (
              <div className="p-4 lg:p-5">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <h1 className="text-xl font-semibold">任务</h1>
                    <p className="mt-1 text-sm text-muted-foreground">
                      导入、向量化、重建和失败重试记录
                    </p>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <Button
                      type="button"
                      variant="outline"
                      disabled={isKnowledgeTaskLoading}
                      onClick={() => void loadKnowledgeTasks()}
                    >
                      {isKnowledgeTaskLoading ? (
                        <LoaderCircleIcon
                          className="animate-spin"
                          data-icon="inline-start"
                        />
                      ) : (
                        <RotateCcwIcon data-icon="inline-start" />
                      )}
                      刷新
                    </Button>
                    <Button
                      type="button"
                      variant="outline"
                      disabled={!canEditDocuments || isSubmittingDocumentTask}
                      onClick={() => void handleRebuildIndex()}
                    >
                      <SlidersHorizontalIcon data-icon="inline-start" />
                      重建索引
                    </Button>
                  </div>
                </div>

                <div className="mt-4 overflow-x-auto rounded-lg border bg-background">
                  <div className="min-w-[860px]">
                    <div className="grid grid-cols-[120px_120px_140px_120px_minmax(220px,1fr)_120px] border-b px-4 py-3 text-sm font-medium text-muted-foreground">
                      <span>类型</span>
                      <span>状态</span>
                      <span>进度</span>
                      <span>尝试次数</span>
                      <span>更新时间 / 错误</span>
                      <span>操作</span>
                    </div>
                    {isKnowledgeTaskLoading ? (
                      <div className="flex min-h-48 items-center justify-center text-sm text-muted-foreground">
                        <LoaderCircleIcon className="animate-spin" />
                      </div>
                    ) : knowledgeTasks.length ? (
                      knowledgeTasks.map((task) => (
                        <div
                          key={task.id}
                          className="grid min-h-16 grid-cols-[120px_120px_140px_120px_minmax(220px,1fr)_120px] items-center border-b px-4 py-3 text-sm last:border-b-0"
                        >
                          <span className="font-medium">
                            {taskTypeLabel(task.task_type)}
                          </span>
                          <span className="flex items-center gap-2">
                            <span
                              className={cn(
                                "size-2.5 rounded-full",
                                taskStatusDotClassName(task.status)
                              )}
                            />
                            {taskStatusLabel(task.status)}
                          </span>
                          <span>{task.processed_items}/{task.total_items}</span>
                          <span>
                            {task.attempts}/{task.max_attempts}
                          </span>
                          <span className="min-w-0">
                            <span className="block truncate text-muted-foreground">
                              {formatDateTime(task.updated_at, locale)}
                            </span>
                            {task.last_error ? (
                              <span className="block truncate text-xs text-destructive">
                                {task.last_error}
                              </span>
                            ) : null}
                          </span>
                          <span>
                            <Button
                              type="button"
                              variant="outline"
                              size="sm"
                              disabled={
                                !canEditDocuments ||
                                isRetryingTask ||
                                task.status !== "failed"
                              }
                              onClick={() => void handleRetryKnowledgeTask(task)}
                            >
                              <RotateCcwIcon data-icon="inline-start" />
                              重试
                            </Button>
                          </span>
                        </div>
                      ))
                    ) : (
                      <div className="flex min-h-48 items-center justify-center text-sm text-muted-foreground">
                        暂无任务
                      </div>
                    )}
                  </div>
                </div>
              </div>
            ) : null}

            {activeDetailTab === "questions" ? (
              <div className="p-4 lg:p-5">
                <h1 className="text-xl font-semibold">问题</h1>
                <div className="mt-4 rounded-lg border p-8 text-sm text-muted-foreground">
                  暂无问题
                </div>
              </div>
            ) : null}

            {activeDetailTab === "hit-test" ? (
              <div className="p-4 lg:p-5">
                <div className="max-w-4xl">
                  <h1 className="text-xl font-semibold">命中测试</h1>
                  <p className="mt-1 text-sm text-muted-foreground">
                    使用当前知识库的向量索引和权威切片状态验证召回结果
                  </p>

                  <form
                    className="mt-4 rounded-lg border bg-background p-4"
                    onSubmit={(event) => void handleQueryKnowledgeBase(event)}
                  >
                    <label className="text-sm font-medium" htmlFor="query-text">
                      查询内容
                    </label>
                    <textarea
                      id="query-text"
                      value={queryText}
                      onChange={(event) => setQueryText(event.target.value)}
                      className="mt-2 min-h-28 w-full rounded-md border bg-background px-3 py-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
                      placeholder="输入要测试的检索问题"
                    />
                    <div className="mt-3 flex flex-wrap items-end gap-3">
                      <label className="grid gap-1 text-sm font-medium">
                        返回数量
                        <Input
                          type="number"
                          min={1}
                          max={20}
                          value={queryLimit}
                          onChange={(event) =>
                            setQueryLimit(
                              Math.min(
                                20,
                                Math.max(1, Number(event.target.value) || 1)
                              )
                            )
                          }
                          className="w-28"
                        />
                      </label>
                      <Button
                        type="submit"
                        disabled={!queryText.trim() || isQuerying}
                      >
                        {isQuerying ? (
                          <LoaderCircleIcon
                            className="animate-spin"
                            data-icon="inline-start"
                          />
                        ) : (
                          <TargetIcon data-icon="inline-start" />
                        )}
                        测试召回
                      </Button>
                    </div>
                  </form>

                  <div className="mt-4 rounded-lg border bg-background">
                    <div className="border-b px-4 py-3">
                      <h2 className="text-sm font-semibold">召回结果</h2>
                    </div>
                    {queryHits.length ? (
                      <div className="divide-y">
                        {queryHits.map((hit) => (
                          <article key={hit.chunk_id} className="p-4">
                            <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground">
                              <span className="font-medium text-foreground">
                                {hit.document_filename} / #{hit.chunk_index + 1}
                              </span>
                              <span>distance {formatDistance(hit.distance)}</span>
                            </div>
                            <MarkdownContent content={hit.content} className="mt-3" />
                          </article>
                        ))}
                      </div>
                    ) : (
                      <div className="flex min-h-40 items-center justify-center px-4 text-sm text-muted-foreground">
                        暂无测试结果
                      </div>
                    )}
                  </div>
                </div>
              </div>
            ) : null}

            {activeDetailTab === "settings" ? (
              <div className="w-full max-w-6xl p-4 lg:p-6">
                <h1 className="text-xl font-semibold">设置</h1>
                <div className="mt-4 rounded-lg border p-5 lg:p-6">
                  <div className="flex flex-wrap gap-2">
                    <PermissionBadge
                      permission={selectedKnowledgeBase.permission}
                    />
                    <StatusBadge status={selectedKnowledgeBase.status} />
                  </div>
                  <p className="mt-5 text-sm font-medium">描述</p>
                  <p className="mt-2 text-sm leading-6 whitespace-pre-wrap text-muted-foreground">
                    {selectedKnowledgeBase.description || "-"}
                  </p>
                  <div className="mt-5 grid gap-4 text-sm sm:grid-cols-2">
                    <div className="min-w-0 rounded-md border p-4">
                      <p className="text-xs font-medium text-muted-foreground">
                        Embedding 模型
                      </p>
                      <p className="mt-1 truncate font-medium">
                        {registeredModelLabel(selectedEmbeddingModel)}
                      </p>
                    </div>
                    <div className="min-w-0 rounded-md border p-4">
                      <p className="text-xs font-medium text-muted-foreground">
                        Rerank 模型
                      </p>
                      <p className="mt-1 truncate font-medium">
                        {registeredModelLabel(selectedRerankerModel)}
                      </p>
                    </div>
                  </div>
                  <div className="mt-5 flex flex-wrap gap-2">
                    {selectedKnowledgeBase.permission === "edit" ? (
                      <Button
                        type="button"
                        variant="outline"
                        onClick={() =>
                          setEditForm({
                            id: selectedKnowledgeBase.id,
                            name: selectedKnowledgeBase.name,
                            description: selectedKnowledgeBase.description,
                            embedding_model_id:
                              selectedKnowledgeBase.embedding_model_id,
                            reranker_model_id:
                              selectedKnowledgeBase.reranker_model_id,
                          })
                        }
                      >
                        <PencilIcon data-icon="inline-start" />
                        编辑
                      </Button>
                    ) : null}
                    {selectedKnowledgeBase.permission === "edit" ? (
                      <Button
                        type="button"
                        variant="outline"
                        disabled={
                          isTestingModels ||
                          !selectedKnowledgeBase.embedding_model_id
                        }
                        onClick={() => void handleTestKnowledgeModels()}
                      >
                        {isTestingModels ? (
                          <LoaderCircleIcon data-icon="inline-start" />
                        ) : (
                          <FlaskConicalIcon data-icon="inline-start" />
                        )}
                        测试模型
                      </Button>
                    ) : null}
                    {modelTestError ? (
                      <div className="flex w-full flex-col gap-2 rounded-md border border-destructive/30 bg-destructive/5 px-4 py-3 text-sm text-destructive">
                        <div className="flex items-center gap-2 font-medium">
                          <AlertCircleIcon className="size-4 shrink-0" />
                          模型测试失败
                        </div>
                        <p className="break-words leading-6">
                          {modelTestError}
                        </p>
                      </div>
                    ) : modelTestResult ? (
                      <div className="flex w-full flex-col gap-2 rounded-md border border-emerald-500/30 bg-emerald-500/5 px-4 py-3 text-sm">
                        <div className="flex items-center gap-2 font-medium text-emerald-600 dark:text-emerald-400">
                          <CircleCheckIcon className="size-4 shrink-0" />
                          模型测试通过
                        </div>
                        <dl className="flex flex-wrap gap-x-6 gap-y-1">
                          <div className="flex items-center gap-1.5">
                            <dt className="text-muted-foreground">Embedding</dt>
                            <dd className="font-medium">
                              {modelTestResult.embedding_dimensions} 维
                            </dd>
                          </div>
                          <div className="flex items-center gap-1.5">
                            <dt className="text-muted-foreground">Rerank</dt>
                            <dd className="font-medium">
                              {modelTestResult.reranker_results} 条
                            </dd>
                          </div>
                        </dl>
                      </div>
                    ) : null}
                    {canManagePermissions(selectedKnowledgeBase) ? (
                      <Button
                        type="button"
                        variant="outline"
                        onClick={() =>
                          void handleOpenPermissions(selectedKnowledgeBase)
                        }
                      >
                        <UsersIcon data-icon="inline-start" />
                        授权
                      </Button>
                    ) : null}
                  </div>
                </div>
              </div>
            ) : null}
          </div>
        </div>

        <KnowledgeBaseDialogs
          page={page}
          form={form}
          setForm={setForm}
          editForm={editForm}
          setEditForm={setEditForm}
          permissionForm={permissionForm}
          setPermissionForm={setPermissionForm}
          shareTargets={shareTargets}
          permissions={permissions}
          registeredModels={registeredModels}
          isDialogOpen={isDialogOpen}
          setIsDialogOpen={setIsDialogOpen}
          isSaving={isSaving}
          handleCreate={handleCreate}
          handleUpdate={handleUpdate}
          handleGrantPermission={handleGrantPermission}
          handleRevokePermission={handleRevokePermission}
        />
      </>
    )
  }

  return (
    <>
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <h1 className="truncate text-2xl font-semibold">{page.label}</h1>
          <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
            {page.description}
          </p>
        </div>
        <Button
          type="button"
          className="shrink-0"
          disabled={!selectedWorkspaceId}
          onClick={() => setIsDialogOpen(true)}
        >
          <PlusIcon data-icon="inline-start" />
          {page.actionLabel}
        </Button>
      </div>

      {!selectedWorkspaceId ? (
        <div className="rounded-lg border bg-background p-6 shadow-sm">
          <div className="mx-auto flex min-h-[240px] max-w-xl flex-col items-center justify-center gap-3 text-center">
            <span className="flex size-14 items-center justify-center rounded-lg bg-muted">
              <Icon className="size-5 text-muted-foreground" />
            </span>
            <p className="text-base font-semibold">{t("先选择工作空间")}</p>
          </div>
        </div>
      ) : (
        <>
          <div className="rounded-lg border bg-background p-3 shadow-sm">
            <div className="relative min-w-0 sm:w-[320px]">
              <SearchIcon className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                value={knowledgeSearch}
                onChange={(event) => setKnowledgeSearch(event.target.value)}
                placeholder={t("搜索{label}...", { label: page.label })}
                className="pl-9"
              />
            </div>
          </div>

          {isLoading ? (
            <div className="flex min-h-[220px] items-center justify-center rounded-lg border bg-background shadow-sm">
              <LoaderCircleIcon className="animate-spin text-muted-foreground" />
            </div>
          ) : knowledgeBases.length ? (
            <>
              {filteredKnowledgeBases.length ? (
                <div className="flex flex-wrap gap-3">
                  {filteredKnowledgeBases.map((knowledgeBase) => (
                    <div
                      key={knowledgeBase.id}
                      role="button"
                      tabIndex={0}
                      className="flex min-h-44 w-full min-w-0 cursor-pointer flex-col justify-between rounded-lg border bg-background p-3 shadow-sm transition-colors outline-none hover:bg-muted/40 focus-visible:ring-2 focus-visible:ring-ring sm:w-[19rem]"
                      onClick={() => openKnowledgeBase(knowledgeBase)}
                      onKeyDown={(event) => {
                        if (event.key === "Enter" || event.key === " ") {
                          event.preventDefault()
                          openKnowledgeBase(knowledgeBase)
                        }
                      }}
                    >
                      <div className="min-w-0 space-y-2">
                        <div className="min-w-0">
                          <p className="truncate text-sm font-semibold">
                            {knowledgeBase.name}
                          </p>
                          <p className="mt-0.5 text-xs text-muted-foreground">
                            {formatDateTime(knowledgeBase.updated_at, locale)}
                          </p>
                        </div>
                        <p className="line-clamp-3 text-xs leading-5 text-muted-foreground">
                          {knowledgeBase.description || "-"}
                        </p>
                      </div>
                      <div className="mt-3 flex items-center justify-between gap-2">
                        <div className="flex min-w-0 flex-wrap gap-1.5">
                          <PermissionBadge
                            permission={knowledgeBase.permission}
                          />
                          <StatusBadge status={knowledgeBase.status} />
                        </div>
                        <div className="flex shrink-0 justify-end gap-1">
                          {knowledgeBase.permission === "edit" ? (
                            <>
                              <Button
                                type="button"
                                variant="ghost"
                                size="icon-sm"
                                title="编辑知识库"
                                aria-label="编辑知识库"
                                onClick={(event) => {
                                  event.stopPropagation()
                                  setEditForm({
                                    id: knowledgeBase.id,
                                    name: knowledgeBase.name,
                                    description: knowledgeBase.description,
                                    embedding_model_id:
                                      knowledgeBase.embedding_model_id,
                                    reranker_model_id:
                                      knowledgeBase.reranker_model_id,
                                  })
                                }}
                              >
                                <PencilIcon />
                              </Button>
                              <Button
                                type="button"
                                variant="ghost"
                                size="icon-sm"
                                title={
                                  knowledgeBase.status === "active"
                                    ? "归档知识库"
                                    : "恢复知识库"
                                }
                                aria-label={
                                  knowledgeBase.status === "active"
                                    ? "归档知识库"
                                    : "恢复知识库"
                                }
                                onClick={(event) => {
                                  event.stopPropagation()
                                  void handleToggleStatus(knowledgeBase)
                                }}
                              >
                                {knowledgeBase.status === "active" ? (
                                  <ArchiveIcon />
                                ) : (
                                  <RotateCcwIcon />
                                )}
                              </Button>
                            </>
                          ) : null}
                          {canManagePermissions(knowledgeBase) ? (
                            <>
                              <Button
                                type="button"
                                variant="ghost"
                                size="icon-sm"
                                title="资源授权"
                                aria-label="资源授权"
                                onClick={(event) => {
                                  event.stopPropagation()
                                  void handleOpenPermissions(knowledgeBase)
                                }}
                              >
                                <UsersIcon />
                              </Button>
                              <Button
                                type="button"
                                variant="ghost"
                                size="icon-sm"
                                title="永久删除知识库"
                                aria-label="永久删除知识库"
                                onClick={(event) => {
                                  event.stopPropagation()
                                  void handleDelete(knowledgeBase)
                                }}
                              >
                                <Trash2Icon />
                              </Button>
                            </>
                          ) : null}
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="rounded-lg border bg-background p-8 text-center text-sm text-muted-foreground shadow-sm">
                  {t("没有匹配的知识库")}
                </div>
              )}
            </>
          ) : (
            <div className="mx-auto flex min-h-[320px] max-w-xl flex-col items-center justify-center gap-4 p-6 text-center">
              <span className="flex size-14 items-center justify-center rounded-lg bg-muted">
                <Icon className="size-5 text-muted-foreground" />
              </span>
              <div className="flex flex-col gap-2">
                <p className="text-base font-semibold">{page.emptyTitle}</p>
                <p className="text-sm leading-6 text-muted-foreground">
                  {page.emptyDescription}
                </p>
              </div>
              <Button type="button" onClick={() => setIsDialogOpen(true)}>
                <PlusIcon data-icon="inline-start" />
                {page.actionLabel}
              </Button>
            </div>
          )}
        </>
      )}

      <KnowledgeBaseDialogs
        page={page}
        form={form}
        setForm={setForm}
        editForm={editForm}
        setEditForm={setEditForm}
        permissionForm={permissionForm}
        setPermissionForm={setPermissionForm}
        shareTargets={shareTargets}
        permissions={permissions}
        registeredModels={registeredModels}
        isDialogOpen={isDialogOpen}
        setIsDialogOpen={setIsDialogOpen}
        isSaving={isSaving}
        handleCreate={handleCreate}
        handleUpdate={handleUpdate}
        handleGrantPermission={handleGrantPermission}
        handleRevokePermission={handleRevokePermission}
      />
    </>
  )
}
