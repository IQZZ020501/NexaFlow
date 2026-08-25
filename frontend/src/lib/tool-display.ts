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

export function builtinToolDisplayName(
  functionName: string,
  t: TFunction
) {
  if (functionName === "inline_python") return t("Python 代码")
  if (functionName === "current_time") return t("当前时间")
  if (functionName === "create_artifact") return t("创建文件")
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
      event.tool_name !== "create_artifact" ||
      event.status !== "succeeded" ||
      !event.output ||
      typeof event.output !== "object"
    ) {
      continue
    }
    const output = event.output as Record<string, unknown>
    const filename =
      typeof output.filename === "string" ? output.filename.trim() : ""
    const downloadUrl =
      typeof output.download_url === "string"
        ? output.download_url.trim()
        : ""
    if (
      !filename ||
      !downloadUrl.startsWith("/api/v1/artifacts/") ||
      filenames.has(filename) ||
      linkedUrls.has(downloadUrl)
    ) {
      continue
    }
    filenames.add(filename)
    linkedUrls.add(downloadUrl)
    artifacts.push({ filename, downloadUrl })
  }

  for (const { filename, downloadUrl } of artifacts.reverse()) {
    const link = `[${filename.replace(/([\\[\]])/g, "\\$1")}](${downloadUrl})`
    const escapedUrl = downloadUrl.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")
    const absoluteUrl = "https?://[^/\\s<>()\\[\\]]+" + escapedUrl
    value = value
      .replace(
        new RegExp("\\[[^\\]\\n]*\\]\\(" + absoluteUrl + "\\)", "g"),
        link
      )
      .replace(new RegExp("<" + absoluteUrl + ">", "g"), link)
      .replace(new RegExp(absoluteUrl, "g"), link)
    const inlineCode = `\`${downloadUrl}\``
    if (value.includes(inlineCode)) {
      value = value.replaceAll(inlineCode, link)
    } else if (
      !value.includes(`](${downloadUrl})`) &&
      !(
        artifacts.length === 1 &&
        /\/api\/v1\/artifacts\/[A-Za-z0-9._~-]+/.test(value)
      )
    ) {
      value = value.includes(downloadUrl)
        ? value.replaceAll(downloadUrl, link)
        : `${value.trimEnd()}\n\n${link}`
    }
  }

  if (artifacts.length === 1) {
    const { filename, downloadUrl } = artifacts[0]!
    const link = `[${filename.replace(/([\\[\]])/g, "\\$1")}](${downloadUrl})`
    const artifactPath = "/api/v1/artifacts/[A-Za-z0-9._~-]+"
    const artifactUrl = `(?:https?://[^\\s<>()\\[\\]]+)?${artifactPath}`
    value = value.replace(
      new RegExp(
        `\\[[^\\]\\n]*\\]\\(${artifactUrl}\\)|<${artifactUrl}>|${artifactUrl}`,
        "g"
      ),
      link
    )
  }

  return value
}

/**
 * Resolves the localized display name for a tool.
 *
 * @param tool - The tool whose display name is resolved
 * @param t - The translation function
 * @returns The localized name for built-in tools or the tool's configured display name
 */
export function toolDisplayName(tool: DisplayableTool, t: TFunction) {
  return builtinToolDisplayName(tool.function_name, t) ?? tool.display_name
}

/**
 * Resolves the localized display description for a tool.
 *
 * @param tool - The tool whose description should be displayed
 * @param t - The translation function
 * @returns The localized description for a built-in tool or the tool's configured description
 */
export function toolDisplayDescription(tool: DisplayableTool, t: TFunction) {
  if (tool.function_name === "inline_python") {
    return t("在工作流沙箱中运行 Python 代码。")
  }
  if (tool.function_name === "current_time") return t("返回当前 UTC 时间。")
  if (tool.function_name === "create_artifact") {
    return t("在隔离沙箱中生成或重写任意常见文件，并提供可下载链接。")
  }
  return tool.description
}

/**
 * Provides the localized display name for a tool source.
 *
 * @param source - The tool source whose display name is being determined
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
