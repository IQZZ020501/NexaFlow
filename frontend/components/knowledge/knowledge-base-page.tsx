"use client"

import * as React from "react"
import ModelIcon from "@lobehub/icons/es/features/ModelIcon"
import {
  AlertCircleIcon,
  ArchiveIcon,
  ArrowDownIcon,
  ArrowLeftIcon,
  ArrowUpDownIcon,
  ArrowUpIcon,
  BookOpenTextIcon,
  CircleCheckIcon,
  DatabaseIcon,
  DownloadIcon,
  FileTextIcon,
  FlaskConicalIcon,
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
import { useParams, useRouter } from "next/navigation"
import type { MeResponse } from "@/lib/api/auth"
import type { AppNotification } from "@/lib/notifications"
import { useSession } from "@/contexts/session-context"
import { useLanguage } from "@/contexts/language-provider"
import { Button } from "@/components/ui/button"
import { IconButton } from "@/components/ui/icon-button"
import { CardMoreMenu } from "@/components/ui/card-more-menu"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { Input } from "@/components/ui/input"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Field, FieldGroup, FieldLabel } from "@/components/ui/field"
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
} from "@/lib/api/knowledge"
import type {
  KnowledgeBase,
  KnowledgeBaseListItem,
  KnowledgeDocument,
  KnowledgeModelTestResult,
  KnowledgeQueryHit,
  KnowledgeTask,
  ResourcePermission,
} from "@/lib/api/knowledge"
import { listRegisteredModels } from "@/lib/api/llm"
import type { RegisteredModel } from "@/lib/api/llm"
import { listWorkspaceMembers } from "@/lib/api/system"
import type { WorkspaceMember } from "@/lib/api/system"
import { languageLocales, type TFunction, type TranslationKey } from "@/i18n"
import { cn } from "@/lib/utils"
import { formatDateTime, getMembershipRole, modelLabel } from "@/lib/display"
import { getErrorMessage } from "@/lib/errors"
import {
  knowledgeUploadPath,
  knowledgeUploadSegmentPath,
  type KnowledgeUploadRouteState,
  type KnowledgeUploadStep,
} from "@/lib/knowledge-upload-route"
import { KnowledgeBaseDialogs } from "@/components/knowledge/knowledge-base-dialogs"
import { MarkdownContent } from "@/components/knowledge/markdown-content"
import { KnowledgeUploadFlow } from "@/components/knowledge/knowledge-upload-flow"
import {
  documentStatusDotClassName,
  documentStatusLabel,
  formatBytes,
  taskStatusDotClassName,
  taskStatusLabel,
  taskTypeLabel,
} from "@/components/knowledge/status-labels"
import {
  PermissionBadge,
  StatusBadge,
} from "@/components/knowledge/status-badges"
import type {
  KnowledgeBaseDetailTab,
  KnowledgeBaseEditForm,
  KnowledgeBaseForm,
  KnowledgeBasePermissionForm,
} from "@/lib/api/knowledge"

type DocumentSortKey =
  | "name"
  | "size_bytes"
  | "chunk_count"
  | "created_at"
  | "updated_at"

const DOCUMENT_SORT_OPTIONS: Array<{
  key: DocumentSortKey
  label: TranslationKey
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

const DOCUMENT_PAGE_SIZE = 20

const SMART_CHUNK_SIZE = 1200
const SMART_CHUNK_OVERLAP = 150
const SMART_CLEANING_RULES = ["trim_lines", "remove_empty_lines"]
const SMART_SPLIT_SEPARATOR = "\n\n"

const CLEANING_RULE_OPTIONS: Array<{
  value: string
  labelKey: "去除行首尾空白" | "删除空行" | "合并连续空白"
}> = [
  { value: "trim_lines", labelKey: "去除行首尾空白" },
  { value: "remove_empty_lines", labelKey: "删除空行" },
  { value: "collapse_spaces", labelKey: "合并连续空白" },
]

const SPLIT_SEPARATOR_OPTIONS: Array<{
  value: string
  labelKey: "换行" | "空行（段落）" | "中文句号（。）" | "英文句号（.）"
}> = [
  { value: "\n", labelKey: "换行" },
  { value: "\n\n", labelKey: "空行（段落）" },
  { value: "。", labelKey: "中文句号（。）" },
  { value: ".", labelKey: "英文句号（.）" },
]

function documentStatusText(
  document: KnowledgeDocument,
  tasks: KnowledgeTask[],
  t: TFunction
) {
  if (document.status === "indexing") {
    const indexTask = tasks.find(
      (task) =>
        task.document_id === document.id &&
        task.task_type === "index" &&
        task.total_items > 0
    )
    if (indexTask) {
      return t("向量化中 {done}/{total}", {
        done: indexTask.processed_items,
        total: indexTask.total_items,
      })
    }
  }

  return documentStatusLabel(document.status, t)
}

export function KnowledgeBasePage({
  uploadStep,
  uploadRouteState,
}: {
  uploadStep?: KnowledgeUploadStep
  uploadRouteState?: KnowledgeUploadRouteState
} = {}) {
  const { token, me, selectedWorkspaceId, notify } = useSession()

  if (!token || !me) {
    return null
  }

  return (
    <KnowledgeBasePageContent
      token={token}
      me={me}
      selectedWorkspaceId={selectedWorkspaceId}
      notify={notify}
      uploadStep={uploadStep}
      uploadRouteState={uploadRouteState}
    />
  )
}

function KnowledgeBasePageContent({
  token,
  me,
  selectedWorkspaceId,
  notify,
  uploadStep,
  uploadRouteState,
}: {
  token: string
  me: MeResponse
  selectedWorkspaceId: string | null
  notify: (kind: AppNotification["kind"], message: string) => void
  uploadStep?: KnowledgeUploadStep
  uploadRouteState?: KnowledgeUploadRouteState
}) {
  const router = useRouter()
  const params = useParams<{ id?: string }>()
  const activeKnowledgeBaseId = params.id ?? null
  const Icon = DatabaseIcon
  const { language, t } = useLanguage()
  const locale = languageLocales[language]
  const [knowledgeBases, setKnowledgeBases] = React.useState<
    KnowledgeBaseListItem[]
  >([])
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
  const [documentPage, setDocumentPage] = React.useState(1)
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
  const [segmentDialogDocument, setSegmentDialogDocument] =
    React.useState<KnowledgeDocument | null>(null)
  const [segmentMode, setSegmentMode] = React.useState<"smart" | "advanced">(
    "smart"
  )
  const [chunkSize, setChunkSize] = React.useState(SMART_CHUNK_SIZE)
  const [chunkOverlap, setChunkOverlap] = React.useState(SMART_CHUNK_OVERLAP)
  const [splitSeparator, setSplitSeparator] = React.useState(
    SMART_SPLIT_SEPARATOR
  )
  const [cleaningRules, setCleaningRules] = React.useState<string[]>(
    SMART_CLEANING_RULES
  )
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
  const selectAllDocumentsRef = React.useRef<HTMLInputElement>(null)

  const workspaceRole = getMembershipRole(me, selectedWorkspaceId)
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
    setDocumentPage(1)
  }
  const selectedDocuments = documents.filter((document) =>
    selectedDocumentIds.includes(document.id)
  )
  const selectedDocumentCount = selectedDocuments.length
  const visibleDocuments = filteredDocuments.slice(
    (documentPage - 1) * DOCUMENT_PAGE_SIZE,
    documentPage * DOCUMENT_PAGE_SIZE
  )
  const documentPageCount = Math.max(
    1,
    Math.ceil(filteredDocuments.length / DOCUMENT_PAGE_SIZE)
  )
  const isAllFilteredDocumentsSelected =
    visibleDocuments.length > 0 &&
    visibleDocuments.every((document) =>
      selectedDocumentIds.includes(document.id)
    )
  const isSomeFilteredDocumentSelected = visibleDocuments.some((document) =>
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
      notify("error", message)
      return message
    },
    [notify, t]
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

  const previousActiveKnowledgeBaseId = React.useRef(activeKnowledgeBaseId)
  React.useEffect(() => {
    // Refresh list stats only when returning from a knowledge base detail view.
    if (
      previousActiveKnowledgeBaseId.current !== null &&
      activeKnowledgeBaseId === null
    ) {
      void loadKnowledgeBases()
    }
    previousActiveKnowledgeBaseId.current = activeKnowledgeBaseId
  }, [activeKnowledgeBaseId, loadKnowledgeBases])

  React.useEffect(() => {
    if (
      uploadStep &&
      selectedKnowledgeBase &&
      selectedKnowledgeBase.permission !== "edit"
    ) {
      router.replace(`/app/knowledge/${selectedKnowledgeBase.id}`)
    }
  }, [router, selectedKnowledgeBase, uploadStep])

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

  const cancelUpload = React.useCallback(() => {
    if (selectedKnowledgeBaseId) {
      router.push(`/app/knowledge/${selectedKnowledgeBaseId}`)
    }
  }, [router, selectedKnowledgeBaseId])

  const routeUploadSegment = React.useCallback(
    (routeState: KnowledgeUploadRouteState) => {
      if (!selectedKnowledgeBaseId) {
        return
      }

      const path = knowledgeUploadSegmentPath(
        selectedKnowledgeBaseId,
        routeState.documentIds,
        routeState.parseSettings
      )
      if (uploadStep === "segment") {
        router.replace(path)
      } else {
        router.push(path)
      }
    },
    [router, selectedKnowledgeBaseId, uploadStep]
  )

  const backToUploadFiles = React.useCallback(() => {
    if (selectedKnowledgeBaseId) {
      router.push(knowledgeUploadPath(selectedKnowledgeBaseId))
    }
  }, [router, selectedKnowledgeBaseId])

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
    const visibleDocumentIds = visibleDocuments.map((document) => document.id)
    setSelectedDocumentIds((current) =>
      checked
        ? Array.from(new Set([...current, ...visibleDocumentIds]))
        : current.filter((id) => !visibleDocumentIds.includes(id))
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
        item.id === knowledgeBase.id ? { ...item, ...knowledgeBase } : item
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
    router.push(`/app/knowledge/${knowledgeBase.id}`)
  }

  function closeKnowledgeBase() {
    setKnowledgeTasks([])
    router.push("/app/knowledge")
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
      setKnowledgeBases((current) => [
        ...current,
        { ...knowledgeBase, document_count: 0, char_count: 0 },
      ])
      resetForm()
      setIsDialogOpen(false)
      notify("success", t("知识库已新建"))
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
      notify("success", t("知识库已更新"))
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
      notify(
        "success",
        t(nextStatus === "active" ? "知识库已恢复" : "知识库已归档")
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
      notify("success", t("知识库已删除"))
    } catch (error) {
      reportError(error)
    }
  }

  async function handleParseDocumentWithOptions(document: KnowledgeDocument) {
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
        segmentMode === "smart"
          ? {
              strategy: "hierarchical",
              chunk_size: SMART_CHUNK_SIZE,
              chunk_overlap: SMART_CHUNK_OVERLAP,
              cleaning_rules: SMART_CLEANING_RULES,
              split_separator: SMART_SPLIT_SEPARATOR,
              auto_index: true,
            }
          : {
              strategy: "flat",
              chunk_size: chunkSize,
              chunk_overlap: chunkOverlap,
              cleaning_rules: cleaningRules,
              split_separator: splitSeparator,
              auto_index: true,
            }
      )
      setSegmentDialogDocument(null)
      await loadDocuments()
      await loadKnowledgeTasks()
      notify("success", t("已提交解析任务"))
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
      notify(
        "success",
        targetDocuments.length === 1
          ? t("已提交向量化任务")
          : t("已提交 {value} 个向量化任务", {
              value: targetDocuments.length,
            })
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
      notify("success", t(updated.is_active ? "文档已启用" : "文档已停用"))
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
        t("永久删除选中的 {value} 个文档？此操作不可恢复。", {
          value: selectedDocuments.length,
        })
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
      notify("success", t("已删除 {value} 个文档", { value: selectedDocuments.length }))
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
      notify("success", t("已提交重建索引任务"))
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
      notify("success", t("已重新提交任务"))
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
      notify("success", t("文档已删除"))
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
      notify("success", t("授权已保存"))
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
      notify("success", t("授权已撤销"))
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
    { key: "documents", label: t("文档"), icon: FileTextIcon },
    { key: "tasks", label: t("任务"), icon: RotateCcwIcon },
    { key: "hit-test", label: t("命中测试"), icon: TargetIcon },
    { key: "settings", label: t("设置"), icon: SettingsIcon },
  ]

  if (selectedKnowledgeBase && uploadStep && selectedWorkspaceId) {
    if (!canEditDocuments) {
      return null
    }

    return (
      <KnowledgeUploadFlow
        token={token}
        workspaceId={selectedWorkspaceId}
        knowledgeBase={selectedKnowledgeBase}
        step={uploadStep}
        routeState={uploadRouteState}
        onCancel={cancelUpload}
        onRouteSegment={routeUploadSegment}
        onBackToFiles={backToUploadFiles}
        onDone={async () => {
          setActiveDetailTab("documents")
          await Promise.all([loadDocuments(), loadKnowledgeTasks()])
          router.push(`/app/knowledge/${selectedKnowledgeBase.id}`)
        }}
        onNotify={notify}
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
                aria-label={t("返回")}
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
                      onClick={() =>
                        router.push(
                          knowledgeUploadPath(selectedKnowledgeBase.id)
                        )
                      }
                    >
                      <UploadIcon data-icon="inline-start" />
                      {t("上传文档")}
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
                      {t("向量化")}
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
                      {t("重建索引")}
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
                      {t("删除")}
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
                            {t(
                              DOCUMENT_SORT_OPTIONS.find(
                                (option) => option.key === documentSortKey
                              )?.label ?? "排序"
                            )}
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
                            {t(option.label)}
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
                        onChange={(event) => {
                          setDocumentSearch(event.target.value)
                          setDocumentPage(1)
                        }}
                        className="pl-9"
                        placeholder={t("按名称搜索")}
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
                            aria-label={t("选择所有文档")}
                            checked={isAllFilteredDocumentsSelected}
                            disabled={!filteredDocuments.length}
                            onChange={(event) =>
                              toggleAllFilteredDocuments(event.target.checked)
                            }
                          />
                        </label>
                        <span>{t("文件名称")}</span>
                        <span>{t("文件状态")}</span>
                        <button
                          type="button"
                          className="flex cursor-pointer items-center gap-1 outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring"
                          onClick={() => cycleDocumentSort("size_bytes")}
                        >
                          {t("大小")}
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
                          className="flex cursor-pointer items-center gap-1 outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring"
                          onClick={() => cycleDocumentSort("chunk_count")}
                        >
                          {t("分段")}
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
                        <span>{t("启用状态")}</span>
                        <button
                          type="button"
                          className="flex cursor-pointer items-center gap-1 outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring"
                          onClick={() => cycleDocumentSort("created_at")}
                        >
                          {t("创建时间")}
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
                          className="flex cursor-pointer items-center gap-1 outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring"
                          onClick={() => cycleDocumentSort("updated_at")}
                        >
                          {t("更新时间")}
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
                          {t("操作")}
                        </span>
                      </div>
                      {isDocumentLoading ? (
                        <div className="flex min-h-56 items-center justify-center px-3 py-10 text-sm text-muted-foreground">
                          <LoaderCircleIcon className="animate-spin" />
                        </div>
                      ) : visibleDocuments.length ? (
                        visibleDocuments.map((document) => (
                          <div
                            key={document.id}
                            className="grid min-h-14 grid-cols-[44px_240px_120px_100px_90px_110px_170px_170px_220px] items-center border-b px-3 text-sm last:border-b-0 hover:bg-muted/40"
                          >
                            <label className="flex items-center justify-center">
                              <input
                                type="checkbox"
                                className="size-4"
                                aria-label={t("选择 {value}", { value: document.filename })}
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
                                  className="min-w-0 cursor-pointer truncate text-left font-medium outline-none hover:text-primary focus-visible:underline"
                                  title={document.filename}
                                  onClick={() =>
                                    router.push(
                                      `/app/knowledge/${selectedKnowledgeBaseId}/documents/${document.id}`
                                    )
                                  }
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
                                knowledgeTasks,
                                t
                              )}
                            </span>
                            <span>{formatBytes(document.size_bytes)}</span>
                            <span>{document.chunk_count}</span>
                            <span className="flex items-center gap-2">
                              <button
                                type="button"
                                role="switch"
                                aria-checked={document.is_active}
                                aria-label={t(
                                  document.is_active ? "停用 {value}" : "启用 {value}",
                                  { value: document.filename }
                                )}
                                disabled={!canEditDocuments || isSubmittingDocumentTask}
                                onClick={() =>
                                  void handleToggleDocumentActive(document)
                                }
                                className={cn(
                                  "relative h-5 w-9 cursor-pointer rounded-full transition-colors outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50",
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
                                {t(document.is_active ? "已启用" : "已停用")}
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
                                aria-label={t("重新分段 {value}", { value: document.filename })}
                                title={t("重新分段 {value}", { value: document.filename })}
                                onClick={() => {
                                  setChunkSize(SMART_CHUNK_SIZE)
                                  setChunkOverlap(SMART_CHUNK_OVERLAP)
                                  setSplitSeparator(SMART_SPLIT_SEPARATOR)
                                  setCleaningRules(SMART_CLEANING_RULES)
                                  setSegmentMode("smart")
                                  setSegmentDialogDocument(document)
                                }}
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
                                aria-label={t("向量化 {value}", { value: document.filename })}
                                title={t("向量化 {value}", { value: document.filename })}
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
                                    aria-label={t("操作 {value}", { value: document.filename })}
                                    title={t("操作 {value}", { value: document.filename })}
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
                                    {t("下载原文")}
                                  </DropdownMenuItem>
                                  <DropdownMenuSeparator />
                                  <DropdownMenuItem
                                    onSelect={() =>
                                      router.push(
                                        `/app/knowledge/${selectedKnowledgeBaseId}/documents/${document.id}`
                                      )
                                    }
                                  >
                                    <FileTextIcon />
                                    {t("预览切片")}
                                  </DropdownMenuItem>
                                  <DropdownMenuItem
                                    onSelect={() =>
                                      void handleIndexDocuments([document])
                                    }
                                  >
                                    <SlidersHorizontalIcon />
                                    {t("向量化")}
                                  </DropdownMenuItem>
                                  <DropdownMenuSeparator />
                                  <DropdownMenuItem
                                    variant="destructive"
                                    onSelect={() =>
                                      void handleDeleteDocument(document)
                                    }
                                  >
                                    <Trash2Icon />
                                    {t("删除")}
                                  </DropdownMenuItem>
                                </DropdownMenuContent>
                              </DropdownMenu>
                            </span>
                          </div>
                        ))
                      ) : (
                        <div className="flex min-h-56 items-center justify-center px-3 py-10 text-sm text-muted-foreground">
                          {t(documents.length ? "没有匹配的文档" : "暂无文档")}
                        </div>
                      )}
                    </div>
                  </div>
                  {filteredDocuments.length > DOCUMENT_PAGE_SIZE ? (
                    <div className="flex items-center justify-between gap-3 border-t px-4 py-3 text-sm">
                      <span className="text-muted-foreground">
                        {t("共 {value} 条", { value: filteredDocuments.length })}
                      </span>
                      <div className="flex items-center gap-2">
                        <Button
                          type="button"
                          variant="outline"
                          size="sm"
                          disabled={documentPage <= 1}
                          onClick={() =>
                            setDocumentPage((current) => Math.max(1, current - 1))
                          }
                        >
                          {t("上一页")}
                        </Button>
                        <span className="text-muted-foreground">
                          {documentPage} / {documentPageCount}
                        </span>
                        <Button
                          type="button"
                          variant="outline"
                          size="sm"
                          disabled={documentPage >= documentPageCount}
                          onClick={() =>
                            setDocumentPage((current) =>
                              Math.min(documentPageCount, current + 1)
                            )
                          }
                        >
                          {t("下一页")}
                        </Button>
                      </div>
                    </div>
                  ) : null}
                </div>
              </div>
            ) : null}

            <Dialog
              open={segmentDialogDocument !== null}
              onOpenChange={(open) => {
                if (!open) {
                  setSegmentDialogDocument(null)
                }
              }}
            >
              <DialogContent>
                <DialogHeader>
                  <DialogTitle>{t("重新分段")}</DialogTitle>
                  <DialogDescription>
                    {t("先用智能规则生成预览，需要时再精调。")}
                  </DialogDescription>
                </DialogHeader>
                <form
                  onSubmit={(event) => {
                    event.preventDefault()
                    if (segmentDialogDocument) {
                      void handleParseDocumentWithOptions(segmentDialogDocument)
                    }
                  }}
                >
                  <FieldGroup>
                    <div className="grid gap-2 sm:grid-cols-2">
                      <button
                        type="button"
                        className={cn(
                          "rounded-lg border p-3 text-left transition-colors outline-none focus-visible:ring-2 focus-visible:ring-ring",
                          segmentMode === "smart"
                            ? "border-primary bg-primary/5"
                            : "hover:bg-muted"
                        )}
                        onClick={() => setSegmentMode("smart")}
                      >
                        <span className="block text-sm font-medium">
                          {t("智能分段")}
                        </span>
                        <span className="mt-1 block text-xs leading-5 text-muted-foreground">
                          {t("按常见文档结构自动设置长度、重叠和清洗规则。")}
                        </span>
                      </button>
                      <button
                        type="button"
                        className={cn(
                          "rounded-lg border p-3 text-left transition-colors outline-none focus-visible:ring-2 focus-visible:ring-ring",
                          segmentMode === "advanced"
                            ? "border-primary bg-primary/5"
                            : "hover:bg-muted"
                        )}
                        onClick={() => setSegmentMode("advanced")}
                      >
                        <span className="block text-sm font-medium">
                          {t("高级分段")}
                        </span>
                        <span className="mt-1 block text-xs leading-5 text-muted-foreground">
                          {t("手动控制片段字符数、重叠字符和文本清洗规则。")}
                        </span>
                      </button>
                    </div>

                    {segmentMode === "advanced" ? (
                      <>
                        <div className="grid gap-4 sm:grid-cols-2">
                          <Field>
                            <FieldLabel htmlFor="row-segment-size">
                              {t("片段字符")}
                            </FieldLabel>
                            <Input
                              id="row-segment-size"
                              type="number"
                              min={100}
                              max={8000}
                              value={chunkSize}
                              onChange={(event) =>
                                setChunkSize(Number(event.target.value))
                              }
                              required
                            />
                          </Field>
                          <Field>
                            <FieldLabel htmlFor="row-segment-overlap">
                              {t("重叠字符")}
                            </FieldLabel>
                            <Input
                              id="row-segment-overlap"
                              type="number"
                              min={0}
                              max={2000}
                              value={chunkOverlap}
                              onChange={(event) =>
                                setChunkOverlap(Number(event.target.value))
                              }
                              required
                            />
                          </Field>
                        </div>
                        {chunkOverlap >= chunkSize ? (
                          <p className="text-sm text-destructive">
                            {t("重叠字符必须小于片段字符")}
                          </p>
                        ) : null}
                        <div className="grid gap-4 sm:grid-cols-2">
                          <Field>
                            <FieldLabel>{t("切分字符")}</FieldLabel>
                            <DropdownMenu modal={false}>
                              <DropdownMenuTrigger asChild>
                                <Button
                                  type="button"
                                  variant="outline"
                                  className="h-9 w-full justify-between font-normal"
                                >
                                  <span className="truncate">
                                    {t(
                                      SPLIT_SEPARATOR_OPTIONS.find(
                                        (option) =>
                                          option.value === splitSeparator
                                      )?.labelKey ?? "空行（段落）"
                                    )}
                                  </span>
                                </Button>
                              </DropdownMenuTrigger>
                              <DropdownMenuContent align="start">
                                {SPLIT_SEPARATOR_OPTIONS.map((option) => (
                                  <DropdownMenuItem
                                    key={option.value}
                                    onSelect={() =>
                                      setSplitSeparator(option.value)
                                    }
                                  >
                                    {t(option.labelKey)}
                                  </DropdownMenuItem>
                                ))}
                              </DropdownMenuContent>
                            </DropdownMenu>
                          </Field>
                          <Field>
                            <FieldLabel>{t("清洗规则")}</FieldLabel>
                            <DropdownMenu modal={false}>
                              <DropdownMenuTrigger asChild>
                                <Button
                                  type="button"
                                  variant="outline"
                                  className="h-9 w-full justify-between font-normal"
                                >
                                  <span className="truncate">
                                    {cleaningRules.length
                                      ? cleaningRules
                                          .map(
                                            (rule) =>
                                              t(
                                                CLEANING_RULE_OPTIONS.find(
                                                  (option) =>
                                                    option.value === rule
                                                )?.labelKey ??
                                                  "去除行首尾空白"
                                              )
                                          )
                                          .join(t("列表分隔符"))
                                      : t("不使用")}
                                  </span>
                                </Button>
                              </DropdownMenuTrigger>
                              <DropdownMenuContent align="start">
                                {CLEANING_RULE_OPTIONS.map((option) => (
                                  <DropdownMenuItem
                                    key={option.value}
                                    onSelect={() =>
                                      setCleaningRules((current) =>
                                        current.includes(option.value)
                                          ? current.filter(
                                              (rule) => rule !== option.value
                                            )
                                          : [...current, option.value]
                                      )
                                    }
                                  >
                                    {t(option.labelKey)}
                                  </DropdownMenuItem>
                                ))}
                              </DropdownMenuContent>
                            </DropdownMenu>
                          </Field>
                        </div>
                      </>
                    ) : null}
                  </FieldGroup>
                  <DialogFooter className="pt-5">
                    <Button
                      type="button"
                      variant="outline"
                      onClick={() => setSegmentDialogDocument(null)}
                    >
                      {t("取消")}
                    </Button>
                    <Button
                      type="submit"
                      disabled={
                        isSubmittingDocumentTask ||
                        (segmentMode === "advanced" &&
                          chunkOverlap >= chunkSize)
                      }
                    >
                      {isSubmittingDocumentTask ? (
                        <LoaderCircleIcon
                          className="animate-spin"
                          data-icon="inline-start"
                        />
                      ) : null}
                      {t("开始导入")}
                    </Button>
                  </DialogFooter>
                </form>
              </DialogContent>
            </Dialog>

            {activeDetailTab === "tasks" ? (
              <div className="p-4 lg:p-5">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <h1 className="text-xl font-semibold">{t("任务")}</h1>
                    <p className="mt-1 text-sm text-muted-foreground">
                      {t("导入、向量化、重建和失败重试记录")}
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
                      {t("刷新")}
                    </Button>
                    <Button
                      type="button"
                      variant="outline"
                      disabled={!canEditDocuments || isSubmittingDocumentTask}
                      onClick={() => void handleRebuildIndex()}
                    >
                      <SlidersHorizontalIcon data-icon="inline-start" />
                      {t("重建索引")}
                    </Button>
                  </div>
                </div>

                <div className="mt-4 overflow-x-auto rounded-lg border bg-background">
                  <div className="min-w-[860px]">
                    <div className="grid grid-cols-[120px_120px_140px_120px_minmax(220px,1fr)_120px] border-b px-4 py-3 text-sm font-medium text-muted-foreground">
                      <span>{t("类型")}</span>
                      <span>{t("状态")}</span>
                      <span>{t("进度")}</span>
                      <span>{t("尝试次数")}</span>
                      <span>{t("更新时间 / 错误")}</span>
                      <span>{t("操作")}</span>
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
                            {taskTypeLabel(task.task_type, t)}
                          </span>
                          <span className="flex items-center gap-2">
                            <span
                              className={cn(
                                "size-2.5 rounded-full",
                                taskStatusDotClassName(task.status)
                              )}
                            />
                            {taskStatusLabel(task.status, t)}
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
                              {t("重试")}
                            </Button>
                          </span>
                        </div>
                      ))
                    ) : (
                      <div className="flex min-h-48 items-center justify-center text-sm text-muted-foreground">
                        {t("暂无任务")}
                      </div>
                    )}
                  </div>
                </div>
              </div>
            ) : null}

            {activeDetailTab === "hit-test" ? (
              <div className="p-4 lg:p-5">
                <div className="max-w-4xl">
                  <h1 className="text-xl font-semibold">{t("命中测试")}</h1>
                  <p className="mt-1 text-sm text-muted-foreground">
                    {t("使用当前知识库的向量索引和权威切片状态验证召回结果")}
                  </p>

                  <form
                    className="mt-4 rounded-lg border bg-background p-4"
                    onSubmit={(event) => void handleQueryKnowledgeBase(event)}
                  >
                    <label className="text-sm font-medium" htmlFor="query-text">
                      {t("查询内容")}
                    </label>
                    <textarea
                      id="query-text"
                      value={queryText}
                      onChange={(event) => setQueryText(event.target.value)}
                      className="mt-2 min-h-28 w-full rounded-md border bg-background px-3 py-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
                      placeholder={t("输入要测试的检索问题")}
                    />
                    <div className="mt-3 flex flex-wrap items-end gap-3">
                      <label className="grid gap-1 text-sm font-medium">
                        {t("返回数量")}
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
                        {t("测试召回")}
                      </Button>
                    </div>
                  </form>

                  <div className="mt-4 rounded-lg border bg-background">
                    <div className="border-b px-4 py-3">
                      <h2 className="text-sm font-semibold">{t("召回结果")}</h2>
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
                        {t("暂无测试结果")}
                      </div>
                    )}
                  </div>
                </div>
              </div>
            ) : null}

            {activeDetailTab === "settings" ? (
              <div className="w-full max-w-6xl p-4 lg:p-6">
                <h1 className="text-xl font-semibold">{t("设置")}</h1>
                <div className="mt-4 rounded-lg border p-5 lg:p-6">
                  <div className="flex flex-wrap gap-2">
                    <PermissionBadge
                      permission={selectedKnowledgeBase.permission}
                    />
                    <StatusBadge status={selectedKnowledgeBase.status} />
                  </div>
                  <p className="mt-5 text-sm font-medium">{t("描述")}</p>
                  <p className="mt-2 text-sm leading-6 whitespace-pre-wrap text-muted-foreground">
                    {selectedKnowledgeBase.description || "-"}
                  </p>
                  <div className="mt-5 grid gap-4 text-sm sm:grid-cols-2">
                    <div className="min-w-0 rounded-md border p-4">
                      <p className="text-xs font-medium text-muted-foreground">
                        {t("Embedding 模型")}
                      </p>
                      <p className="mt-1 flex items-center gap-1.5 truncate font-medium">
                        {selectedEmbeddingModel ? (
                          <ModelIcon
                            model={selectedEmbeddingModel.model_name}
                            size={14}
                            type="color"
                            className="shrink-0"
                          />
                        ) : null}
                        <span className="truncate">
                          {selectedEmbeddingModel
                            ? modelLabel(selectedEmbeddingModel)
                            : t("未配置")}
                        </span>
                      </p>
                    </div>
                    <div className="min-w-0 rounded-md border p-4">
                      <p className="text-xs font-medium text-muted-foreground">
                        {t("Rerank 模型")}
                      </p>
                      <p className="mt-1 flex items-center gap-1.5 truncate font-medium">
                        {selectedRerankerModel ? (
                          <ModelIcon
                            model={selectedRerankerModel.model_name}
                            size={14}
                            type="color"
                            className="shrink-0"
                          />
                        ) : null}
                        <span className="truncate">
                          {selectedRerankerModel
                            ? modelLabel(selectedRerankerModel)
                            : t("未配置")}
                        </span>
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
                        {t("编辑")}
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
                        {t("测试模型")}
                      </Button>
                    ) : null}
                    {modelTestError ? (
                      <div className="flex w-full flex-col gap-2 rounded-md border border-destructive/30 bg-destructive/5 px-4 py-3 text-sm text-destructive">
                        <div className="flex items-center gap-2 font-medium">
                          <AlertCircleIcon className="size-4 shrink-0" />
                          {t("模型测试失败")}
                        </div>
                        <p className="break-words leading-6">
                          {modelTestError}
                        </p>
                      </div>
                    ) : modelTestResult ? (
                      <div className="flex w-full flex-col gap-2 rounded-md border border-emerald-500/30 bg-emerald-500/5 px-4 py-3 text-sm">
                        <div className="flex items-center gap-2 font-medium text-emerald-600 dark:text-emerald-400">
                          <CircleCheckIcon className="size-4 shrink-0" />
                          {t("模型测试通过")}
                        </div>
                        <dl className="flex flex-wrap gap-x-6 gap-y-1">
                          <div className="flex items-center gap-1.5">
                            <dt className="text-muted-foreground">Embedding</dt>
                            <dd className="font-medium">
                              {t("{value} 维", { value: modelTestResult.embedding_dimensions })}
                            </dd>
                          </div>
                          <div className="flex items-center gap-1.5">
                            <dt className="text-muted-foreground">Rerank</dt>
                            <dd className="font-medium">
                              {t("{value} 条", { value: modelTestResult.reranker_results })}
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
                        {t("授权")}
                      </Button>
                    ) : null}
                  </div>
                </div>
              </div>
            ) : null}
          </div>
        </div>

        <KnowledgeBaseDialogs
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
          <h1 className="truncate text-2xl font-semibold">{t("知识库")}</h1>
          <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
            {t("管理文档、数据源与向量索引，让应用可以检索你的业务知识。")}
          </p>
        </div>
        <Button
          type="button"
          className="shrink-0"
          disabled={!selectedWorkspaceId}
          onClick={() => setIsDialogOpen(true)}
        >
          <PlusIcon data-icon="inline-start" />
          {t("新建知识库")}
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
                placeholder={t("搜索{label}...", { label: t("知识库") })}
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
                <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">
                  {filteredKnowledgeBases.map((knowledgeBase) => {
                    return (
                      <div
                        key={knowledgeBase.id}
                        role="button"
                        tabIndex={0}
                        className="flex min-h-40 cursor-pointer flex-col rounded-md border p-3 outline-none transition-colors hover:bg-muted/40 focus-visible:ring-2 focus-visible:ring-ring"
                        onClick={() => openKnowledgeBase(knowledgeBase)}
                        onKeyDown={(event) => {
                          if (event.target !== event.currentTarget) return
                          if (event.key === "Enter" || event.key === " ") {
                            event.preventDefault()
                            openKnowledgeBase(knowledgeBase)
                          }
                        }}
                      >
                        <div className="flex items-start justify-between gap-3">
                          <div className="flex min-w-0 gap-3">
                            <span className="flex size-9 shrink-0 items-center justify-center rounded-md bg-muted">
                              <BookOpenTextIcon className="size-5 text-muted-foreground" />
                            </span>
                            <div className="min-w-0">
                              <div className="flex flex-wrap items-center gap-2">
                                <h2 className="truncate text-sm font-semibold">
                                  {knowledgeBase.name}
                                </h2>
                                <StatusBadge
                                  status={knowledgeBase.status}
                                />
                                <PermissionBadge
                                  permission={knowledgeBase.permission}
                                />
                              </div>
                              <p className="mt-1 truncate text-sm text-muted-foreground">
                                {knowledgeBase.description ||
                                  formatDateTime(
                                    knowledgeBase.updated_at,
                                    locale
                                  )}
                              </p>
                            </div>
                          </div>
                          {knowledgeBase.permission === "edit" ? (
                            <IconButton
                              label={t("编辑知识库")}
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
                              <PencilIcon className="size-4" />
                            </IconButton>
                          ) : null}
                        </div>
                        <div className="mt-auto flex items-end justify-between gap-2 pt-4">
                          <dl className="flex min-w-0 items-center text-sm">
                            <div className="flex items-baseline gap-1 pr-3">
                              <dt className="order-2 text-muted-foreground">
                                {t("文档数")}
                              </dt>
                              <dd className="order-1 font-semibold">
                                {knowledgeBase.document_count.toLocaleString(
                                  locale
                                )}
                              </dd>
                            </div>
                            <div className="flex min-w-0 items-baseline gap-1 border-l pl-3">
                              <dt className="order-2 truncate text-muted-foreground">
                                {t("字符数")}
                              </dt>
                              <dd className="order-1 truncate font-semibold">
                                {`${(
                                  knowledgeBase.char_count / 1_000
                                ).toLocaleString(locale, {
                                  minimumFractionDigits: 1,
                                  maximumFractionDigits: 1,
                                })}K`}
                              </dd>
                            </div>
                          </dl>
                          {knowledgeBase.permission === "edit" ||
                          canManagePermissions(knowledgeBase) ? (
                            <CardMoreMenu label={t("更多")}>
                              {knowledgeBase.permission === "edit" ? (
                                <DropdownMenuItem
                                  onSelect={() =>
                                    void handleToggleStatus(knowledgeBase)
                                  }
                                >
                                  {knowledgeBase.status === "active" ? (
                                    <ArchiveIcon />
                                  ) : (
                                    <RotateCcwIcon />
                                  )}
                                  {t(
                                    knowledgeBase.status === "active"
                                      ? "归档知识库"
                                      : "恢复知识库"
                                  )}
                                </DropdownMenuItem>
                              ) : null}
                              {knowledgeBase.permission === "edit" &&
                              canManagePermissions(knowledgeBase) ? (
                                <DropdownMenuSeparator />
                              ) : null}
                              {canManagePermissions(knowledgeBase) ? (
                                <>
                                  <DropdownMenuItem
                                    onSelect={() =>
                                      void handleOpenPermissions(knowledgeBase)
                                    }
                                  >
                                    <UsersIcon />
                                    {t("资源授权")}
                                  </DropdownMenuItem>
                                  <DropdownMenuItem
                                    variant="destructive"
                                    onSelect={() =>
                                      void handleDelete(knowledgeBase)
                                    }
                                  >
                                    <Trash2Icon />
                                    {t("永久删除知识库")}
                                  </DropdownMenuItem>
                                </>
                              ) : null}
                            </CardMoreMenu>
                          ) : null}
                        </div>
                      </div>
                    )
                  })}
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
                <p className="text-base font-semibold">{t("还没有知识库")}</p>
                <p className="text-sm leading-6 text-muted-foreground">
                  {t("创建知识库后，你可以上传文档、配置检索方式，并让应用调用这些知识。")}
                </p>
              </div>
              <Button type="button" onClick={() => setIsDialogOpen(true)}>
                <PlusIcon data-icon="inline-start" />
                {t("新建知识库")}
              </Button>
            </div>
          )}
        </>
      )}

      <KnowledgeBaseDialogs
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
