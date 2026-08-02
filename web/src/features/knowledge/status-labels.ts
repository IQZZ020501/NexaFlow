export function documentStatusLabel(status: string) {
  const labels: Record<string, string> = {
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

  return labels[status] ?? status
}

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

export function taskTypeLabel(taskType: string) {
  const labels: Record<string, string> = {
    parse: "解析",
    index: "向量化",
    rebuild_index: "重建索引",
  }

  return labels[taskType] ?? taskType
}

export function taskStatusLabel(status: string) {
  const labels: Record<string, string> = {
    queued: "排队中",
    running: "运行中",
    succeeded: "成功",
    failed: "失败",
  }

  return labels[status] ?? status
}

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

export function formatBytes(bytes: number) {
  if (bytes < 1024) {
    return `${bytes} B`
  }
  if (bytes < 1024 * 1024) {
    return `${(bytes / 1024).toFixed(1)} KB`
  }
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}
