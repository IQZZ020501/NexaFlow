import type { TFunction } from "@/i18n"

type DisplayableTool = {
  function_name: string
  display_name: string
  description: string
}

type DisplayableToolSource = {
  kind: string
  name: string
}

type ToolOutputEvent = {
  tool_name?: string
  status?: string
  output?: unknown
}

const ARTIFACT_URL_PATTERN =
  /(?:https?:\/\/[^\s<>()\x5B\x5D]+)?\/api\/v1\/artifacts\/[A-Za-z0-9._~-]+/g
const ARTIFACT_TOOL_FUNCTIONS = new Set([
  "create_artifact",
  "documents_skill",
  "pdf_skill",
  "pptx_skill",
  "spreadsheets_skill",
])

function artifactLink(filename: string, downloadUrl: string) {
  return `[${filename.replace(/[\x5B\x5D]/g, "\\$&")}](${downloadUrl})`
}

function replaceArtifactReferences(
  content: string,
  downloadUrl: string,
  link: string
) {
  const escapedUrl = downloadUrl.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")
  return content.replace(
    new RegExp(
      `\\[[^\\]\\n]*\\]\\s*\\(\\s*(?:https?:\\/\\/[^\\s<>()\\[\\]]+)?${escapedUrl}\\s*\\)|<${escapedUrl}>|${escapedUrl}`,
      "g"
    ),
    link
  )
}

function artifactFilenameFromContent(content: string) {
  const match = content.match(
    /(?:文件名|filename)\s*[：:]\s*[`*\x5B]*([^\s`*\x5B\x5D()<>{}（）]+\.[A-Za-z0-9]{1,10})/i
  )
  return match?.[1] ?? null
}

export function withArtifactDownloadLinksInContent(content: string) {
  const urls = [...new Set(content.match(ARTIFACT_URL_PATTERN) ?? [])]
  const filename = artifactFilenameFromContent(content)
  if (urls.length === 0 || !filename) return content

  let value = content
  for (const rawUrl of urls) {
    const url = rawUrl.match(/\/api\/v1\/artifacts\/[A-Za-z0-9._~-]+/)?.[0]
    if (url)
      value = replaceArtifactReferences(value, url, artifactLink(filename, url))
  }
  return value
}

export function builtinToolDisplayName(functionName: string, t: TFunction) {
  if (functionName === "inline_python") return t("Python 代码")
  if (functionName === "current_time") return t("当前时间")
  if (functionName === "create_artifact") return t("创建文件")
  if (functionName === "documents_skill") return t("DOCX")
  if (functionName === "pdf_skill") return t("PDF")
  if (functionName === "pptx_skill") return t("PPTX")
  if (functionName === "spreadsheets_skill") return t("Excel")
  return null
}

export function withArtifactDownloadLinks(
  content: string,
  events: readonly ToolOutputEvent[]
) {
  let value = content
  const artifacts: Array<{ filename: string; downloadUrl: string }> = []
  const filenames = new Set<string>()
  const linkedUrls = new Set<string>()

  for (let index = events.length - 1; index >= 0; index -= 1) {
    const event = events[index]
    if (
      !ARTIFACT_TOOL_FUNCTIONS.has(event.tool_name ?? "") ||
      event.status !== "succeeded" ||
      !event.output ||
      typeof event.output !== "object"
    )
      continue
    const output = event.output as Record<string, unknown>
    const filename =
      typeof output.filename === "string" ? output.filename.trim() : ""
    const downloadUrl =
      typeof output.download_url === "string" ? output.download_url.trim() : ""
    if (
      !filename ||
      !downloadUrl.startsWith("/api/v1/artifacts/") ||
      filenames.has(filename) ||
      linkedUrls.has(downloadUrl)
    )
      continue
    filenames.add(filename)
    linkedUrls.add(downloadUrl)
    artifacts.push({ filename, downloadUrl })
  }

  for (const { filename, downloadUrl } of artifacts.reverse()) {
    const link = artifactLink(filename, downloadUrl)
    const escapedUrl = downloadUrl.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")
    const artifactUrl = `(?:https?:\\/\\/[^\\s<>()\\[\\]]+)?${escapedUrl}`
    const wasMentioned =
      new RegExp(artifactUrl).test(value) || value.includes(filename)
    value = value.replace(
      new RegExp(
        `\\[[^\\]\\n]*\\]\\s*\\(\\s*${artifactUrl}\\s*\\)|<${artifactUrl}>|\\x60${artifactUrl}\\x60|${artifactUrl}`,
        "g"
      ),
      link
    )
    if (wasMentioned && !value.includes(`](${downloadUrl})`)) {
      value = `${value.trimEnd()}\n\n${link}`
    }
  }

  if (artifacts.length === 1) {
    const { filename, downloadUrl } = artifacts[0]!
    const artifactUrl =
      "(?:https?:\\/\\/[^\\s<>()\\[\\]]+)?\\/api\\/v1\\/artifacts\\/[A-Za-z0-9._~-]+"
    value = value.replace(
      new RegExp(
        `\\[[^\\]\\n]*\\]\\s*\\(\\s*${artifactUrl}\\s*\\)|<${artifactUrl}>|\\x60${artifactUrl}\\x60|${artifactUrl}`,
        "g"
      ),
      artifactLink(filename, downloadUrl)
    )
  }
  return value
}

/**
 * Resolves the localized display name for a tool.
 *
 * @param tool - The tool whose display name is resolved
 * @param t - The translation function
 * @returns The localized display name for built-in tools or the tool's configured display name
 */
export function toolDisplayName(tool: DisplayableTool, t: TFunction) {
  return builtinToolDisplayName(tool.function_name, t) ?? tool.display_name
}

/**
 * Resolves the localized display description for a tool.
 *
 * @param tool - The tool whose description should be determined
 * @param t - The translation function
 * @returns The localized description for a built-in tool or the tool's configured description
 */
export function toolDisplayDescription(tool: DisplayableTool, t: TFunction) {
  if (tool.function_name === "inline_python") {
    return t("在工作流沙箱中运行 Python 代码。")
  }
  if (tool.function_name === "current_time") return t("返回当前 UTC 时间。")
  if (tool.function_name === "create_artifact") {
    return t(
      "根据文件名和内容创建可下载文件；文本文件直接保存，复杂格式由平台生成。"
    )
  }
  if (tool.function_name === "documents_skill") {
    return t("创建 DOCX 文件。")
  }
  if (tool.function_name === "pdf_skill") {
    return t("创建 PDF 文件。")
  }
  if (tool.function_name === "pptx_skill") {
    return t("创建 PPTX 演示文稿。")
  }
  if (tool.function_name === "spreadsheets_skill") {
    return t("创建 Excel 工作簿。")
  }
  return tool.description
}

/**
 * Provides the localized display name for a tool source.
 *
 * @param source - The tool source whose display name is determined
 * @param t - The translation function
 * @returns The localized built-in label or the source's configured name
 */
export function toolSourceDisplayName(
  source: DisplayableToolSource,
  t: TFunction
) {
  if (source.kind === "builtin") return t("内置")
  return source.name
}
