import { FileTextIcon, ImageIcon, PaperclipIcon, XIcon } from "lucide-react"
import type { TFunction } from "@/i18n"

export type RunAttachment = {
  filename: string
  content_type: string
  size_bytes: number
  category: "document" | "image"
}

export function runAttachmentFromFile(file: File): RunAttachment {
  return {
    filename: file.name,
    content_type: file.type || "application/octet-stream",
    size_bytes: file.size,
    category: file.type.startsWith("image/") ? "image" : "document",
  }
}

export function transferredFiles(dataTransfer: DataTransfer) {
  const files = Array.from(dataTransfer.files)
  if (files.length) return files
  return Array.from(dataTransfer.items)
    .filter((item) => item.kind === "file")
    .map((item) => item.getAsFile())
    .filter((file): file is File => file !== null)
}

export function appendAttachmentFiles(
  current: File[],
  added: ArrayLike<File>
) {
  return [...current, ...Array.from(added)]
}

export function RunAttachmentCards({
  attachments,
  t,
}: {
  attachments: unknown
  t: TFunction
}) {
  if (!Array.isArray(attachments)) return null
  const files = attachments.flatMap((attachment) => {
    if (!attachment || typeof attachment !== "object") return []
    const value = attachment as Record<string, unknown>
    const filename = value.filename ?? value.name
    if (typeof filename !== "string" || !filename) return []
    return [
      {
        filename,
        category: value.category === "image" ? "image" : "document",
      } as const,
    ]
  })
  if (!files.length) return null

  return (
    <ul className="grid w-fit max-w-full gap-1.5">
      {files.map((file, index) => {
        const Icon = file.category === "image" ? ImageIcon : FileTextIcon
        return (
          <li
            key={`${file.filename}-${index}`}
            title={file.filename}
            className="flex min-w-0 max-w-[min(22rem,78vw)] items-center gap-2.5 rounded-2xl rounded-br-md border border-border/70 bg-muted/45 py-2.5 pr-4 pl-2.5 text-left shadow-xs"
          >
            <span
              className={`flex size-9 shrink-0 items-center justify-center rounded-xl ${
                file.category === "image"
                  ? "bg-violet-500/12 text-violet-500"
                  : "bg-blue-500/12 text-blue-500"
              }`}
            >
              <Icon className="size-4.5" />
            </span>
            <span className="min-w-0 pr-1">
              <span className="block truncate text-sm font-medium leading-5 text-foreground">
                {file.filename}
              </span>
              <span className="mt-px block text-[11px] leading-4 text-muted-foreground">
                {t(file.category === "image" ? "图片" : "文档")}
              </span>
            </span>
          </li>
        )
      })}
    </ul>
  )
}

/**
 * Renders attached files with localized remove controls.
 *
 * @param files - The files to display
 * @param onRemove - Called with the index of the file selected for removal
 * @returns The attachment list, or `null` when `files` is empty
 */
export function AgentAttachmentList({
  files,
  onRemove,
  t,
}: {
  files: File[]
  onRemove: (index: number) => void
  t: TFunction
}) {
  if (!files.length) return null

  return (
    <ul className="flex max-h-24 flex-wrap gap-1.5 overflow-y-auto px-3 pb-1 pr-24">
      {files.map((file, index) => (
        <li
          key={`${file.name}-${file.size}-${file.lastModified}-${index}`}
          title={file.name}
          className="flex max-w-48 items-center gap-1 rounded-md bg-muted py-1 pr-1 pl-2 text-xs text-muted-foreground"
        >
          <PaperclipIcon className="size-3" />
          <span className="truncate">{file.name}</span>
          <button
            type="button"
            className="rounded-sm p-0.5 hover:bg-background hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            aria-label={t("移除 {value}", { value: file.name })}
            onClick={() => onRemove(index)}
          >
            <XIcon className="size-3" />
          </button>
        </li>
      ))}
    </ul>
  )
}
