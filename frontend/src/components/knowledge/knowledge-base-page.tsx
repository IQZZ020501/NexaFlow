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
  CheckIcon,
  ChevronDownIcon,
  CircleCheckIcon,
  DatabaseIcon,
  DownloadIcon,
  FileTextIcon,
  FolderInputIcon,
  FlaskConicalIcon,
  LoaderCircleIcon,
  MoreHorizontalIcon,
  PencilIcon,
  PlusIcon,
  RotateCcwIcon,
  SearchIcon,
  SettingsIcon,
  SlidersHorizontalIcon,
  SquareIcon,
  Trash2Icon,
  UploadIcon,
  UsersIcon,
} from "lucide-react"
import { useParams, useRouter } from "next/navigation"
import type { MeResponse } from "@/lib/api/auth"
import type { AppNotification } from "@/lib/notifications"
import { useSession } from "@/contexts/session-context"
import { useLanguage } from "@/contexts/language-provider"
import { useConfirmDialog } from "@/components/app/confirm-dialog"
import { FilterDropdown } from "@/components/app/filter-dropdown"
import { CARD_BATCH_SIZE, useInfiniteScroll } from "@/lib/use-infinite-scroll"
import { Button } from "@/components/ui/button"
import { IconButton } from "@/components/ui/icon-button"
import { CardMoreMenu } from "@/components/ui/card-more-menu"
import {
  ResourceCard,
  ResourceCardActions,
  ResourceCardFooter,
  ResourceCardHeader,
  ResourceCardIcon,
  ResourceCardMeta,
  ResourceCardSpecs,
  ResourceCardTitle,
  resourceCardGridClass,
} from "@/components/ui/resource-card"
import { Spec } from "@/components/ui/spec"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
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
  deleteKnowledgeTask,
  deleteKnowledgeTasks,
  deleteKnowledgeBase,
  downloadKnowledgeDocument,
  indexKnowledgeDocument,
  indexKnowledgeDocuments,
  listKnowledgeBasePermissions,
  listKnowledgeBases,
  getKnowledgeDocumentPage,
  getKnowledgeDocumentOptions,
  getKnowledgeTaskPage,
  parseKnowledgeDocument,
  rebuildKnowledgeIndex,
  retryKnowledgeTask,
  stopKnowledgeTask,
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
  KnowledgeDocumentIndexScope,
  KnowledgeDocumentSummary,
  KnowledgeDocumentSort,
  KnowledgeDocumentStatusFilter,
  KnowledgeDocumentOption,
  KnowledgeModelTestResult,
  KnowledgeTask,
  ResourcePermission,
} from "@/lib/api/knowledge"
import { listRegisteredModels } from "@/lib/api/llm"
import type { RegisteredModel } from "@/lib/api/llm"
import { listWorkspaceMembers } from "@/lib/api/system"
import type { WorkspaceMember } from "@/lib/api/system"
import { languageLocales, type TFunction, type TranslationKey } from "@/i18n"
import { cn } from "@/lib/utils"
import { formatDateTime, formatUserIdentity, modelLabel } from "@/lib/display"
import { getErrorMessage } from "@/lib/errors"
import {
  DEFAULT_KNOWLEDGE_UPLOAD_PARSE_SETTINGS,
  knowledgeUploadPath,
  knowledgeUploadSegmentPath,
  type KnowledgeUploadRouteState,
  type KnowledgeUploadStep,
} from "@/lib/knowledge-upload-route"
import { knowledgeBaseDetailPath } from "@/lib/knowledge-views"
import { KnowledgeBaseDialogs } from "@/components/knowledge/knowledge-base-dialogs"
import { KnowledgeUploadFlow } from "@/components/knowledge/knowledge-upload-flow"
import { KnowledgeEvaluation } from "@/components/knowledge/knowledge-evaluation"
import {
  ResourceBulkMoveBar,
  toggleResourceSelection,
} from "@/components/resource-folders/resource-bulk-move-bar"
import { ResourceFolderLayout } from "@/components/resource-folders/resource-folder-layout"
import { ResourceFolderPickerDialog } from "@/components/resource-folders/resource-folder-picker-dialog"
import { ResourceFolderTree } from "@/components/resource-folders/resource-folder-tree"
import { useResourceFolders } from "@/components/resource-folders/use-resource-folders"
import {
  getDocumentFileIcon,
  getDocumentFileIconColor,
} from "@/components/knowledge/document-file-icon"
import {
  documentStatusDotClassName,
  documentStatusLabel,
  formatBytes,
  taskDurationLabel,
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
import { PHONE_LIST_QUERY, useMediaQuery } from "@/lib/use-media-query"

type DocumentSortKey =
  "name" | "size_bytes" | "chunk_count" | "created_at" | "updated_at"

type DocumentStatusFilterKey = "all" | KnowledgeDocumentStatusFilter

type KnowledgeBaseSortKey = "updated_at" | "created_at" | "name"

function sortKnowledgeBases(
  knowledgeBases: KnowledgeBaseListItem[],
  sortKey: KnowledgeBaseSortKey,
  locale: string
) {
  const collator = new Intl.Collator(locale, {
    numeric: true,
    sensitivity: "base",
  })
  return [...knowledgeBases].sort((left, right) => {
    if (sortKey === "name") return collator.compare(left.name, right.name)
    return (
      Date.parse(right[sortKey]) - Date.parse(left[sortKey]) ||
      collator.compare(left.name, right.name)
    )
  })
}

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

const DOCUMENT_STATUS_FILTER_OPTIONS: Array<{
  key: DocumentStatusFilterKey
  label: TranslationKey
}> = [
  { key: "all", label: "全部状态" },
  { key: "indexed", label: "已向量化" },
  { key: "indexing", label: "向量化中" },
  { key: "pending", label: "待向量化" },
  { key: "failed", label: "失败" },
]

const DOCUMENT_SORT_FIELDS: Record<DocumentSortKey, KnowledgeDocumentSort> = {
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

const PROCESSING_TASK_STATUSES: Record<string, true> = {
  queued: true,
  running: true,
  cancelling: true,
}

const EMPTY_DOCUMENT_SUMMARY: KnowledgeDocumentSummary = {
  total: 0,
  indexed: 0,
  indexing: 0,
  pending: 0,
  failed: 0,
  processing: 0,
}

export const DOCUMENT_PAGE_SIZES = [10, 20, 50, 100] as const
export type DocumentPageSize = (typeof DOCUMENT_PAGE_SIZES)[number]

/**
 * Calculates the number of document pages for a result set.
 *
 * @param total - The total number of documents
 * @param pageSize - The maximum number of documents per page
 * @returns The number of pages, with at least one page
 */
export function documentPageCount(total: number, pageSize: number): number {
  return Math.max(1, Math.ceil(total / pageSize))
}

/**
 * Renders document count, page-size selection, and pagination controls.
 *
 * @param total - The total number of documents.
 * @param page - The currently selected page.
 * @param pageSize - The number of documents displayed per page.
 * @param onPageChange - Called when the selected page changes.
 * @param onPageSizeChange - Called when the page size changes.
 * @returns Pagination controls, or `null` when there are no documents.
 */
function PaginationFooter({
  total,
  page,
  pageSize,
  onPageChange,
  onPageSizeChange,
}: {
  total: number
  page: number
  pageSize: DocumentPageSize
  onPageChange: (page: number) => void
  onPageSizeChange: (pageSize: DocumentPageSize) => void
}) {
  const { t } = useLanguage()
  const totalPages = documentPageCount(total, pageSize)
  const currentPage = Math.min(page, totalPages)

  React.useEffect(() => {
    if (page > totalPages) onPageChange(totalPages)
  }, [onPageChange, page, totalPages])

  if (!total) {
    return null
  }

  return (
    <div className="flex items-center justify-between gap-3 border-t px-4 py-3 text-sm">
      <div className="flex items-center gap-2">
        <span className="text-muted-foreground">
          {t("共 {value} 条", { value: total })}
        </span>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="h-7 justify-between gap-2"
            >
              <span>{t("每页 {value} 条", { value: pageSize })}</span>
              <ChevronDownIcon className="size-3.5" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="start" className="w-36">
            {DOCUMENT_PAGE_SIZES.map((option) => (
              <DropdownMenuItem
                key={option}
                className="justify-between"
                onSelect={() => onPageSizeChange(option)}
              >
                {t("每页 {value} 条", { value: option })}
                {pageSize === option ? (
                  <CheckIcon className="size-3.5 text-primary" />
                ) : null}
              </DropdownMenuItem>
            ))}
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
      <div className="flex items-center gap-2">
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={currentPage <= 1}
          onClick={() => onPageChange(Math.max(1, currentPage - 1))}
        >
          {t("上一页")}
        </Button>
        <span className="text-muted-foreground">
          {currentPage} / {totalPages}
        </span>
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={currentPage >= totalPages}
          onClick={() => onPageChange(Math.min(totalPages, currentPage + 1))}
        >
          {t("下一页")}
        </Button>
      </div>
    </div>
  )
}

const {
  chunkSize: SMART_CHUNK_SIZE,
  chunkOverlap: SMART_CHUNK_OVERLAP,
  cleaningRules: SMART_CLEANING_RULES,
  splitSeparator: SMART_SPLIT_SEPARATOR,
} = DEFAULT_KNOWLEDGE_UPLOAD_PARSE_SETTINGS

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

/**
 * Renders the workspace-aware knowledge-base management page for the authenticated user.
 *
 * @param initialDetailTab - The detail tab displayed initially.
 * @param uploadStep - The upload workflow step to display.
 * @param uploadRouteState - The state associated with the upload route.
 */
export function KnowledgeBasePage({
  initialDetailTab = "documents",
  uploadStep,
  uploadRouteState,
}: {
  initialDetailTab?: KnowledgeBaseDetailTab
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
      initialDetailTab={initialDetailTab}
      uploadStep={uploadStep}
      uploadRouteState={uploadRouteState}
    />
  )
}

/**
 * Renders the workspace-scoped knowledge-base list, detail views, and upload flow.
 *
 * @param token - Authentication token used for knowledge-base operations
 * @param me - Current user and workspace membership information
 * @param selectedWorkspaceId - Currently selected workspace identifier
 * @param notify - Displays localized success and error notifications
 * @param initialDetailTab - Detail tab to show when a knowledge base is opened
 * @param uploadStep - Current upload-flow step, when an upload route is active
 * @param uploadRouteState - State required to render the current upload-flow step
 */
function KnowledgeBasePageContent({
  token,
  me,
  selectedWorkspaceId,
  notify,
  initialDetailTab,
  uploadStep,
  uploadRouteState,
}: {
  token: string
  me: MeResponse
  selectedWorkspaceId: string | null
  notify: (kind: AppNotification["kind"], message: string) => void
  initialDetailTab: KnowledgeBaseDetailTab
  uploadStep?: KnowledgeUploadStep
  uploadRouteState?: KnowledgeUploadRouteState
}) {
  const router = useRouter()
  const params = useParams<{ id?: string }>()
  const activeKnowledgeBaseId = params.id ?? null
  const Icon = DatabaseIcon
  const { language, t } = useLanguage()
  const isPhoneListLayout = useMediaQuery(PHONE_LIST_QUERY)
  const resourceFolders = useResourceFolders("knowledge")
  const { isInSelectedFolder } = resourceFolders
  const [confirmAction, confirmDialog] = useConfirmDialog()
  const locale = languageLocales[language]
  const [knowledgeBases, setKnowledgeBases] = React.useState<
    KnowledgeBaseListItem[]
  >([])
  const [knowledgeBasesHasMore, setKnowledgeBasesHasMore] = React.useState(true)
  const [isKnowledgeBasesLoadingMore, setIsKnowledgeBasesLoadingMore] =
    React.useState(false)
  const knowledgeBasesLoadingRef = React.useRef(false)
  const knowledgeBasesRequestRef = React.useRef(0)
  const knowledgeBasesOffsetRef = React.useRef(0)
  const deletedKnowledgeBaseIds = React.useRef(new Set<string>())
  const [documents, setDocuments] = React.useState<KnowledgeDocument[]>([])
  const [documentTotal, setDocumentTotal] = React.useState(0)
  const [evaluationDocuments, setEvaluationDocuments] = React.useState<
    KnowledgeDocumentOption[]
  >([])
  const [documentSummary, setDocumentSummary] = React.useState(
    EMPTY_DOCUMENT_SUMMARY
  )
  const [documentTasks, setDocumentTasks] = React.useState<KnowledgeTask[]>([])
  const [activeRebuildIndexTask, setActiveRebuildIndexTask] =
    React.useState<KnowledgeTask | null>(null)
  const documentRequestRef = React.useRef(0)
  const taskRequestRef = React.useRef(0)
  const [knowledgeTasks, setKnowledgeTasks] = React.useState<KnowledgeTask[]>(
    []
  )
  const [knowledgeTaskTotal, setKnowledgeTaskTotal] = React.useState(0)
  const [hasProcessingTasks, setHasProcessingTasks] = React.useState(false)
  const [knowledgeTaskNow, setKnowledgeTaskNow] = React.useState(Date.now)
  const documentsById = React.useMemo(
    () => new Map(documents.map((document) => [document.id, document])),
    [documents]
  )
  const [selectedDocumentIds, setSelectedDocumentIds] = React.useState<
    string[]
  >([])
  const [selectedKnowledgeTaskIds, setSelectedKnowledgeTaskIds] =
    React.useState<string[]>([])
  const [registeredModels, setRegisteredModels] = React.useState<
    RegisteredModel[]
  >([])
  const [knowledgeSearch, setKnowledgeSearch] = React.useState("")
  const [knowledgeBaseSortKey, setKnowledgeBaseSortKey] =
    React.useState<KnowledgeBaseSortKey>("updated_at")
  const [documentSearch, setDocumentSearch] = React.useState("")
  const [documentStatusFilter, setDocumentStatusFilter] =
    React.useState<DocumentStatusFilterKey>("all")
  const [documentPage, setDocumentPage] = React.useState(1)
  const [documentPageSize, setDocumentPageSize] =
    React.useState<DocumentPageSize>(10)
  const [knowledgeTaskPage, setKnowledgeTaskPage] = React.useState(1)
  const [knowledgeTaskPageSize, setKnowledgeTaskPageSize] =
    React.useState<DocumentPageSize>(10)
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
    React.useState<KnowledgeBaseDetailTab>(initialDetailTab)
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
  const [cleaningRules, setCleaningRules] =
    React.useState<string[]>(SMART_CLEANING_RULES)
  const [busyKnowledgeTaskId, setBusyKnowledgeTaskId] = React.useState<
    string | null
  >(null)
  const [isDeletingKnowledgeTasks, setIsDeletingKnowledgeTasks] =
    React.useState(false)
  const [isTestingModels, setIsTestingModels] = React.useState(false)
  const [modelTestResult, setModelTestResult] =
    React.useState<KnowledgeModelTestResult | null>(null)
  const [modelTestError, setModelTestError] = React.useState<string | null>(
    null
  )
  const [isSaving, setIsSaving] = React.useState(false)
  const [isDialogOpen, setIsDialogOpen] = React.useState(false)
  const [moveKnowledgeBaseTarget, setMoveKnowledgeBaseTarget] =
    React.useState<KnowledgeBaseListItem | null>(null)
  const [selectedKnowledgeBaseIds, setSelectedKnowledgeBaseIds] =
    React.useState<string[]>([])
  const [isBatchManaging, setIsBatchManaging] = React.useState(false)
  const [isBatchMoveOpen, setIsBatchMoveOpen] = React.useState(false)
  const selectAllDocumentsRef = React.useRef<HTMLInputElement>(null)
  const selectAllKnowledgeTasksRef = React.useRef<HTMLInputElement>(null)

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

    const inFolder = knowledgeBases.filter((knowledgeBase) =>
      isInSelectedFolder(knowledgeBase.folder_id)
    )
    const matched = search
      ? inFolder.filter((knowledgeBase) =>
          [knowledgeBase.name, knowledgeBase.description].some((value) =>
            value.toLowerCase().includes(search)
          )
        )
      : inFolder
    return sortKnowledgeBases(
      matched,
      knowledgeBaseSortKey,
      languageLocales[language]
    )
  }, [
    knowledgeBases,
    knowledgeBaseSortKey,
    knowledgeSearch,
    language,
    isInSelectedFolder,
  ])
  const movableKnowledgeBaseIds = filteredKnowledgeBases
    .filter((knowledgeBase) => knowledgeBase.permission === "edit")
    .map((knowledgeBase) => knowledgeBase.id)
  function selectDocumentSort(key: DocumentSortKey) {
    if (documentSortKey === key) {
      cycleDocumentSort(key)
      return
    }
    setDocumentSortKey(key)
    setDocumentSortDirection(key === "name" ? "asc" : "desc")
    setDocumentPage(1)
  }

  function cycleDocumentSort(key: DocumentSortKey) {
    setDocumentPage(1)
    if (documentSortKey === key) {
      setDocumentSortDirection((current) =>
        current === "asc" ? "desc" : "asc"
      )
      return
    }
    selectDocumentSort(key)
  }
  const selectedDocuments = documents.filter((document) =>
    selectedDocumentIds.includes(document.id)
  )
  const selectedDocumentCount = selectedDocuments.length
  const documentIndexSummary = activeRebuildIndexTask
    ? {
        ...documentSummary,
        indexed: 0,
        indexing: documentSummary.indexing + documentSummary.indexed,
      }
    : documentSummary
  const documentIndexProgressCompleted = activeRebuildIndexTask
    ? activeRebuildIndexTask.processed_items
    : documentIndexSummary.indexed
  const documentIndexProgressTotal = activeRebuildIndexTask
    ? activeRebuildIndexTask.total_items
    : documentSummary.total
  const documentIndexProgress = documentIndexProgressTotal
    ? Math.round(
        (documentIndexProgressCompleted / documentIndexProgressTotal) * 100
      )
    : 0
  const documentIndexProgressLabel = activeRebuildIndexTask
    ? t("重建索引")
    : t("进度")
  const visibleDocuments = documents
  const visibleKnowledgeTasks = knowledgeTasks
  const selectedKnowledgeTasks = knowledgeTasks.filter(
    (task) =>
      selectedKnowledgeTaskIds.includes(task.id) &&
      !PROCESSING_TASK_STATUSES[task.status]
  )
  const visibleDeletableKnowledgeTasks = visibleKnowledgeTasks.filter(
    (task) => !PROCESSING_TASK_STATUSES[task.status]
  )
  const isAllVisibleKnowledgeTasksSelected =
    visibleDeletableKnowledgeTasks.length > 0 &&
    visibleDeletableKnowledgeTasks.every((task) =>
      selectedKnowledgeTaskIds.includes(task.id)
    )
  const isSomeVisibleKnowledgeTaskSelected =
    visibleDeletableKnowledgeTasks.some((task) =>
      selectedKnowledgeTaskIds.includes(task.id)
    )
  const isKnowledgeTaskMutationBusy =
    busyKnowledgeTaskId !== null || isDeletingKnowledgeTasks
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

  React.useEffect(() => {
    if (selectAllKnowledgeTasksRef.current) {
      selectAllKnowledgeTasksRef.current.indeterminate =
        isSomeVisibleKnowledgeTaskSelected &&
        !isAllVisibleKnowledgeTasksSelected
    }
  }, [isAllVisibleKnowledgeTasksSelected, isSomeVisibleKnowledgeTaskSelected])

  const reportError = React.useCallback(
    (error: unknown) => {
      const message = getErrorMessage(error, t)
      notify("error", message)
      return message
    },
    [notify, t]
  )

  const loadKnowledgeBases = React.useCallback(async () => {
    const request = ++knowledgeBasesRequestRef.current
    knowledgeBasesOffsetRef.current = 0
    setIsKnowledgeBasesLoadingMore(false)
    if (!selectedWorkspaceId) {
      setKnowledgeBases([])
      setRegisteredModels([])
      knowledgeBasesLoadingRef.current = false
      setIsLoading(false)
      return
    }

    knowledgeBasesLoadingRef.current = true
    setIsLoading(true)
    try {
      const [knowledgeBases, models] = await Promise.all([
        listKnowledgeBases(token, selectedWorkspaceId, {
          limit: CARD_BATCH_SIZE,
          offset: 0,
        }),
        listRegisteredModels(token, selectedWorkspaceId),
      ])
      if (request !== knowledgeBasesRequestRef.current) return
      const visible = knowledgeBases.filter(
        (item) => !deletedKnowledgeBaseIds.current.has(item.id)
      )
      knowledgeBasesOffsetRef.current = visible.length
      setKnowledgeBases(visible)
      setKnowledgeBasesHasMore(knowledgeBases.length === CARD_BATCH_SIZE)
      setRegisteredModels(models)
    } catch (error) {
      if (request !== knowledgeBasesRequestRef.current) return
      setKnowledgeBases([])
      setRegisteredModels([])
      reportError(error)
    } finally {
      if (request === knowledgeBasesRequestRef.current) {
        knowledgeBasesLoadingRef.current = false
        setIsLoading(false)
      }
    }
  }, [reportError, selectedWorkspaceId, token])

  const loadMoreKnowledgeBases = React.useCallback(async () => {
    if (!selectedWorkspaceId) {
      return
    }
    if (knowledgeBasesLoadingRef.current || !knowledgeBasesHasMore) {
      return
    }
    knowledgeBasesLoadingRef.current = true
    const request = knowledgeBasesRequestRef.current
    setIsKnowledgeBasesLoadingMore(true)
    try {
      const batch = await listKnowledgeBases(token, selectedWorkspaceId, {
        limit: CARD_BATCH_SIZE,
        offset: knowledgeBasesOffsetRef.current,
      })
      if (request !== knowledgeBasesRequestRef.current) return
      knowledgeBasesOffsetRef.current += batch.filter(
        (item) => !deletedKnowledgeBaseIds.current.has(item.id)
      ).length
      setKnowledgeBases((current) => {
        const existingIds = new Set(current.map((item) => item.id))
        return [
          ...current,
          ...batch.filter(
            (item) =>
              !existingIds.has(item.id) &&
              !deletedKnowledgeBaseIds.current.has(item.id)
          ),
        ]
      })
      setKnowledgeBasesHasMore(batch.length === CARD_BATCH_SIZE)
    } catch (error) {
      if (request !== knowledgeBasesRequestRef.current) return
      reportError(error)
    } finally {
      if (request === knowledgeBasesRequestRef.current) {
        knowledgeBasesLoadingRef.current = false
        setIsKnowledgeBasesLoadingMore(false)
      }
    }
  }, [
    knowledgeBasesHasMore,
    reportError,
    selectedWorkspaceId,
    token,
  ])

  const knowledgeBasesListEndRef = useInfiniteScroll(loadMoreKnowledgeBases)

  const loadDocuments = React.useCallback(
    async (silent = false) => {
      const requestId = ++documentRequestRef.current
      if (!selectedWorkspaceId || !selectedKnowledgeBaseId) {
        setDocuments([])
        setDocumentTotal(0)
        setDocumentSummary(EMPTY_DOCUMENT_SUMMARY)
        setDocumentTasks([])
        setActiveRebuildIndexTask(null)
        return
      }

      if (!silent) {
        setIsDocumentLoading(true)
      }
      try {
        const result = await getKnowledgeDocumentPage(
          token,
          selectedWorkspaceId,
          selectedKnowledgeBaseId,
          {
            limit: documentPageSize,
            offset: (documentPage - 1) * documentPageSize,
            search: documentSearch.trim(),
            status:
              documentStatusFilter === "all" ? undefined : documentStatusFilter,
            sortBy: DOCUMENT_SORT_FIELDS[documentSortKey],
            sortDirection: documentSortDirection,
          }
        )
        if (requestId !== documentRequestRef.current) return
        setDocuments(result.items)
        setDocumentTotal(result.total)
        setDocumentSummary(result.summary)
        setDocumentTasks(result.document_tasks)
        setActiveRebuildIndexTask(result.active_rebuild_task)
        setSelectedDocumentIds((current) =>
          current.filter((id) => result.items.some((item) => item.id === id))
        )
      } catch (error) {
        if (requestId === documentRequestRef.current && !silent) {
          setDocuments([])
          setDocumentTotal(0)
          reportError(error)
        }
      } finally {
        if (requestId === documentRequestRef.current) {
          setIsDocumentLoading(false)
        }
      }
    },
    [
      documentPage,
      documentPageSize,
      documentSearch,
      documentStatusFilter,
      documentSortDirection,
      documentSortKey,
      reportError,
      selectedKnowledgeBaseId,
      selectedWorkspaceId,
      token,
    ]
  )

  const loadKnowledgeTasks = React.useCallback(
    async (silent = false) => {
      const requestId = ++taskRequestRef.current
      if (!selectedWorkspaceId || !selectedKnowledgeBaseId) {
        setKnowledgeTasks([])
        setKnowledgeTaskTotal(0)
        setHasProcessingTasks(false)
        setSelectedKnowledgeTaskIds([])
        return
      }

      if (!silent) {
        setIsKnowledgeTaskLoading(true)
      }
      try {
        const result = await getKnowledgeTaskPage(
          token,
          selectedWorkspaceId,
          selectedKnowledgeBaseId,
          {
            limit: knowledgeTaskPageSize,
            offset: (knowledgeTaskPage - 1) * knowledgeTaskPageSize,
          }
        )
        if (requestId !== taskRequestRef.current) return
        const tasks = result.items
        setKnowledgeTaskNow(Date.now())
        setKnowledgeTasks(tasks)
        setKnowledgeTaskTotal(result.total)
        setHasProcessingTasks(result.has_processing)
        setSelectedKnowledgeTaskIds((current) =>
          current.filter((taskId) =>
            tasks.some(
              (task) =>
                task.id === taskId && !PROCESSING_TASK_STATUSES[task.status]
            )
          )
        )
      } catch (error) {
        if (requestId === taskRequestRef.current && !silent) {
          setKnowledgeTasks([])
          setKnowledgeTaskTotal(0)
          setSelectedKnowledgeTaskIds([])
          reportError(error)
        }
      } finally {
        if (requestId === taskRequestRef.current) {
          setIsKnowledgeTaskLoading(false)
        }
      }
    },
    [
      knowledgeTaskPage,
      knowledgeTaskPageSize,
      reportError,
      selectedKnowledgeBaseId,
      selectedWorkspaceId,
      token,
    ]
  )

  React.useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void loadKnowledgeBases()
    return () => {
      knowledgeBasesRequestRef.current += 1
    }
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
    return () => {
      documentRequestRef.current += 1
    }
  }, [loadDocuments])

  React.useEffect(() => {
    if (activeDetailTab !== "tasks") {
      return
    }

    // eslint-disable-next-line react-hooks/set-state-in-effect
    void loadKnowledgeTasks()
    return () => {
      taskRequestRef.current += 1
    }
  }, [activeDetailTab, loadKnowledgeTasks])

  React.useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setActiveDetailTab(initialDetailTab)
  }, [activeKnowledgeBaseId, initialDetailTab])

  React.useEffect(() => {
    // Reset selection and paging when the resource scope changes.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setDocuments([])
    setDocumentTotal(0)
    setDocumentSummary(EMPTY_DOCUMENT_SUMMARY)
    setDocumentTasks([])
    setActiveRebuildIndexTask(null)
    setSelectedDocumentIds([])
    setDocumentPage(1)
    setDocumentSearch("")
    setDocumentStatusFilter("all")
    setKnowledgeTasks([])
    setKnowledgeTaskTotal(0)
    setSelectedKnowledgeTaskIds([])
    setKnowledgeTaskPage(1)
    setHasProcessingTasks(false)
  }, [selectedKnowledgeBaseId, selectedWorkspaceId])

  React.useEffect(() => {
    if (
      activeDetailTab !== "evaluation" ||
      !selectedWorkspaceId ||
      !selectedKnowledgeBaseId
    ) return
    let cancelled = false
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setEvaluationDocuments([])
    void getKnowledgeDocumentOptions(
      token, selectedWorkspaceId, selectedKnowledgeBaseId
    )
      .then((items) => {
        if (!cancelled) setEvaluationDocuments(items)
      })
      .catch((error) => {
        if (!cancelled) reportError(error)
      })
    return () => {
      cancelled = true
    }
  }, [activeDetailTab, reportError, selectedKnowledgeBaseId, selectedWorkspaceId, token])

  const hasProcessingDocuments = documentSummary.processing > 0
  const shouldPollTasks =
    (activeDetailTab === "tasks" && hasProcessingTasks) ||
    activeRebuildIndexTask !== null
  const hasRunningTaskDuration =
    activeDetailTab === "tasks" &&
    visibleKnowledgeTasks.some(
      (task) =>
        task.started_at &&
        (task.status === "running" || task.status === "cancelling")
    )

  React.useEffect(() => {
    if (!hasRunningTaskDuration) return

    const timer = window.setInterval(
      () => setKnowledgeTaskNow(Date.now()),
      1000
    )
    return () => window.clearInterval(timer)
  }, [hasRunningTaskDuration])

  React.useEffect(() => {
    if (!hasProcessingDocuments && !shouldPollTasks) {
      return
    }

    const timer = window.setInterval(() => {
      void loadDocuments(true)
      if (activeDetailTab === "tasks") void loadKnowledgeTasks(true)
    }, 3000)
    return () => window.clearInterval(timer)
  }, [
    activeDetailTab,
    hasProcessingDocuments,
    loadDocuments,
    loadKnowledgeTasks,
    shouldPollTasks,
  ])

  const cancelUpload = React.useCallback(() => {
    if (selectedKnowledgeBaseId) {
      router.replace(`/app/knowledge/${selectedKnowledgeBaseId}`)
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
        routeState.parseSettings,
        routeState.importMode
      )
      router.replace(path)
    },
    [router, selectedKnowledgeBaseId]
  )

  const backToUploadFiles = React.useCallback(() => {
    if (selectedKnowledgeBaseId) {
      router.replace(knowledgeUploadPath(selectedKnowledgeBaseId))
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

  function toggleKnowledgeTaskSelection(taskId: string, checked: boolean) {
    setSelectedKnowledgeTaskIds((current) =>
      checked
        ? current.includes(taskId)
          ? current
          : [...current, taskId]
        : current.filter((id) => id !== taskId)
    )
  }

  function toggleAllVisibleKnowledgeTasks(checked: boolean) {
    const visibleTaskIds = visibleDeletableKnowledgeTasks.map((task) => task.id)
    setSelectedKnowledgeTaskIds((current) =>
      checked
        ? Array.from(new Set([...current, ...visibleTaskIds]))
        : current.filter((id) => !visibleTaskIds.includes(id))
    )
  }

  function canManagePermissions(knowledgeBase: KnowledgeBase) {
    // Grants stay with the owner: other users, admins included, never see or
    // manage someone else's knowledge base.
    return knowledgeBase.created_by_user_id === me.user.id
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
    setDocumentStatusFilter("all")
    setSelectedDocumentIds([])
    setSelectedKnowledgeTaskIds([])
    setKnowledgeTasks([])
    router.push(`/app/knowledge/${knowledgeBase.id}`)
  }

  function closeKnowledgeBase() {
    setSelectedKnowledgeTaskIds([])
    setKnowledgeTasks([])
    router.push("/app/knowledge")
  }

  function changeDetailTab(tab: KnowledgeBaseDetailTab) {
    if (!selectedKnowledgeBaseId) {
      return
    }
    setActiveDetailTab(tab)
    window.history.pushState(
      null,
      "",
      knowledgeBaseDetailPath(selectedKnowledgeBaseId, tab)
    )
  }

  async function handleCreate(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!selectedWorkspaceId || !form.name.trim()) {
      return
    }

    setIsSaving(true)
    try {
      const knowledgeBase = await createKnowledgeBase(
        token,
        selectedWorkspaceId,
        { ...form, name: form.name.trim(), description: form.description.trim() }
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
    if (!selectedWorkspaceId || !editForm || !editForm.name.trim()) {
      return
    }

    setIsSaving(true)
    try {
      updateKnowledgeBaseInList(
        await updateKnowledgeBase(token, selectedWorkspaceId, editForm.id, {
          name: editForm.name.trim(),
          description: editForm.description.trim(),
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
      !(await confirmAction({
        description: t("永久删除 {name}？此操作不可恢复。", {
          name: knowledgeBase.name,
        }),
        confirmLabel: t("删除"),
        destructive: true,
      }))
    ) {
      return
    }

    try {
      await deleteKnowledgeBase(token, selectedWorkspaceId, knowledgeBase.id)
      deletedKnowledgeBaseIds.current.add(knowledgeBase.id)
      if (knowledgeBases.some((item) => item.id === knowledgeBase.id))
        knowledgeBasesOffsetRef.current = Math.max(
          0,
          knowledgeBasesOffsetRef.current - 1
        )
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
    if (
      !selectedWorkspaceId ||
      !selectedKnowledgeBase ||
      !targetDocuments.length
    ) {
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

  async function handleIndexAllDocuments(scope: KnowledgeDocumentIndexScope) {
    if (!selectedWorkspaceId || !selectedKnowledgeBase) return
    setIsSubmittingDocumentTask(true)
    try {
      const result = await indexKnowledgeDocuments(
        token,
        selectedWorkspaceId,
        selectedKnowledgeBase.id,
        scope
      )
      setSelectedDocumentIds([])
      await Promise.all([loadDocuments(), loadKnowledgeTasks()])
      notify(
        "success",
        result.queued_count
          ? t("已提交 {value} 个向量化任务", { value: result.queued_count })
          : t("没有需要向量化的文档")
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
    if (
      !selectedWorkspaceId ||
      !selectedKnowledgeBase ||
      !selectedDocuments.length
    ) {
      return
    }

    if (
      !(await confirmAction({
        description: t("永久删除选中的 {value} 个文档？此操作不可恢复。", {
          value: selectedDocuments.length,
        }),
        confirmLabel: t("删除"),
        destructive: true,
      }))
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
      const deletedIds = new Set(
        selectedDocuments.map((document) => document.id)
      )
      setDocuments((current) =>
        current.filter((item) => !deletedIds.has(item.id))
      )
      setSelectedDocumentIds([])
      await Promise.all([loadDocuments(), loadKnowledgeTasks()])
      notify(
        "success",
        t("已删除 {value} 个文档", { value: selectedDocuments.length })
      )
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
      const task = await rebuildKnowledgeIndex(
        token,
        selectedWorkspaceId,
        selectedKnowledgeBase.id
      )
      setKnowledgeTasks((current) => [
        task,
        ...current.filter((item) => item.id !== task.id),
      ])
      setActiveRebuildIndexTask(task)
      await Promise.all([loadDocuments(), loadKnowledgeTasks()])
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

    setBusyKnowledgeTaskId(task.id)
    try {
      await retryKnowledgeTask(
        token,
        selectedWorkspaceId,
        selectedKnowledgeBase.id,
        task.id
      )
      await Promise.all([loadDocuments(), loadKnowledgeTasks()])
      notify("success", t("已重新提交任务"))
    } catch (error) {
      reportError(error)
    } finally {
      setBusyKnowledgeTaskId(null)
    }
  }

  async function handleStopKnowledgeTask(task: KnowledgeTask) {
    if (!selectedWorkspaceId || !selectedKnowledgeBase) return
    setBusyKnowledgeTaskId(task.id)
    try {
      const stopped = await stopKnowledgeTask(
        token,
        selectedWorkspaceId,
        selectedKnowledgeBase.id,
        task.id
      )
      setKnowledgeTasks((current) =>
        current.map((item) => (item.id === stopped.id ? stopped : item))
      )
      await loadDocuments()
      notify("success", t("已停止任务"))
    } catch (error) {
      reportError(error)
    } finally {
      setBusyKnowledgeTaskId(null)
    }
  }

  async function handleDeleteKnowledgeTask(task: KnowledgeTask) {
    if (!selectedWorkspaceId || !selectedKnowledgeBase) return
    if (
      !(await confirmAction({
        description: t("删除此任务记录？此操作不可恢复。"),
        confirmLabel: t("删除"),
        destructive: true,
      }))
    ) {
      return
    }
    setBusyKnowledgeTaskId(task.id)
    try {
      await deleteKnowledgeTask(
        token,
        selectedWorkspaceId,
        selectedKnowledgeBase.id,
        task.id
      )
      setKnowledgeTasks((current) =>
        current.filter((item) => item.id !== task.id)
      )
      setSelectedKnowledgeTaskIds((current) =>
        current.filter((id) => id !== task.id)
      )
      await loadKnowledgeTasks()
      notify("success", t("已删除任务"))
    } catch (error) {
      reportError(error)
    } finally {
      setBusyKnowledgeTaskId(null)
    }
  }

  async function handleDeleteSelectedKnowledgeTasks() {
    if (
      !selectedWorkspaceId ||
      !selectedKnowledgeBase ||
      !selectedKnowledgeTasks.length
    ) {
      return
    }
    if (
      !(await confirmAction({
        description: t("删除选中的 {value} 个任务？此操作不可恢复。", {
          value: selectedKnowledgeTasks.length,
        }),
        confirmLabel: t("删除"),
        destructive: true,
      }))
    ) {
      return
    }

    setIsDeletingKnowledgeTasks(true)
    try {
      const result = await deleteKnowledgeTasks(
        token,
        selectedWorkspaceId,
        selectedKnowledgeBase.id,
        selectedKnowledgeTasks.map((task) => task.id)
      )
      const deletedIds = new Set(result.deleted_task_ids)
      setKnowledgeTasks((current) =>
        current.filter((task) => !deletedIds.has(task.id))
      )
      setSelectedKnowledgeTaskIds((current) =>
        current.filter((taskId) => !deletedIds.has(taskId))
      )
      await loadKnowledgeTasks()
      notify(
        "success",
        t("已删除 {value} 个任务", { value: result.deleted_task_ids.length })
      )
    } catch (error) {
      reportError(error)
    } finally {
      setIsDeletingKnowledgeTasks(false)
    }
  }

  async function handleDeleteDocument(document: KnowledgeDocument) {
    if (!selectedWorkspaceId || !selectedKnowledgeBase) {
      return
    }

    if (
      !(await confirmAction({
        description: t("永久删除 {name}？此操作不可恢复。", {
          name: document.filename,
        }),
        confirmLabel: t("删除"),
        destructive: true,
      }))
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
      await Promise.all([loadDocuments(), loadKnowledgeTasks()])
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
    { key: "evaluation", label: t("检索评测"), icon: FlaskConicalIcon },
    { key: "settings", label: t("设置"), icon: SettingsIcon },
  ]

  function renderDocumentActionMenu(document: KnowledgeDocument) {
    return (
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button
            type="button"
            variant="ghost"
            size="icon-sm"
            className="text-muted-foreground hover:text-foreground"
            disabled={!canEditDocuments || isSubmittingDocumentTask}
            aria-label={t("操作 {value}", {
              value: document.filename,
            })}
            title={t("操作 {value}", {
              value: document.filename,
            })}
          >
            <MoreHorizontalIcon />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent side="bottom" align="end" className="min-w-40">
          <DropdownMenuItem
            onSelect={() => void handleDownloadDocument(document)}
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
            onSelect={() => void handleIndexDocuments([document])}
          >
            <SlidersHorizontalIcon />
            {t("向量化")}
          </DropdownMenuItem>
          <DropdownMenuSeparator />
          <DropdownMenuItem
            variant="destructive"
            onSelect={() => void handleDeleteDocument(document)}
          >
            <Trash2Icon />
            {t("删除")}
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    )
  }

  function renderKnowledgeTaskDocument(task: KnowledgeTask) {
    if (
      !task.document_id &&
      (task.task_type === "rebuild_index" || task.task_type === "evaluate")
    ) {
      return <span className="text-muted-foreground">{t("整个知识库")}</span>
    }

    const document = task.document_id
      ? documentsById.get(task.document_id)
      : undefined
    const filename = task.document_filename ?? document?.filename
    if (!filename || !task.document_id) {
      return (
        <span className="text-muted-foreground">
          {isDocumentLoading ? "—" : t("文档不可用")}
        </span>
      )
    }

    return (
      <button
        type="button"
        className="block max-w-full truncate text-left outline-none hover:text-primary focus-visible:underline"
        title={filename}
        onClick={() =>
          router.push(
            `/app/knowledge/${task.knowledge_base_id}/documents/${task.document_id}`
          )
        }
      >
        {filename}
      </button>
    )
  }

  function renderKnowledgeTaskActionMenu(task: KnowledgeTask) {
    const isTaskActionDisabled =
      !canEditDocuments || isKnowledgeTaskMutationBusy
    const canStopTask = ["queued", "running"].includes(task.status)
    const canRetryTask =
      ["parse", "index", "rebuild_index", "evaluate"].includes(task.task_type) &&
      ["failed", "cancelled"].includes(task.status)
    const canDeleteTask = !["queued", "running", "cancelling"].includes(
      task.status
    )
    const hasAvailableAction = canStopTask || canRetryTask || canDeleteTask

    return (
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button
            type="button"
            variant="ghost"
            size="icon-sm"
            className="text-muted-foreground hover:text-foreground"
            disabled={isTaskActionDisabled || !hasAvailableAction}
            aria-label={t("操作 {value}", { value: task.id })}
            title={t("更多")}
          >
            <MoreHorizontalIcon />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent side="bottom" align="end" className="min-w-40">
          {canStopTask ? (
            <DropdownMenuItem
              onSelect={() => void handleStopKnowledgeTask(task)}
            >
              <SquareIcon className="fill-current" />
              {t("停止")}
            </DropdownMenuItem>
          ) : null}
          {canRetryTask ? (
            <DropdownMenuItem
              onSelect={() => void handleRetryKnowledgeTask(task)}
            >
              <RotateCcwIcon />
              {t("重试")}
            </DropdownMenuItem>
          ) : null}
          {canDeleteTask && (canStopTask || canRetryTask) ? (
            <DropdownMenuSeparator />
          ) : null}
          {canDeleteTask ? (
            <DropdownMenuItem
              variant="destructive"
              onSelect={() => void handleDeleteKnowledgeTask(task)}
            >
              <Trash2Icon />
              {t("删除")}
            </DropdownMenuItem>
          ) : null}
        </DropdownMenuContent>
      </DropdownMenu>
    )
  }

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
        onDone={() => {
          setActiveDetailTab("documents")
          void Promise.all([loadDocuments(), loadKnowledgeTasks()])
          router.replace(`/app/knowledge/${selectedKnowledgeBase.id}`)
        }}
        onNotify={notify}
      />
    )
  }

  if (selectedKnowledgeBase) {
    return (
      <>
        <div className="-mx-4 grid min-h-[calc(100svh-6.5rem)] grid-cols-1 content-start overflow-hidden border-y bg-background sm:-mx-6 lg:-mx-8 lg:h-[calc(100svh-6.5rem)] lg:min-h-0 lg:grid-cols-[220px_minmax(0,1fr)] lg:content-stretch">
          <aside className="border-b bg-muted/30 p-3 lg:h-full lg:min-h-0 lg:overflow-y-auto lg:border-r lg:border-b-0 lg:p-4">
            <div className="mb-6 flex items-center gap-2">
              <Button
                type="button"
                variant="ghost"
                size="icon-sm"
                aria-label={t("返回")}
                title={t("返回")}
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
            <nav className="flex flex-wrap gap-2 lg:flex-col lg:flex-nowrap lg:overflow-visible">
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
                    aria-current={isActive ? "page" : undefined}
                    onClick={() => changeDetailTab(tab.key)}
                  >
                    <TabIcon className="size-4" />
                    {tab.label}
                  </button>
                )
              })}
            </nav>
          </aside>

          <div className="min-h-0 min-w-0 overflow-hidden lg:h-full lg:overflow-y-auto lg:overscroll-contain">
            {activeDetailTab === "documents" ? (
              <div className="min-w-0 p-3 sm:p-4 lg:p-5">
                <section
                  aria-label={t("进度")}
                  className="mb-3 rounded-lg border bg-background px-4 py-3"
                >
                  <div className="grid gap-4 md:grid-cols-[minmax(220px,1.2fr)_minmax(0,2fr)] md:items-center">
                    <div>
                      <div className="flex items-baseline justify-between gap-4">
                        <p className="text-sm font-medium">
                          {documentIndexProgressLabel}
                          <span className="ml-2 font-normal text-muted-foreground tabular-nums">
                            {documentIndexProgressCompleted} /{" "}
                            {documentIndexProgressTotal}
                          </span>
                        </p>
                        <span className="text-sm font-semibold text-emerald-700 tabular-nums dark:text-emerald-400">
                          {documentIndexProgress}%
                        </span>
                      </div>
                      <div
                        role="progressbar"
                        aria-label={documentIndexProgressLabel}
                        aria-valuemin={0}
                        aria-valuemax={100}
                        aria-valuenow={documentIndexProgress}
                        className="mt-2 h-1.5 overflow-hidden rounded-full bg-muted"
                      >
                        <div
                          className="h-full rounded-full bg-emerald-500 transition-[width]"
                          style={{ width: `${documentIndexProgress}%` }}
                        />
                      </div>
                    </div>
                    <div className="grid grid-cols-4">
                      {[
                        {
                          label: t("已向量化"),
                          value: documentIndexSummary.indexed,
                          dotClassName: "bg-emerald-500",
                        },
                        {
                          label: t("向量化中"),
                          value: documentIndexSummary.indexing,
                          dotClassName: "bg-sky-500",
                        },
                        {
                          label: t("待向量化"),
                          value: documentIndexSummary.pending,
                          dotClassName: "bg-amber-500",
                        },
                        {
                          label: t("失败"),
                          value: documentIndexSummary.failed,
                          dotClassName: "bg-destructive",
                        },
                      ].map((item) => (
                        <div
                          key={item.label}
                          role="group"
                          aria-label={item.label}
                          className="min-w-0 border-l px-3 first:border-l-0 first:pl-0 last:pr-0"
                        >
                          <p className="flex items-center gap-1.5 truncate text-[11px] font-medium text-muted-foreground sm:text-xs">
                            <span
                              className={cn(
                                "size-1.5 shrink-0 rounded-full",
                                item.dotClassName
                              )}
                            />
                            {item.label}
                          </p>
                          <p className="mt-1 text-lg font-semibold tracking-tight tabular-nums">
                            {item.value}
                          </p>
                        </div>
                      ))}
                    </div>
                  </div>
                </section>
                <div className="overflow-hidden rounded-lg border bg-background">
                  <div className="flex flex-col gap-3 border-b p-3 sm:p-4 xl:flex-row xl:items-center xl:justify-between">
                    <div className="flex flex-wrap gap-2">
                      <Button
                        type="button"
                        className="h-9 shadow-sm"
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
                      <DropdownMenu>
                        <DropdownMenuTrigger asChild>
                          <Button
                            type="button"
                            variant={
                              selectedDocumentCount ? "secondary" : "outline"
                            }
                            className="h-9"
                            disabled={
                              !canEditDocuments ||
                              documentSummary.total === 0 ||
                              isSubmittingDocumentTask
                            }
                          >
                            {isSubmittingDocumentTask ? (
                              <LoaderCircleIcon
                                className="animate-spin"
                                data-icon="inline-start"
                              />
                            ) : (
                              <SlidersHorizontalIcon data-icon="inline-start" />
                            )}
                            {t("向量化")}
                            {selectedDocumentCount
                              ? `(${selectedDocumentCount})`
                              : ""}
                            <ChevronDownIcon
                              data-icon="inline-end"
                              className="text-muted-foreground transition-transform duration-150 [[data-state=open]>&]:rotate-180"
                            />
                          </Button>
                        </DropdownMenuTrigger>
                        <DropdownMenuContent
                          align="start"
                          sideOffset={6}
                          className="w-56 p-1.5"
                        >
                          <DropdownMenuItem
                            className="gap-2.5 rounded-md px-2.5 py-2"
                            onSelect={() =>
                              void handleIndexAllDocuments("unsuccessful")
                            }
                          >
                            <RotateCcwIcon className="size-4" />
                            <span>{t("向量化未成功的文档")}</span>
                          </DropdownMenuItem>
                          <DropdownMenuItem
                            className="gap-2.5 rounded-md px-2.5 py-2"
                            onSelect={() => void handleIndexAllDocuments("all")}
                          >
                            <DatabaseIcon className="size-4" />
                            <span>{t("向量化全部文档")}</span>
                          </DropdownMenuItem>
                          {selectedDocumentCount ? (
                            <>
                              <DropdownMenuSeparator className="my-1" />
                              <DropdownMenuItem
                                className="gap-2.5 rounded-md px-2.5 py-2"
                                onSelect={() =>
                                  void handleIndexDocuments(selectedDocuments)
                                }
                              >
                                <CircleCheckIcon className="size-4" />
                                <span className="flex-1">
                                  {t("向量化所选文档")}
                                </span>
                                <span
                                  aria-hidden="true"
                                  className="rounded bg-muted px-1.5 py-0.5 text-xs font-medium text-muted-foreground tabular-nums"
                                >
                                  {selectedDocumentCount}
                                </span>
                              </DropdownMenuItem>
                            </>
                          ) : null}
                          <DropdownMenuLabel className="mt-1 rounded-md border border-border/50 bg-muted/40 px-2.5 py-2 text-xs leading-relaxed font-normal whitespace-normal text-pretty text-muted-foreground">
                            {t("仅处理已分段文档，正在处理的文档会自动跳过。")}
                          </DropdownMenuLabel>
                        </DropdownMenuContent>
                      </DropdownMenu>
                      <Button
                        type="button"
                        variant="outline"
                        className="h-9"
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
                        variant={
                          selectedDocumentCount ? "destructive" : "outline"
                        }
                        className="h-9"
                        disabled={
                          !canEditDocuments ||
                          selectedDocumentCount === 0 ||
                          isSubmittingDocumentTask
                        }
                        onClick={() => void handleDeleteSelectedDocuments()}
                      >
                        <Trash2Icon data-icon="inline-start" />
                        {t("删除")}
                        {selectedDocumentCount
                          ? `(${selectedDocumentCount})`
                          : ""}
                      </Button>
                    </div>
                    <div className="grid min-w-0 grid-cols-2 gap-2 sm:flex sm:items-center">
                      <div className="relative col-span-2 min-w-0 sm:w-64 xl:w-72">
                        <SearchIcon className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" />
                        <Input
                          value={documentSearch}
                          onChange={(event) => {
                            setDocumentSearch(event.target.value)
                            setDocumentPage(1)
                          }}
                          className="h-9 rounded-lg bg-muted/25 pl-9"
                          placeholder={t("按名称搜索")}
                        />
                      </div>
                      <FilterDropdown
                        ariaLabel={t("文件状态")}
                        value={documentStatusFilter}
                        options={DOCUMENT_STATUS_FILTER_OPTIONS.map(
                          (option) => ({
                            value: option.key,
                            label: t(option.label),
                          })
                        )}
                        className="h-9 sm:w-32"
                        onChange={(value) => {
                          setDocumentStatusFilter(
                            value as DocumentStatusFilterKey
                          )
                          setDocumentPage(1)
                        }}
                      />
                      <FilterDropdown
                        ariaLabel={t("排序")}
                        value={documentSortKey}
                        options={DOCUMENT_SORT_OPTIONS.map((option) => ({
                          value: option.key,
                          label: t(option.label),
                        }))}
                        className="h-9 sm:w-32"
                        onChange={(value) =>
                          selectDocumentSort(value as DocumentSortKey)
                        }
                      />
                    </div>
                  </div>

                  {isPhoneListLayout ? (
                    <ul className="flex flex-col gap-2 p-3">
                      {isDocumentLoading ? (
                        <li className="flex min-h-40 items-center justify-center text-sm text-muted-foreground">
                          <LoaderCircleIcon className="animate-spin" />
                        </li>
                      ) : visibleDocuments.length ? (
                        visibleDocuments.map((document) => {
                          const isSelected = selectedDocumentIds.includes(
                            document.id
                          )
                          const isDocumentActionDisabled =
                            !canEditDocuments || isSubmittingDocumentTask

                          return (
                            <li
                              key={document.id}
                              className={cn(
                                "rounded-xl border bg-background p-3",
                                isSelected &&
                                  "border-primary/50 bg-primary/[0.035]"
                              )}
                            >
                              <div className="flex items-start gap-3">
                                <label className="flex size-10 shrink-0 items-center justify-center">
                                  <input
                                    type="checkbox"
                                    className="size-4 accent-primary"
                                    aria-label={t("选择 {value}", {
                                      value: document.filename,
                                    })}
                                    checked={isSelected}
                                    onChange={(event) =>
                                      toggleDocumentSelection(
                                        document.id,
                                        event.target.checked
                                      )
                                    }
                                  />
                                </label>
                                <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-muted/70">
                                  {React.createElement(
                                    getDocumentFileIcon(document.filename),
                                    {
                                      "aria-hidden": true,
                                      className: cn(
                                        "size-4 text-base leading-none",
                                        getDocumentFileIconColor(
                                          document.filename
                                        )
                                      ),
                                    }
                                  )}
                                </span>
                                <button
                                  type="button"
                                  className="min-w-0 flex-1 text-left text-sm font-medium break-words outline-none hover:text-primary focus-visible:underline"
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

                              <dl className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-2 text-xs text-muted-foreground">
                                <div className="min-w-0">
                                  <dt className="sr-only">{t("文件状态")}</dt>
                                  <dd className="inline-flex w-fit max-w-full items-center gap-1.5 rounded-full border bg-background px-2.5 py-1 font-medium text-foreground">
                                    {PROCESSING_DOCUMENT_STATUSES[
                                      document.status
                                    ] ? (
                                      <LoaderCircleIcon className="size-3.5 shrink-0 animate-spin text-primary" />
                                    ) : (
                                      <span
                                        className={cn(
                                          "size-2 shrink-0 rounded-full",
                                          documentStatusDotClassName(
                                            document.status
                                          )
                                        )}
                                      />
                                    )}
                                    <span className="truncate">
                                      {documentStatusText(
                                        document,
                                        documentTasks,
                                        t
                                      )}
                                    </span>
                                  </dd>
                                </div>
                                <div className="flex items-center gap-1">
                                  <dt>{t("大小")}</dt>
                                  <dd className="font-medium text-foreground">
                                    {formatBytes(document.size_bytes)}
                                  </dd>
                                </div>
                                <div className="flex items-center gap-1">
                                  <dt>{t("分段")}</dt>
                                  <dd className="font-semibold text-foreground">
                                    {document.chunk_count}
                                  </dd>
                                </div>
                                <div className="flex items-center gap-2">
                                  <dt>{t("启用状态")}</dt>
                                  <dd className="flex items-center gap-2">
                                    <button
                                      type="button"
                                      role="switch"
                                      aria-checked={document.is_active}
                                      aria-label={t(
                                        document.is_active
                                          ? "停用 {value}"
                                          : "启用 {value}",
                                        { value: document.filename }
                                      )}
                                      disabled={isDocumentActionDisabled}
                                      onClick={() =>
                                        void handleToggleDocumentActive(
                                          document
                                        )
                                      }
                                      className={cn(
                                        "relative h-5 w-9 shrink-0 cursor-pointer rounded-full transition-colors outline-none after:absolute after:-inset-2 after:content-[''] focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50",
                                        document.is_active
                                          ? "bg-primary"
                                          : "bg-muted-foreground/35"
                                      )}
                                    >
                                      <span
                                        className={cn(
                                          "block size-4 rounded-full bg-background shadow-sm transition-transform",
                                          document.is_active
                                            ? "translate-x-[18px]"
                                            : "translate-x-0.5"
                                        )}
                                      />
                                    </button>
                                    <span>
                                      {t(
                                        document.is_active ? "已启用" : "已停用"
                                      )}
                                    </span>
                                  </dd>
                                </div>
                                <div className="flex w-full items-center gap-1">
                                  <dt className="shrink-0">{t("更新时间")}</dt>
                                  <dd className="min-w-0 truncate">
                                    {formatDateTime(
                                      document.updated_at,
                                      locale
                                    )}
                                  </dd>
                                </div>
                              </dl>

                              {document.last_error ? (
                                <p className="mt-2 text-xs break-words text-destructive">
                                  {getErrorMessage(new Error(document.last_error), t)}
                                </p>
                              ) : null}

                              <div className="mt-3 flex flex-wrap items-center gap-2 border-t pt-3">
                                <Button
                                  type="button"
                                  variant="outline"
                                  size="sm"
                                  className="gap-1.5"
                                  disabled={isDocumentActionDisabled}
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
                                  {t("重新分段")}
                                </Button>
                                <Button
                                  type="button"
                                  variant="outline"
                                  size="sm"
                                  className="gap-1.5"
                                  disabled={isDocumentActionDisabled}
                                  onClick={() =>
                                    void handleIndexDocuments([document])
                                  }
                                >
                                  <SlidersHorizontalIcon />
                                  {t("向量化")}
                                </Button>
                                <div className="ml-auto">
                                  {renderDocumentActionMenu(document)}
                                </div>
                              </div>
                            </li>
                          )
                        })
                      ) : (
                        <li className="flex min-h-40 flex-col items-center justify-center gap-2 p-3 text-sm text-muted-foreground">
                          <span className="flex size-10 items-center justify-center rounded-lg bg-muted/60">
                            <FileTextIcon className="size-4" />
                          </span>
                          {t(documentSummary.total ? "没有匹配的文档" : "暂无文档")}
                        </li>
                      )}
                    </ul>
                  ) : null}

                  <div className="hidden overflow-x-auto md:block">
                    <div className="min-w-[1040px]">
                      <div className="grid grid-cols-[44px_minmax(280px,1fr)_140px_92px_84px_124px_164px_132px] items-center border-b bg-muted/30 px-3 py-3 text-xs font-medium text-muted-foreground">
                        <label className="flex items-center justify-center">
                          <input
                            ref={selectAllDocumentsRef}
                            type="checkbox"
                            className="size-4 accent-primary"
                            aria-label={t("选择所有文档")}
                            checked={isAllFilteredDocumentsSelected}
                            disabled={!documents.length}
                            onChange={(event) =>
                              toggleAllFilteredDocuments(event.target.checked)
                            }
                          />
                        </label>
                        <button
                          type="button"
                          className="flex items-center gap-1 text-left outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring"
                          onClick={() => cycleDocumentSort("name")}
                        >
                          {t("文件名称")}
                          {documentSortKey === "name" ? (
                            documentSortDirection === "asc" ? (
                              <ArrowUpIcon className="size-3.5" />
                            ) : (
                              <ArrowDownIcon className="size-3.5" />
                            )
                          ) : (
                            <ArrowUpDownIcon className="size-3.5" />
                          )}
                        </button>
                        <span className="text-center">{t("文件状态")}</span>
                        <button
                          type="button"
                          className="flex items-center justify-center gap-1 outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring"
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
                          className="flex items-center justify-center gap-1 outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring"
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
                        <span className="text-center">{t("启用状态")}</span>
                        <button
                          type="button"
                          className="flex items-center justify-center gap-1 outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring"
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
                        <span className="text-center">{t("操作")}</span>
                      </div>
                      {isDocumentLoading ? (
                        <div className="flex min-h-56 items-center justify-center px-3 py-10 text-sm text-muted-foreground">
                          <LoaderCircleIcon className="animate-spin" />
                        </div>
                      ) : visibleDocuments.length ? (
                        visibleDocuments.map((document) => {
                          const isSelected = selectedDocumentIds.includes(
                            document.id
                          )

                          return (
                            <div
                              key={document.id}
                              className={cn(
                                "grid min-h-[72px] grid-cols-[44px_minmax(280px,1fr)_140px_92px_84px_124px_164px_132px] items-center border-b px-3 text-sm transition-colors last:border-b-0 hover:bg-muted/25",
                                isSelected && "bg-primary/[0.035]"
                              )}
                            >
                              <label className="flex items-center justify-center">
                                <input
                                  type="checkbox"
                                  className="size-4 accent-primary"
                                  aria-label={t("选择 {value}", {
                                    value: document.filename,
                                  })}
                                  checked={isSelected}
                                  onChange={(event) =>
                                    toggleDocumentSelection(
                                      document.id,
                                      event.target.checked
                                    )
                                  }
                                />
                              </label>
                              <div className="flex min-w-0 items-center gap-3 pr-4">
                                <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-muted/70">
                                  {React.createElement(
                                    getDocumentFileIcon(document.filename),
                                    {
                                      "aria-hidden": true,
                                      className: cn(
                                        "size-4 text-base leading-none",
                                        getDocumentFileIconColor(
                                          document.filename
                                        )
                                      ),
                                    }
                                  )}
                                </span>
                                <div className="min-w-0">
                                  <button
                                    type="button"
                                    className="block max-w-full truncate text-left font-medium outline-none hover:text-primary focus-visible:underline"
                                    title={document.filename}
                                    onClick={() =>
                                      router.push(
                                        `/app/knowledge/${selectedKnowledgeBaseId}/documents/${document.id}`
                                      )
                                    }
                                  >
                                    {document.filename}
                                  </button>
                                  <p className="mt-1 truncate text-xs text-muted-foreground">
                                    {t("创建时间")} ·{" "}
                                    {formatDateTime(
                                      document.created_at,
                                      locale
                                    )}
                                  </p>
                                  {document.last_error ? (
                                    <p className="mt-1 max-h-32 overflow-y-auto whitespace-pre-wrap break-words text-xs text-destructive [overflow-wrap:anywhere]">
                                      {getErrorMessage(new Error(document.last_error), t)}
                                    </p>
                                  ) : null}
                                </div>
                              </div>
                              <span className="inline-flex w-fit max-w-[132px] items-center gap-1.5 justify-self-center rounded-full border bg-background px-2.5 py-1 text-xs font-medium">
                                {PROCESSING_DOCUMENT_STATUSES[
                                  document.status
                                ] ? (
                                  <LoaderCircleIcon className="size-3.5 shrink-0 animate-spin text-primary" />
                                ) : (
                                  <span
                                    className={cn(
                                      "size-2 shrink-0 rounded-full",
                                      documentStatusDotClassName(
                                        document.status
                                      )
                                    )}
                                  />
                                )}
                                <span className="truncate">
                                  {documentStatusText(
                                    document,
                                    documentTasks,
                                    t
                                  )}
                                </span>
                              </span>
                              <span className="text-center text-muted-foreground">
                                {formatBytes(document.size_bytes)}
                              </span>
                              <span className="inline-flex w-fit min-w-8 items-center justify-center justify-self-center rounded-md bg-muted/60 px-2 py-1 text-xs font-semibold">
                                {document.chunk_count}
                              </span>
                              <span className="flex items-center justify-center gap-2">
                                <button
                                  type="button"
                                  role="switch"
                                  aria-checked={document.is_active}
                                  aria-label={t(
                                    document.is_active
                                      ? "停用 {value}"
                                      : "启用 {value}",
                                    { value: document.filename }
                                  )}
                                  disabled={
                                    !canEditDocuments ||
                                    isSubmittingDocumentTask
                                  }
                                  onClick={() =>
                                    void handleToggleDocumentActive(document)
                                  }
                                  className={cn(
                                    "relative h-5 w-9 cursor-pointer rounded-full transition-colors outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50",
                                    document.is_active
                                      ? "bg-primary"
                                      : "bg-muted-foreground/35"
                                  )}
                                >
                                  <span
                                    className={cn(
                                      "block size-4 rounded-full bg-background shadow-sm transition-transform",
                                      document.is_active
                                        ? "translate-x-[18px]"
                                        : "translate-x-0.5"
                                    )}
                                  />
                                </button>
                                <span className="text-xs text-muted-foreground">
                                  {t(document.is_active ? "已启用" : "已停用")}
                                </span>
                              </span>
                              <span className="text-center text-xs whitespace-nowrap text-muted-foreground">
                                {formatDateTime(document.updated_at, locale)}
                              </span>
                              <span className="flex items-center justify-center gap-0.5">
                                <Button
                                  type="button"
                                  variant="ghost"
                                  size="icon-sm"
                                  className="text-muted-foreground hover:text-foreground"
                                  disabled={
                                    !canEditDocuments ||
                                    isSubmittingDocumentTask
                                  }
                                  aria-label={t("重新分段 {value}", {
                                    value: document.filename,
                                  })}
                                  title={t("重新分段 {value}", {
                                    value: document.filename,
                                  })}
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
                                  className="text-muted-foreground hover:text-foreground"
                                  disabled={
                                    !canEditDocuments ||
                                    isSubmittingDocumentTask
                                  }
                                  aria-label={t("向量化 {value}", {
                                    value: document.filename,
                                  })}
                                  title={t("向量化 {value}", {
                                    value: document.filename,
                                  })}
                                  onClick={() =>
                                    void handleIndexDocuments([document])
                                  }
                                >
                                  <SlidersHorizontalIcon />
                                </Button>
                                {renderDocumentActionMenu(document)}
                              </span>
                            </div>
                          )
                        })
                      ) : (
                        <div className="flex min-h-56 flex-col items-center justify-center gap-2 px-3 py-10 text-sm text-muted-foreground">
                          <span className="flex size-10 items-center justify-center rounded-lg bg-muted/60">
                            <FileTextIcon className="size-4" />
                          </span>
                          {t(documentSummary.total ? "没有匹配的文档" : "暂无文档")}
                        </div>
                      )}
                    </div>
                  </div>
                  <PaginationFooter
                    total={documentTotal}
                    page={documentPage}
                    pageSize={documentPageSize}
                    onPageChange={setDocumentPage}
                    onPageSizeChange={(pageSize) => {
                      setDocumentPageSize(pageSize)
                      setDocumentPage(1)
                    }}
                  />
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
                                          .map((rule) =>
                                            t(
                                              CLEANING_RULE_OPTIONS.find(
                                                (option) =>
                                                  option.value === rule
                                              )?.labelKey ?? "去除行首尾空白"
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
                      variant="destructive"
                      disabled={
                        !canEditDocuments ||
                        selectedKnowledgeTasks.length === 0 ||
                        isKnowledgeTaskMutationBusy
                      }
                      onClick={() => void handleDeleteSelectedKnowledgeTasks()}
                    >
                      {isDeletingKnowledgeTasks ? (
                        <LoaderCircleIcon
                          className="animate-spin"
                          data-icon="inline-start"
                        />
                      ) : (
                        <Trash2Icon data-icon="inline-start" />
                      )}
                      {t("批量删除")}
                      {selectedKnowledgeTasks.length
                        ? `(${selectedKnowledgeTasks.length})`
                        : ""}
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
                  {isPhoneListLayout ? (
                    <ul className="flex flex-col gap-2 p-3">
                      {isKnowledgeTaskLoading ? (
                        <li className="flex min-h-40 items-center justify-center text-sm text-muted-foreground">
                          <LoaderCircleIcon className="animate-spin" />
                        </li>
                      ) : visibleKnowledgeTasks.length ? (
                        visibleKnowledgeTasks.map((task) => {
                          const isSelected = selectedKnowledgeTaskIds.includes(
                            task.id
                          )

                          return (
                            <li
                              key={task.id}
                              className={cn(
                                "rounded-xl border bg-background p-3",
                                isSelected &&
                                  "border-primary/50 bg-primary/[0.035]"
                              )}
                            >
                              <div className="flex items-start gap-3">
                                <label className="flex size-10 shrink-0 items-center justify-center">
                                  <input
                                    type="checkbox"
                                    className="size-4 accent-primary"
                                    aria-label={t("选择任务 {value}", {
                                      value: task.id,
                                    })}
                                    checked={isSelected}
                                    disabled={
                                      !canEditDocuments ||
                                      Boolean(
                                        PROCESSING_TASK_STATUSES[task.status]
                                      ) ||
                                      isKnowledgeTaskMutationBusy
                                    }
                                    onChange={(event) =>
                                      toggleKnowledgeTaskSelection(
                                        task.id,
                                        event.target.checked
                                      )
                                    }
                                  />
                                </label>
                                <div className="min-w-0 flex-1">
                                  <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm font-medium">
                                    {taskTypeLabel(task.task_type, t)}
                                    <span className="inline-flex items-center gap-1.5 text-xs font-normal text-muted-foreground">
                                      <span
                                        className={cn(
                                          "size-2.5 shrink-0 rounded-full",
                                          taskStatusDotClassName(task.status)
                                        )}
                                      />
                                      {taskStatusLabel(task.status, t)}
                                    </span>
                                  </p>
                                  <dl className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
                                    <div className="flex w-full min-w-0 items-center gap-1">
                                      <dt className="shrink-0">
                                        {t("关联文档")}
                                      </dt>
                                      <dd className="min-w-0 flex-1 text-foreground">
                                        {renderKnowledgeTaskDocument(task)}
                                      </dd>
                                    </div>
                                    <div className="flex items-center gap-1">
                                      <dt>{t("进度")}</dt>
                                      <dd className="font-semibold text-foreground">
                                        {task.processed_items}/
                                        {task.total_items}
                                      </dd>
                                    </div>
                                    <div className="flex items-center gap-1">
                                      <dt>{t("尝试次数")}</dt>
                                      <dd className="font-semibold text-foreground">
                                        {task.attempts}/{task.max_attempts}
                                      </dd>
                                    </div>
                                    <div className="flex items-center gap-1">
                                      <dt>{t("执行耗时")}</dt>
                                      <dd className="text-foreground tabular-nums">
                                        {taskDurationLabel(
                                          task,
                                          knowledgeTaskNow,
                                          t
                                        )}
                                      </dd>
                                    </div>
                                    <div className="flex w-full items-center gap-1">
                                      <dt className="shrink-0">
                                        {t("更新时间")}
                                      </dt>
                                      <dd className="min-w-0 truncate">
                                        {formatDateTime(
                                          task.updated_at,
                                          locale
                                        )}
                                      </dd>
                                    </div>
                                  </dl>
                                  {task.last_error ? (
                                    <p className="mt-2 text-xs break-words text-destructive">
                                      {getErrorMessage(new Error(task.last_error), t)}
                                    </p>
                                  ) : null}
                                </div>
                              </div>
                              <div className="mt-3 flex flex-wrap items-center justify-end gap-1 border-t pt-3">
                                {renderKnowledgeTaskActionMenu(task)}
                              </div>
                            </li>
                          )
                        })
                      ) : (
                        <li className="flex min-h-40 items-center justify-center p-3 text-sm text-muted-foreground">
                          {t("暂无任务")}
                        </li>
                      )}
                    </ul>
                  ) : null}
                  <div className="min-w-[1120px] max-md:hidden">
                    <div className="grid grid-cols-[44px_96px_minmax(180px,1fr)_104px_104px_96px_208px_136px_64px] items-center border-b px-4 py-3 text-sm font-medium text-muted-foreground">
                      <label className="flex items-center justify-center">
                        <input
                          ref={selectAllKnowledgeTasksRef}
                          type="checkbox"
                          className="size-4"
                          aria-label={t("选择所有可删除任务")}
                          checked={isAllVisibleKnowledgeTasksSelected}
                          disabled={
                            !canEditDocuments ||
                            !visibleDeletableKnowledgeTasks.length ||
                            isKnowledgeTaskMutationBusy
                          }
                          onChange={(event) =>
                            toggleAllVisibleKnowledgeTasks(event.target.checked)
                          }
                        />
                      </label>
                      <span>{t("类型")}</span>
                      <span>{t("关联文档")}</span>
                      <span>{t("状态")}</span>
                      <span>{t("进度")}</span>
                      <span>{t("尝试次数")}</span>
                      <span>{t("更新时间 / 错误")}</span>
                      <span>{t("执行耗时")}</span>
                      <span className="text-center">{t("操作")}</span>
                    </div>
                    {isKnowledgeTaskLoading ? (
                      <div className="flex min-h-48 items-center justify-center text-sm text-muted-foreground">
                        <LoaderCircleIcon className="animate-spin" />
                      </div>
                    ) : visibleKnowledgeTasks.length ? (
                      visibleKnowledgeTasks.map((task) => (
                        <div
                          key={task.id}
                          className="grid min-h-16 grid-cols-[44px_96px_minmax(180px,1fr)_104px_104px_96px_208px_136px_64px] items-center border-b px-4 py-3 text-sm last:border-b-0"
                        >
                          <label className="flex items-center justify-center">
                            <input
                              type="checkbox"
                              className="size-4"
                              aria-label={t("选择任务 {value}", {
                                value: task.id,
                              })}
                              checked={selectedKnowledgeTaskIds.includes(
                                task.id
                              )}
                              disabled={
                                !canEditDocuments ||
                                Boolean(
                                  PROCESSING_TASK_STATUSES[task.status]
                                ) ||
                                isKnowledgeTaskMutationBusy
                              }
                              onChange={(event) =>
                                toggleKnowledgeTaskSelection(
                                  task.id,
                                  event.target.checked
                                )
                              }
                            />
                          </label>
                          <span className="font-medium">
                            {taskTypeLabel(task.task_type, t)}
                          </span>
                          <span className="min-w-0 pr-4">
                            {renderKnowledgeTaskDocument(task)}
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
                          <span>
                            {task.processed_items}/{task.total_items}
                          </span>
                          <span>
                            {task.attempts}/{task.max_attempts}
                          </span>
                          <span className="min-w-0">
                            <span className="block truncate text-muted-foreground">
                              {formatDateTime(task.updated_at, locale)}
                            </span>
                            {task.last_error ? (
                              <span className="block max-h-32 overflow-y-auto whitespace-pre-wrap break-words text-xs text-destructive [overflow-wrap:anywhere]">
                                {getErrorMessage(new Error(task.last_error), t)}
                              </span>
                            ) : null}
                          </span>
                          <span className="tabular-nums">
                            {taskDurationLabel(task, knowledgeTaskNow, t)}
                          </span>
                          <span className="flex items-center justify-center">
                            {renderKnowledgeTaskActionMenu(task)}
                          </span>
                        </div>
                      ))
                    ) : (
                      <div className="flex min-h-48 items-center justify-center text-sm text-muted-foreground">
                        {t("暂无任务")}
                      </div>
                    )}
                  </div>
                  <PaginationFooter
                    total={knowledgeTaskTotal}
                    page={knowledgeTaskPage}
                    pageSize={knowledgeTaskPageSize}
                    onPageChange={setKnowledgeTaskPage}
                    onPageSizeChange={(pageSize) => {
                      setKnowledgeTaskPageSize(pageSize)
                      setKnowledgeTaskPage(1)
                    }}
                  />
                </div>
              </div>
            ) : null}

            {activeDetailTab === "evaluation" ? (
              <KnowledgeEvaluation
                token={token}
                workspaceId={selectedKnowledgeBase.workspace_id}
                knowledgeBaseId={selectedKnowledgeBase.id}
                documents={evaluationDocuments}
                canEdit={canEditDocuments}
                reportError={reportError}
                onMessage={notify}
              />
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
                        aria-busy={isTestingModels}
                        onClick={() => void handleTestKnowledgeModels()}
                      >
                        {isTestingModels ? (
                          <LoaderCircleIcon
                            data-icon="inline-start"
                            aria-hidden="true"
                            className="animate-spin motion-reduce:animate-none"
                          />
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
                        <p className="leading-6 break-words">
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
                              {t("{value} 维", {
                                value: modelTestResult.embedding_dimensions,
                              })}
                            </dd>
                          </div>
                          <div className="flex items-center gap-1.5">
                            <dt className="text-muted-foreground">Rerank</dt>
                            <dd className="font-medium">
                              {t("{value} 条", {
                                value: modelTestResult.reranker_results,
                              })}
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
        {confirmDialog}
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
        <ResourceFolderLayout
          sidebar={
            <ResourceFolderTree
              folders={resourceFolders.folders}
              selectedFolderId={resourceFolders.selectedFolderId}
              canManageAllFolders={me?.user.is_global_admin ?? false}
              currentUserId={me?.user.id ?? null}
              isLoading={resourceFolders.isLoading}
              onSelect={resourceFolders.setSelectedFolderId}
              onCreate={resourceFolders.create}
              onRename={resourceFolders.rename}
              onDelete={resourceFolders.remove}
              onFolderDeleted={(folderId, parentId) =>
                setKnowledgeBases((current) =>
                  current.map((knowledgeBase) =>
                    knowledgeBase.folder_id === folderId
                      ? { ...knowledgeBase, folder_id: parentId }
                      : knowledgeBase
                  )
                )
              }
            />
          }
        >
          <div className="flex flex-col gap-3 rounded-lg border bg-background p-3 shadow-sm sm:flex-row sm:items-center sm:justify-between">
            <div className="flex min-w-0 flex-col gap-2 sm:flex-row">
              <div className="relative min-w-0 sm:w-[320px]">
                <SearchIcon className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" />
                <Input
                  value={knowledgeSearch}
                  onChange={(event) => setKnowledgeSearch(event.target.value)}
                  placeholder={t("搜索{label}...", { label: t("知识库") })}
                  className="pl-9"
                />
              </div>
              <FilterDropdown
                ariaLabel={t("排序")}
                value={knowledgeBaseSortKey}
                options={[
                  { value: "updated_at", label: t("最近更新") },
                  { value: "created_at", label: t("创建时间") },
                  { value: "name", label: t("名称") },
                ]}
                className="h-9 sm:w-32"
                onChange={(value) =>
                  setKnowledgeBaseSortKey(value as KnowledgeBaseSortKey)
                }
              />
            </div>
            <ResourceBulkMoveBar
              resourceIds={movableKnowledgeBaseIds}
              selectedIds={selectedKnowledgeBaseIds}
              isManaging={isBatchManaging}
              onSelectedIdsChange={setSelectedKnowledgeBaseIds}
              onManagingChange={setIsBatchManaging}
              onMove={() => setIsBatchMoveOpen(true)}
            />
          </div>

          {isLoading ? (
            <div className="flex min-h-[220px] items-center justify-center rounded-lg border bg-background shadow-sm">
              <LoaderCircleIcon className="animate-spin text-muted-foreground" />
            </div>
          ) : knowledgeBases.length ? (
            <>
              {filteredKnowledgeBases.length ? (
                <div className={resourceCardGridClass}>
                  {filteredKnowledgeBases.map((knowledgeBase) => {
                    const selectable = knowledgeBase.permission === "edit"
                    const selected = selectedKnowledgeBaseIds.includes(
                      knowledgeBase.id
                    )

                    return (
                      <ResourceCard
                        key={knowledgeBase.id}
                        interactive
                        selected={selected}
                        pressed={
                          isBatchManaging && selectable ? selected : undefined
                        }
                        onActivate={() => {
                          if (isBatchManaging && selectable) {
                            setSelectedKnowledgeBaseIds((current) =>
                              toggleResourceSelection(current, knowledgeBase.id)
                            )
                            return
                          }
                          openKnowledgeBase(knowledgeBase)
                        }}
                      >
                        <ResourceCardHeader>
                          <div className="flex min-w-0 gap-3 max-sm:flex-1">
                            <ResourceCardIcon tone="blue">
                              <BookOpenTextIcon className="size-5" />
                            </ResourceCardIcon>
                            <div className="min-w-0 max-sm:flex-1">
                              <div className="flex flex-wrap items-center gap-2">
                                <ResourceCardTitle
                                  className="max-sm:w-full"
                                  title={knowledgeBase.name}
                                >
                                  {knowledgeBase.name}
                                </ResourceCardTitle>
                                <StatusBadge status={knowledgeBase.status} />
                                <PermissionBadge
                                  permission={knowledgeBase.permission}
                                />
                              </div>
                              <p
                                title={knowledgeBase.description}
                                className="mt-1 line-clamp-2 text-sm break-words text-muted-foreground"
                              >
                                {knowledgeBase.description || t("暂无描述")}
                              </p>
                              <ResourceCardMeta>
                                {t("创建者：{creator}", {
                                  creator:
                                    knowledgeBase.created_by_user_id ===
                                    me.user.id
                                      ? t("我")
                                      : formatUserIdentity(
                                          knowledgeBase.created_by_name,
                                          knowledgeBase.created_by_username,
                                          knowledgeBase.created_by_user_id
                                        ),
                                })}{" "}
                                ·{" "}
                                {formatDateTime(
                                  knowledgeBase.updated_at,
                                  locale
                                )}
                              </ResourceCardMeta>
                            </div>
                          </div>
                          {knowledgeBase.permission === "edit" ||
                          canManagePermissions(knowledgeBase) ? (
                            <ResourceCardActions>
                              {isBatchManaging && selectable ? (
                                <input
                                  type="checkbox"
                                  className="size-4 accent-primary"
                                  aria-label={t("选择 {value}", {
                                    value: knowledgeBase.name,
                                  })}
                                  checked={selected}
                                  onClick={(event) => event.stopPropagation()}
                                  onChange={(event) =>
                                    setSelectedKnowledgeBaseIds((current) =>
                                      event.target.checked
                                        ? [...current, knowledgeBase.id]
                                        : current.filter(
                                            (id) => id !== knowledgeBase.id
                                          )
                                    )
                                  }
                                />
                              ) : null}
                              {selectable ? (
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
                              <CardMoreMenu label={t("更多")}>
                                {selectable ? (
                                  <DropdownMenuItem
                                    onSelect={() =>
                                      setMoveKnowledgeBaseTarget(knowledgeBase)
                                    }
                                  >
                                    <FolderInputIcon />
                                    {t("移动到文件夹")}
                                  </DropdownMenuItem>
                                ) : null}
                                {canManagePermissions(knowledgeBase) ? (
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
                                {selectable &&
                                canManagePermissions(knowledgeBase) ? (
                                  <DropdownMenuSeparator />
                                ) : null}
                                {canManagePermissions(knowledgeBase) ? (
                                  <>
                                    <DropdownMenuItem
                                      onSelect={() =>
                                        void handleOpenPermissions(
                                          knowledgeBase
                                        )
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
                            </ResourceCardActions>
                          ) : null}
                        </ResourceCardHeader>
                        <ResourceCardFooter>
                          <ResourceCardSpecs>
                            <Spec
                              label={t("文档数")}
                              value={knowledgeBase.document_count.toLocaleString(
                                locale
                              )}
                            />
                            <Spec
                              label={t("字符数")}
                              value={`${(
                                knowledgeBase.char_count / 1_000
                              ).toLocaleString(locale, {
                                minimumFractionDigits: 1,
                                maximumFractionDigits: 1,
                              })}K`}
                            />
                          </ResourceCardSpecs>
                        </ResourceCardFooter>
                      </ResourceCard>
                    )
                  })}
                </div>
              ) : (
                <div className="rounded-lg border bg-background p-8 text-center text-sm text-muted-foreground shadow-sm">
                  {t("没有匹配的知识库")}
                </div>
              )}
              <div
                ref={knowledgeBasesListEndRef}
                className="flex min-h-12 items-center justify-center gap-2 py-3 text-sm text-muted-foreground"
              >
                {isKnowledgeBasesLoadingMore ? (
                  <>
                    <LoaderCircleIcon className="size-4 animate-spin" />
                    {t("正在加载")}
                  </>
                ) : knowledgeBases.length > 0 && !knowledgeBasesHasMore ? (
                  t("已加载全部")
                ) : null}
              </div>
            </>
          ) : (
            <div className="mx-auto flex min-h-[320px] max-w-xl flex-col items-center justify-center gap-4 p-6 text-center">
              <span className="flex size-14 items-center justify-center rounded-lg bg-muted">
                <Icon className="size-5 text-muted-foreground" />
              </span>
              <div className="flex flex-col gap-2">
                <p className="text-base font-semibold">{t("还没有知识库")}</p>
                <p className="text-sm leading-6 text-muted-foreground">
                  {t(
                    "创建知识库后，你可以上传文档、配置检索方式，并让应用调用这些知识。"
                  )}
                </p>
              </div>
              <Button type="button" onClick={() => setIsDialogOpen(true)}>
                <PlusIcon data-icon="inline-start" />
                {t("新建知识库")}
              </Button>
            </div>
          )}
        </ResourceFolderLayout>
      )}

      <ResourceFolderPickerDialog
        open={isBatchMoveOpen}
        folders={resourceFolders.folders}
        currentFolderId={resourceFolders.selectedFolderId}
        onOpenChange={setIsBatchMoveOpen}
        onMove={async (folderId) => {
          const resourceIds = selectedKnowledgeBaseIds.filter((id) =>
            movableKnowledgeBaseIds.includes(id)
          )
          await resourceFolders.moveMany(resourceIds, folderId)
          setKnowledgeBases((current) =>
            current.map((knowledgeBase) =>
              resourceIds.includes(knowledgeBase.id)
                ? { ...knowledgeBase, folder_id: folderId }
                : knowledgeBase
            )
          )
          setSelectedKnowledgeBaseIds([])
          setIsBatchManaging(false)
        }}
      />

      <ResourceFolderPickerDialog
        open={moveKnowledgeBaseTarget !== null}
        folders={resourceFolders.folders}
        currentFolderId={moveKnowledgeBaseTarget?.folder_id ?? null}
        onOpenChange={(open) => !open && setMoveKnowledgeBaseTarget(null)}
        onMove={async (folderId) => {
          if (!moveKnowledgeBaseTarget) return
          await resourceFolders.move(moveKnowledgeBaseTarget.id, folderId)
          setKnowledgeBases((current) =>
            current.map((knowledgeBase) =>
              knowledgeBase.id === moveKnowledgeBaseTarget.id
                ? { ...knowledgeBase, folder_id: folderId }
                : knowledgeBase
            )
          )
          setSelectedKnowledgeBaseIds((current) =>
            current.filter((id) => id !== moveKnowledgeBaseTarget.id)
          )
        }}
      />

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
      {confirmDialog}
    </>
  )
}
