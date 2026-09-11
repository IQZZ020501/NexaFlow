"use client"

import * as React from "react"
import { FilePlusIcon, LoaderCircleIcon, UploadIcon } from "lucide-react"

import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import {
  Field,
  FieldDescription,
  FieldGroup,
  FieldLabel,
} from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import { useLanguage } from "@/contexts/language-provider"

const TEXTAREA_CLASS =
  "min-h-48 w-full resize-y rounded-md border border-input bg-transparent px-3 py-2 font-mono text-sm shadow-xs outline-none placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 disabled:cursor-not-allowed disabled:opacity-60"

type SkillForm = {
  displayName: string
  description: string
  skillMarkdown: string
}

const EMPTY_FORM: SkillForm = {
  displayName: "",
  description: "",
  skillMarkdown: "",
}

/**
 * Reads Skill name and description from SKILL.md YAML front matter.
 *
 * @param markdown - Raw SKILL.md contents
 */
function parseSkillFrontMatter(markdown: string): Pick<
  SkillForm,
  "displayName" | "description"
> {
  const match = markdown.match(/^---\n([\s\S]*?)\n---/)
  if (!match) return { displayName: "", description: "" }
  const fields: Record<string, string> = {}
  for (const line of match[1].split("\n")) {
    const separator = line.indexOf(":")
    if (separator <= 0) continue
    const key = line.slice(0, separator).trim()
    const value = line.slice(separator + 1).trim().replace(/^["']|["']$/g, "")
    fields[key] = value
  }
  return {
    displayName: fields.name ?? "",
    description: fields.description ?? "",
  }
}

/**
 * Creates a workspace Skill from the editor or a SKILL.md / zip upload.
 *
 * @param returnFocusRef - Element to refocus when the dialog closes
 */
export function SkillDialog({
  open,
  onOpenChange,
  returnFocusRef,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  returnFocusRef?: React.RefObject<HTMLElement | null>
}) {
  const { t } = useLanguage()
  const fileInputRef = React.useRef<HTMLInputElement>(null)
  const [mode, setMode] = React.useState<"choose" | "create">("choose")
  const [form, setForm] = React.useState<SkillForm>(EMPTY_FORM)
  const [importError, setImportError] = React.useState<string | null>(null)
  const [isReading, setIsReading] = React.useState(false)

  function handleOpenChange(nextOpen: boolean) {
    if (!nextOpen) {
      setMode("choose")
      setForm(EMPTY_FORM)
      setImportError(null)
      setIsReading(false)
    }
    onOpenChange(nextOpen)
  }

  function applyImportedMarkdown(markdown: string) {
    const parsed = parseSkillFrontMatter(markdown)
    setForm({
      displayName: parsed.displayName,
      description: parsed.description,
      skillMarkdown: markdown,
    })
    setImportError(null)
    setMode("create")
  }

  async function importSkillFile(file: File) {
    const name = file.name.toLowerCase()
    if (name.endsWith(".zip")) {
      setImportError(t("请先解压 zip，上传其中的 SKILL.md。"))
      return
    }
    if (!name.endsWith(".md")) {
      setImportError(t("请上传 SKILL.md 或 zip。"))
      return
    }
    setIsReading(true)
    try {
      applyImportedMarkdown(await file.text())
    } catch {
      setImportError(t("无法读取该文件。"))
    } finally {
      setIsReading(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent
        className="sm:max-w-2xl"
        onCloseAutoFocus={(event) => {
          if (!returnFocusRef?.current) return
          event.preventDefault()
          returnFocusRef.current.focus()
        }}
      >
        <DialogHeader>
          <DialogTitle>
            {mode === "create" ? t("创建 Skill") : t("Skills")}
          </DialogTitle>
          <DialogDescription>
            {mode === "create"
              ? t("写 SKILL.md，并声明参数。平台会生成 Tool。")
              : t("新建 Skill，或导入 SKILL.md / zip。")}
          </DialogDescription>
        </DialogHeader>

        <input
          ref={fileInputRef}
          type="file"
          accept=".md,.zip,text/markdown,application/zip"
          className="sr-only"
          aria-label={t("选择 Skill 文件")}
          onChange={(event) => {
            const file = event.target.files?.[0]
            event.target.value = ""
            if (file) void importSkillFile(file)
          }}
        />

        {mode === "choose" ? (
          <div className="grid gap-3 sm:grid-cols-2">
            <button
              type="button"
              className="flex min-h-32 flex-col items-start gap-2 rounded-md border p-4 text-left outline-none transition-colors hover:bg-muted/40 focus-visible:ring-2 focus-visible:ring-ring"
              onClick={() => {
                setImportError(null)
                setMode("create")
              }}
            >
              <FilePlusIcon className="size-5 text-muted-foreground" />
              <span className="font-medium">{t("新建 Skill")}</span>
              <span className="text-sm text-muted-foreground">
                {t("写 SKILL.md，并声明参数。平台会生成 Tool。")}
              </span>
            </button>
            <button
              type="button"
              className="flex min-h-32 flex-col items-start gap-2 rounded-md border p-4 text-left outline-none transition-colors hover:bg-muted/40 focus-visible:ring-2 focus-visible:ring-ring"
              disabled={isReading}
              onClick={() => fileInputRef.current?.click()}
            >
              {isReading ? (
                <LoaderCircleIcon className="size-5 animate-spin text-muted-foreground" />
              ) : (
                <UploadIcon className="size-5 text-muted-foreground" />
              )}
              <span className="font-medium">{t("导入 Skill")}</span>
              <span className="text-sm text-muted-foreground">
                {t("上传包含 SKILL.md 的 zip 包。")}
              </span>
            </button>
          </div>
        ) : (
          <FieldGroup>
            <Field>
              <FieldLabel htmlFor="skill-display-name">{t("显示名称")}</FieldLabel>
              <Input
                id="skill-display-name"
                value={form.displayName}
                onChange={(event) =>
                  setForm((current) => ({
                    ...current,
                    displayName: event.target.value,
                  }))
                }
              />
            </Field>
            <Field>
              <FieldLabel htmlFor="skill-description">{t("描述")}</FieldLabel>
              <Input
                id="skill-description"
                value={form.description}
                onChange={(event) =>
                  setForm((current) => ({
                    ...current,
                    description: event.target.value,
                  }))
                }
              />
            </Field>
            <Field>
              <FieldLabel htmlFor="skill-markdown">{t("SKILL.md")}</FieldLabel>
              <FieldDescription>
                {t("参数写在 frontmatter 或稍后在表单里补。")}
              </FieldDescription>
              <textarea
                id="skill-markdown"
                className={TEXTAREA_CLASS}
                value={form.skillMarkdown}
                spellCheck={false}
                onChange={(event) =>
                  setForm((current) => ({
                    ...current,
                    skillMarkdown: event.target.value,
                  }))
                }
              />
            </Field>
          </FieldGroup>
        )}

        {importError ? (
          <p role="alert" className="text-sm text-destructive">
            {importError}
          </p>
        ) : null}

        <DialogFooter>
          {mode === "create" ? (
            <Button
              type="button"
              variant="outline"
              onClick={() => fileInputRef.current?.click()}
              disabled={isReading}
            >
              <UploadIcon />
              {t("导入 Skill")}
            </Button>
          ) : null}
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
            {t("取消")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
