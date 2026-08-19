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

/**
 * Resolves the localized display name for a tool.
 *
 * @param tool - The tool whose display name is resolved
 * @param t - The translation function
 * @returns The localized name for built-in tools or the tool's configured display name
 */
export function toolDisplayName(tool: DisplayableTool, t: TFunction) {
  if (tool.function_name === "inline_python") return t("Python 代码")
  if (tool.function_name === "current_time") return t("当前时间")
  return tool.display_name
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
