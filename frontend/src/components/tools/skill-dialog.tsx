"use client"

import * as React from "react"
import { LoaderCircleIcon, UploadIcon } from "lucide-react"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Field, FieldGroup, FieldLabel } from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import { useLanguage } from "@/contexts/language-provider"
import {
  createAgentSkill,
  inspectSkillImport,
  publishAgentSkill,
  updateAgentSkill,
  type AgentSkill,
  type AgentSkillDefinition,
} from "@/lib/api/agent-skills"
import { getErrorMessage } from "@/lib/errors"

export function SkillDialog({
  open,
  onOpenChange,
  token,
  workspaceId,
  skill,
  onSaved,
  returnFocusRef,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  token: string
  workspaceId: string
  skill?: AgentSkill
  onSaved: () => void
  returnFocusRef?: React.RefObject<HTMLElement | null>
}) {
  const { t } = useLanguage()
  const fileRef = React.useRef<HTMLInputElement>(null)
  const [name, setName] = React.useState(skill?.name ?? "")
  const [description, setDescription] = React.useState(skill?.description ?? "")
  const [instructions, setInstructions] = React.useState(
    skill?.definition.instructions ?? ""
  )
  const [definition, setDefinition] =
    React.useState<AgentSkillDefinition | null>(skill?.definition ?? null)
  const [savedId, setSavedId] = React.useState(skill?.id)
  const [busy, setBusy] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)

  async function importFile(file: File) {
    if (file.size > 2 * 1024 * 1024) {
      setError(t("Skill 包不能超过 2 MiB"))
      return
    }
    setBusy(true)
    setError(null)
    try {
      const draft = await inspectSkillImport(token, workspaceId, file)
      setName(draft.name)
      setDescription(draft.description)
      setInstructions(draft.definition.instructions)
      setDefinition(draft.definition)
    } catch (cause) {
      setError(getErrorMessage(cause, t))
    } finally {
      setBusy(false)
    }
  }

  async function save(publish: boolean) {
    setBusy(true)
    setError(null)
    try {
      // The backend regenerates SKILL.md, preserving imported metadata and files.
      const draft = {
        name: name.trim(),
        description: description.trim(),
        definition: {
          intents: [],
          input_schema: { type: "object", additionalProperties: false },
          output_schema: { type: "object", additionalProperties: false },
          knowledge_base_ids: [],
          tools: [],
          execution_timeout_seconds: 30,
          guardrails: {
            allow_external_reads: false,
            allow_external_writes: false,
            require_approval_for_external_writes: true,
          },
          ...definition,
          instructions,
          files: definition?.files ?? {},
        },
      }
      const saved = savedId
        ? await updateAgentSkill(token, workspaceId, savedId, draft)
        : await createAgentSkill(token, workspaceId, draft)
      setSavedId(saved.id)
      onSaved() // A failed publication still leaves a visible, editable draft.
      if (publish) {
        await publishAgentSkill(token, workspaceId, saved.id)
        onSaved()
      }
      onOpenChange(false)
    } catch (cause) {
      setError(getErrorMessage(cause, t))
    } finally {
      setBusy(false)
    }
  }

  const readOnly = skill && !skill.can_manage
  return (
    <Dialog
      open={open}
      onOpenChange={(value) => {
        if (!busy) onOpenChange(value)
      }}
    >
      <DialogContent
        className="max-h-[calc(100dvh-2rem)] overflow-y-auto sm:max-w-2xl"
        onCloseAutoFocus={(event) => {
          if (returnFocusRef?.current) {
            event.preventDefault()
            returnFocusRef.current.focus()
          }
        }}
      >
        <DialogHeader>
          <DialogTitle>{skill ? t("编辑 Skill") : t("创建 Skill")}</DialogTitle>
          <DialogDescription>
            {t("Skill 是按需加载的指令与文件包，不会自动生成或授权外部工具。")}
          </DialogDescription>
        </DialogHeader>
        <input
          ref={fileRef}
          type="file"
          accept=".md,.zip"
          className="sr-only"
          aria-label={t("选择 Skill 文件")}
          disabled={busy || Boolean(readOnly)}
          onChange={(event) => {
            const file = event.target.files?.[0]
            event.target.value = ""
            if (file) void importFile(file)
          }}
        />
        <FieldGroup>
          <Field>
            <FieldLabel htmlFor="skill-name">{t("显示名称")}</FieldLabel>
            <Input
              id="skill-name"
              value={name}
              maxLength={120}
              disabled={busy || Boolean(readOnly)}
              onChange={(event) => setName(event.target.value)}
            />
          </Field>
          <Field>
            <FieldLabel htmlFor="skill-description">{t("描述")}</FieldLabel>
            <Input
              id="skill-description"
              value={description}
              maxLength={500}
              disabled={busy || Boolean(readOnly)}
              onChange={(event) => setDescription(event.target.value)}
            />
          </Field>
          <Field>
            <FieldLabel htmlFor="skill-instructions">
              {t("技能指令")}
            </FieldLabel>
            <textarea
              id="skill-instructions"
              value={instructions}
              maxLength={12000}
              disabled={busy || Boolean(readOnly)}
              className="max-h-80 min-h-48 w-full resize-y rounded-md border border-input bg-transparent p-3 font-mono text-sm"
              onChange={(event) => setInstructions(event.target.value)}
            />
          </Field>
        </FieldGroup>
        {definition && Object.keys(definition.files).length > 0 ? (
          <p className="text-sm break-all text-muted-foreground">
            {t("包文件")}：{Object.keys(definition.files).join(", ")}
          </p>
        ) : null}
        {skill?.current_version_number ? (
          <p className="text-sm text-muted-foreground">
            {t("已发布版本")}：{skill.current_version_number}
          </p>
        ) : null}
        {error ? (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        ) : null}
        <DialogFooter>
          {!readOnly ? (
            <Button
              variant="outline"
              disabled={busy}
              onClick={() => fileRef.current?.click()}
            >
              <UploadIcon />
              {t("导入 Skill")}
            </Button>
          ) : null}
          <Button
            variant="outline"
            disabled={busy}
            onClick={() => onOpenChange(false)}
          >
            {t("取消")}
          </Button>
          {!readOnly ? (
            <>
              <Button
                variant="outline"
                disabled={
                  busy ||
                  !name.trim() ||
                  !description.trim() ||
                  !instructions.trim()
                }
                onClick={() => void save(false)}
              >
                {t("保存草稿")}
              </Button>
              <Button
                disabled={
                  busy ||
                  !name.trim() ||
                  !description.trim() ||
                  !instructions.trim()
                }
                onClick={() => void save(true)}
              >
                {busy ? <LoaderCircleIcon className="animate-spin" /> : null}
                {t("保存并发布")}
              </Button>
            </>
          ) : null}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
