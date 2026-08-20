import type { TFunction, TranslationKey } from "@/i18n"

/**
 * Resolves a document status to its translated display label.
 *
 * @param status - The document status to label
 * @param t - The translation function
 * @returns The translated label for a known status, or the original status for an unknown value
 */
export function documentStatusLabel(status: string, t: TFunction) {
  const labels: Record<string, TranslationKey> = { // values are TranslationKeys
    uploaded: "待解析",
    parse_queued: "解析排队中",
    parsing: "解析中",
    parsed: "待向量化",
    index_queued: "向量化排队中",
    indexing: "向量化中",
    preview: "预览",
    indexed: "已向量化",
    parse_failed: "解析失败",
    index_failed: "向量化失败",
  }

  const labelKey = labels[status]
  return labelKey ? t(labelKey) : status
}

/**
 * Determines the CSS class for a document status indicator.
 *
 * @param status - The document status
 * @returns The CSS class corresponding to the status
 */
export function documentStatusDotClassName(status: string) {
  if (status.endsWith("_failed")) {
    return "bg-destructive"
  }
  if (status === "parsed" || status === "indexed") {
    return "bg-emerald-500"
  }
  if (
    status.endsWith("_queued") ||
    status === "parsing" ||
    status === "indexing"
  ) {
    return "bg-sky-500"
  }
  return "bg-muted-foreground"
}

/**
 * Converts a task type to its translated label.
 *
 * @param taskType - The task type to label
 * @param t - The translation function
 * @returns The translated label for a known task type, or the original task type
 */
export function taskTypeLabel(taskType: string, t: TFunction) {
  const labels: Record<string, TranslationKey> = { // values are TranslationKeys
    parse: "解析",
    index: "向量化",
    rebuild_index: "重建索引",
  }

  const labelKey = labels[taskType]
  return labelKey ? t(labelKey) : taskType
}

/**
 * Provides a translated label for a task status.
 *
 * @param status - The task status to label
 * @param t - The translation function
 * @returns The translated label for a recognized status, or the original status
 */
export function taskStatusLabel(status: string, t: TFunction) {
  const labels: Record<string, TranslationKey> = { // values are TranslationKeys
    queued: "排队中",
    running: "运行中",
    succeeded: "成功",
    failed: "失败",
  }

  const labelKey = labels[status]
  return labelKey ? t(labelKey) : status
}

/**
 * Determines the CSS class for a task status indicator.
 *
 * @param status - The task status to classify
 * @returns The CSS class corresponding to the status
 */
export function taskStatusDotClassName(status: string) {
  if (status === "failed") {
    return "bg-destructive"
  }
  if (status === "succeeded") {
    return "bg-emerald-500"
  }
  if (status === "queued" || status === "running") {
    return "bg-sky-500"
  }
  return "bg-muted-foreground"
}

/**
 * Formats a byte count using bytes, kilobytes, or megabytes.
 *
 * @param bytes - The number of bytes to format
 * @returns The formatted byte count
 */
export function formatBytes(bytes: number) {
  if (bytes < 1024) {
    return `${bytes} B`
  }
  if (bytes < 1024 * 1024) {
    return `${(bytes / 1024).toFixed(1)} KB`
  }
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}
