"use client"

import * as React from "react"
import { FileTextIcon, ImageIcon, SettingsIcon } from "lucide-react"

import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { IconButton } from "@/components/ui/icon-button"
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

/**
 * Renders controls for editing agent interaction settings.
 *
 * @param appType - The application type used to determine available file upload types
 * @param value - The current interaction configuration
 * @param onChange - Called with the updated interaction configuration
 * @param idPrefix - Prefix used to generate control IDs
 * @param readOnly - Whether editing controls are disabled
 * @param compact - Whether to use the compact layout
 */
export function InteractionConfigFields({
  appType,
  value,
  onChange,
  t,
  idPrefix,
  readOnly = false,
  compact = false,
}: InteractionConfigFieldsProps) {
  const [uploadSettingsOpen, setUploadSettingsOpen] = React.useState(false)
  const uploadTypes = allowedFileUploadTypes(appType)
  const labelClass = compact
    ? "grid gap-1.5 text-xs font-medium"
    : "grid gap-1.5 text-sm font-medium sm:col-span-2"
  const textareaClass = compact
    ? "resize-y rounded-md border bg-background px-2.5 py-2 text-sm leading-5 outline-none focus-visible:border-ring"
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
          className={compact ? "focus-visible:border-ring focus-visible:ring-0" : undefined}
          maxLength={120}
          value={value.user_input_title}
          disabled={readOnly}
          onChange={(event) => update({ user_input_title: event.target.value })}
        />
      </label>

      <div className="flex items-center justify-between gap-3 text-sm font-medium">
        <span>{t("文字转语音")}</span>
        <button
          type="button"
          role="switch"
          id={`${idPrefix}-tts`}
          aria-checked={value.tts_type === "BROWSER"}
          aria-label={t("文字转语音")}
          disabled={readOnly}
          onClick={() =>
            update({ tts_type: value.tts_type === "BROWSER" ? "NONE" : "BROWSER" })
          }
          className={`relative h-5 w-9 cursor-pointer rounded-full transition-colors outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50 ${
            value.tts_type === "BROWSER" ? "bg-primary" : "bg-muted-foreground/40"
          }`}
        >
          <span
            className={`block size-4 rounded-full bg-background shadow-sm transition-transform ${
              value.tts_type === "BROWSER" ? "translate-x-[18px]" : "translate-x-0.5"
            }`}
          />
        </button>
      </div>

      <fieldset
        className={
          compact
            ? "grid gap-3 border-t pt-3"
            : "grid gap-3 sm:col-span-2 sm:grid-cols-2"
        }
        disabled={readOnly}
      >
        <div className="flex items-center justify-between gap-3 text-sm font-medium sm:col-span-2">
          <span>{t("文件上传")}</span>
          <span className="flex items-center gap-1.5">
            <IconButton
              label={t("文件上传设置")}
              className="size-7"
              disabled={readOnly}
              onClick={() => setUploadSettingsOpen(true)}
            >
              <SettingsIcon />
            </IconButton>
            <button
              type="button"
              role="switch"
              id={`${idPrefix}-file-upload`}
              aria-checked={value.file_upload}
              aria-label={t("文件上传")}
              onClick={() => update({ file_upload: !value.file_upload })}
              className={`relative h-5 w-9 cursor-pointer rounded-full transition-colors outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50 ${
                value.file_upload ? "bg-primary" : "bg-muted-foreground/40"
              }`}
            >
              <span
                className={`block size-4 rounded-full bg-background shadow-sm transition-transform ${
                  value.file_upload ? "translate-x-[18px]" : "translate-x-0.5"
                }`}
              />
            </button>
          </span>
        </div>
      </fieldset>
      <Dialog open={uploadSettingsOpen} onOpenChange={setUploadSettingsOpen}>
        <DialogContent className="max-w-xl">
          <DialogHeader>
            <DialogTitle>{t("文件上传设置")}</DialogTitle>
            <DialogDescription>{t("选择允许上传的文件类型。")}</DialogDescription>
          </DialogHeader>
          <div className="grid gap-3">
            {uploadTypes.map((type) => {
              const selected = value.file_upload_setting.file_upload_type.filter(
                (item) => uploadTypes.includes(item) && item !== type
              )
              const checked = value.file_upload_setting.file_upload_type.includes(type)
              const Icon = type === "document" ? FileTextIcon : ImageIcon
              return (
                <label
                  key={type}
                  className="flex cursor-pointer items-center gap-3 rounded-lg border bg-background p-4 transition-colors has-checked:border-ring has-checked:bg-muted/40"
                >
                  <span className="flex size-9 shrink-0 items-center justify-center rounded-md bg-muted">
                    <Icon className="size-5" />
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block text-sm font-medium">
                      {t(type === "document" ? "文档" : "图片")}
                    </span>
                    <span className="mt-1 block text-xs leading-5 text-muted-foreground">
                      {t(
                        type === "document"
                          ? "DOCX、PDF、PPTX、XLSX、TXT、Markdown、HTML、CSV、JSON、XML、IPYNB、EPUB、ZIP"
                          : "PNG、JPG、JPEG、WEBP"
                      )}
                    </span>
                  </span>
                  <input
                    type="checkbox"
                    className="size-4 shrink-0 accent-primary"
                    checked={checked}
                    disabled={readOnly || (checked && selected.length === 0)}
                    onChange={(event) =>
                      updateUploadSetting({
                        file_upload_type: event.target.checked
                          ? [...selected, type]
                          : selected,
                      })
                    }
                  />
                </label>
              )
            })}
          </div>
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => setUploadSettingsOpen(false)}
            >
              {t("关闭")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
