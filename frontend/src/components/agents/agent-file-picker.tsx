"use client"

import { useRef, useState } from "react"
import { FileUpIcon, FolderUpIcon, PlusIcon } from "lucide-react"
import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import type { TFunction } from "@/i18n"
import { isAgentUploadFile } from "@/lib/agent-upload"

export function AgentFilePicker({
  disabled,
  onFiles,
  t,
  label,
}: {
  disabled: boolean
  onFiles: (files: File[]) => void
  t: TFunction
  label?: string
}) {
  const fileInput = useRef<HTMLInputElement>(null)
  const folderInput = useRef<HTMLInputElement>(null)
  const [error, setError] = useState(false)
  function select(input: HTMLInputElement | null) {
    if (!input) return
    input.value = ""
    input.click()
  }
  function accept(files: FileList | null) {
    const usable = Array.from(files ?? []).filter(isAgentUploadFile)
    setError(!!files?.length && !usable.length)
    if (usable.length) onFiles(usable)
  }
  return (
    <>
      <input
        ref={fileInput}
        type="file"
        hidden
        multiple
        aria-label={t("上传文件或 ZIP")}
        disabled={disabled}
        onChange={(event) => accept(event.target.files)}
      />
      <input
        ref={(input) => {
          folderInput.current = input
          input?.setAttribute("webkitdirectory", "")
        }}
        type="file"
        hidden
        multiple
        aria-label={t("上传文件夹")}
        disabled={disabled}
        onChange={(event) => accept(event.target.files)}
      />
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button
            type="button"
            variant={label ? "outline" : "ghost"}
            size={label ? "sm" : "icon-sm"}
            className={
              label
                ? undefined
                : "rounded-md text-muted-foreground hover:text-foreground"
            }
            aria-label={label ?? t("添加附件")}
            title={label ?? t("添加附件")}
            disabled={disabled}
          >
            <PlusIcon />
            {label}
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="start" side="top" sideOffset={6}>
          <DropdownMenuItem onSelect={() => select(fileInput.current)}>
            <FileUpIcon />
            {t("上传文件或 ZIP")}
          </DropdownMenuItem>
          <DropdownMenuItem onSelect={() => select(folderInput.current)}>
            <FolderUpIcon />
            {t("上传文件夹")}
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
      {error ? (
        <span role="alert" className="text-xs text-destructive">
          {t("未找到可上传的文件")}
        </span>
      ) : null}
    </>
  )
}
