import * as React from "react"
import {
  AlertCircleIcon,
  ArrowLeftIcon,
  CheckCircle2Icon,
  DatabaseIcon,
  FileSpreadsheetIcon,
  FileTextIcon,
  FilesIcon,
  FolderOpenIcon,
  LoaderCircleIcon,
  RotateCcwIcon,
  ScissorsIcon,
  type LucideIcon,
  UploadIcon,
  XIcon,
} from "lucide-react"
import { useLanguage } from "@/contexts/language-provider"
import { FilterDropdown } from "@/components/app/filter-dropdown"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Field,
  FieldDescription,
  FieldGroup,
  FieldLabel,
} from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import { getErrorMessage } from "@/lib/errors"
import type { AppNotification } from "@/lib/notifications"
import {
  createKnowledgeDocuments,
  deleteKnowledgeAttachment,
  deleteKnowledgeDocument,
  indexKnowledgeDocument,
  listKnowledgeDocumentChunks,
  listKnowledgeDocuments,
  listKnowledgeTasks,
  parseKnowledgeDocument,
  uploadKnowledgeAttachment,
} from "@/lib/api/knowledge"
import { ChunkPreviewList } from "@/components/knowledge/chunk-preview-list"
import { useKnowledgeUploadState } from "@/components/knowledge/knowledge-upload-state"
import { appendKnowledgeUploadFiles } from "./knowledge-upload-files"
import type {
  KnowledgeBase,
  KnowledgeDocument,
  KnowledgeDocumentChunk,
  KnowledgeSegmentationStrategy,
} from "@/lib/api/knowledge"
import type { TFunction, TranslationKey } from "@/i18n"
import {
  DEFAULT_KNOWLEDGE_UPLOAD_PARSE_SETTINGS,
  MAX_KNOWLEDGE_UPLOAD_DOCUMENTS,
  type KnowledgeImportMode,
  type KnowledgeUploadParseSettings,
  type KnowledgeUploadRouteState,
  type KnowledgeUploadStep,
} from "@/lib/knowledge-upload-route"
import { cn } from "@/lib/utils"
import { formatBytes } from "@/components/knowledge/status-labels"

export { appendKnowledgeUploadFiles }

type SegmentMode = KnowledgeUploadParseSettings["segmentMode"]

type UploadedDocument = KnowledgeDocument & {
  chunks: KnowledgeDocumentChunk[]
}

/**
 * Keeps the selected document ID valid for the available documents.
 *
 * @param documents - The documents available for selection
 * @param selectedDocumentId - The currently selected document ID
 * @returns The selected ID when it exists, the first document's ID when it does not, or `null` when no documents are available
 */
export function resolveSelectedDocumentId(
  documents: ReadonlyArray<{ id: string }>,
  selectedDocumentId: string | null,
) {
  return documents.some((document) => document.id === selectedDocumentId)
    ? selectedDocumentId
    : (documents[0]?.id ?? null)
}

const UNPARSED_STATUS = "uploaded"
const PARSING_STATUSES: Record<string, true> = {
  parse_queued: true,
  parsing: true,
}
const UNINDEXED_STATUSES: Record<string, true> = {
  uploaded: true,
  parse_queued: true,
  parsing: true,
  parsed: true,
  parse_failed: true,
}
export const SUPPORTED_FILE_TYPES = [
  ".docx",
  ".md",
  ".markdown",
  ".pdf",
  ".txt",
  ".pptx",
  ".xlsx",
  ".xls",
  ".html",
  ".csv",
  ".json",
  ".xml",
  ".ipynb",
  ".epub",
  ".zip",
  ".png",
  ".jpg",
  ".jpeg",
  ".webp",
]
export const QA_FILE_TYPES = [".csv", ".xlsx"]
const SMART_CHUNK_SIZE = DEFAULT_KNOWLEDGE_UPLOAD_PARSE_SETTINGS.chunkSize
const SMART_CHUNK_OVERLAP =
  DEFAULT_KNOWLEDGE_UPLOAD_PARSE_SETTINGS.chunkOverlap
const SMART_CLEANING_RULES =
  DEFAULT_KNOWLEDGE_UPLOAD_PARSE_SETTINGS.cleaningRules
const SMART_SPLIT_SEPARATOR =
  DEFAULT_KNOWLEDGE_UPLOAD_PARSE_SETTINGS.splitSeparator

/**
 * Manages the file selection, segmentation preview, and knowledge base import workflow.
 *
 * @param token - Authentication token used for knowledge base operations
 * @param workspaceId - Workspace containing the knowledge base
 * @param knowledgeBase - Knowledge base receiving the imported documents
 * @param step - Current step of the upload workflow
 * @param routeState - Optional state used to restore an in-progress import
 * @param onCancel - Called when the workflow is cancelled
 * @param onRouteSegment - Called when transitioning to or updating the segmentation step
 * @param onBackToFiles - Called when returning to file selection
 * @param onDone - Called after documents are successfully submitted for indexing
 * @param onNotify - Reports workflow success and error messages
 */
export function KnowledgeUploadFlow({
  token,
  workspaceId,
  knowledgeBase,
  step,
  routeState,
  onCancel,
  onRouteSegment,
  onBackToFiles,
  onDone,
  onNotify,
}: {
  token: string
  workspaceId: string
  knowledgeBase: KnowledgeBase
  step: KnowledgeUploadStep
  routeState?: KnowledgeUploadRouteState
  onCancel: () => void
  onRouteSegment: (routeState: KnowledgeUploadRouteState) => void
  onBackToFiles: () => void
  onDone: () => void | Promise<void>
  onNotify: (kind: AppNotification["kind"], message: string) => void
}) {
  const { t } = useLanguage()
  const { files, setFiles, prepareUpload, startUpload } =
    useKnowledgeUploadState()
  const cleaningRuleOptions = [
    { value: "trim_lines", label: t("去除行首尾空白") },
    { value: "remove_empty_lines", label: t("删除空行") },
    { value: "collapse_spaces", label: t("合并连续空白") },
  ]
  const splitSeparatorOptions = [
    { value: "\n\n", label: t("空行（段落）") },
    { value: "\n", label: t("换行") },
    { value: "。", label: t("中文句号（。）") },
    { value: ".", label: t("英文句号（.）") },
  ]
  const [uploadedDocuments, setUploadedDocuments] = React.useState<
    UploadedDocument[]
  >([])
  const [selectedDocumentId, setSelectedDocumentId] = React.useState<
    string | null
  >(null)
  const [importMode, setImportMode] = React.useState<KnowledgeImportMode>(
    routeState?.importMode ?? "document",
  )
  const [segmentMode, setSegmentMode] = React.useState<SegmentMode>(
    routeState?.parseSettings.segmentMode ?? "smart",
  )
  const [chunkSize, setChunkSize] = React.useState(
    routeState?.parseSettings.chunkSize ?? SMART_CHUNK_SIZE,
  )
  const [chunkOverlap, setChunkOverlap] = React.useState(
    routeState?.parseSettings.chunkOverlap ?? SMART_CHUNK_OVERLAP,
  )
  const [cleaningRules, setCleaningRules] = React.useState<string[]>(() => [
    ...(routeState?.parseSettings.cleaningRules ?? SMART_CLEANING_RULES),
  ])
  const [splitSeparator, setSplitSeparator] = React.useState(
    routeState?.parseSettings.splitSeparator ?? SMART_SPLIT_SEPARATOR,
  )
  const [previewOptionsSignature, setPreviewOptionsSignature] = React.useState<
    string | null
  >(null)
  const [isDragActive, setIsDragActive] = React.useState(false)
  const [isUploading, setIsUploading] = React.useState(false)
  const [isParsing, setIsParsing] = React.useState(false)
  const [isRefreshing, setIsRefreshing] = React.useState(false)
  const [isIndexing, setIsIndexing] = React.useState(false)
  const [deletingDocumentId, setDeletingDocumentId] = React.useState<
    string | null
  >(null)
  const fileInputRef = React.useRef<HTMLInputElement>(null)
  const folderInputRef = React.useRef<HTMLInputElement>(null)

  React.useEffect(() => {
    folderInputRef.current?.setAttribute("webkitdirectory", "")
  }, [])

  const totalChunks = uploadedDocuments.reduce(
    (count, document) => count + document.chunks.length,
    0,
  )
  const selectedDocument =
    uploadedDocuments.find((document) => document.id === selectedDocumentId) ??
    uploadedDocuments[0] ??
    null
  const selectedFileBytes = files.reduce((total, file) => total + file.size, 0)
  const supportedFileTypes =
    importMode === "qa" ? QA_FILE_TYPES : SUPPORTED_FILE_TYPES
  const supportedFileTypesLabel = supportedFileTypes.map((extension) =>
    extension.slice(1).toUpperCase(),
  ).join(t("列表分隔符"))
  const hasPendingParsing = uploadedDocuments.some((document) =>
    document.status in PARSING_STATUSES,
  )
  const hasUnpreviewedDocuments = uploadedDocuments.some(
    (document) =>
      document.status === UNPARSED_STATUS ||
      document.status in PARSING_STATUSES,
  )
  const hasFailedParsing = uploadedDocuments.some((document) =>
    document.status.endsWith("_failed"),
  )
  const isPreviewRunning = isUploading || isParsing || hasPendingParsing
  const isNavigationLocked =
    isRefreshing ||
    isPreviewRunning ||
    isIndexing ||
    deletingDocumentId !== null
  const isSegmentInvalid =
    importMode === "document" &&
    segmentMode === "advanced" &&
    chunkOverlap >= chunkSize

  const reportError = React.useCallback(
    (error: unknown) => {
      onNotify("error", getErrorMessage(error, t))
    },
    [onNotify, t],
  )

  const loadPreviewDocuments = React.useCallback(
    async (documentIds: string[]) => {
      const documents = await listKnowledgeDocuments(
        token,
        workspaceId,
        knowledgeBase.id,
        { includeStaged: true },
      )
      const documentsById = new Map(
        documents.map((document) => [document.id, document]),
      )
      const loadedDocuments = await Promise.all(
        documentIds.map(async (documentId) => {
          const document = documentsById.get(documentId)
          if (!document) {
            return null
          }
          const chunks = await listKnowledgeDocumentChunks(
            token,
            workspaceId,
            knowledgeBase.id,
            documentId,
          )
          return { ...document, chunks }
        }),
      )
      return loadedDocuments.filter(
        (document): document is UploadedDocument => document !== null,
      )
    },
    [knowledgeBase.id, token, workspaceId],
  )

  const applyPreviewDocuments = React.useCallback(
    (nextDocuments: UploadedDocument[]) => {
      setUploadedDocuments(nextDocuments)
      setSelectedDocumentId((current) =>
        resolveSelectedDocumentId(nextDocuments, current),
      )
    },
    [],
  )

  function chooseFiles(nextFiles: File[]) {
    if (!nextFiles.length) {
      return
    }

    const supportedFiles = nextFiles.filter((file) =>
      supportedFileTypes.some((extension) =>
        file.name.toLowerCase().endsWith(extension),
      ),
    )
    const limitedFiles = appendKnowledgeUploadFiles(files, supportedFiles)
    setFiles((current) => appendKnowledgeUploadFiles(current, supportedFiles))
    if (supportedFiles.length !== nextFiles.length) {
      onNotify("error", t("已忽略不支持的文件格式"))
    }
    if (limitedFiles.length < files.length + supportedFiles.length) {
      onNotify(
        "error",
        t("队列最多保留 {value} 个文件", {
          value: MAX_KNOWLEDGE_UPLOAD_DOCUMENTS,
        }),
      )
    }
  }

  function removeFile(indexToRemove: number) {
    setFiles((current) => current.filter((_, index) => index !== indexToRemove))
  }

  function changeImportMode(nextMode: KnowledgeImportMode) {
    setImportMode(nextMode)
    setFiles([])
    if (fileInputRef.current) {
      fileInputRef.current.value = ""
    }
    if (folderInputRef.current) {
      folderInputRef.current.value = ""
    }
  }

  function currentParseSettings(): KnowledgeUploadParseSettings {
    return importMode === "qa" || segmentMode === "smart"
      ? {
          ...DEFAULT_KNOWLEDGE_UPLOAD_PARSE_SETTINGS,
          cleaningRules: [...SMART_CLEANING_RULES],
        }
      : {
          segmentMode,
          chunkSize,
          chunkOverlap,
          splitSeparator,
          cleaningRules,
        }
  }

  const currentParseOptionsSignature = JSON.stringify(currentParseSettings())
  const hasStalePreview =
    previewOptionsSignature !== currentParseOptionsSignature
  const canStartIndex =
    uploadedDocuments.length > 0 &&
    !hasUnpreviewedDocuments &&
    !hasFailedParsing &&
    !hasStalePreview &&
    uploadedDocuments.every(
      (document) => document.status === "parsed" && document.chunks.length > 0,
    )

  const generatePreviewForDocuments = React.useCallback(async (
    documents: UploadedDocument[],
    parseSettings: KnowledgeUploadParseSettings,
    resumeExisting = false,
  ) => {
    if (
      !documents.length ||
      (parseSettings.segmentMode === "advanced" &&
        parseSettings.chunkOverlap >= parseSettings.chunkSize)
    ) {
      return
    }

    setIsParsing(true)
    const documentsToEnqueue = resumeExisting
      ? documents.filter((document) => document.status === UNPARSED_STATUS)
      : documents
    const existingPendingDocumentIds = resumeExisting
      ? documents
          .filter((document) => document.status in PARSING_STATUSES)
          .map((document) => document.id)
      : []
    const previewDocumentIds = new Set([
      ...documentsToEnqueue.map((document) => document.id),
      ...existingPendingDocumentIds,
    ])
    applyPreviewDocuments(
      documents.map((document) =>
        previewDocumentIds.has(document.id)
          ? {
              ...document,
              status: "parsing",
              last_error: null,
              chunks: [],
            }
          : document,
      ),
    )
    try {
      const parseOptionsSignature = JSON.stringify(parseSettings)
      const parsePayload = {
        strategy: (parseSettings.segmentMode === "smart"
          ? "hierarchical"
          : "flat") as KnowledgeSegmentationStrategy,
        chunk_size: parseSettings.chunkSize,
        chunk_overlap: parseSettings.chunkOverlap,
        split_separator: parseSettings.splitSeparator,
        cleaning_rules: parseSettings.cleaningRules,
        auto_index: false,
      }
      const enqueueResults = await Promise.allSettled(
        documentsToEnqueue.map((document) =>
          parseKnowledgeDocument(
            token,
            workspaceId,
            knowledgeBase.id,
            document.id,
            parsePayload,
          ),
        ),
      )
      const taskIdByDocumentId = new Map<string, string>()
      const failedAtEnqueue: UploadedDocument[] = []
      documentsToEnqueue.forEach((document, index) => {
        const result = enqueueResults[index]
        if (result?.status === "fulfilled") {
          taskIdByDocumentId.set(document.id, result.value.id)
        } else {
          failedAtEnqueue.push({
            ...document,
            status: "parse_failed",
            last_error: getErrorMessage(result?.reason, t),
            chunks: [],
          })
        }
      })

      const nextDocuments = [...documents]
      let remainingDocumentIds = new Set([
        ...existingPendingDocumentIds,
        ...taskIdByDocumentId.keys(),
      ])
      const startedAt = Date.now()
      const PARSE_POLL_INTERVAL_MS = 2000
      const PARSE_TIMEOUT_MS = 5 * 60 * 1000
      while (remainingDocumentIds.size > 0) {
        await new Promise((resolve) =>
          window.setTimeout(resolve, PARSE_POLL_INTERVAL_MS),
        )
        if (Date.now() - startedAt > PARSE_TIMEOUT_MS) {
          for (const documentId of remainingDocumentIds) {
            const index = documents.findIndex(
              (document) => document.id === documentId,
            )
            if (index >= 0) {
              nextDocuments[index] = {
                ...documents[index],
                status: "parse_failed",
                last_error: t("分段超时"),
                chunks: [],
              }
            }
          }
          break
        }

        const taskResults = await Promise.allSettled(
          [...remainingDocumentIds].map((documentId) =>
            listKnowledgeTasks(
              token,
              workspaceId,
              knowledgeBase.id,
              documentId,
            ),
          ),
        )
        const documentIds = [...remainingDocumentIds]
        const stillPending: string[] = []
        documentIds.forEach((documentId, index) => {
          const result = taskResults[index]
          const task = result?.status === "fulfilled" ? result.value[0] : null
          const documentIndex = documents.findIndex(
            (document) => document.id === documentId,
          )
          if (documentIndex < 0) {
            return
          }
          if (task?.status === "succeeded") {
            nextDocuments[documentIndex] = {
              ...documents[documentIndex],
              status: "parsed",
              last_error: null,
              chunks: [],
            }
          } else if (task?.status === "failed") {
            nextDocuments[documentIndex] = {
              ...documents[documentIndex],
              status: "parse_failed",
              last_error: task.last_error || t("分段失败"),
              chunks: [],
            }
          } else {
            stillPending.push(documentId)
          }
        })
        remainingDocumentIds = new Set(stillPending)
      }

      // Load chunks for every parsed document.
      await Promise.all(
        nextDocuments.map(async (document, index) => {
          if (document.status !== "parsed") {
            return
          }
          try {
            nextDocuments[index] = {
              ...document,
              chunks: await listKnowledgeDocumentChunks(
                token,
                workspaceId,
                knowledgeBase.id,
                document.id,
              ),
            }
          } catch (error) {
            nextDocuments[index] = {
              ...document,
              status: "parse_failed",
              last_error: getErrorMessage(error, t),
              chunks: [],
            }
          }
        }),
      )

      for (const failed of failedAtEnqueue) {
        const index = nextDocuments.findIndex(
          (document) => document.id === failed.id,
        )
        if (index >= 0) {
          nextDocuments[index] = failed
        }
      }

      applyPreviewDocuments(nextDocuments)
      setPreviewOptionsSignature(parseOptionsSignature)

      const failedDocuments = nextDocuments.filter(
        (document) => document.status === "parse_failed",
      )
      if (failedDocuments.length) {
        onNotify(
          "error",
          failedDocuments.length === 1
            ? t("{value} 分段失败", {
                value: failedDocuments[0].filename,
              })
            : t("{value} 个文档分段失败", {
                value: failedDocuments.length,
              }),
        )
        return
      }

      const emptyPreviewDocuments = nextDocuments.filter(
        (document) => !document.chunks.length,
      )
      if (emptyPreviewDocuments.length) {
        onNotify(
          "error",
          emptyPreviewDocuments.length === 1
            ? t("{value} 未返回分段片段", {
                value: emptyPreviewDocuments[0].filename,
              })
            : t("{value} 个文档未返回分段片段", {
                value: emptyPreviewDocuments.length,
              }),
        )
        return
      }

      onNotify("success", t("已生成分段预览"))
    } catch (error) {
      reportError(error)
    } finally {
      setIsParsing(false)
    }
  }, [
    applyPreviewDocuments,
    knowledgeBase.id,
    onNotify,
    reportError,
    t,
    token,
    workspaceId,
  ])

  const refreshPreview = React.useCallback(async () => {
    const documentIds = uploadedDocuments.length
      ? uploadedDocuments.map((document) => document.id)
      : (routeState?.documentIds ?? [])
    if (!documentIds.length) {
      return
    }

    setIsRefreshing(true)
    try {
      const nextDocuments = await loadPreviewDocuments(documentIds)
      applyPreviewDocuments(nextDocuments)
      if (!routeState) {
        return
      }
      if (
        nextDocuments.every(
          (document) =>
            document.status === "parsed" && document.chunks.length > 0,
        )
      ) {
        setPreviewOptionsSignature(JSON.stringify(routeState.parseSettings))
      } else if (
        nextDocuments.some(
          (document) =>
            document.status === UNPARSED_STATUS ||
            document.status in PARSING_STATUSES,
        )
      ) {
        await generatePreviewForDocuments(
          nextDocuments,
          routeState.parseSettings,
          true,
        )
      }
    } catch (error) {
      reportError(error)
    } finally {
      setIsRefreshing(false)
    }
  }, [
    applyPreviewDocuments,
    generatePreviewForDocuments,
    loadPreviewDocuments,
    reportError,
    routeState,
    uploadedDocuments,
  ])

  React.useEffect(() => {
    if (step !== "segment") {
      return
    }
    if (!routeState) {
      onBackToFiles()
      return
    }

    let cancelled = false

    if (!routeState.documentIds.length) {
      const upload = startUpload()
      if (!upload) {
        onBackToFiles()
        return
      }

      // eslint-disable-next-line react-hooks/set-state-in-effect
      setIsUploading(true)
      void upload
        .then((documents) => {
          if (cancelled) {
            return
          }
          if (!documents.length) {
            onBackToFiles()
            return
          }

          const nextDocuments = documents.map((document) => ({
            ...document,
            chunks: [],
          }))
          applyPreviewDocuments(nextDocuments)
          setPreviewOptionsSignature(null)
          setIsUploading(false)
          onRouteSegment({
            documentIds: nextDocuments.map((document) => document.id),
            parseSettings: routeState.parseSettings,
            importMode,
          })
        })
        .catch((error) => {
          if (!cancelled) {
            reportError(error)
            onBackToFiles()
          }
        })
        .finally(() => {
          if (!cancelled) {
            setIsUploading(false)
          }
        })

      return () => {
        cancelled = true
      }
    }

    const routeSignature = JSON.stringify(routeState.parseSettings)
    setIsRefreshing(true)

    void loadPreviewDocuments(routeState.documentIds)
      .then(async (nextDocuments) => {
        if (cancelled) {
          return
        }
        if (!nextDocuments.length) {
          onBackToFiles()
          return
        }

        applyPreviewDocuments(nextDocuments)
        if (
          nextDocuments.every(
            (document) =>
              document.status === "parsed" && document.chunks.length > 0,
          )
        ) {
          setPreviewOptionsSignature(routeSignature)
          return
        }
        if (
          nextDocuments.some(
            (document) =>
              document.status === UNPARSED_STATUS ||
              document.status in PARSING_STATUSES,
          )
        ) {
          await generatePreviewForDocuments(
            nextDocuments,
            routeState.parseSettings,
            true,
          )
        }
      })
      .catch(reportError)
      .finally(() => {
        if (!cancelled) {
          setIsRefreshing(false)
        }
      })

    return () => {
      cancelled = true
    }
  }, [
    applyPreviewDocuments,
    generatePreviewForDocuments,
    importMode,
    loadPreviewDocuments,
    onBackToFiles,
    onRouteSegment,
    reportError,
    routeState,
    startUpload,
    step,
  ])

  async function discardStagedDocuments() {
    const pendingDocuments = uploadedDocuments.filter((document) =>
      document.meta.staged === true && document.status in UNINDEXED_STATUSES,
    )
    const documentResults = await Promise.allSettled(
      pendingDocuments.map((document) =>
        deleteKnowledgeDocument(
          token,
          workspaceId,
          knowledgeBase.id,
          document.id,
        ),
      ),
    )
    const deletedIds = new Set(
      pendingDocuments
        .filter((_, index) => documentResults[index]?.status === "fulfilled")
        .map((document) => document.id),
    )
    setUploadedDocuments((current) =>
      current.filter((document) => !deletedIds.has(document.id)),
    )
    const firstFailure = documentResults.find(
      (result) => result.status === "rejected",
    )
    if (firstFailure?.status === "rejected") {
      reportError(firstFailure.reason)
      return false
    }
    return true
  }

  async function handleRemoveDocument(document: UploadedDocument) {
    if (
      isNavigationLocked ||
      document.meta.staged !== true ||
      !(document.status in UNINDEXED_STATUSES)
    ) {
      return
    }

    setDeletingDocumentId(document.id)
    try {
      await deleteKnowledgeDocument(
        token,
        workspaceId,
        knowledgeBase.id,
        document.id,
      )
      const nextDocuments = uploadedDocuments.filter(
        (item) => item.id !== document.id,
      )
      applyPreviewDocuments(nextDocuments)
      if (nextDocuments.length) {
        onRouteSegment({
          documentIds: nextDocuments.map((item) => item.id),
          parseSettings: routeState?.parseSettings ?? currentParseSettings(),
          importMode,
        })
      } else {
        setFiles([])
        onBackToFiles()
      }
    } catch (error) {
      reportError(error)
    } finally {
      setDeletingDocumentId(null)
    }
  }

  async function handleCancel() {
    if (isNavigationLocked || !(await discardStagedDocuments())) {
      return
    }
    onCancel()
  }

  async function handleBackToFiles() {
    if (isNavigationLocked || !(await discardStagedDocuments())) {
      return
    }
    onBackToFiles()
  }

  function handleNext() {
    if (!files.length) {
      return
    }

    prepareUpload(uploadPendingFiles)
    onRouteSegment({
      documentIds: [],
      parseSettings: currentParseSettings(),
      importMode,
    })
  }

  async function uploadPendingFiles() {
    if (!files.length) {
      return []
    }

    const uploadResults = await Promise.allSettled(
      files.map((file) =>
        uploadKnowledgeAttachment(token, workspaceId, knowledgeBase.id, file),
      ),
    )
    const attachments = uploadResults.flatMap((result) =>
      result.status === "fulfilled" ? [result.value] : [],
    )
    const failedCount = uploadResults.length - attachments.length
    const firstFailure = uploadResults.find(
      (result) => result.status === "rejected",
    )
    if (!attachments.length) {
      if (firstFailure?.status === "rejected") {
        reportError(firstFailure.reason)
      }
      return []
    }

    try {
      const documents = await createKnowledgeDocuments(
        token,
        workspaceId,
        knowledgeBase.id,
        attachments.map((attachment) => attachment.id),
        true,
        importMode,
      )
      const consumedAttachmentIds = new Set(
        documents
          .map((document) => document.attachment_id)
          .filter((attachmentId): attachmentId is string => attachmentId !== null),
      )
      await Promise.allSettled(
        attachments
          .filter((attachment) => !consumedAttachmentIds.has(attachment.id))
          .map((attachment) =>
            deleteKnowledgeAttachment(
              token,
              workspaceId,
              knowledgeBase.id,
              attachment.id,
            ),
          ),
      )

      if (failedCount) {
        onNotify(
          "error",
          t("已上传 {uploaded} 个文件，{failed} 个上传失败", {
            uploaded: documents.length,
            failed: failedCount,
          }),
        )
      }
      return documents.map((document) => ({ ...document, chunks: [] }))
    } catch (error) {
      await Promise.allSettled(
        attachments.map((attachment) =>
          deleteKnowledgeAttachment(
            token,
            workspaceId,
            knowledgeBase.id,
            attachment.id,
          ),
        ),
      )
      reportError(error)
      return []
    }
  }

  async function handleGeneratePreview() {
    if (!uploadedDocuments.length || isSegmentInvalid) {
      return
    }

    const parseSettings = currentParseSettings()
    await generatePreviewForDocuments(uploadedDocuments, parseSettings)
    onRouteSegment({
      documentIds: uploadedDocuments.map((document) => document.id),
      parseSettings,
      importMode,
    })
  }

  async function handleStartImport() {
    if (!canStartIndex) {
      return
    }

    setIsIndexing(true)
    try {
      const results = await Promise.allSettled(
        uploadedDocuments.map((document) =>
          indexKnowledgeDocument(
            token,
            workspaceId,
            knowledgeBase.id,
            document.id,
          ),
        ),
      )
      const succeededCount = results.filter(
        (result) => result.status === "fulfilled",
      ).length
      const failedCount = results.length - succeededCount
      const firstFailure = results.find(
        (result) => result.status === "rejected",
      )

      if (!succeededCount) {
        if (firstFailure?.status === "rejected") {
          reportError(firstFailure.reason)
        }
        return
      }

      onNotify(
        failedCount ? "error" : "success",
        failedCount
          ? t("已提交 {submitted} 个向量化任务，{failed} 个提交失败", {
              submitted: succeededCount,
              failed: failedCount,
            })
          : t("已提交 {value} 个向量化任务", { value: succeededCount }),
      )
      await onDone()
    } catch (error) {
      reportError(error)
    } finally {
      setIsIndexing(false)
    }
  }

  function toggleCleaningRule(rule: string, checked: boolean) {
    setCleaningRules((current) =>
      checked
        ? current.includes(rule)
          ? current
          : [...current, rule]
        : current.filter((item) => item !== rule),
    )
  }

  return (
    <div className="-mx-4 flex min-h-[calc(100svh-6.5rem)] flex-col bg-muted/20 sm:-mx-6 lg:-mx-8">
      <header>
        <div className="mx-auto flex w-full max-w-[90rem] items-center px-4 py-1 sm:px-6 lg:px-8">
          <div className="flex min-w-0 items-center gap-3">
            <Button
              type="button"
              variant="ghost"
              size="icon-sm"
              aria-label={t("返回知识库")}
              disabled={isNavigationLocked}
              onClick={() => void handleCancel()}
            >
              <ArrowLeftIcon />
            </Button>
            <div className="min-w-0">
              <p className="text-xs font-medium text-muted-foreground">
                {t("知识库导入")}
              </p>
              <h1 className="truncate text-xl font-semibold text-foreground">
                {knowledgeBase.name}
              </h1>
            </div>
          </div>
        </div>
      </header>

      {step === "files" ? (
        <>
          <div className="mx-auto w-full max-w-[90rem] px-4 py-5 sm:px-6 lg:px-8">
            <main className="min-w-0 space-y-5">
              <section className="overflow-hidden rounded-lg border bg-background shadow-sm">
                <div className="flex flex-col gap-4 border-b px-5 py-4 sm:flex-row sm:items-center sm:justify-between">
                  <SectionTitle
                    icon={UploadIcon}
                    title={t("选择导入文件")}
                    description={
                      importMode === "qa"
                        ? t("每行问答生成一个检索片段；仅支持 CSV 和 XLSX。")
                        : t("先确认分段效果，点击开始导入后才会写入知识库。")
                    }
                  />
                  <div className="flex shrink-0 items-center gap-2 text-sm font-medium">
                    <span>{t("导入类型")}</span>
                    <FilterDropdown
                      ariaLabel={t("导入类型")}
                      className="h-9 min-w-28 px-3"
                      value={importMode}
                      options={[
                        { value: "document", label: t("普通文档") },
                        { value: "qa", label: t("问答表") },
                      ]}
                      onChange={(value) =>
                        changeImportMode(value as KnowledgeImportMode)
                      }
                    />
                  </div>
                </div>

                <div
                  className={cn(
                    "m-5 flex min-h-[360px] flex-col items-center justify-center rounded-lg border border-dashed px-6 py-10 text-center transition-colors",
                    isDragActive
                      ? "border-primary bg-primary/5"
                      : "border-border bg-muted/20 hover:bg-muted/30",
                  )}
                  onDragOver={(event) => {
                    event.preventDefault()
                    setIsDragActive(true)
                  }}
                  onDragLeave={() => setIsDragActive(false)}
                  onDrop={(event) => {
                    event.preventDefault()
                    setIsDragActive(false)
                    chooseFiles(Array.from(event.dataTransfer.files))
                  }}
                >
                  <input
                    ref={fileInputRef}
                    type="file"
                    accept={supportedFileTypes.join(",")}
                    multiple
                    className="hidden"
                    onChange={(event) =>
                      chooseFiles(Array.from(event.target.files ?? []))
                    }
                  />
                  <input
                    ref={folderInputRef}
                    type="file"
                    accept={supportedFileTypes.join(",")}
                    multiple
                    className="hidden"
                    onChange={(event) =>
                      chooseFiles(Array.from(event.target.files ?? []))
                    }
                  />
                  <span className="flex size-14 items-center justify-center rounded-lg border bg-background shadow-sm">
                    <UploadIcon className="size-6 text-primary" />
                  </span>
                  <div className="mt-5 space-y-2">
                    <p className="text-lg font-semibold text-foreground">
                      {importMode === "qa"
                        ? t("拖入 CSV 或 XLSX 文件")
                        : t("拖入文件或文件夹")}
                    </p>
                    <p className="mx-auto max-w-xl text-sm leading-6 text-muted-foreground">
                      {importMode === "qa"
                        ? t(
                            "CSV/XLSX 需包含 question/问题、answer/答案，可选 source/来源 列。",
                          )
                        : t(
                            "保留文档标题和段落结构，表格会在预览阶段转换为 Markdown。",
                          )}
                    </p>
                    <p className="mx-auto max-w-3xl text-xs leading-5 text-muted-foreground">
                      {t("支持格式：{value}", {
                        value: supportedFileTypesLabel,
                      })}
                    </p>
                  </div>
                  <div className="mt-6 flex flex-wrap items-center justify-center gap-2">
                    <Button
                      type="button"
                      onClick={() => fileInputRef.current?.click()}
                    >
                      <FilesIcon data-icon="inline-start" />
                      {t("选择文件")}
                    </Button>
                    {importMode === "document" ? (
                      <Button
                        type="button"
                        variant="outline"
                        onClick={() => folderInputRef.current?.click()}
                      >
                        <FolderOpenIcon data-icon="inline-start" />
                        {t("选择文件夹")}
                      </Button>
                    ) : null}
                  </div>
                </div>
              </section>

              <FileList files={files} onRemove={removeFile} />
            </main>
          </div>

          <div className="sticky bottom-4 z-10 mt-auto">
            <div className="mx-auto w-full max-w-[90rem] px-4 sm:px-6 lg:px-8">
              <div className="flex flex-col gap-3 rounded-lg border bg-background/95 px-4 py-3 shadow-sm backdrop-blur sm:flex-row sm:items-center sm:justify-between">
                <p className="text-sm text-muted-foreground">
                  {files.length
                    ? t("已选择 {count} 个文件，合计 {size}", {
                        count: files.length,
                        size: formatBytes(selectedFileBytes),
                      })
                    : t("等待选择文件")}
                </p>
                <div className="flex flex-wrap justify-end gap-2">
                  <Button
                    type="button"
                    variant="outline"
                    disabled={isNavigationLocked}
                    onClick={() => void handleCancel()}
                  >
                    {t("取消")}
                  </Button>
                  <Button
                    type="button"
                    disabled={!files.length}
                    onClick={handleNext}
                  >
                    <UploadIcon data-icon="inline-start" />
                    {t("下一步")}
                  </Button>
                </div>
              </div>
            </div>
          </div>
        </>
      ) : (
        <>
          <div className="mx-auto grid w-full max-w-[90rem] gap-4 px-4 py-5 sm:px-6 lg:h-[calc(100svh-17rem)] lg:min-h-[34rem] lg:grid-cols-[18rem_minmax(0,1fr)] lg:px-8 xl:grid-cols-[19rem_minmax(0,1fr)]">
            <aside className="space-y-4 lg:min-h-0 lg:overflow-y-auto lg:pr-1">
              <section className="rounded-lg border bg-background p-4 shadow-sm">
                <SectionTitle
                  icon={importMode === "qa" ? FileSpreadsheetIcon : ScissorsIcon}
                  title={importMode === "qa" ? t("问答导入") : t("分段规则")}
                  description={
                    importMode === "qa"
                      ? t("每行按问题、答案和来源生成一个片段，分段规则不适用。")
                      : t("先用智能规则生成预览，需要时再精调。")
                  }
                />

                {importMode === "document" ? (
                  <div className="mt-4 space-y-3">
                    <SegmentModeOption
                      checked={segmentMode === "smart"}
                      title={t("智能分段")}
                      description={t(
                        "按常见文档结构自动设置长度、重叠和清洗规则。",
                      )}
                      onSelect={() => setSegmentMode("smart")}
                    />
                    <SegmentModeOption
                      checked={segmentMode === "advanced"}
                      title={t("高级分段")}
                      description={t(
                        "手动控制片段字符数、重叠字符和文本清洗规则。",
                      )}
                      onSelect={() => setSegmentMode("advanced")}
                    />
                  </div>
                ) : null}

                {importMode === "document" && segmentMode === "advanced" ? (
                  <FieldGroup className="mt-5">
                    <div className="grid grid-cols-2 gap-3">
                      <Field>
                        <FieldLabel htmlFor="knowledge-chunk-size">
                          {t("片段字符")}
                        </FieldLabel>
                        <Input
                          id="knowledge-chunk-size"
                          type="number"
                          min={100}
                          max={8000}
                          value={chunkSize}
                          onChange={(event) =>
                            setChunkSize(
                              Number(event.target.value) || SMART_CHUNK_SIZE,
                            )
                          }
                        />
                      </Field>
                      <Field>
                        <FieldLabel htmlFor="knowledge-chunk-overlap">
                          {t("重叠字符")}
                        </FieldLabel>
                        <Input
                          id="knowledge-chunk-overlap"
                          type="number"
                          min={0}
                          max={2000}
                          value={chunkOverlap}
                          onChange={(event) =>
                            setChunkOverlap(Number(event.target.value) || 0)
                          }
                        />
                      </Field>
                    </div>
                    <Field>
                      <FieldLabel htmlFor="knowledge-split-separator">
                        {t("切分字符")}
                      </FieldLabel>
                      <FilterDropdown
                        id="knowledge-split-separator"
                        ariaLabel={t("切分字符")}
                        className="h-9 px-3"
                        value={splitSeparator}
                        options={splitSeparatorOptions}
                        onChange={setSplitSeparator}
                      />
                    </Field>
                    {isSegmentInvalid ? (
                      <FieldDescription className="text-destructive">
                        {t("重叠字符必须小于片段字符")}
                      </FieldDescription>
                    ) : null}
                    <Field>
                      <FieldLabel>{t("清洗规则")}</FieldLabel>
                      <div className="space-y-2">
                        {cleaningRuleOptions.map((rule) => (
                          <label
                            key={rule.value}
                            className="flex min-h-9 items-center gap-2 text-sm"
                          >
                            <input
                              type="checkbox"
                              className="size-4"
                              checked={cleaningRules.includes(rule.value)}
                              onChange={(event) =>
                                toggleCleaningRule(
                                  rule.value,
                                  event.target.checked,
                                )
                              }
                            />
                            {rule.label}
                          </label>
                        ))}
                      </div>
                    </Field>
                  </FieldGroup>
                ) : null}

                <Button
                  type="button"
                  className="mt-5 w-full"
                  variant="outline"
                  disabled={
                    !uploadedDocuments.length ||
                    isPreviewRunning ||
                    isSegmentInvalid
                  }
                  onClick={() => void handleGeneratePreview()}
                >
                  {isPreviewRunning ? (
                    <LoaderCircleIcon
                      className="animate-spin"
                      data-icon="inline-start"
                    />
                  ) : (
                    <ScissorsIcon data-icon="inline-start" />
                  )}
                  {isPreviewRunning
                    ? t("正在生成预览")
                    : totalChunks
                      ? t("重新生成预览")
                      : t("生成分段预览")}
                </Button>
              </section>

              <section className="rounded-lg border bg-background p-4 shadow-sm">
                <SectionTitle
                  icon={DatabaseIcon}
                  title={t("入库状态")}
                  description={t("预览无误后提交向量化任务。")}
                />
                <dl className="mt-4 grid grid-cols-2 gap-x-4 gap-y-3">
                  <MetricItem
                    label={t("文档")}
                    value={`${uploadedDocuments.length}`}
                  />
                  <MetricItem label={t("片段")} value={`${totalChunks}`} />
                  <MetricItem
                    label={t("规则")}
                    value={
                      importMode === "qa"
                        ? t("问答表")
                        : segmentMode === "smart"
                          ? t("智能")
                          : t("高级")
                    }
                  />
                  <MetricItem
                    label={t("状态")}
                    value={canStartIndex ? t("可入库") : t("待预览")}
                  />
                </dl>
              </section>
            </aside>

            <main className="min-w-0 overflow-hidden rounded-lg border bg-background shadow-sm lg:flex lg:min-h-0 lg:flex-col">
              <div className="flex shrink-0 flex-col gap-3 border-b px-5 py-4 sm:flex-row sm:items-center sm:justify-between">
                <SectionTitle
                  icon={importMode === "qa" ? FileSpreadsheetIcon : FileTextIcon}
                  title={importMode === "qa" ? t("问答预览") : t("分段预览")}
                  description={
                    importMode === "qa"
                      ? t("按行查看解析后的问题、答案和来源。")
                      : t("按文件查看解析后的片段内容。")
                  }
                />
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  disabled={isRefreshing}
                  onClick={() => void refreshPreview()}
                >
                  {isRefreshing ? (
                    <LoaderCircleIcon
                      className="animate-spin"
                      data-icon="inline-start"
                    />
                  ) : (
                    <RotateCcwIcon data-icon="inline-start" />
                  )}
                  {t("刷新")}
                </Button>
              </div>

              <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
                <div className="flex gap-2 overflow-x-auto pb-1 [scrollbar-width:thin]">
                  {uploadedDocuments.map((document) => (
                    <div
                      key={document.id}
                      className={cn(
                        "group/document-tab inline-flex h-9 max-w-64 shrink-0 items-center rounded-md border text-sm font-medium transition-colors",
                        selectedDocument?.id === document.id
                          ? "border-primary bg-primary/10 text-primary"
                          : "text-muted-foreground hover:bg-muted/50 hover:text-foreground",
                      )}
                    >
                      <button
                        type="button"
                        className="flex h-full min-w-0 items-center gap-2 rounded-l-md py-0 pr-1 pl-3 outline-none focus-visible:ring-2 focus-visible:ring-ring/50"
                        onClick={() => setSelectedDocumentId(document.id)}
                      >
                        <FileTextIcon className="size-4 shrink-0" />
                        <span className="truncate">{document.filename}</span>
                      </button>
                      {document.meta.staged === true &&
                      document.status in UNINDEXED_STATUSES ? (
                        <Button
                          type="button"
                          variant="ghost"
                          size="icon-xs"
                          className={cn(
                            "mr-1 rounded-sm text-muted-foreground/60 opacity-0 transition-[color,background-color,opacity] hover:bg-destructive/10 hover:text-destructive focus-visible:bg-destructive/10 focus-visible:text-destructive focus-visible:opacity-100 group-hover/document-tab:opacity-100 group-focus-within/document-tab:opacity-100",
                            selectedDocument?.id === document.id && "opacity-100",
                            deletingDocumentId === document.id &&
                              "bg-destructive/10 text-destructive opacity-100",
                          )}
                          aria-label={t("移除 {value}", {
                            value: document.filename,
                          })}
                          disabled={isNavigationLocked}
                          onClick={() => void handleRemoveDocument(document)}
                        >
                          {deletingDocumentId === document.id ? (
                            <LoaderCircleIcon className="size-3.5 animate-spin" />
                          ) : (
                            <XIcon className="size-3.5" />
                          )}
                        </Button>
                      ) : null}
                    </div>
                  ))}
                </div>

                <PreviewPane
                  document={selectedDocument}
                  isLoading={isUploading || isRefreshing || isParsing}
                  token={token}
                  workspaceId={workspaceId}
                  knowledgeBaseId={knowledgeBase.id}
                />
              </div>
            </main>
          </div>

          <div className="sticky bottom-4 z-10 mt-auto">
            <div className="mx-auto w-full max-w-[90rem] px-4 sm:px-6 lg:px-8">
              <div className="flex flex-col gap-3 rounded-lg border bg-background/95 px-4 py-3 shadow-sm backdrop-blur sm:flex-row sm:items-center sm:justify-between">
                <p className="text-sm text-muted-foreground">
                  {canStartIndex
                    ? t("{documents} 个文档、{chunks} 个片段可入库", {
                        documents: uploadedDocuments.length,
                        chunks: totalChunks,
                      })
                    : hasStalePreview && totalChunks
                      ? t("分段规则已修改，请重新生成预览后再入库")
                      : t("生成预览并确认片段后才能入库")}
                </p>
                <div className="flex flex-wrap justify-end gap-2">
                  <Button
                    type="button"
                    variant="outline"
                    disabled={isNavigationLocked}
                    onClick={() => void handleCancel()}
                  >
                    {t("取消")}
                  </Button>
                  <Button
                    type="button"
                    variant="outline"
                    disabled={isNavigationLocked}
                    onClick={() => void handleBackToFiles()}
                  >
                    {t("上一步")}
                  </Button>
                  <Button
                    type="button"
                    disabled={!canStartIndex || isIndexing}
                    onClick={() => void handleStartImport()}
                  >
                    {isIndexing ? (
                      <LoaderCircleIcon
                        className="animate-spin"
                        data-icon="inline-start"
                      />
                    ) : (
                      <CheckCircle2Icon data-icon="inline-start" />
                    )}
                    {t("开始导入")}
                  </Button>
                </div>
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  )
}

/**
 * Renders a section heading with an icon, title, and description.
 *
 * @param icon - The icon displayed beside the heading
 * @param title - The section title
 * @param description - The supporting description
 */
function SectionTitle({
  icon: Icon,
  title,
  description,
}: {
  icon: LucideIcon
  title: string
  description: string
}) {
  return (
    <div className="flex min-w-0 items-start gap-3">
      <span className="flex size-9 shrink-0 items-center justify-center rounded-lg border bg-muted/40">
        <Icon className="size-4 text-primary" />
      </span>
      <div className="min-w-0">
        <h2 className="truncate text-base font-semibold text-foreground">
          {title}
        </h2>
        <p className="mt-1 text-sm leading-5 text-muted-foreground">
          {description}
        </p>
      </div>
    </div>
  )
}

/**
 * Renders a labeled metric value.
 *
 * @param label - The metric label
 * @param value - The metric value
 */
function MetricItem({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0 border-t pt-3">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="mt-1 truncate text-sm font-semibold text-foreground">
        {value}
      </dd>
    </div>
  )
}

/**
 * Renders a selectable segmentation mode option with its title and description.
 *
 * @param checked - Whether the option is currently selected
 * @param title - The option's title
 * @param description - The option's descriptive text
 * @param onSelect - Called when the option is selected
 */
function SegmentModeOption({
  checked,
  title,
  description,
  onSelect,
}: {
  checked: boolean
  title: string
  description: string
  onSelect: () => void
}) {
  return (
    <button
      type="button"
      className={cn(
        "flex w-full items-start gap-3 rounded-lg border px-3 py-3 text-left transition-colors",
        checked
          ? "border-primary bg-primary/5"
          : "border-border bg-background hover:bg-muted/40",
      )}
      onClick={onSelect}
    >
      <span
        className={cn(
          "mt-0.5 flex size-5 shrink-0 items-center justify-center rounded-full border",
          checked ? "border-primary bg-primary" : "border-border bg-muted/30",
        )}
      >
        {checked ? (
          <span className="size-1.5 rounded-full bg-primary-foreground" />
        ) : null}
      </span>
      <span className="min-w-0">
        <span className="block text-sm font-semibold text-foreground">
          {title}
        </span>
        <span className="mt-1 block text-sm leading-5 text-muted-foreground">
          {description}
        </span>
      </span>
    </button>
  )
}

/**
 * Displays the queued files and provides controls to remove individual files.
 *
 * @param files - The files awaiting upload
 * @param onRemove - Called with the index of a file selected for removal
 */
function FileList({
  files,
  onRemove,
}: {
  files: File[]
  onRemove: (index: number) => void
}) {
  const { t } = useLanguage()
  if (!files.length) {
    return null
  }

  return (
    <section className="overflow-hidden rounded-lg border bg-background shadow-sm">
      <div className="flex items-center justify-between gap-3 border-b px-4 py-3">
        <SectionTitle
          icon={FilesIcon}
          title={t("待上传队列")}
          description={t("确认这些文件后继续进入分段预览。")}
        />
        <Badge variant="outline">
          {t("{value} 个", { value: files.length })}
        </Badge>
      </div>
      <div className="divide-y">
        {files.map((file, index) => (
          <div
            key={`${file.name}-${file.size}-${file.lastModified}-${index}`}
            className="grid min-h-12 grid-cols-[minmax(0,1fr)_auto_auto] items-center gap-3 px-4 py-2 text-sm"
          >
            <div className="flex min-w-0 items-center gap-3">
              <span className="flex size-8 shrink-0 items-center justify-center rounded-md bg-muted">
                <FileTextIcon className="size-4 text-muted-foreground" />
              </span>
              <span className="min-w-0 truncate font-medium text-foreground">
                {file.name}
              </span>
            </div>
            <Badge variant="outline">{formatBytes(file.size)}</Badge>
            <Button
              type="button"
              variant="ghost"
              size="icon-sm"
              aria-label={t("移除 {value}", { value: file.name })}
              onClick={() => onRemove(index)}
            >
              <XIcon />
            </Button>
          </div>
        ))}
      </div>
    </section>
  )
}

/**
 * Displays the selected document's parsing status and segmented content preview.
 *
 * @param document - The document whose preview should be displayed
 * @param isLoading - Whether a preview is currently being generated
 * @param token - Authentication token used to load chunk content
 * @param workspaceId - Workspace containing the knowledge base
 * @param knowledgeBaseId - Knowledge base containing the document
 */
function PreviewPane({
  document,
  isLoading,
  token,
  workspaceId,
  knowledgeBaseId,
}: {
  document: UploadedDocument
  isLoading: boolean
  token: string
  workspaceId: string
  knowledgeBaseId: string
}) {
  const { t } = useLanguage()
  if (!document) {
    return (
      <div className="mt-4 flex min-h-72 flex-col items-center justify-center rounded-lg border border-dashed px-4 text-center text-sm text-muted-foreground">
        {isLoading ? (
          <LoaderCircleIcon className="mb-2 size-5 animate-spin" />
        ) : (
          <FolderOpenIcon className="mb-2 size-5" />
        )}
        {isLoading ? t("正在生成分段预览") : t("暂无文件")}
      </div>
    )
  }

  const isFailed = document.status.endsWith("_failed")
  const isParsing = isLoading || document.status in PARSING_STATUSES
  if (isFailed || !document.chunks.length) {
    return (
      <div
        className={cn(
          "mt-4 flex min-h-72 flex-col items-center justify-center rounded-lg border border-dashed px-4 text-center text-sm text-muted-foreground",
          isFailed && "border-destructive/40 bg-destructive/5 text-destructive",
        )}
      >
        {isFailed ? (
          <AlertCircleIcon className="mb-2 size-5" />
        ) : isParsing ? (
          <LoaderCircleIcon className="mb-2 size-5 animate-spin" />
        ) : (
          <ScissorsIcon className="mb-2 size-5" />
        )}
        {document.last_error ??
          (isParsing ? t("正在生成分段预览") : t("生成分段预览后查看片段内容"))}
      </div>
    )
  }

  return (
    <div className="mt-4 space-y-3">
      <div className="flex items-center justify-between gap-3 rounded-lg border bg-muted/20 px-4 py-3">
        <h2 className="truncate text-base font-semibold text-foreground">
          {document.filename}
        </h2>
        <Badge
          variant={
            document.status.endsWith("_failed") ? "destructive" : "outline"
          }
        >
          {documentStatusLabel(document.status, t)}
        </Badge>
      </div>
      <ChunkPreviewList
        chunks={document.chunks}
        fileName={document.filename}
        token={token}
        workspaceId={workspaceId}
        knowledgeBaseId={knowledgeBaseId}
      />
    </div>
  )
}

/**
 * Resolves a document status to its localized display label.
 *
 * @param status - The document status to label
 * @returns The localized label for a recognized status, or the original status for an unrecognized value
 */
function documentStatusLabel(status: string, t: TFunction) {
  const labels: Record<string, TranslationKey> = {
    uploaded: "待分段",
    parse_queued: "分段排队中",
    parsing: "分段中",
    parsed: "待向量化",
    index_queued: "向量化排队中",
    indexing: "向量化中",
    indexed: "已向量化",
    parse_failed: "分段失败",
    index_failed: "向量化失败",
  }

  const labelKey = labels[status]
  return labelKey ? t(labelKey) : status
}
