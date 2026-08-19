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

/**
 * Gets the file upload types supported by an application type.
 *
 * @param appType - The application type to inspect
 * @returns The file upload types supported by `appType`
 */
export function allowedFileUploadTypes(appType: AppType) {
  return FILE_UPLOAD_TYPES[appType]
}

/**
 * Creates the default interaction configuration for an agent.
 *
 * @returns An interaction configuration with empty text fields, browser text-to-speech, disabled file uploads, and the default document and image upload settings.
 */
export function defaultInteractionConfig(): AgentInteractionConfig {
  return {
    prologue: "",
    tts_type: "BROWSER",
    file_upload: false,
    file_upload_setting: { ...AGENT_FILE_UPLOAD_SETTING },
    user_input_title: "",
  }
}

/**
 * Normalizes interaction settings for the specified application type.
 *
 * @param config - The interaction configuration to normalize
 * @param appType - The application type whose supported settings determine the result
 * @returns A configuration with application-specific interaction and file upload settings
 */
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

/**
 * Converts selected file upload types into a comma-separated list of accepted file extensions.
 *
 * @param types - The file upload types to convert
 * @returns A comma-separated extension list, or `undefined` when no extensions are available
 */
export function acceptedUploadExtensions(types: FileUploadType[]) {
  const extensions = types.flatMap((type) => FILE_UPLOAD_EXTENSIONS[type] ?? [])
  return extensions.length ? extensions.join(",") : undefined
}
