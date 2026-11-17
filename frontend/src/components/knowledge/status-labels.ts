import type { TFunction, TranslationKey } from "@/i18n"
import type { KnowledgeTask } from "@/lib/api/knowledge"

/**
 * Resolves a document status to its translated display label.
 *
 * @param status - The document status to label
 * @param t - The translation function
 * @returns The translated label for a known status, or the original status for an unknown value
 */
export function documentStatusLabel(status: string, t: TFunction) {
  const labels: Record<string, TranslationKey> = {
    // values are TranslationKeys
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
  const labels: Record<string, TranslationKey> = {
    // values are TranslationKeys
    parse: "解析",
    index: "向量化",
    rebuild_index: "重建索引",
    evaluate: "检索评测",
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
  const labels: Record<string, TranslationKey> = {
    // values are TranslationKeys
    queued: "排队中",
    running: "运行中",
    succeeded: "成功",
    failed: "失败",
    cancelling: "停止中",
    cancelled: "已停止",
  }

  const labelKey = labels[status]
  return labelKey ? t(labelKey) : status
}

/** Formats the current execution attempt, keeping terminal durations fixed. */
export function taskDurationLabel(
  task: Pick<KnowledgeTask, "status" | "started_at" | "finished_at">,
  now: number,
  t: TFunction
) {
  if (!task.started_at || task.status === "queued") return "—"

  const startedAt = Date.parse(task.started_at)
  const finishedAt = task.finished_at
    ? Date.parse(task.finished_at)
    : task.status === "running" || task.status === "cancelling"
      ? now
      : NaN
  if (!Number.isFinite(startedAt) || !Number.isFinite(finishedAt)) return "—"

  const seconds = Math.max(0, Math.floor((finishedAt - startedAt) / 1000))
  if (seconds < 60) return t("{value} 秒", { value: seconds })
  if (seconds < 3600) {
    return t("{minutes} 分 {seconds} 秒", {
      minutes: Math.floor(seconds / 60),
      seconds: seconds % 60,
    })
  }
  return t("{hours} 小时 {minutes} 分", {
    hours: Math.floor(seconds / 3600),
    minutes: Math.floor((seconds % 3600) / 60),
  })
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
  if (status === "cancelled") {
    return "bg-muted-foreground"
  }
  if (status === "succeeded") {
    return "bg-emerald-500"
  }
  if (["queued", "running", "cancelling"].includes(status)) {
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
