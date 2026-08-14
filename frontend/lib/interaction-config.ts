import type {
  AgentInteractionConfig,
  AppType,
} from "@/lib/api/agents"

export type FileUploadType =
  AgentInteractionConfig["file_upload_setting"]["file_upload_type"][number]

const FILE_UPLOAD_TYPES: Record<AppType, readonly FileUploadType[]> = {
  agent: ["document", "image"],
  workflow: ["document", "image"],
}

const FILE_UPLOAD_EXTENSIONS: Partial<Record<FileUploadType, readonly string[]>> = {
  document: [
    ".csv", ".docx", ".epub", ".html", ".ipynb", ".json", ".md", ".pdf",
    ".pptx", ".txt", ".xls", ".xlsx", ".xml", ".zip",
  ],
  image: [".jpeg", ".jpg", ".png", ".webp"],
}

export const AGENT_FILE_UPLOAD_SETTING: AgentInteractionConfig["file_upload_setting"] = {
  file_upload_type: ["document", "image"],
}

export function allowedFileUploadTypes(appType: AppType) {
  return FILE_UPLOAD_TYPES[appType]
}

export function defaultInteractionConfig(): AgentInteractionConfig {
  return {
    prologue: "",
    tts_type: "BROWSER",
    file_upload: false,
    file_upload_setting: { ...AGENT_FILE_UPLOAD_SETTING },
    user_input_title: "",
  }
}

export function normalizeInteractionConfigForAppType(
  config: AgentInteractionConfig,
  appType: AppType
): AgentInteractionConfig {
  if (appType === "agent") {
    return {
      ...config,
      prologue: "",
      tts_type: "NONE",
      file_upload: true,
      file_upload_setting: { ...AGENT_FILE_UPLOAD_SETTING },
      user_input_title: "",
    }
  }
  const allowed = allowedFileUploadTypes(appType)
  const selected = config.file_upload_setting.file_upload_type.filter((type) =>
    allowed.includes(type)
  )
  return {
    ...config,
    file_upload_setting: {
      ...config.file_upload_setting,
      file_upload_type: selected.length ? selected : [allowed[0]],
    },
  }
}

export function acceptedUploadExtensions(types: FileUploadType[]) {
  const extensions = types.flatMap((type) => FILE_UPLOAD_EXTENSIONS[type] ?? [])
  return extensions.length ? extensions.join(",") : undefined
}
