"use client"

import { Input } from "@/components/ui/input"
import type { TFunction } from "@/i18n"
import type {
  AgentInteractionConfig,
  AppType,
} from "@/lib/api/agents"
import { allowedFileUploadTypes } from "@/lib/interaction-config"

type InteractionConfigFieldsProps = {
  appType: AppType
  value: AgentInteractionConfig
  onChange: (value: AgentInteractionConfig) => void
  t: TFunction
  idPrefix: string
  readOnly?: boolean
  compact?: boolean
}

export function InteractionConfigFields({
  appType,
  value,
  onChange,
  t,
  idPrefix,
  readOnly = false,
  compact = false,
}: InteractionConfigFieldsProps) {
  const uploadTypes = allowedFileUploadTypes(appType)
  const labelClass = compact
    ? "grid gap-1.5 text-xs font-medium"
    : "grid gap-1.5 text-sm font-medium sm:col-span-2"
  const textareaClass = compact
    ? "resize-y rounded-md border bg-background px-2.5 py-2 text-sm leading-5 outline-none focus-visible:ring-2 focus-visible:ring-ring"
    : "min-h-20 w-full resize-y rounded-lg border border-input bg-muted/20 px-3 py-2 text-sm leading-6 shadow-xs outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 disabled:opacity-50"

  function update(next: Partial<AgentInteractionConfig>) {
    onChange({ ...value, ...next })
  }

  function updateUploadSetting(
    next: Partial<AgentInteractionConfig["file_upload_setting"]>
  ) {
    update({
      file_upload_setting: {
        ...value.file_upload_setting,
        ...next,
      },
    })
  }

  return (
    <div className={compact ? "grid gap-3" : "grid gap-4 sm:grid-cols-2"}>
      <label className={labelClass} htmlFor={`${idPrefix}-prologue`}>
        <span>{t("开场白")}</span>
        <textarea
          id={`${idPrefix}-prologue`}
          rows={3}
          maxLength={1000}
          value={value.prologue}
          disabled={readOnly}
          onChange={(event) => update({ prologue: event.target.value })}
          className={textareaClass}
        />
      </label>

      <label className={labelClass} htmlFor={`${idPrefix}-input-title`}>
        <span>{t("用户输入标题")}</span>
        <Input
          id={`${idPrefix}-input-title`}
          maxLength={120}
          value={value.user_input_title}
          disabled={readOnly}
          onChange={(event) => update({ user_input_title: event.target.value })}
        />
      </label>

      <label
        className={compact ? labelClass : "grid gap-1.5 text-sm font-medium"}
        htmlFor={`${idPrefix}-tts`}
      >
        <span>{t("文字转语音")}</span>
        <select
          id={`${idPrefix}-tts`}
          className="h-9 rounded-md border bg-background px-2.5 text-sm"
          value={value.tts_type}
          disabled={readOnly}
          onChange={(event) =>
            update({ tts_type: event.target.value as "NONE" | "BROWSER" })
          }
        >
          <option value="BROWSER">{t("浏览器语音")}</option>
          <option value="NONE">{t("关闭")}</option>
        </select>
      </label>

      <fieldset
        className={
          compact
            ? "grid gap-3 border-t pt-3"
            : "grid gap-3 sm:col-span-2 sm:grid-cols-2"
        }
        disabled={readOnly}
      >
        <label className="flex items-center justify-between gap-3 text-sm font-medium sm:col-span-2">
          <span>{t("文件上传")}</span>
          <input
            type="checkbox"
            className="size-4 accent-primary"
            checked={value.file_upload}
            onChange={(event) => update({ file_upload: event.target.checked })}
          />
        </label>
        {value.file_upload ? (
          <>
            <div className="flex flex-wrap gap-3 sm:col-span-2">
              {uploadTypes.map((type) => (
                <label key={type} className="flex items-center gap-1.5 text-xs">
                  <input
                    type="checkbox"
                    className="size-4 accent-primary"
                    checked={value.file_upload_setting.file_upload_type.includes(
                      type
                    )}
                    onChange={(event) => {
                      const selected =
                        value.file_upload_setting.file_upload_type.filter(
                          (item) => uploadTypes.includes(item) && item !== type
                        )
                      const next = event.target.checked
                        ? [...selected, type]
                        : selected
                      if (next.length) {
                        updateUploadSetting({ file_upload_type: next })
                      }
                    }}
                  />
                  {t(
                    type === "document"
                      ? "文档"
                      : type === "image"
                        ? "图片"
                        : "音频"
                  )}
                </label>
              ))}
            </div>
          </>
        ) : null}
      </fieldset>
    </div>
  )
}
