export type KnowledgeUploadStep = "files" | "segment"
export type KnowledgeImportMode = "document" | "qa"

export type KnowledgeUploadParseSettings = {
  segmentMode: "smart" | "advanced"
  chunkSize: number
  chunkOverlap: number
  splitSeparator: string
  cleaningRules: string[]
}

export type KnowledgeUploadRouteState = {
  documentIds: string[]
  parseSettings: KnowledgeUploadParseSettings
  importMode?: KnowledgeImportMode
}

export type KnowledgeUploadSearchParams = Record<
  string,
  string | string[] | undefined
>

export const MAX_KNOWLEDGE_UPLOAD_DOCUMENTS = 30

export const DEFAULT_KNOWLEDGE_UPLOAD_PARSE_SETTINGS: KnowledgeUploadParseSettings =
  {
    segmentMode: "smart",
    chunkSize: 1200,
    chunkOverlap: 150,
    splitSeparator: "\n\n",
    cleaningRules: ["trim_lines", "remove_empty_lines"],
  }

const UUID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i
const SPLIT_SEPARATORS = new Set(["\n\n", "\n", "。", "."])
const CLEANING_RULES = new Set([
  "trim_lines",
  "remove_empty_lines",
  "collapse_spaces",
])

function firstValue(
  searchParams: KnowledgeUploadSearchParams,
  key: string,
) {
  const value = searchParams[key]
  return Array.isArray(value) ? value[0] : value
}

function integerValue(
  value: string | undefined,
  minimum: number,
  maximum: number,
  fallback: number,
) {
  const parsed = Number(value)
  return Number.isInteger(parsed) && parsed >= minimum && parsed <= maximum
    ? parsed
    : fallback
}

export function knowledgeUploadPath(knowledgeBaseId: string) {
  return `/app/knowledge/${encodeURIComponent(knowledgeBaseId)}/upload`
}

export function knowledgeUploadSegmentPath(
  knowledgeBaseId: string,
  documentIds: string[],
  parseSettings: KnowledgeUploadParseSettings,
  importMode: KnowledgeImportMode = "document",
) {
  const searchParams = new URLSearchParams()
  searchParams.set(
    "documents",
    [...new Set(documentIds)].slice(0, MAX_KNOWLEDGE_UPLOAD_DOCUMENTS).join(","),
  )
  searchParams.set("mode", parseSettings.segmentMode)
  searchParams.set("chunk_size", String(parseSettings.chunkSize))
  searchParams.set("chunk_overlap", String(parseSettings.chunkOverlap))
  searchParams.set("separator", parseSettings.splitSeparator)
  searchParams.set("cleaning", parseSettings.cleaningRules.join(","))
  searchParams.set("import", importMode)
  return `${knowledgeUploadPath(knowledgeBaseId)}/segment?${searchParams}`
}

export function parseKnowledgeUploadRouteState(
  searchParams: KnowledgeUploadSearchParams,
): KnowledgeUploadRouteState {
  const documentIds = [
    ...new Set(
      (firstValue(searchParams, "documents") ?? "")
        .split(",")
        .filter((documentId) => UUID_PATTERN.test(documentId)),
    ),
  ].slice(0, MAX_KNOWLEDGE_UPLOAD_DOCUMENTS)
  const importMode =
    firstValue(searchParams, "import") === "qa" ? "qa" : "document"

  if (importMode === "qa") {
    return {
      documentIds,
      importMode,
      parseSettings: {
        ...DEFAULT_KNOWLEDGE_UPLOAD_PARSE_SETTINGS,
        cleaningRules: [
          ...DEFAULT_KNOWLEDGE_UPLOAD_PARSE_SETTINGS.cleaningRules,
        ],
      },
    }
  }

  const segmentMode =
    firstValue(searchParams, "mode") === "advanced" ? "advanced" : "smart"
  if (segmentMode === "smart") {
    return {
      documentIds,
      importMode,
      parseSettings: {
        ...DEFAULT_KNOWLEDGE_UPLOAD_PARSE_SETTINGS,
        cleaningRules: [
          ...DEFAULT_KNOWLEDGE_UPLOAD_PARSE_SETTINGS.cleaningRules,
        ],
      },
    }
  }

  let chunkSize = integerValue(
    firstValue(searchParams, "chunk_size"),
    100,
    8000,
    DEFAULT_KNOWLEDGE_UPLOAD_PARSE_SETTINGS.chunkSize,
  )
  let chunkOverlap = integerValue(
    firstValue(searchParams, "chunk_overlap"),
    0,
    2000,
    DEFAULT_KNOWLEDGE_UPLOAD_PARSE_SETTINGS.chunkOverlap,
  )
  if (chunkOverlap >= chunkSize) {
    chunkSize = DEFAULT_KNOWLEDGE_UPLOAD_PARSE_SETTINGS.chunkSize
    chunkOverlap = DEFAULT_KNOWLEDGE_UPLOAD_PARSE_SETTINGS.chunkOverlap
  }

  const separator = firstValue(searchParams, "separator")
  const splitSeparator =
    separator && SPLIT_SEPARATORS.has(separator)
      ? separator
      : DEFAULT_KNOWLEDGE_UPLOAD_PARSE_SETTINGS.splitSeparator
  const cleaning = firstValue(searchParams, "cleaning")
  const rawCleaningRules = cleaning === undefined ? null : cleaning.split(",")
  const cleaningRules =
    rawCleaningRules?.every((rule) => !rule || CLEANING_RULES.has(rule))
      ? [...new Set(rawCleaningRules.filter(Boolean))]
      : [...DEFAULT_KNOWLEDGE_UPLOAD_PARSE_SETTINGS.cleaningRules]

  return {
    documentIds,
    importMode,
    parseSettings: {
      segmentMode,
      chunkSize,
      chunkOverlap,
      splitSeparator,
      cleaningRules,
    },
  }
}
