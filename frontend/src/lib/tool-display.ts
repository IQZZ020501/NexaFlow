import type { TFunction } from "@/i18n"
import { artifactContentUrl } from "@/lib/agent-artifacts"
import { integrationSourceName, integrationToolName } from "@/lib/integrations"

export function executionWaitSummary(output: unknown, t: TFunction) {
  const reason = (output as { resource_wait?: { reason?: string } } | null)
    ?.resource_wait?.reason
  if (reason === "workspace_quota") return t("等待工作区执行额度")
  if (reason === "consumer_quota") return t("等待调用方执行额度")
  if (reason === "environment_cleanup") return t("等待旧执行环境清理")
  if (reason === "environment_owned") return t("等待执行环境释放")
  return t("等待执行资源")
}

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
  /(?:https?:\/\/[^\s<>()\x5B\x5D]+)?\/api\/v1\/artifacts\/[A-Za-z0-9._~-]+(?:\/content)?/g
const IMAGE_PREVIEW_LINK_LINE =
  /^[ \t]*(?:[-*+•]|\d+[.)])?[ \t]*(?:[*_]{1,2})?(?:预览链接|预览地址|preview (?:link|url))[ \t]*[：:][ \t]*(?:[*_]{1,2})?[^\r\n]*(?:\r?\n|$)/gim
const IMAGE_PREVIEW_URL_LINE =
  /^[ \t]*(?:[-*+•]|\d+[.)])?[ \t]*(?:[*_]{1,2})?(?:图片)?预览[ \t]*[：:][ \t]*(?:[*_]{1,2})?[^\r\n]*(?:\r?\n|$)/gim
const UUID_V4_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/
const ARTIFACT_TOOL_FUNCTIONS = new Set([
  "create_artifact",
  "documents_skill",
  "pdf_skill",
  "pptx_skill",
  "spreadsheets_skill",
  "generate_image",
  "bash",
  "run_skill_script",
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
    const url = rawUrl.match(
      /\/api\/v1\/artifacts\/[A-Za-z0-9._~-]+(?:\/content)?/
    )?.[0]
    if (url)
      value = replaceArtifactReferences(value, url, artifactLink(filename, url))
  }
  return value
}

export function builtinToolDisplayName(functionName: string, t: TFunction) {
  if (functionName === "search_knowledge") return t("知识库检索")
  if (functionName === "bash") return t("命令行")
  if (functionName === "create_artifact") return t("创建文件")
  if (functionName === "documents_skill") return t("生成 Word")
  if (functionName === "pdf_skill") return t("生成 PDF")
  if (functionName === "pptx_skill") return t("生成 PPT")
  if (functionName === "spreadsheets_skill") return t("生成 Excel")
  if (functionName === "skill_creator") return t("技能创建")
  if (functionName === "generate_image") return t("图片生成")
  return null
}

export function withArtifactDownloadLinks(
  content: string,
  events: readonly ToolOutputEvent[]
) {
  events = events.flatMap((event) => {
    const output = event.output
    if (
      (event.tool_name === "bash" || event.tool_name === "run_skill_script") &&
      output &&
      typeof output === "object" &&
      "artifacts" in output &&
      Array.isArray(output.artifacts)
    ) {
      return output.artifacts.map((artifact: unknown) => ({
        ...event,
        output: artifact,
      }))
    }
    return [event]
  })
  let value = content
  const artifacts: Array<{
    sourceFilename: string
    downloadUrl: string
    sourceDownloadUrl: string
    previewUrl?: string
    sourcePreviewUrl?: string
  }> = []
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
    const sourceFilename =
      typeof output.relative_path === "string" && output.relative_path
        ? output.relative_path
        : typeof output.filename === "string"
          ? output.filename.trim()
          : ""
    const sourceDownloadUrl =
      typeof output.download_url === "string" ? output.download_url.trim() : ""
    const isGeneratedImage = event.tool_name === "generate_image"
    if (
      !sourceFilename ||
      !sourceDownloadUrl.startsWith("/api/v1/artifacts/") ||
      (!isGeneratedImage && filenames.has(sourceFilename)) ||
      linkedUrls.has(sourceDownloadUrl)
    )
      continue
    const artifactId =
      typeof output.artifact_id === "string" ? output.artifact_id.trim() : ""
    const downloadUrl =
      isGeneratedImage && UUID_V4_PATTERN.test(artifactId)
        ? `/api/v1/artifacts/${artifactId}`
        : (artifactContentUrl(output) ?? sourceDownloadUrl)
    filenames.add(sourceFilename)
    linkedUrls.add(sourceDownloadUrl)
    const sourcePreviewUrl =
      isGeneratedImage && output.preview_url === `${sourceDownloadUrl}/preview`
        ? output.preview_url
        : undefined
    const previewUrl = sourcePreviewUrl ? `${downloadUrl}/preview` : undefined
    artifacts.push({
      sourceFilename,
      downloadUrl,
      sourceDownloadUrl,
      previewUrl,
      sourcePreviewUrl,
    })
  }

  for (const {
    sourceFilename,
    downloadUrl,
    sourceDownloadUrl,
    previewUrl,
    sourcePreviewUrl,
  } of artifacts.reverse()) {
    if (previewUrl) {
      value = value.replace(IMAGE_PREVIEW_LINK_LINE, "")
      value = value.replace(IMAGE_PREVIEW_URL_LINE, (line) =>
        line.includes(previewUrl) ||
        (sourcePreviewUrl && line.includes(sourcePreviewUrl))
          ? ""
          : line
      )
      if (sourcePreviewUrl && sourcePreviewUrl !== previewUrl) {
        value = value.replaceAll(sourcePreviewUrl, previewUrl)
      }
    }
    const link = artifactLink(sourceFilename, downloadUrl)
    let wasMentioned = value.includes(sourceFilename)
    for (const referencedUrl of new Set([sourceDownloadUrl, downloadUrl])) {
      const escapedUrl = referencedUrl.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")
      const artifactUrl = `(?:https?:\\/\\/[^\\s<>()\\[\\]]+)?${escapedUrl}(?!/preview)`
      wasMentioned ||= new RegExp(artifactUrl).test(value)
      value = value.replace(
        new RegExp(
          `\\[[^\\]\\n]*\\]\\s*\\(\\s*${artifactUrl}\\s*\\)|<${artifactUrl}>|\\x60${artifactUrl}\\x60|${artifactUrl}`,
          "g"
        ),
        link
      )
    }
    if ((wasMentioned || previewUrl) && !value.includes(`](${downloadUrl})`)) {
      value = `${value.trimEnd()}\n\n${link}`
    }
  }

  if (artifacts.length === 1) {
    const { sourceFilename, downloadUrl } = artifacts[0]!
    const artifactUrl =
      "(?:https?:\\/\\/[^\\s<>()\\[\\]]+)?\\/api\\/v1\\/artifacts\\/[A-Za-z0-9._~-]+(?:\\/content)?(?![A-Za-z0-9._~-]|/)"
    value = value.replace(
      new RegExp(
        `\\[[^\\]\\n]*\\]\\s*\\(\\s*${artifactUrl}\\s*\\)|<${artifactUrl}>|\\x60${artifactUrl}\\x60|${artifactUrl}`,
        "g"
      ),
      artifactLink(sourceFilename, downloadUrl)
    )
  }
  for (const { sourceFilename, previewUrl } of artifacts) {
    if (!previewUrl) continue
    const hasEmbeddedPreview = [
      ...value.matchAll(
        /!\[[^\]\r\n]*\]\((\/api\/v1\/artifacts\/[A-Za-z0-9._~-]+\/preview)\)/g
      ),
    ].some((match) => match[1] === previewUrl)
    if (!hasEmbeddedPreview) {
      value = `${value.trimEnd()}\n\n![${sourceFilename.replace(/[\x5B\x5D]/g, "\\$&")}](${previewUrl})`
    }
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
  return (
    builtinToolDisplayName(tool.function_name, t) ??
    integrationToolName(tool.function_name, t) ??
    tool.display_name
  )
}

/**
 * Resolves the localized display description for a tool.
 *
 * @param tool - The tool whose description should be determined
 * @param t - The translation function
 * @returns The localized description for a built-in tool or the tool's configured description
 */
export function toolDisplayDescription(tool: DisplayableTool, t: TFunction) {
  const integrationLabel = integrationToolName(tool.function_name, t)
  if (integrationLabel) return integrationLabel
  if (tool.function_name === "bash") {
    return t("在 Run 的私有沙箱中执行命令，保留文件并生成可下载的结果。")
  }
  if (tool.function_name === "create_artifact") {
    return t(
      "根据文件名和内容创建可下载文件；文本文件直接保存，复杂格式由平台生成。"
    )
  }
  if (tool.function_name === "documents_skill") {
    return t("加载 Word 文档处理指引，在沙箱中读取、创建或修改 DOCX。")
  }
  if (tool.function_name === "pdf_skill") {
    return t("加载 PDF 处理指引，在沙箱中读取、转换或修改 PDF。")
  }
  if (tool.function_name === "pptx_skill") {
    return t("加载 PPT 处理指引，在沙箱中自由设计或修改演示文稿。")
  }
  if (tool.function_name === "spreadsheets_skill") {
    return t("加载表格处理指引，在沙箱中分析 CSV 或修改 Excel。")
  }
  if (tool.function_name === "skill_creator") {
    return t("生成可导入的技能包；不自动发布或授权。")
  }
  if (tool.function_name === "generate_image") {
    return t("使用 Agent 选定的生图模型生成图片；每次调用需要确认。")
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
  if (source.kind === "integration") {
    const key = integrationSourceName(source.name)
    if (key) return t(key)
  }
  return source.name
}
