import type {
  AgentInteractionConfig,
  AppType,
} from "@/lib/api/agents"

export type FileUploadType =
  AgentInteractionConfig["file_upload_setting"]["file_upload_type"][number]

const FILE_UPLOAD_TYPES: Record<AppType, readonly FileUploadType[]> = {
  agent: ["document", "image"],
  workflow: ["document", "image", "audio"],
}

export function allowedFileUploadTypes(appType: AppType) {
  return FILE_UPLOAD_TYPES[appType]
}

export function normalizeInteractionConfigForAppType(
  config: AgentInteractionConfig,
  appType: AppType
): AgentInteractionConfig {
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
