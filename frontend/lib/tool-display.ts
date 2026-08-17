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

export function toolDisplayName(tool: DisplayableTool, t: TFunction) {
  if (tool.function_name === "inline_python") return t("Python 代码")
  if (tool.function_name === "current_time") return t("当前时间")
  return tool.display_name
}

export function toolDisplayDescription(tool: DisplayableTool, t: TFunction) {
  if (tool.function_name === "inline_python") {
    return t("在工作流沙箱中运行 Python 代码。")
  }
  if (tool.function_name === "current_time") return t("返回当前 UTC 时间。")
  return tool.description
}

export function toolSourceDisplayName(
  source: DisplayableToolSource,
  t: TFunction
) {
  if (source.kind === "builtin") return t("内置")
  return source.name
}
